/* Track R2 (TEST ONLY, default OFF): the SNAPSHOT RING for rollback, on top of R1's marked-page save (r1_state.c).
 * Included by r1_state.c (it uses that file's statics: the mark maps, the flat shadow of the first full save, the
 * thread holds, the fiber save, the parallel page copy). No game content in this file. Plan: plan\phases\R2_snapshot_ring.md.
 *
 * Design ("pointer shadow + undo log"):
 *  - every guest page the ring tracks has a global id: window 1 (the game's 62 GB region) pages, then window 2
 *    (image + modules) pages, then the "extras" (main's guest stack, TLS blocks, fighter DLL data, catch table, malloc
 *    arena: the ranges r1 copies whole);
 *  - g_rg_idx[id] says where the page's value AT THE NEWEST CAPTURE is: 0 = the flat shadow of the first full save
 *    (never written since), 1 = decommitted by the game, >= 2 = a 4 KB buffer of the page pool;
 *  - capture(f): every page marked since the previous capture (and every extras page that differs) gets a NEW pool
 *    buffer with its current bytes (one copy, done by main + helper threads); the slot of f keeps the list
 *    (id, previous idx) = an undo log: the buffers of the values at the previous capture are not copied, only moved
 *    into the log. Plus per slot: main's registers, the other threads' wait places and registers, the fibers' host
 *    state, the command buffers' recordings in progress (nvn_gl.c's save area, through the linker map);
 *  - load(g): the undo logs of the slots newer than g are applied newest first, pointers only (no copy); every page
 *    they name, every page marked since the newest capture and every extras page is then copied ONCE from its value at
 *    g into memory; the slots newer than g are dropped (g becomes the newest), older ones stay loadable;
 *  - the oldest slot is dropped when the ring is full (SSBU_RB_DEPTH, default 7 frames back = 8 states).
 * Public API (a future rb_rollback.c, at the safe point run-ahead uses, the kick after the submission):
 *    int r1_ring_capture(long long frame, Ctx *c);  1 = captured; 0 = not now (a thread not at a wait in time)
 *    int r1_ring_load(long long frame, Ctx *c);     1 = loaded (c = main's registers of that frame); 0 = not in the ring
 *    void r1_ring_release(void);                    every slot dropped
 *    long long r1_ring_oldest(void), r1_ring_newest(void);   (-1 = empty)
 *    double r1_ring_last_ms(int load);              the last capture / load in ms
 * Test driver (SSBU_RB_SIM=<N>[,<K>[,<warm>]]): a ROLLBACK SIMULATION in one process: every pass of the fight is
 * captured; every N real passes the state of k passes back is loaded (k = 1..K rotating) and those passes run again
 * with player 1's recorded pads, not presented (run-ahead's quiet phase); tests\rb_sim_cmp.py checks the real timeline
 * against a run without it and every re-run frame against the frame it replays. SSBU_RB_SIM_SKIP=<mask>: run-ahead's
 * kick-skip mask in re-run passes except the last one (experiment). SSBU_RB_PARK_MS (default 30): hold limit. */

#define RG_MAXSLOT 16
#define RG_FLAT 0u
#define RG_DECOM 1u
#define RG_POOL_MAX (1u << 20)                 /* 4 GB of 4 KB buffers (reserved, committed as used) */
#define RG_ENT_RES (64ull << 20)               /* per slot: room for 8 M (id, old) pairs */
#define RG_FP_RES (256ull << 20)               /* per slot: fibers' host stacks */
#define RG_CB_RES (64ull << 20)                /* per slot: command-buffer recordings */
#define RG_CBS_SIZE 144                        /* nvn_gl.c CbSave: CmdBuf *cb; CmdBuf copy (120: data, len, cap, ...); data; cap */
typedef struct {
    long long frame;
    uint32_t *ent; size_t nent, entcom;
    Ctx ctx;
    Th th[256]; int nth, ninfo;
    Fib *fib; int nfib; uint8_t *fpool; size_t fpool_used, fpool_com;
    int ncbs; uint8_t *cbs; uint8_t *cbd; size_t cbd_used, cbd_com;
    size_t pages, xpages;
} RgSlot;
static RgSlot *g_rg; static int g_rg_cap, g_rg_head, g_rg_count, g_rg_ready, g_rg_depth = 7;
static uint32_t *g_rg_idx; static uint8_t *g_rg_touch; static uint32_t *g_rg_tl; static size_t g_rg_ntl, g_rg_tlcap;
static size_t g_rg_n1, g_rg_n2, g_rg_nx;               /* page counts: window 1, window 2, extras */
static uint8_t **g_rg_xa, **g_rg_xb;                   /* extras page e: its address, its flat (first save) bytes */
static uint8_t *g_rg_pool; static uint32_t g_rg_bump, g_rg_pcom, *g_rg_free, g_rg_nfree;
static uint8_t *g_rg_cbs; static int *g_rg_ncbs; static int g_rg_cb_ok = -1;
static double g_rg_park_ms = 30;
static int g_rg_keep, g_rg_kept, g_rg_keep_on = -1; static long long g_rg_kept_n, g_rg_kept_same;   /* capture -> load at the same safe point: threads stay held */
static long long g_rg_caps, g_rg_cap_fail, g_rg_loads, g_rg_overflow;
static double g_rg_last[2];
static int g_rgs_on; static long long g_rgv_target; static void rgv_before(int si, long long target); static void rgv_after(void);   /* (simulation / verify, below) */
/* costs: capture (all, hold, sweep + queue, copy, fibers / threads / cb), load per k */
#define RG_NST 65536
static double *g_rgc[5]; static size_t *g_rgc_pg, *g_rgc_xp; static int g_rgc_n;
#define RG_NL 4096
static double g_rgl[RG_MAXSLOT][RG_NL][3]; static size_t g_rgl_pg[RG_MAXSLOT][RG_NL]; static int g_rgl_n[RG_MAXSLOT];

static uint8_t *rg_vres(size_t n) { return VirtualAlloc(NULL, n, MEM_RESERVE, PAGE_READWRITE); }
static int rg_vcom(uint8_t *base, size_t *com, size_t need, size_t step) {   /* commit [0, need) of a reservation */
    if (need <= *com) return 1;
    size_t to = (need + step - 1) / step * step;
    if (!VirtualAlloc(base + *com, to - *com, MEM_COMMIT, PAGE_READWRITE)) return 0;
    *com = to; return 1;
}
static uint32_t rg_pool_get(void) {
    if (g_rg_nfree) return g_rg_free[--g_rg_nfree];
    if (g_rg_bump >= RG_POOL_MAX) return 0;
    if (g_rg_bump >= g_rg_pcom) {
        if (!VirtualAlloc(g_rg_pool + (size_t)g_rg_pcom * PG, 256 * PG, MEM_COMMIT, PAGE_READWRITE)) return 0;
        g_rg_pcom += 256;
    }
    return 2 + g_rg_bump++;
}
static void rg_pool_put(uint32_t i) { if (i >= 2) g_rg_free[g_rg_nfree++] = i; }
static uint8_t *rg_pool_ptr(uint32_t i) { return g_rg_pool + (size_t)(i - 2) * PG; }
static uint8_t *rg_addr(uint32_t id) {
    if (id < g_rg_n1) return g_win1 + (size_t)id * PG;
    if (id < g_rg_n1 + g_rg_n2) return (uint8_t *)(uintptr_t)WIN2 + (size_t)(id - g_rg_n1) * PG;
    return g_rg_xa[id - g_rg_n1 - g_rg_n2];
}
/* the bytes of page `id` as recorded at the newest capture (NULL = zero page, (uint8_t *)1 = decommitted) */
static uint8_t *rg_src(uint32_t id) {
    uint32_t v = g_rg_idx[id];
    if (v >= 2) return rg_pool_ptr(v);
    if (v == RG_DECOM) return (uint8_t *)1;
    if (id < g_rg_n1) return g_sh1c[id] ? g_sh1 + (size_t)id * PG : NULL;
    if (id < g_rg_n1 + g_rg_n2) { size_t j = id - g_rg_n1; return g_sh2c[j] ? g_sh2 + j * PG : NULL; }
    return g_rg_xb[id - g_rg_n1 - g_rg_n2];
}
static int rg_push(RgSlot *s, uint32_t id, uint32_t old) {
    if (!rg_vcom((uint8_t *)s->ent, &s->entcom, (s->nent + 1) * 8, 1u << 20)) return 0;
    s->ent[2 * s->nent] = id; s->ent[2 * s->nent + 1] = old; s->nent++;
    return 1;
}
static void rg_touch(uint32_t id) {
    if (g_rg_touch[id]) return;
    if (g_rg_ntl >= g_rg_tlcap) { g_rg_overflow++; return; }
    g_rg_touch[id] = 1; g_rg_tl[g_rg_ntl++] = id;
}
/* every page marked since the last sweep, in both windows (the same block lists as mark_sweep); marks cleared */
static void rg_sweep(void (*fn)(uint32_t id, int w, size_t j)) {
    if (g_full_sweep < 0) g_full_sweep = getenv("SSBU_R1_FULL_SWEEP") != NULL;
    if (!g_blk1 && !g_full_sweep && g_win1) blk1_init();
    if (g_blk1 && g_blk1_dirty) blk1_rebuild();
    for (int w = 0; w < 2; w++) {
        uint8_t *map = w ? *pm2 : *pm1; size_t np = (size_t)((w ? WN2 : g_wn1) >> 12);
        uint8_t *mem = w ? (uint8_t *)(uintptr_t)WIN2 : g_win1;
        uint64_t *q = (uint64_t *)map;
        uint32_t *bl = !g_blk1 ? NULL : w ? g_blk2_list : g_blk1_list;
        size_t nq = !bl ? np / 8 : (w ? g_blk2_n : g_blk1_n) * 8;
        for (size_t qi = 0; qi < nq; qi++) {
            size_t i = !bl ? qi : (size_t)bl[qi >> 3] * 8 + (qi & 7);
            if (!q[i]) continue;
            for (size_t j = i * 8; j < i * 8 + 8; j++) {
                if (!map[j]) continue;
                map[j] = 0;
                if (g_audio_free && is_async(mem + j * PG)) continue;
                if (w ? g_ns2[j] : g_ns1[j]) continue;          /* not simulation */
                fn((uint32_t)(w ? g_rg_n1 + j : j), w, j);
            }
        }
    }
}
static RgSlot *g_rg_cur; static int g_rg_fail_now;
static void rg_cap_page(uint32_t id, int w, size_t j) {
    if (g_rg_fail_now) return;
    uint32_t old = g_rg_idx[id];
    if (!w && g_dc[j]) {                                        /* decommitted by the game: its value is "decommitted" */
        if (old == RG_DECOM) return;
        if (!rg_push(g_rg_cur, id, old)) { g_rg_fail_now = 1; return; }
        g_rg_idx[id] = RG_DECOM; g_rg_cur->pages++;
        return;
    }
    uint32_t nb = rg_pool_get();
    if (!nb || !rg_push(g_rg_cur, id, old)) { if (nb) rg_pool_put(nb); g_rg_fail_now = 1; return; }
    cp_add(rg_pool_ptr(nb), rg_addr(id));
    g_rg_idx[id] = nb; g_rg_cur->pages++;
}
static void rg_load_page(uint32_t id, int w, size_t j) { (void)w; (void)j; rg_touch(id); }
static void rg_slot_drop(RgSlot *s, int log_too) {     /* log_too: the values in its undo log are no longer reachable */
    if (log_too) for (size_t i = 0; i < s->nent; i++) rg_pool_put(s->ent[2 * i + 1]);
    s->nent = 0; s->frame = -1;
}
static void rg_cb_find(void) {
    if (g_rg_cb_ok >= 0) return;
    uint64_t a = map_sym("g_cbs"), n = map_sym("g_ncbs"), all = map_sym("g_all_cb");
    g_rg_cb_ok = a && n && all && all - a == 512ull * RG_CBS_SIZE;
    if (g_rg_cb_ok) { g_rg_cbs = (uint8_t *)(uintptr_t)a; g_rg_ncbs = (int *)(uintptr_t)n; }
    LOG("r1: RING: command-buffer save area of nvn_gl.c %s (g_cbs %llx, g_ncbs %llx, g_all_cb %llx)\n", g_rg_cb_ok ? "found: saved per slot" : "NOT found (layout differs): the newest capture's is put back at every load",
        (unsigned long long)a, (unsigned long long)n, (unsigned long long)all);
}
static int rg_cb_capture(RgSlot *s) {
    s->ncbs = 0; s->cbd_used = 0;
    if (!g_rg_cb_ok) return 1;
    int n = *g_rg_ncbs; if (n < 0 || n > 512) return 0;
    memcpy(s->cbs, g_rg_cbs, (size_t)n * RG_CBS_SIZE);
    for (int i = 0; i < n; i++) {
        uint8_t *e = g_rg_cbs + (size_t)i * RG_CBS_SIZE;
        size_t len = *(size_t *)(e + 16); uint8_t *d = *(uint8_t **)(e + 128);
        if (!*(void **)e || !len || !d) continue;
        if (!rg_vcom(s->cbd, &s->cbd_com, s->cbd_used + len, 1u << 20)) return 0;
        memcpy(s->cbd + s->cbd_used, d, len); s->cbd_used += len;
    }
    s->ncbs = n;
    return 1;
}
static void rg_cb_load(RgSlot *s) {
    if (g_rg_cb_ok) {
        size_t off = 0;
        for (int i = 0; i < s->ncbs; i++) {
            uint8_t *e = g_rg_cbs + (size_t)i * RG_CBS_SIZE, *se = s->cbs + (size_t)i * RG_CBS_SIZE;
            uint8_t *d = *(uint8_t **)(e + 128); size_t cap = *(size_t *)(e + 136);
            memcpy(e, se, 128);                                 /* cb + the record's copy; the save area's own buffer stays */
            size_t len = *(size_t *)(se + 16);
            if (*(void **)se && len && *(uint8_t **)(se + 128)) {
                if (cap < len) { cap = len + 65536; d = realloc(d, cap); }
                memcpy(d, s->cbd + off, len); off += len;
            }
            *(uint8_t **)(e + 128) = d; *(size_t *)(e + 136) = cap;
        }
        *g_rg_ncbs = s->ncbs;
    }
    nvn_r1_cb_restore();
}
static void rg_meta_capture(RgSlot *s, Ctx *c) {       /* threads still held: their places, the fibers, the command buffers */
    s->ctx = *c;
    s->nth = g_nth; s->ninfo = g_ninfo;
    memcpy(s->th, g_th, (size_t)g_nth * sizeof *g_th);
    for (int i = 0; i < s->nth; i++) s->th[i].held = 0;
    s->nfib = g_nfib; memcpy(s->fib, g_fib, (size_t)g_nfib * sizeof *g_fib);
    s->fpool_used = 0;
    if (g_fpool_used && rg_vcom(s->fpool, &s->fpool_com, g_fpool_used, 1u << 20)) { memcpy(s->fpool, g_fpool, g_fpool_used); s->fpool_used = g_fpool_used; }
    else if (g_fpool_used) for (int i = 0; i < s->nfib; i++) s->fib[i].susp = 0;
    if (!rg_cb_capture(s)) s->ncbs = 0;
}
static int rg_init(void) {
    g_rg_n1 = g_win1 ? (size_t)(g_wn1 >> 12) : 0; g_rg_n2 = (size_t)(WN2 >> 12);
    g_rg_nx = 0; for (int i = 0; i < g_nx; i++) g_rg_nx += g_x[i].n / PG;
    size_t tot = g_rg_n1 + g_rg_n2 + g_rg_nx;
    { const char *e = getenv("SSBU_RB_DEPTH"); if (e) g_rg_depth = atoi(e); if (g_rg_depth < 1) g_rg_depth = 1; if (g_rg_depth > RG_MAXSLOT - 1) g_rg_depth = RG_MAXSLOT - 1; }
    g_rg_cap = g_rg_depth + 1;
    g_rg_idx = VirtualAlloc(NULL, tot * 4, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    g_rg_touch = VirtualAlloc(NULL, tot, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    g_rg_tlcap = 8u << 20; g_rg_tl = VirtualAlloc(NULL, g_rg_tlcap * 4, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    g_rg_pool = rg_vres((size_t)RG_POOL_MAX * PG);
    g_rg_free = VirtualAlloc(NULL, (size_t)RG_POOL_MAX * 4, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    g_rg_xa = malloc((g_rg_nx + 1) * sizeof *g_rg_xa); g_rg_xb = malloc((g_rg_nx + 1) * sizeof *g_rg_xb);
    g_rg = calloc((size_t)g_rg_cap, sizeof *g_rg);
    if (!g_rg_idx || !g_rg_touch || !g_rg_tl || !g_rg_pool || !g_rg_free || !g_rg_xa || !g_rg_xb || !g_rg) { LOG("r1: RING: allocation FAILED\n"); return 0; }
    size_t e = 0;
    for (int i = 0; i < g_nx; i++) for (size_t o = 0; o < g_x[i].n; o += PG) { g_rg_xa[e] = g_x[i].a + o; g_rg_xb[e] = g_x[i].b + o; e++; }
    for (int i = 0; i < g_rg_cap; i++) {
        RgSlot *s = &g_rg[i]; s->frame = -1;
        s->ent = (uint32_t *)rg_vres(RG_ENT_RES); s->fpool = rg_vres(RG_FP_RES); s->cbd = rg_vres(RG_CB_RES);
        s->fib = malloc(1024 * sizeof *s->fib); s->cbs = malloc(512 * RG_CBS_SIZE);
        if (!s->ent || !s->fpool || !s->cbd || !s->fib || !s->cbs) { LOG("r1: RING: slot allocation FAILED\n"); return 0; }
    }
    for (int k = 0; k < 5; k++) g_rgc[k] = calloc(RG_NST, sizeof(double));
    g_rgc_pg = calloc(RG_NST, sizeof(size_t)); g_rgc_xp = calloc(RG_NST, sizeof(size_t));
    if (getenv("SSBU_RB_PARK_MS")) g_rg_park_ms = atof(getenv("SSBU_RB_PARK_MS"));
    rg_cb_find(); cp_init();
    LOG("r1: RING on: depth %d frames (%d states), pages: window 1 %zu, window 2 %zu, extras %zu (%.1f MB); pool up to %.0f GB; hold limit %.1f ms\n",
        g_rg_depth, g_rg_cap, g_rg_n1, g_rg_n2, g_rg_nx, g_rg_nx * PG / 1048576.0, (double)RG_POOL_MAX * PG / 1073741824.0, g_rg_park_ms);
    return 1;
}
static RgSlot *rg_slot(int i) { return &g_rg[(g_rg_head + i) % g_rg_cap]; }     /* i = 0 oldest */
void r1_ring_let_go(void) { if (g_rg_kept) { unpark(); g_rg_kept = 0; } }      /* after a capture made with g_rg_keep and no load */
long long r1_ring_oldest(void) { return g_rg_count ? rg_slot(0)->frame : -1; }
long long r1_ring_newest(void) { return g_rg_count ? rg_slot(g_rg_count - 1)->frame : -1; }
double r1_ring_last_ms(int load) { return g_rg_last[load ? 1 : 0]; }
void r1_ring_release(void) {                              /* every slot dropped: the newest values stay (g_rg_idx), the logs' old values go back to the pool */
    for (int i = 0; i < g_rg_count; i++) rg_slot_drop(rg_slot(i), 1);
    g_rg_count = 0; g_rg_head = 0;
}
int r1_ring_capture(long long frame, Ctx *c) {
    double t0 = now_ms();
    if (!g_rg_ready) {                                    /* the first time: r1's full save (shadow filled, marks on: one hitch), the ring's base */
        g_save_failed = 0; g_ra_wd_pause = 1;
        save(c); release();
        g_ra_wd_pause = 0;
        if (g_save_failed) return 0;
        g_ra_ready = 1; g_cycle = 1;
        if (g_mark <= 0) { g_ra_off = 1; LOG("r1: RING: no marks (the game DLL with marks is not loaded): OFF\n"); return 0; }
        if (!rg_init()) { g_ra_off = 1; return 0; }
        g_rg_ready = 1;
        RgSlot *s = &g_rg[0]; g_rg_head = 0; g_rg_count = 1;
        s->frame = frame; s->nent = 0;
        rg_meta_capture(s, &g_ctx_save);
        LOG("r1: RING: base state (frame %lld): full save in %.1f ms\n", frame, now_ms() - t0);
        return 1;
    }
    if (!ra_hold_quiet(g_rg_park_ms)) { g_rg_cap_fail++; if (g_rg_cap_fail <= 20 || g_rg_cap_fail % 100 == 0) LOG("r1: RING: capture %lld (frame %lld) skipped: thread %s not at a wait within %.1f ms\n", g_rg_cap_fail, frame, g_ra_busy ? g_ra_busy : "?", g_rg_park_ms); return 0; }
    double t1 = now_ms();
    if (g_rg_count == g_rg_cap) { rg_slot_drop(rg_slot(0), 1); g_rg_head = (g_rg_head + 1) % g_rg_cap; g_rg_count--; }
    RgSlot *s = rg_slot(g_rg_count);
    s->frame = frame; s->nent = 0; s->pages = 0; s->xpages = 0;
    g_rg_cur = s; g_rg_fail_now = 0;
    rg_sweep(rg_cap_page);
    for (size_t e = 0; e < g_rg_nx && !g_rg_fail_now; e++) {             /* extras: the pages that differ from their newest value */
        uint32_t id = (uint32_t)(g_rg_n1 + g_rg_n2 + e);
        if (!memcmp(g_rg_xa[e], rg_src(id), PG)) continue;
        uint32_t nb = rg_pool_get();
        if (!nb || !rg_push(s, id, g_rg_idx[id])) { if (nb) rg_pool_put(nb); g_rg_fail_now = 1; break; }
        cp_add(rg_pool_ptr(nb), g_rg_xa[e]); g_rg_idx[id] = nb; s->xpages++;
    }
    double t2 = now_ms();
    cp_run();
    double t3 = now_ms();
    fibers_save();
    nvn_r1_cb_save();
    rg_meta_capture(s, c);
    double t4 = now_ms();
    if (g_rg_keep) g_rg_kept = 1;                          /* a load follows at once (r1_ring_load / r1_ring_let_go lets them go) */
    else unpark();                                         /* every thread, the audio ones too (a real pass follows) */
    double t5 = now_ms();
    g_rg_count++; g_rg_caps++;
    if (g_rg_fail_now) {                                   /* out of pool / log room: the newest values are right, the older states are not reachable */
        LOG("r1: RING: capture at frame %lld ran out of room (pool %u buffers): older states dropped\n", frame, g_rg_bump);
        while (g_rg_count > 1) { rg_slot_drop(rg_slot(0), 1); g_rg_head = (g_rg_head + 1) % g_rg_cap; g_rg_count--; }
    }
    g_rg_last[0] = t5 - t0;
    if (g_rgc_n < RG_NST) { int i = g_rgc_n++; g_rgc[0][i] = t5 - t0; g_rgc[1][i] = t1 - t0; g_rgc[2][i] = t2 - t1; g_rgc[3][i] = t3 - t2; g_rgc[4][i] = (t4 - t3) + (t5 - t4); g_rgc_pg[i] = s->pages; g_rgc_xp[i] = s->xpages; }
    return 1;
}
int r1_ring_load(long long frame, Ctx *c) {
    int si = -1;
    for (int i = 0; i < g_rg_count; i++) if (rg_slot(i)->frame == frame) si = i;
    if (si < 0) return 0;
    double t0 = now_ms();
    RgSlot *g = rg_slot(si);
    int k = g_rg_count - 1 - si;
    static Th cur[256]; int ncur = g_rg_kept ? g_nth : 0;  /* threads still held from the capture just made (g_rg_keep) */
    if (ncur) memcpy(cur, g_th, (size_t)ncur * sizeof *cur);
    g_rg_kept = 0;
    g_ninfo = g->ninfo;
    stop_born_threads();
    if (g_nborn) LOG("r1: RING: %d guest threads created after frame %lld, held for good:%s\n", g_nborn, frame, g_born);
    g_nth = g->nth; memcpy(g_th, g->th, (size_t)g->nth * sizeof *g_th);
    if (ncur) g_rg_kept_n++;
    for (int j = 0; j < ncur; j++) {                      /* held at the same wait as in capture g: stays held; otherwise let go (the loop below waits for it) */
        if (!cur[j].held) continue;
        int keep = 0;
        for (int i = 0; i < g_nth; i++) if (g_th[i].h == cur[j].h) { if (g_th[i].parked && cur[j].from == g_th[i].from && cur[j].imp == g_th[i].imp) { g_th[i].held = 1; keep = 1; } break; }
        if (keep) g_rg_kept_same++; else ResumeThread(cur[j].h);
    }
    for (double tq = now_ms();;) {                        /* each thread at the wait it was held at in that capture, no job running */
        ra_hold_restore();
        if (ra_fibers_quiet() || now_ms() - tq > 200) { if (g_ra_busy_fibers) LOG("r1: RING load: %d fibers still busy after 200 ms\n", g_ra_busy_fibers); break; }
        for (int i = 0; i < g_nth; i++) if (g_th[i].held) { ResumeThread(g_th[i].h); g_th[i].held = 0; }
        SwitchToThread();
    }
    double t1 = now_ms();
    g_rg_ntl = 0;
    if (g_rgs_on > 0) rgv_before(si, r1_ring_newest());
    for (int i = g_rg_count - 1; i > si; i--) {           /* undo logs newest first: pointers only */
        RgSlot *s = rg_slot(i);
        for (size_t n = 0; n < s->nent; n++) {
            uint32_t id = s->ent[2 * n], old = s->ent[2 * n + 1];
            rg_pool_put(g_rg_idx[id]); g_rg_idx[id] = old; rg_touch(id);
        }
        rg_slot_drop(s, 0);
    }
    g_rg_count = si + 1;
    rg_sweep(rg_load_page);                                /* written since the newest capture */
    for (size_t e = 0; e < g_rg_nx; e++) rg_touch((uint32_t)(g_rg_n1 + g_rg_n2 + e));
    size_t pages = g_rg_ntl;
    for (size_t n = 0; n < g_rg_ntl; n++) {               /* each page once, from its value at `frame` */
        uint32_t id = g_rg_tl[n]; g_rg_touch[id] = 0;
        uint8_t *a = rg_addr(id), *src = rg_src(id);
        if (src == (uint8_t *)1) continue;                 /* decommitted then: left as it is */
        if (id < g_rg_n1 && g_dc[id]) { if (!src) continue; VirtualAlloc(a, PG, MEM_COMMIT, PAGE_READWRITE); g_dc[id] = 0; }
        if (!src) memset(a, 0, PG); else cp_add(a, src);
    }
    cp_run();
    double t2 = now_ms();
    g_nfib = g->nfib; memcpy(g_fib, g->fib, (size_t)g->nfib * sizeof *g_fib);
    if (g->fpool_used) memcpy(g_fpool, g->fpool, g->fpool_used);
    g_fpool_used = g->fpool_used;
    restore_thread_regs();
    fibers_restore_all();
    rg_cb_load(g);
    double t3 = now_ms();
    unpark();
    *c = g->ctx;
    g_rg_loads++;
    if (g_th_mismatch || g_fib_diff) LOG("r1: RING load of frame %lld (k %d): %d threads not at their wait, %d fibers not restored\n", frame, k, g_th_mismatch, g_fib_diff);
    g_rg_last[1] = now_ms() - t0;
    if (k < RG_MAXSLOT && g_rgl_n[k] < RG_NL) { int i = g_rgl_n[k]++; g_rgl[k][i][0] = now_ms() - t0; g_rgl[k][i][1] = t1 - t0; g_rgl[k][i][2] = t2 - t1; g_rgl_pg[k][i] = pages; (void)t3; }
    return 1;
}

/* ---------------------------------------------------------------- the rollback simulation (SSBU_RB_SIM) */
static int g_rgs_on = -1, g_rgs_n = 10, g_rgs_k = 7, g_rgs_warm = 30, g_rgs_skip, g_rgs_left, g_rgs_ki;
static long long g_rgs_next, g_rgs_real_since, g_rgs_done, g_rgs_nocap, g_rgs_padmiss, g_rgs_ksum[RG_MAXSLOT];
static PadRec g_rgs_pad[256]; static long long g_rgs_padf[256]; static int g_rgs_polls_cur; static long long g_rgs_multi;
static double g_rgs_pass_t0, g_rgs_pass[2]; static long long g_rgs_npass[2];
static double g_rgs_pass_v[2][RG_NST / 4]; static int g_rgs_pass_nv[2];
static int rgs_wanted(void) {
    if (g_rgs_on < 0) { const char *e = getenv("SSBU_RB_SIM"); g_rgs_on = e && e[0] && e[0] != '0'; if (g_rgs_on) sscanf(e, "%d,%d,%d", &g_rgs_n, &g_rgs_k, &g_rgs_warm); if (g_rgs_k < 1) g_rgs_k = 1; if (g_rgs_k > RG_MAXSLOT - 1) g_rgs_k = RG_MAXSLOT - 1; if (g_rgs_n < 1) g_rgs_n = 1; }
    return g_rgs_on;
}
static void rgs_report(void);
/* at the safe point (H2) of every pass while the fight runs */
static void rgs_step(Ctx *c) {
    double t = now_ms();
    if (g_rgs_pass_t0 > 0 && g_rg_ready) {                /* the pass that just ended: real (0) or re-run (1), without the capture / load */
        int kd = g_ra_phase == 2; double d = t - g_rgs_pass_t0;
        g_rgs_pass[kd] += d; g_rgs_npass[kd]++; if (g_rgs_pass_nv[kd] < RG_NST / 4) g_rgs_pass_v[kd][g_rgs_pass_nv[kd]++] = d;
    }
    if (g_rgs_polls_cur > 1) g_rgs_multi++;
    g_rgs_polls_cur = 0;
    if (g_ra_off || !ra_fight_on()) { if (g_ra_phase) g_ra_after_quiet = 1; g_ra_phase = 0; g_rgs_left = 0; g_rgs_pass_t0 = 0; return; }
    long long i = g_rgs_next;                             /* the pass that ended here */
    if (g_rg_keep_on < 0) { const char *e = getenv("SSBU_RB_KEEP"); g_rg_keep_on = !e || atoi(e) != 0; }
    {   /* will a load follow this capture? then the threads stay held from the capture to the load (SSBU_RB_KEEP=0: not) */
        int ph = g_ra_phase == 2 && g_rgs_left - 1 <= 0 ? 0 : g_ra_phase;
        g_rg_keep = g_rg_keep_on && g_rg_ready && ph == 0 && g_rg_caps + 1 >= g_rgs_warm && g_rgs_real_since + (ph == 0) >= g_rgs_n;
    }
    int ok = r1_ring_capture(i, c);
    g_rg_keep = 0;
    if (g_rgv_target >= 0 && i == g_rgv_target) { if (ok) rgv_after(); else g_rgv_target = -1; }
    if (!g_rg_ready) { g_rgs_pass_t0 = 0; return; }
    if (!ok) g_rgs_nocap++;
    if (g_ra_phase == 2 && --g_rgs_left <= 0) { g_ra_phase = 0; g_ra_after_quiet = 1; g_rgs_left = 0; }
    g_rgs_next = i + 1;
    if (g_ra_phase == 0) g_rgs_real_since++;
    if (g_ra_phase == 0 && ok && g_rg_caps >= g_rgs_warm && g_rgs_real_since >= g_rgs_n) {
        int k = 1 + g_rgs_ki % g_rgs_k;
        long long target = i - k, best = -1;
        for (int s = 0; s < g_rg_count; s++) { long long f = rg_slot(s)->frame; if (f <= target && f > best) best = f; }
        if (best >= 0 && r1_ring_load(best, c)) {
            g_rgs_ki++; g_rgs_real_since = 0; g_rgs_done++;
            g_rgs_left = (int)(i - best); g_rgs_next = best + 1; g_ra_phase = 2;
            if (g_rgs_left < RG_MAXSLOT) g_rgs_ksum[g_rgs_left]++;
            if (g_rgs_done <= 30 || g_rgs_done % 50 == 0) LOG("r1: RB SIM: rollback %lld at pass %lld (fight frame %lld) to pass %lld (k %d) in %.3f ms\n", g_rgs_done, i, g_ff, best, g_rgs_left, g_rg_last[1]);
        }
    }
    r1_ring_let_go();                                     /* (no load after a kept capture) */
    g_rgs_pass_t0 = now_ms(); g_ra_t_mark = g_rgs_pass_t0;
}
/* ---- logic-only re-run (R2_logic_only_study.md section 6): presentation-side callees of the main loop skipped in re-run passes
 * but the last (SSBU_RB_SIM_LITE=<mask>: 1 camera, 2 UI, 4 lighting, 8 render layers, 16 recorder, 32 dynamic resolution,
 * 64 effect emitter tick); only when called from the main loop FUN 0x7103747270. SSBU_RB_SIM_PROF=1: the same hooks time their
 * calls (real and re-run passes) without skipping anything. */
typedef struct { uint64_t a; int grp; uint64_t ret; ImportFn orig; long long n[2], sk; double ms[2]; } RgsLite;
static RgsLite g_rgl_h[] = {
    {0x710361d040ull, 1, 0}, {0x71036186d0ull, 1, 0}, {0x7103864700ull, 1, 0}, {0x7103619080ull, 1, 0}, {0x7103618b80ull, 1, 0},
    {0x7103632850ull, 2, 0}, {0x710361e7e0ull, 2, 0}, {0x71035c13d0ull, 2, 0},
    {0x7103575fa0ull, 4, 0}, {0x7103575c60ull, 4, 0}, {0x71035763c0ull, 4, 0}, {0x7103593c40ull, 4, 0},
    {0x71037857f0ull, 8, 0},
    {0x71036f2c00ull, 16, 0}, {0x71036f2d40ull, 16, 0}, {0x71036e6e00ull, 16, 0}, {0x71036f7410ull, 16, 1},
    {0x7103618ef0ull, 32, 0},
    {0x710356d7a0ull, 64, 0},
};
#define RGL_N ((int)(sizeof g_rgl_h / sizeof g_rgl_h[0]))
static int g_rgs_lite, g_rgs_prof; static uint64_t g_rgl_lo, g_rgl_hi;
static void rgs_lite_hook(Ctx *c, void *user) {
    RgsLite *h = user; uint64_t lr = c->x[30];
    int inloop = lr >= g_rgl_lo && lr < g_rgl_hi, kd = g_ra_phase == 2;
    if (inloop && (g_rgs_lite & h->grp) && g_rgs_on > 0 && g_ra_phase == 2 && g_rgs_left > 1) { h->sk++; c->x[0] = h->ret; return; }
    if (!g_rgs_prof || !inloop) { h->orig(c); return; }
    double t = now_ms(); h->orig(c); h->ms[kd] += now_ms() - t; h->n[kd]++;
}
static void rgs_lite_init(void) {
    const char *e = getenv("SSBU_RB_SIM_LITE"); g_rgs_lite = e ? atoi(e) : 0; g_rgs_prof = getenv("SSBU_RB_SIM_PROF") != NULL;
    if (!g_rgs_lite && !g_rgs_prof) return;
    g_rgl_lo = GA(0x7103747270ull); g_rgl_hi = GA(0x710374e000ull);
    int ok = 0;
    for (int i = 0; i < RGL_N; i++) if ((g_rgs_prof || (g_rgs_lite & g_rgl_h[i].grp)) && hook_install(GA(g_rgl_h[i].a), rgs_lite_hook, &g_rgl_h[i], &g_rgl_h[i].orig)) ok++;
    LOG("r1: RB SIM logic-only re-run: skip mask %d, profile %d: %d hooks installed\n", g_rgs_lite, g_rgs_prof, ok);
}
static void rgs_lite_report(void) {
    if (!g_rgs_lite && !g_rgs_prof) return;
    for (int i = 0; i < RGL_N; i++) if (g_rgl_h[i].orig) LOG("r1: RB SIM lite %llx (group %d): skipped %lld; timed real %lld calls %.4f ms/call, re-run %lld calls %.4f ms/call\n", (unsigned long long)g_rgl_h[i].a, g_rgl_h[i].grp, g_rgl_h[i].sk,
        g_rgl_h[i].n[0], g_rgl_h[i].n[0] ? g_rgl_h[i].ms[0] / g_rgl_h[i].n[0] : 0, g_rgl_h[i].n[1], g_rgl_h[i].n[1] ? g_rgl_h[i].ms[1] / g_rgl_h[i].n[1] : 0);
}
/* ---- SSBU_RB_SIM_VERIFY=1: every rollback, the whole tracked state is compared, not only the fighters' hash: at the load, a hash of the
 * NEWEST value of every page the newer slots changed; when the re-run is back at that pass, the same pages (and every page the re-run
 * wrote that the original window did not: against its value at the loaded state). Window pages and extras counted apart. */
static int g_rgv_on = -1; static uint8_t *g_rgv_in; static uint32_t *g_rgv_id; static uint64_t *g_rgv_h; static size_t g_rgv_n;
#define RGV_MAX (8u << 20)
static long long g_rgv_target = -1, g_rgv_from, g_rgv_runs, g_rgv_bad_runs, g_rgv_pages, g_rgv_diff[3];
static uint64_t rgv_hash(const uint8_t *p) {
    if (!p) return 0x9e3779b97f4a7c15ull;
    if (p == (uint8_t *)1) return 1;
    const uint64_t *q = (const uint64_t *)p; uint64_t h = 1469598103934665603ull;
    for (int i = 0; i < PG / 8; i++) h = (h ^ q[i]) * 1099511628211ull + (h >> 29);
    return h;
}
static uint8_t *rg_src_v(uint32_t id, uint32_t v) { uint32_t s = g_rg_idx[id]; g_rg_idx[id] = v; uint8_t *r = rg_src(id); g_rg_idx[id] = s; return r; }
static void rgv_before(int si, long long target) {        /* in r1_ring_load, before the undo logs are applied */
    if (g_rgv_on < 0) g_rgv_on = getenv("SSBU_RB_SIM_VERIFY") != NULL;
    if (!g_rgv_on) return;
    size_t tot = g_rg_n1 + g_rg_n2 + g_rg_nx;
    if (!g_rgv_in) { g_rgv_in = calloc(tot, 1); g_rgv_id = malloc((size_t)RGV_MAX * 4); g_rgv_h = malloc((size_t)RGV_MAX * 8); }
    g_rgv_n = 0;
    for (int i = g_rg_count - 1; i > si; i--) {
        RgSlot *s = rg_slot(i);
        for (size_t n = 0; n < s->nent; n++) {
            uint32_t id = s->ent[2 * n]; if (g_rgv_in[id] || g_rgv_n >= RGV_MAX / 2) continue;
            g_rgv_in[id] = 1; g_rgv_id[g_rgv_n] = id; g_rgv_h[g_rgv_n] = rgv_hash(rg_src(id)); g_rgv_n++;
        }
    }
    g_rgv_target = target; g_rgv_from = rg_slot(si)->frame;
}
static int rgv_kind(uint32_t id) { return id < g_rg_n1 ? 0 : id < g_rg_n1 + g_rg_n2 ? 1 : 2; }
/* differing pages by 64 KB block (where() name of the block), over every rollback: which memory is not reproduced */
#define RGV_NB 4096
static struct { uint64_t blk; long long n, runs; long long last; } g_rgv_b[RGV_NB]; static int g_rgv_nb;
static void rgv_note(uint32_t id) {
    uint64_t blk = (uint64_t)(uintptr_t)rg_addr(id) >> 16;
    for (int i = 0; i < g_rgv_nb; i++) if (g_rgv_b[i].blk == blk) { g_rgv_b[i].n++; if (g_rgv_b[i].last != g_rgv_runs) { g_rgv_b[i].runs++; g_rgv_b[i].last = g_rgv_runs; } return; }
    if (g_rgv_nb < RGV_NB) { g_rgv_b[g_rgv_nb].blk = blk; g_rgv_b[g_rgv_nb].n = 1; g_rgv_b[g_rgv_nb].runs = 1; g_rgv_b[g_rgv_nb].last = g_rgv_runs; g_rgv_nb++; }
}
static int rgv_cmpb(const void *a, const void *b) { long long x = ((const long long *)a)[1], y = ((const long long *)b)[1]; return x < y ? 1 : x > y ? -1 : 0; }
static void rgv_blocks_report(void) {
    if (!g_rgv_nb) return;
    qsort(g_rgv_b, (size_t)g_rgv_nb, sizeof g_rgv_b[0], rgv_cmpb);
    char b[3000]; int o = 0;
    for (int i = 0; i < g_rgv_nb && i < 40 && o < 2900; i++) o += snprintf(b + o, sizeof b - o, " [%s: %lld pages, %lld rollbacks]", where((uint8_t *)(uintptr_t)(g_rgv_b[i].blk << 16)), g_rgv_b[i].n, g_rgv_b[i].runs);
    b[o] = 0;
    LOG("r1: RB VERIFY differing 64 KB blocks (%d, the 40 largest):%s\n", g_rgv_nb, b);
}
static void rgv_after(void) {                               /* right after the capture of the re-run pass that reached the target */
    long long d[3] = {0, 0, 0}, pages = (long long)g_rgv_n; char first[400]; int o = 0; first[0] = 0;
    for (size_t n = 0; n < g_rgv_n; n++) {
        uint32_t id = g_rgv_id[n];
        if (rgv_hash(rg_src(id)) != g_rgv_h[n]) { int k = rgv_kind(id); d[k]++; rgv_note(id); if (o < 330 && d[k] <= 3) o += snprintf(first + o, sizeof first - o, " %s", where(rg_addr(id))); }
    }
    size_t extra = 0;
    for (int i = 0; i < g_rg_count; i++) {                  /* pages the re-run wrote that the original window did not */
        RgSlot *s = rg_slot(i); if (s->frame <= g_rgv_from || s->frame > g_rgv_target) continue;
        for (size_t n = 0; n < s->nent; n++) {
            uint32_t id = s->ent[2 * n]; if (g_rgv_in[id]) continue;
            if (g_rgv_n + extra >= RGV_MAX) continue;
            g_rgv_in[id] = 2; g_rgv_id[g_rgv_n + extra++] = id;
            pages++;
            if (rgv_hash(rg_src(id)) != rgv_hash(rg_src_v(id, s->ent[2 * n + 1]))) { int k = rgv_kind(id); d[k]++; rgv_note(id); if (o < 330 && d[k] <= 3) o += snprintf(first + o, sizeof first - o, " %s(re-run only)", where(rg_addr(id))); }
        }
    }
    for (size_t n = 0; n < g_rgv_n + extra; n++) g_rgv_in[g_rgv_id[n]] = 0;
    g_rgv_runs++; g_rgv_pages += pages; for (int k = 0; k < 3; k++) g_rgv_diff[k] += d[k];
    if (d[0] || d[1]) g_rgv_bad_runs++;
    if (d[0] || d[1] || d[2] || g_rgv_runs <= 5) LOG("r1: RB VERIFY rollback to %lld, back at %lld: %lld pages compared; differ: window 1 %lld, window 2 %lld, extras %lld;%s\n", g_rgv_from, g_rgv_target, pages, d[0], d[1], d[2], first);
    g_rgv_target = -1;
}
static int rgs_skip_now(void) { return g_rgs_on > 0 && g_ra_phase == 2 && g_rgs_left > 1 ? g_rgs_skip : 0; }
static int rgs_poll(void) { g_rgs_polls_cur++; return g_ra_phase == 2; }    /* a re-run pass: the input sequence waits */
static void rgs_pad(uint64_t *b, int *lx, int *ly, int *rx, int *ry) {
    long long p = g_rgs_next; int x = (int)(p & 255);
    if (g_ra_phase == 2) {
        if (g_rgs_padf[x] == p) { PadRec r = g_rgs_pad[x]; *b = r.b; *lx = r.lx; *ly = r.ly; *rx = r.rx; *ry = r.ry; } else g_rgs_padmiss++;
    } else { PadRec r = {*b, *lx, *ly, *rx, *ry}; g_rgs_pad[x] = r; g_rgs_padf[x] = p; }
}
static int cmp_d(const void *a, const void *b);
static double rg_pct(const double *v, int n, int p) {
    if (n <= 0) return 0;
    double *w = malloc((size_t)n * sizeof *w); memcpy(w, v, (size_t)n * sizeof *w); qsort(w, (size_t)n, sizeof *w, cmp_d);
    double r = w[(size_t)n * p / 100 < (size_t)n ? (size_t)n * p / 100 : (size_t)n - 1]; free(w); return r;
}
static double rg_mean(const double *v, int n) { double s = 0; for (int i = 0; i < n; i++) s += v[i]; return n ? s / n : 0; }
static void rgs_report(void) {
    if (!g_rg_ready) return;
    int n = g_rgc_n; double pg = 0, xp = 0; for (int i = 0; i < n; i++) { pg += (double)g_rgc_pg[i]; xp += (double)g_rgc_xp[i]; }
    LOG("r1: RING report: %lld captures (%lld skipped: a thread not at a wait), %lld loads, %u pool buffers made (%.1f MB), %u free; log overflows %lld\n",
        g_rg_caps, g_rg_cap_fail, g_rg_loads, g_rg_bump, g_rg_bump * (double)PG / 1048576.0, g_rg_nfree, g_rg_overflow);
    LOG("r1: RING loads right after a capture with the threads kept held: %lld (threads kept at the same wait: %lld); fibers %d (last); stale fiber-block notes refused %lld\n", g_rg_kept_n, g_rg_kept_same, g_nfib, g_r1_fls_stale);
    LOG("r1: RING capture: median %.3f mean %.3f p99 %.3f ms; parts (means): hold %.3f, sweep + undo log %.3f, page copy (parallel) %.3f, fibers + threads + command buffers + let go %.3f; pages %.0f + extras %.0f mean (%.1f MB)\n",
        rg_pct(g_rgc[0], n, 50), rg_mean(g_rgc[0], n), rg_pct(g_rgc[0], n, 99), rg_mean(g_rgc[1], n), rg_mean(g_rgc[2], n), rg_mean(g_rgc[3], n), rg_mean(g_rgc[4], n), n ? pg / n : 0, n ? xp / n : 0, n ? (pg + xp) / n * PG / 1048576.0 : 0);
    for (int k = 0; k < RG_MAXSLOT; k++) {
        int m = g_rgl_n[k]; if (!m) continue;
        static double v[RG_NL], h[RG_NL], cpy[RG_NL]; double p = 0;
        for (int i = 0; i < m; i++) { v[i] = g_rgl[k][i][0]; h[i] = g_rgl[k][i][1]; cpy[i] = g_rgl[k][i][2]; p += (double)g_rgl_pg[k][i]; }
        LOG("r1: RING load k %d (%d): median %.3f mean %.3f p99 %.3f ms (hold %.3f, undo + page copy %.3f, rest %.3f); pages copied %.0f mean (%.1f MB)\n",
            k, m, rg_pct(v, m, 50), rg_mean(v, m), rg_pct(v, m, 99), rg_mean(h, m), rg_mean(cpy, m), rg_mean(v, m) - rg_mean(h, m) - rg_mean(cpy, m), p / m, p / m * PG / 1048576.0);
    }
    if (g_rgs_on > 0) {
        if (g_rgv_on > 0) rgv_blocks_report();
        if (g_rgv_on > 0) LOG("r1: RB VERIFY: %lld rollbacks checked, %lld with window pages differing; pages compared %lld; differ: window 1 %lld, window 2 %lld, extras %lld\n", g_rgv_runs, g_rgv_bad_runs, g_rgv_pages, g_rgv_diff[0], g_rgv_diff[1], g_rgv_diff[2]);
        rgs_lite_report();
        LOG("r1: RB SIM: %lld rollbacks (k: 1 %lld, 2 %lld, 3 %lld, 4 %lld, 5 %lld, 6 %lld, 7 %lld), captures failed %lld, re-run pads missing %lld, passes with more than one poll %lld\n",
            g_rgs_done, g_rgs_ksum[1], g_rgs_ksum[2], g_rgs_ksum[3], g_rgs_ksum[4], g_rgs_ksum[5], g_rgs_ksum[6], g_rgs_ksum[7], g_rgs_nocap, g_rgs_padmiss, g_rgs_multi);
        LOG("r1: RB SIM passes (safe point to safe point, without the capture / load): real %lld mean %.3f median %.3f ms; re-run %lld mean %.3f median %.3f ms (kick skip mask in re-run passes but the last: %d)\n",
            g_rgs_npass[0], g_rgs_npass[0] ? g_rgs_pass[0] / g_rgs_npass[0] : 0, rg_pct(g_rgs_pass_v[0], g_rgs_pass_nv[0], 50), g_rgs_npass[1], g_rgs_npass[1] ? g_rgs_pass[1] / g_rgs_npass[1] : 0, rg_pct(g_rgs_pass_v[1], g_rgs_pass_nv[1], 50), g_rgs_skip);
        for (int k = 0; k < 3; k += 2) if (g_rapn[k]) LOG("r1: RB SIM %s passes (%lld), means ms: pass start -> poll %.3f, poll -> frame end %.3f, frame end call %.3f, frame end -> safe point %.3f\n",
            k == 0 ? "real" : "re-run", g_rapn[k], g_rap[k][0] / g_rapn[k], g_rap[k][1] / g_rapn[k], g_rap[k][2] / g_rapn[k], g_rap[k][3] / g_rapn[k]);
    }
}
