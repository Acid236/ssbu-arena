/* Fighter source: host side. #included by nnro.c (it uses nnro.c's module tables); not compiled on its own
 * (after editing this file, touch nnro.c: build.py looks at nnro.c's date).
 *
 * When the game loads a script module lua2cpp_<name>, fighters_bin\<name>.dll is loaded if it exists
 * (fighter_sdk\tools\build_fighter.py). It lists the script functions it has as C++ source by their offset in the
 * module; nro_call_indirect asks fighter_dispatch first, so the game runs the source instead of the lifted code.
 *
 *   SSBU_FIGHTER_SRC=0            do not load fighter DLLs (everything lifted)
 *   SSBU_FIGHTER_LIFTED=1         load, but run everything lifted;  =name1,name2  only these scripts lifted
 *   SSBU_FIGHTER_DIFF=1           differential test on every call of a script that has source: the lifted function runs
 *                                 for real while its calls into the game are recorded (name, arguments, results); then the
 *                                 source runs from the same arguments with every game call answered from the recording
 *                                 and compared. Equal = same calls in the same order with the same arguments.
 *                                 lib::L2CValue's own value functions (constructors, conversions) are not events: the
 *                                 source builds values natively; what is compared is the VALUE handed to the game.
 *   SSBU_FIGHTER_REPORT=<file>    where the per-function table goes (default fighter_report.txt); rewritten when a
 *                                 module is unloaded and every 2000 dispatched calls
 *   SSBU_FIGHTER_TRACE=<text>     print every game call made by source scripts whose name contains <text>
 *
 * Scripts run on FIBERS (os_threads.c): a script waits inside app::sv_animcmd::frame()/wait() by switching fibers and
 * goes on later, or is ended there for good by an exception (nnunwind.c) when the motion changes. So all state of a
 * running script is per fiber (FLS), a recording can span many game frames, and a recording whose script was ended
 * is compared as a PREFIX ("interrupted"): the source must make the same calls up to the one that never returned.
 */
#include <setjmp.h>
typedef struct { void (*call)(Ctx *, int); void (*log)(const char *); Ctx *(*ctx)(void); void (*call_addr)(Ctx *, uint64_t); } FsHost;
typedef struct { uint32_t off; const char *name; void (*fn)(Ctx *); } FsOverride;
typedef struct { const char *name; const char *spec; } FsSym;
typedef struct { const FsSym *syms; int sym_count; uint64_t *addr; const FsOverride *ovr; int ovr_count; } FsTable;
typedef void (*FsBindFn)(const FsHost *, FsTable *);

typedef struct { long long calls, equal, partial, differ, synth_equal, synth_differ, synth_cut; int lifted; char first[200]; } FsStat;
typedef struct FsMod {
    NroModule *mod;
    HMODULE dll;
    char loaded_path[MAX_PATH * 2];
    FsTable t;
    ImportFn *fn;                 /* per slot: lifted function to call directly, or NULL */
    unsigned char *pure;          /* per slot: lib::L2CValue value function (not an event) */
    unsigned char *local;         /* per slot: a function defined in this module */
    int *slot_of_sym;             /* module dynamic symbol index -> slot, -1 */
    FsOverride *ovr;              /* sorted by offset */
    FsStat *stat;
    int ovr_count, synth_done;
} FsMod;

#define FS_MAX_EVENTS 8192
typedef struct {
    const char *name; const char *spec;
    uint64_t x[8]; uint32_t f[8]; uint8_t lv[8][16];
    uint64_t r_x0; V128 r_v0; uint8_t sret[16]; uint64_t x8; int done;
    uint64_t target;              /* a call through a function pointer: the address called */
} FsEvent;

typedef struct {
    FsMod *mod; const char *script; Ctx *ctx;      /* the source script running on this fiber */
    int rec, replay, partial, depth, count, pos, bad, synth, cut, inlifted;
    unsigned synth_n;
    FsMod *rec_mod; int rec_at; uint64_t rec_sp; uintptr_t rec_host; uint64_t entry[32];
    uint64_t res_at; uint8_t res_before[16];       /* S3: result buffer of the function under test */
    uint64_t lr;                                   /* S3: return address the running source function was called with */
    FsEvent *ev;
    char why[200];
    jmp_buf jb, synth_jb;
} FsFiber;
#define FS_SYNTH_CAP 400                           /* synthetic test: calls after which a run of the original is cut */
static int g_fs_offline;                           /* SSBU_FIGHTER_OFFLINE: modules are loaded by fighter_offline, the game never starts */

static DWORD g_fs_fls = FLS_OUT_OF_INDEXES;
static volatile LONG g_fs_recording;               /* recordings in flight (fast test in nro_import_host) */
static FsMod *g_fs_mods[128];
static int g_fs_mod_count;
static long long g_fs_dispatched, g_fs_interrupted;
static FsMod *g_fs_export_mod;
static int fighter_export_override(Ctx *c, uint64_t addr, ImportFn lifted);

static FsFiber *fs_fiber(void) {
    FsFiber *ff = FlsGetValue(g_fs_fls);
    if (!ff) { ff = calloc(1, sizeof *ff); FlsSetValue(g_fs_fls, ff); }
    return ff;
}

static int fs_is_pure(const char *n) {
    if (strstr(n, "push_variadic")) return 0;          /* hands the script's result to the caller: an event */
    return strncmp(n, "_ZN3lib8L2CValue", 16) == 0 || strncmp(n, "_ZNK3lib8L2CValue", 17) == 0;
}

static void fs_capture(FsEvent *e, const Ctx *c, const char *name, const char *spec) {
    e->name = name; e->spec = spec; e->x8 = c->x[8]; e->done = 0;
    for (int i = 0; i < 8; i++) { e->x[i] = c->x[i]; e->f[i] = c->v[i].w[0]; }
    int xi = 0;
    for (const char *p = spec ? spec : ""; *p; p++) {
        if (*p == 'S' || *p == 'f') continue;
        if (*p == 'V' && xi < 8 && c->x[xi]) memcpy(e->lv[xi], (const void *)(uintptr_t)c->x[xi], 16);
        xi++;
    }
}

/* same arguments? compares what the description says each register carries */
static int fs_same(const FsEvent *a, const FsEvent *b, char *why, size_t n) {
    if (strcmp(a->name, b->name) != 0) { snprintf(why, n, "calls %.60s where the original calls %.60s", b->name, a->name); return 0; }
    int xi = 0, fi = 0, k = 0;
    for (const char *p = a->spec ? a->spec : ""; *p; p++, k++) {
        uint64_t u = a->x[xi & 7], v = b->x[xi & 7], mask = ~0ull;
        if (*p == 'S') { k--; continue; }
        if (*p == 'f') { if (a->f[fi] != b->f[fi]) { snprintf(why, n, "%.60s: float argument %d is %g, original %g", a->name, k, *(const float *)&b->f[fi], *(const float *)&a->f[fi]); return 0; } fi++; continue; }
        if (*p == 'V') {
            uint32_t ta, tb; uint64_t ra, rb;
            memcpy(&ta, a->lv[xi], 4); memcpy(&tb, b->lv[xi], 4); memcpy(&ra, a->lv[xi] + 8, 8); memcpy(&rb, b->lv[xi] + 8, 8);
            uint64_t m = ta == 0 ? 0 : ta == 1 ? 1 : ta == 3 ? 0xffffffffull : ~0ull;
            if (ta != tb || ((ra ^ rb) & m)) { snprintf(why, n, "%.60s: value %d is type %u %llx, original type %u %llx", a->name, k, tb, (unsigned long long)rb, ta, (unsigned long long)ra); return 0; }
            xi++; continue;
        }
        if (*p == 'i') mask = 0xffffffffull; else if (*p == 'b') mask = 1; else if (*p == 'H') mask = 0xffffffffffull;
        if ((u ^ v) & mask) { snprintf(why, n, "%.60s: argument %d is %llx, original %llx", a->name, k, (unsigned long long)(v & mask), (unsigned long long)(u & mask)); return 0; }
        xi++;
    }
    return 1;
}

static void fs_trace_event(const char *script, const char *name, const char *spec, const Ctx *c) {
    char line[600]; int o = snprintf(line, sizeof line, "[fs] %s: %.70s(", script ? script : "?", name);
    int xi = 0, fi = 0;
    for (const char *p = spec ? spec : ""; *p && o < 520; p++) {
        if (*p == 'S') continue;
        if (*p == 'f') { o += snprintf(line + o, sizeof line - o, "%g ", (double)c->v[fi++].f[0]); continue; }
        if (*p == 'V' && c->x[xi]) {
            uint32_t t = rd32(c->x[xi]); uint64_t r = rd64(c->x[xi] + 8); float fl; memcpy(&fl, &r, 4);
            if (t == 3) o += snprintf(line + o, sizeof line - o, "num %g ", (double)fl);
            else o += snprintf(line + o, sizeof line - o, "%s %lld ", t == 0 ? "nil" : t == 1 ? "bool" : t == 2 ? "int" : t == 7 ? "hash" : "other", (long long)r);
        } else if (*p != 'p' && *p != 'T') o += snprintf(line + o, sizeof line - o, "%lld ", (long long)c->x[xi]);
        xi++;
    }
    printf("%s)\n", line);
}

/* replay: the next recorded call must be this one; it is answered from the recording */
static void fs_replay_event(FsFiber *ff, Ctx *c, const char *name, const char *spec) {
    FsEvent now;
    fs_capture(&now, c, name, spec);
    if (ff->pos >= ff->count) {
        if (ff->partial) longjmp(ff->jb, 1);                /* the original was ended here: so is the comparison */
        if (!ff->bad) snprintf(ff->why, sizeof ff->why, "calls %.80s after the original had finished (call %d)", name, ff->pos);
        ff->bad = 1; longjmp(ff->jb, 1);                    /* S2: a difference ends the replay (what follows has no answers) */
    }
    FsEvent *e = &ff->ev[ff->pos++];
    if (!ff->bad && !fs_same(e, &now, ff->why, sizeof ff->why)) ff->bad = 1;
    if (ff->bad || !e->done) longjmp(ff->jb, 1);            /* a difference, or the call the original never came back from */
    c->x[0] = e->r_x0; c->v[0] = e->r_v0;
    if (spec[0] == 'S' && c->x[8]) memcpy((void *)(uintptr_t)c->x[8], e->sret, 16);
}
static volatile LONG g_fs_replaying;
/* nro_import_host during a replay: lifted code of the module under test (run by fs_call, see there) calls an import */
static int fighter_replay_import(Ctx *c, NroModule *m, int sym) {
    FsFiber *ff = FlsGetValue(g_fs_fls);
    if (!ff || !ff->replay || !ff->inlifted || ff->rec_mod->mod != m) return 0;
    const char *name = m->syms[sym].name;
    if (fs_is_pure(name)) return 0;
    int slot = ff->rec_mod->slot_of_sym[sym];
    fs_replay_event(ff, c, name, slot >= 0 ? ff->rec_mod->t.syms[slot].spec : "");
    return 1;
}

/* a source script calls the game function behind `slot` */
static void fs_call(Ctx *c, int slot) {
    FsFiber *ff = fs_fiber();
    FsMod *fm = ff->mod;
    const FsSym *s = &fm->t.syms[slot];
    static int trace = -1;
    if (trace < 0) trace = getenv("SSBU_FIGHTER_TRACE") != NULL;
    if (trace && !ff->replay && ff->script && strstr(ff->script, getenv("SSBU_FIGHTER_TRACE"))) fs_trace_event(ff->script, s->name, s->spec, c);
    if (ff->replay && !fm->pure[slot]) {
        /* S2: a function of this same module that the original calls DIRECTLY (not through its import table) left no
         * event of its own in the recording, only the calls it made: here its lifted code runs, and those calls are
         * answered from the recording (fighter_replay_import). */
        if (fm->local[slot] && fm->fn[slot] && (ff->pos >= ff->count || strcmp(ff->ev[ff->pos].name, s->name) != 0)) {
            ff->inlifted++; fm->fn[slot](c); ff->inlifted--;
            return;
        }
        fs_replay_event(ff, c, s->name, s->spec);
        return;
    }
    if (g_fs_export_mod && !g_fs_hookmode && !ff->replay && fighter_export_override(c, fm->t.addr[slot], fm->fn[slot])) return;   /* source calls source */
    /* S3: a source function has no frame on the game's stack. What it calls must see the return address the source
     * function itself was called with (as after a tail call), not whatever the last lifted call left in x30:
     * the exception unwinder (nnunwind.c) walks the game's frames by these addresses. */
    if (ff->lr) c->x[30] = ff->lr;
    if (fm->fn[slot]) fm->fn[slot](c); else call_indirect(c, fm->t.addr[slot]);
}

static void fs_log(const char *s) { printf("%s\n", s); }
static Ctx *fs_get_ctx(void) { return fs_fiber()->ctx; }

/* S2: a script function called through a pointer taken from a table (global_table's "uniq" functions).
 * It is one event of the differential test: (agent, target address) -> the L2CValue it returns. */
static const char FS_PTR_NAME[] = "(function pointer)";
static void fs_call_addr(Ctx *c, uint64_t addr) {
    FsFiber *ff = fs_fiber();
    if (!ff->replay) { call_indirect(c, addr); return; }
    FsEvent now;
    fs_capture(&now, c, FS_PTR_NAME, "ST");
    if (ff->pos >= ff->count) {
        if (ff->partial) longjmp(ff->jb, 1);
        if (!ff->bad) snprintf(ff->why, sizeof ff->why, "calls a function pointer after the original had finished (call %d)", ff->pos);
        ff->bad = 1; longjmp(ff->jb, 1);
    }
    FsEvent *e = &ff->ev[ff->pos++];
    if (!ff->bad && (!fs_same(e, &now, ff->why, sizeof ff->why) || e->target != addr)) {
        if (!ff->why[0]) snprintf(ff->why, sizeof ff->why, "calls the function at %llx, original %llx", (unsigned long long)addr, (unsigned long long)e->target);
        ff->bad = 1;
    }
    if (ff->bad || !e->done) longjmp(ff->jb, 1);
    c->x[0] = e->r_x0; c->v[0] = e->r_v0;
    if (c->x[8]) memcpy((void *)(uintptr_t)c->x[8], e->sret, 16);
}
static const FsHost g_fs_host = {fs_call, fs_log, fs_get_ctx, fs_call_addr};

static int fighter_synth_answer(Ctx *c, FsEvent *e);
static FsMod *g_fs_export_mod;                     /* lua2cpp_common with source: its functions are also reached by name (imports) */

/* S2: module `m` calls its import `sym` (or source calls address `addr`): if that is a function of lua2cpp_common that
 * exists as source, run the source. Returns 1 if handled. */
static int fighter_export_override(Ctx *c, uint64_t addr, ImportFn lifted) {
    FsMod *xm = g_fs_export_mod;
    if (!xm || !xm->dll || addr - xm->mod->info->base >= xm->mod->info->image_size) return 0;
    return fighter_dispatch(c, xm->mod, addr, lifted);
}

/* recording side of the same: the lifted function being recorded calls a module address through a pointer (nro_call_indirect) */
static int fighter_rec_pointer(Ctx *c, uint64_t addr, ImportFn fn) {
    FsFiber *ff = FlsGetValue(g_fs_fls);
    if (ff && ff->replay && ff->inlifted) { fs_call_addr(c, addr); return 1; }      /* lifted code run inside a replay */
    if (!ff || !ff->rec || ff->depth || c->x[31] >= ff->rec_sp) return 0;
    if (ff->synth && ff->count >= FS_SYNTH_CAP) longjmp(ff->synth_jb, 1);
    if (ff->count >= FS_MAX_EVENTS) return 0;
    FsEvent *e = &ff->ev[ff->count++];
    fs_capture(e, c, FS_PTR_NAME, "ST");
    e->target = addr;
    if (ff->synth) { ff->depth++; fighter_synth_answer(c, e); return 1; }
    ff->depth++;
    fn(c);
    ff = FlsGetValue(g_fs_fls);
    ff->depth--;
    e->r_x0 = c->x[0]; e->r_v0 = c->v[0]; e->done = 1;
    if (e->x8) memcpy(e->sret, (const void *)(uintptr_t)e->x8, 16);
    return 1;
}

/* recording side: the lifted module calls import `sym` */
static FsEvent *fighter_rec_begin(Ctx *c, NroModule *m, int sym) {
    FsFiber *ff = FlsGetValue(g_fs_fls);
    if (!ff || !ff->rec) return NULL;
    if (ff->depth++ || ff->rec_mod->mod != m) return NULL;
    const char *name = m->syms[sym].name;
    if (fs_is_pure(name)) return NULL;
    if (ff->synth && ff->count >= FS_SYNTH_CAP) longjmp(ff->synth_jb, 1);     /* a script that loops on made-up answers: compared up to here */
    if (ff->count >= FS_MAX_EVENTS) { ff->bad = 1; snprintf(ff->why, sizeof ff->why, "more than %d calls", FS_MAX_EVENTS); return NULL; }
    int slot = ff->rec_mod->slot_of_sym[sym];
    FsEvent *e = &ff->ev[ff->count++];
    fs_capture(e, c, name, slot >= 0 ? ff->rec_mod->t.syms[slot].spec : "");
    return e;
}
/* SSBU_FIGHTER_SYNTH: the recorded call is not made; it is answered with a made-up value (see fighter_synth) */
static int fighter_synth_answer(Ctx *c, FsEvent *e) {
    FsFiber *ff = FlsGetValue(g_fs_fls);
    if (!ff || !ff->synth) return 0;
    ff->depth--;
    uint64_t b = ff->synth == 1 ? 0 : ff->synth == 2 ? 1 : (ff->synth_n++ * 2654435761u >> 16) & 1;
    c->x[0] = b; c->v[0].d[0] = 0; c->v[0].d[1] = 0;
    { float f = b ? 1.0f : -1.0f; memcpy(&c->v[0], &f, 4); }      /* S2: a float result is -1 / +1, so that both sides of float comparisons run */
    if (e->spec[0] == 'S' && e->x8) { wr64(e->x8, 1); wr64(e->x8 + 8, b); }      /* an L2CValue: bool b */
    e->r_x0 = c->x[0]; e->r_v0 = c->v[0]; e->done = 1;
    if (e->spec[0] == 'S' && e->x8) memcpy(e->sret, (const void *)(uintptr_t)e->x8, 16);
    return 1;
}
static void fighter_rec_end(Ctx *c, FsEvent *e) {
    FsFiber *ff = FlsGetValue(g_fs_fls);
    if (!ff || !ff->rec) return;
    ff->depth--;
    if (!e) return;
    e->r_x0 = c->x[0]; e->r_v0 = c->v[0]; e->done = 1;
    if (e->spec[0] == 'S' && e->x8) memcpy(e->sret, (const void *)(uintptr_t)e->x8, 16);
}

static void fighter_report(void) {
    const char *path = getenv("SSBU_FIGHTER_REPORT");
    FILE *f = fopen(path && path[0] ? path : "fighter_report.txt", "w");
    if (!f) return;
    for (int k = 0; k < g_fs_mod_count; k++) {
        FsMod *fm = g_fs_mods[k];
        long long called = 0, eq = 0, pa = 0, df = 0, calls = 0, fn_eq = 0, fn_df = 0, fn_none = 0;
        for (int i = 0; i < fm->ovr_count; i++) {
            FsStat *s = &fm->stat[i];
            if (s->calls) called++;
            calls += s->calls; eq += s->equal; pa += s->partial; df += s->differ;
            if (s->differ) fn_df++; else if (s->equal || s->partial) fn_eq++; else if (s->calls) fn_none++;
        }
        fprintf(f, "module %s: %d scripts as source; called in this run: %lld scripts, %lld calls\n", fm->mod->info->name, fm->ovr_count, called, calls);
        fprintf(f, "  differential, by call: %lld equal to the end, %lld equal up to where the game ended the script, %lld differing, %lld not compared (still running, or run lifted inside another recording)\n",
                eq, pa, df, calls - eq - pa - df);
        fprintf(f, "  differential, by script: %lld equal on every compared call, %lld differing, %lld called but never compared\n", fn_eq, fn_df, fn_none);
        long long se = 0, sd = 0;
        for (int i = 0; i < fm->ovr_count; i++) { if (fm->stat[i].synth_differ) sd++; else if (fm->stat[i].synth_equal == 3) se++; }
        fprintf(f, "  synthetic differential (SSBU_FIGHTER_SYNTH, 3 passes per script): %lld scripts equal on all passes, %lld differing\n", se, sd);
        for (int i = 0; i < fm->ovr_count; i++) {
            FsStat *s = &fm->stat[i];
            if (s->calls || s->synth_differ)fprintf(f, "  %-44s calls %6lld  equal %6lld  equal-interrupted %6lld  differ %6lld%s%s%s\n", fm->ovr[i].name, s->calls, s->equal, s->partial, s->differ,
                                  s->lifted ? "  (forced lifted)" : "", s->first[0] ? "  first: " : "", s->first);
        }
    }
    fclose(f);
}

static int fs_cmp_ovr(const void *a, const void *b) { return (int)((const FsOverride *)a)->off - (int)((const FsOverride *)b)->off; }

/* S3: with the hook table (hook_host.c) every function that exists as source is hooked at its own entry, so it is
 * reached however it is called: by pointer, by import, and by the DIRECT calls inside the lifted module. One record
 * per function for the life of the process (the module DLL stays loaded, the fighter DLL is a new copy every match). */
typedef struct FsHookRec { NroModule *m; uint64_t addr; ImportFn orig; int id; struct FsHookRec *next; } FsHookRec;
static FsHookRec *g_fs_hk[1 << 16];
static long long g_fs_hk_count, g_fs_hk_refused;
static FsHookRec *fs_hook_rec(uint64_t addr) {
    FsHookRec *r = g_fs_hk[(addr >> 4) & 0xffff];
    while (r && r->addr != addr) r = r->next;
    return r;
}
static void fs_hook_entry(Ctx *c, void *user) {
    FsHookRec *r = user;
    if (r->m->fighter && fighter_dispatch(c, r->m, r->addr, r->orig)) return;
    r->orig(c);
}
static void fs_hook_function(NroModule *m, uint64_t addr, const char *name) {
    if (fs_hook_rec(addr)) return;
    FsHookRec *r = calloc(1, sizeof *r);
    r->m = m; r->addr = addr;
    r->id = hook_install(addr, fs_hook_entry, r, &r->orig);
    if (!r->id) { if (g_fs_hk_refused++ < 5) printf("fighter source: %s stays lifted: %s\n", name, hook_error()); free(r); return; }
    r->next = g_fs_hk[(addr >> 4) & 0xffff]; g_fs_hk[(addr >> 4) & 0xffff] = r;
    g_fs_hk_count++;
}
/* the lifted original of a module function: behind its hook if it has one */
static ImportFn fs_lifted(NroModule *m, uint64_t addr) {
    FsHookRec *r = fs_hook_rec(addr);
    return r ? r->orig : fn_in_table(m->fns, m->fn_count, addr);
}

static void fighter_attach(NroModule *m) {
    const char *on = getenv("SSBU_FIGHTER_SRC");
    if (on && on[0] == '0') return;
    const char *name = m->info->name;
    if (strncmp(name, "lua2cpp_", 8) == 0) name += 8;
    char src[MAX_PATH * 2], dst[MAX_PATH * 2];
    DWORD n = GetModuleFileNameA(NULL, src, MAX_PATH);
    while (n && src[n - 1] != '\\' && src[n - 1] != '/') n--;
    { const char *fb = getenv("SSBU_FIGHTER_BIN");     /* S3: another folder of fighter DLLs (work in progress), e.g. fighters_bin_s3 */
      snprintf(src + n, sizeof src - n, "%s\\%s.dll", fb && fb[0] ? fb : "fighters_bin", name); }
    if (GetFileAttributesA(src) == INVALID_FILE_ATTRIBUTES) snprintf(src + n, sizeof src - n, "fighters_bin\\%s.dll", name);
    if (GetFileAttributesA(src) == INVALID_FILE_ATTRIBUTES) return;
    if (g_fs_fls == FLS_OUT_OF_INDEXES) {
        g_fs_fls = FlsAlloc(NULL);
        /* once per run: remove the DLL copies earlier runs left (a copy another running game still uses cannot be deleted: it stays) */
        char pat[MAX_PATH * 2]; WIN32_FIND_DATAA fd;
        memcpy(pat, src, n); snprintf(pat + n, sizeof pat - n, "fighters_bin\\*.run*.dll");
        HANDLE h = FindFirstFileA(pat, &fd);
        if (h != INVALID_HANDLE_VALUE) {
            do { char old[MAX_PATH * 2]; memcpy(old, src, n); snprintf(old + n, sizeof old - n, "fighters_bin\\%s", fd.cFileName); DeleteFileA(old); } while (FindNextFileA(h, &fd));
            FindClose(h);
        }
    }
    /* load a private copy, so that the fighter can be rebuilt while the game runs: the next match loads the new one */
    static volatile LONG serial;
    LARGE_INTEGER qf, q0, q1, q2, q3;                  /* S4: what loading a fighter DLL costs, and on which thread */
    QueryPerformanceFrequency(&qf); QueryPerformanceCounter(&q0);
    memcpy(dst, src, n); snprintf(dst + n, sizeof dst - n, "fighters_bin\\%s.run%lu_%ld.dll", name, (unsigned long)GetCurrentProcessId(), (long)InterlockedIncrement(&serial));
    if (!CopyFileA(src, dst, FALSE)) { printf("fighter source: cannot copy %s (error %lu)\n", src, (unsigned long)GetLastError()); return; }
    QueryPerformanceCounter(&q1);
    HMODULE dll = LoadLibraryA(dst);
    QueryPerformanceCounter(&q2);
    FsBindFn bind = dll ? (FsBindFn)(void *)GetProcAddress(dll, "fighter_bind") : NULL;
    if (!bind) { printf("fighter source: %s is not a fighter DLL\n", src); if (dll) FreeLibrary(dll); DeleteFileA(dst); return; }
    FsMod *fm = calloc(1, sizeof *fm);
    fm->mod = m; fm->dll = dll; strcpy(fm->loaded_path, dst);
    bind(&g_fs_host, &fm->t);
    fm->fn = calloc((size_t)fm->t.sym_count, sizeof *fm->fn);
    fm->pure = calloc((size_t)fm->t.sym_count, 1);
    fm->local = calloc((size_t)fm->t.sym_count, 1);
    fm->slot_of_sym = malloc((size_t)m->sym_count * sizeof(int));
    for (int i = 0; i < m->sym_count; i++) fm->slot_of_sym[i] = -1;
    int missing = 0;
    for (int s = 0; s < fm->t.sym_count; s++) {
        fm->pure[s] = (unsigned char)fs_is_pure(fm->t.syms[s].name);
        int found = -1;
        for (int i = 1; i < m->sym_count; i++) if (strcmp(m->syms[i].name, fm->t.syms[s].name) == 0) { found = i; break; }
        if (found < 0 || !m->bind_addr[found]) {
            /* one SDK serves all modules: a function this module never imports is bound like an import would be (main, then the other modules) */
            int mi = main_find(fm->t.syms[s].name);
            const Export *e = mi >= 0 && dyn_syms[mi].defined ? NULL : exp_find(fm->t.syms[s].name);
            uint64_t a = mi >= 0 && dyn_syms[mi].defined ? GUEST_BASE + dyn_syms[mi].value : e ? e->value : 0;
            if (a) { fm->t.addr[s] = a; fm->fn[s] = function_at(a); } else missing++;
            continue;
        }
        fm->slot_of_sym[found] = s;
        fm->local[s] = (unsigned char)(m->bind_addr[found] - m->info->base < m->info->image_size);
        fm->t.addr[s] = m->bind_addr[found];
        fm->fn[s] = m->bind_fn[found];
        if (!fm->fn[s] && fm->local[s]) fm->fn[s] = fn_in_table(m->fns, m->fn_count, m->bind_addr[found]);   /* the module was not mapped yet when it was bound */
    }
    fm->ovr_count = fm->t.ovr_count;
    fm->ovr = malloc((size_t)fm->ovr_count * sizeof *fm->ovr);
    memcpy(fm->ovr, fm->t.ovr, (size_t)fm->ovr_count * sizeof *fm->ovr);
    qsort(fm->ovr, (size_t)fm->ovr_count, sizeof *fm->ovr, fs_cmp_ovr);
    fm->stat = calloc((size_t)fm->ovr_count + 1, sizeof *fm->stat);
    const char *lifted = getenv("SSBU_FIGHTER_LIFTED");
    int forced = 0;
    for (int i = 0; lifted && i < fm->ovr_count; i++) {
        const char *hit = strcmp(lifted, "1") == 0 ? lifted : strstr(lifted, fm->ovr[i].name);
        size_t len = strlen(fm->ovr[i].name);
        if (hit && (strcmp(lifted, "1") == 0 || ((hit == lifted || hit[-1] == ',') && (hit[len] == 0 || hit[len] == ',')))) { fm->stat[i].lifted = 1; forced++; }
    }
    { const char *hm = getenv("SSBU_FIGHTER_HOOK"); if (hm) g_fs_hookmode = hm[0] != '0'; }
    if (g_fs_hookmode) for (int i = 0; i < fm->ovr_count; i++) fs_hook_function(m, m->info->base + fm->ovr[i].off, fm->ovr[i].name);
    m->fighter = fm;
    if (strcmp(name, "common") == 0) g_fs_export_mod = fm;
    if (g_fs_mod_count < 128) g_fs_mods[g_fs_mod_count++] = fm;
    printf("fighter source: %s: %d scripts run as C++ source (%d forced lifted), %d game symbols bound (%d missing)%s%s\n", name, fm->ovr_count - forced, forced,
           fm->t.sym_count - missing, missing, getenv("SSBU_FIGHTER_DIFF") ? ", differential test ON" : "", g_fs_hookmode ? ", installed as entry hooks" : ", reached by pointer/import only");
    trace_printf("fighter source: %s loaded from %s\n", name, dst);
    QueryPerformanceCounter(&q3);
    { static double total; double k = 1000.0 / (double)qf.QuadPart;
      total += (double)(q3.QuadPart - q0.QuadPart) * k;
      printf("fighter source: %s: load cost %.1f ms on thread %lu (copy %.1f, LoadLibrary %.1f, bind %.1f); all modules so far %.1f ms\n", name, (double)(q3.QuadPart - q0.QuadPart) * k,
             (unsigned long)GetCurrentThreadId(), (double)(q1.QuadPart - q0.QuadPart) * k, (double)(q2.QuadPart - q1.QuadPart) * k, (double)(q3.QuadPart - q2.QuadPart) * k, total); }
}

static void fighter_detach(NroModule *m) {
    FsMod *fm = m->fighter;
    if (!fm) return;
    fighter_report();
    if (g_fs_export_mod == fm) g_fs_export_mod = NULL;
    /* S2 fix (crash 0xc0000005 after "UnloadModule: lua2cpp_mario", found by track V): the DLL copy must STAY loaded.
     * The report keeps reading the script names, which are strings inside the DLL, and a script fiber can still be
     * suspended inside one of its functions. It was freed here; now it is only marked as detached (dll = NULL) and
     * the file is removed by the next run (fs_remove_old_copies). */
    m->fighter = NULL;              /* the FsMod stays (its statistics are in the report) */
    fm->dll = NULL;
}

/* S3, offline test only: the made-up agent's BattleObject (agent+0x38) is 64 KB in which every word is a pointer
 * into the same 64 KB, so that a function that follows pointers from it (object -> member -> field) reads memory
 * instead of address 0x60 and can be compared at all. It is put back before the original and before the source run. */
static uint8_t *g_fs_soup, *g_fs_soup0;
static int g_fs_guard_phase;                       /* defined with the fault guard below */
static void fs_soup_reset(void) {
    if (!g_fs_offline) return;
    if (!g_fs_soup) {
        g_fs_soup = VirtualAlloc(NULL, 0x20000, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
        g_fs_soup0 = g_fs_soup + 0x10000;
        for (unsigned i = 0; i < 0x2000; i++) { uint64_t p = (uint64_t)(uintptr_t)g_fs_soup + ((i * 296u + 0x100u) & 0xfff8u); memcpy(g_fs_soup0 + 8 * i, &p, 8); }
    }
    memcpy(g_fs_soup, g_fs_soup0, 0x10000);
}

/* S3: the RESULT of a function of the script classes (the L2CValue written through x8) is part of the comparison:
 * sessions 1-2 compared only the calls a function makes, which says nothing about what it hands back to a lifted
 * caller. Before the original runs the 16 bytes at x8 are kept (fs_result_begin); the source starts from the same
 * bytes and must leave the same value. Only for lua2cpp_common (ACMD scripts have no result buffer). */
static int fs_writable16(uint64_t p) {
    MEMORY_BASIC_INFORMATION mi;
    if (p < 0x10000 || (p & 7) || !VirtualQuery((void *)(uintptr_t)p, &mi, sizeof mi)) return 0;
    return mi.State == MEM_COMMIT && (mi.Protect & (PAGE_READWRITE | PAGE_EXECUTE_READWRITE)) && !(mi.Protect & PAGE_GUARD) && ((p + 15) >> 12) == (p >> 12);
}
static void fs_result_begin(FsFiber *ff, FsMod *fm, const Ctx *c) {
    ff->res_at = (fm == g_fs_export_mod && fs_writable16(c->x[8])) ? c->x[8] : 0;
    if (ff->res_at) memcpy(ff->res_before, (const void *)(uintptr_t)ff->res_at, 16);
}

/* run the source of the recorded script against the recording; partial = the original was ended before it returned */
static void __declspec(noinline) fs_compare(Ctx *c, FsFiber *ff, int partial) {
    FsMod *fm = ff->rec_mod;
    FsStat *st = &fm->stat[ff->rec_at];
    ff->rec = 0;
    InterlockedDecrement(&g_fs_recording);
    if (!fm->dll) return;                              /* its module was unloaded meanwhile */
    uint8_t res_lifted[16];
    fs_soup_reset();
    if (partial) ff->res_at = 0;                      /* ended from outside: no result, and its buffer may be gone */
    if (ff->res_at) { memcpy(res_lifted, (const void *)(uintptr_t)ff->res_at, 16); memcpy((void *)(uintptr_t)ff->res_at, ff->res_before, 16); }
    Ctx after = *c;
    FsMod *saved_mod = ff->mod; const char *saved_script = ff->script; Ctx *saved_ctx = ff->ctx;
    memcpy(c->x, ff->entry, sizeof ff->entry);
    ff->mod = fm; ff->script = fm->ovr[ff->rec_at].name; ff->ctx = c;
    ff->pos = 0; ff->partial = partial; ff->replay = 1; ff->inlifted = 0;
    InterlockedIncrement(&g_fs_replaying);
    if (setjmp(ff->jb) == 0) { g_fs_guard_phase = g_fs_offline ? 2 : 0; fm->ovr[ff->rec_at].fn(c); }      /* nothing reaches the game: every call is answered from the recording */
    g_fs_guard_phase = 0;
    InterlockedDecrement(&g_fs_replaying);
    ff->replay = 0; ff->inlifted = 0;
    if (!ff->bad && ff->pos != ff->count)
        { ff->bad = 1; snprintf(ff->why, sizeof ff->why, "stops after %d of the original's %d calls (next: %.80s)", ff->pos, ff->count, ff->ev[ff->pos].name); }
    if (ff->res_at) {
        uint32_t ta, tb; uint64_t ra, rb;
        memcpy(&ta, res_lifted, 4); memcpy(&ra, res_lifted + 8, 8);
        memcpy(&tb, (const void *)(uintptr_t)ff->res_at, 4); memcpy(&rb, (const void *)(uintptr_t)(ff->res_at + 8), 8);
        uint64_t m = ta == 0 ? 0 : ta == 1 ? 1 : ta == 3 ? 0xffffffffull : (ta == 2 || ta == 4 || ta == 7) ? ~0ull : 0;      /* tables, strings: the type only */
        if (!ff->bad && !partial && (ta != tb || ((ra ^ rb) & m)))
            { ff->bad = 1; snprintf(ff->why, sizeof ff->why, "returns type %u %llx, original type %u %llx", tb, (unsigned long long)rb, ta, (unsigned long long)ra); }
        memcpy((void *)(uintptr_t)ff->res_at, res_lifted, 16);      /* the original's result stands */
        ff->res_at = 0;
    }
    if (ff->synth) {
        if (!ff->bad) st->synth_equal++;
        else if (!st->synth_differ++) { snprintf(st->first, sizeof st->first, "synthetic %d: %s", ff->synth, ff->why); printf("fighter synthetic diff: %s differs: %s\n", fm->ovr[ff->rec_at].name, ff->why); }
    }
    else if (ff->bad) { if (!st->differ++) { snprintf(st->first, sizeof st->first, "%s", ff->why); printf("fighter diff: %s differs: %s\n", fm->ovr[ff->rec_at].name, ff->why); } }
    else if (partial) { st->partial++; g_fs_interrupted++; }
    else st->equal++;
    ff->mod = saved_mod; ff->script = saved_script; ff->ctx = saved_ctx;
    *c = after;
}

/* SSBU_FIGHTER_SYNTH=1: once per module, when the game first calls one of its source scripts, EVERY source script is
 * compared with its lifted original on made-up answers: both run from the same arguments (this call's agent), no call
 * reaches the game, every game function "returns" false (pass 1), true (pass 2), a fixed pseudo-random pattern
 * (pass 3). It covers the scripts a match does not reach and both sides of every condition; it does not prove
 * anything about what the game answers - the recorded real calls (SSBU_FIGHTER_DIFF) do that. */
/* S3, offline test: an access violation inside a function under test does not end the whole test. The handler puts
 * the thread back at the setjmp of the run in progress (registers from the jmp_buf: nothing is unwound, as the
 * abandoned frames are lifted code or source without resources): during the ORIGINAL's run the function cannot be
 * tested on the made-up agent (reported as such), during the SOURCE's run it is a difference. */
static FsFiber *g_fs_guard_ff; static int g_fs_guard_phase;      /* 1 = the original runs, 2 = the source runs */
static void fs_guard_resume(CONTEXT *x, jmp_buf jb, int value) {
    _JUMP_BUFFER *j = (_JUMP_BUFFER *)jb;
    x->Rbx = j->Rbx; x->Rsp = j->Rsp; x->Rbp = j->Rbp; x->Rsi = j->Rsi; x->Rdi = j->Rdi;
    x->R12 = j->R12; x->R13 = j->R13; x->R14 = j->R14; x->R15 = j->R15; x->Rip = j->Rip;
    memcpy(&x->Xmm6, &j->Xmm6, 160);
    x->Rax = (DWORD64)value;
}
static LONG CALLBACK fs_guard(EXCEPTION_POINTERS *ep) {
    FsFiber *ff = g_fs_guard_ff;
    if (!ff || !g_fs_guard_phase || ep->ExceptionRecord->ExceptionCode != EXCEPTION_ACCESS_VIOLATION) return EXCEPTION_CONTINUE_SEARCH;
    int phase = g_fs_guard_phase;
    g_fs_guard_phase = 0;
    if (phase == 1) fs_guard_resume(ep->ContextRecord, ff->synth_jb, 3);
    else { if (!ff->bad) snprintf(ff->why, sizeof ff->why, "the source faults (reads or writes address %llx) where the original does not", (unsigned long long)ep->ExceptionRecord->ExceptionInformation[1]); ff->bad = 1; fs_guard_resume(ep->ContextRecord, ff->jb, 1); }
    return EXCEPTION_CONTINUE_EXECUTION;
}

static void fighter_synth(Ctx *c, NroModule *m, FsMod *fm, FsFiber *ff) {
    Ctx saved = *c;
    if (g_fs_offline && !g_fs_guard_ff) { g_fs_guard_ff = ff; AddVectoredExceptionHandler(1, fs_guard); }
    if (!ff->ev) ff->ev = malloc(sizeof(FsEvent) * FS_MAX_EVENTS);
    for (int i = 0; i < fm->ovr_count; i++) {
        ImportFn lifted = fs_lifted(m, m->info->base + fm->ovr[i].off);
        if (!lifted) continue;
        {   /* S3: SSBU_FIGHTER_OFFLINE_SKIP=<file>: names (one per line) the test leaves out, e.g. those that stopped an earlier run */
            static char *skip; static int skip_read;
            if (!skip_read) {
                skip_read = 1;
                FILE *sf = getenv("SSBU_FIGHTER_OFFLINE_SKIP") ? fopen(getenv("SSBU_FIGHTER_OFFLINE_SKIP"), "rb") : NULL;
                if (sf) { skip = calloc(1, 1 << 20); skip[0] = '\n'; size_t n = fread(skip + 1, 1, (1 << 20) - 3, sf); skip[n + 1] = '\n'; fclose(sf); }
            }
            char key[160]; snprintf(key, sizeof key, "\n%.150s\n", fm->ovr[i].name);
            if (skip && strstr(skip, key)) continue;
        }
        if (g_fs_offline > 1) printf("synth %s\n", fm->ovr[i].name);
        for (int pass = 1; pass <= 3; pass++) {
            *c = saved;
            memcpy(ff->entry, c->x, sizeof ff->entry);
            ff->count = 0; ff->bad = 0; ff->depth = 0; ff->why[0] = 0; ff->synth_n = (unsigned)i * 7919u;
            ff->rec_mod = fm; ff->rec_at = i; ff->rec_sp = c->x[31];
            ff->synth = pass; ff->rec = 1; ff->cut = 0;
            fs_soup_reset();
            if (g_fs_offline && c->x[0]) wr64(c->x[0] + 0x38, (uint64_t)(uintptr_t)g_fs_soup);
            fs_result_begin(ff, fm, c);
            InterlockedIncrement(&g_fs_recording);
            int sj = setjmp(ff->synth_jb);
            if (sj == 0) { g_fs_guard_phase = g_fs_offline ? 1 : 0; lifted(c); g_fs_guard_phase = 0; }
            else if (sj == 3) {                         /* the original itself faults on the made-up agent: not testable here */
                ff->rec = 0; ff->synth = 0; ff->depth = 0; InterlockedDecrement(&g_fs_recording);
                if (!fm->stat[i].synth_differ++) { snprintf(fm->stat[i].first, sizeof fm->stat[i].first, "the original faults on the test agent"); printf("fighter synthetic diff: %s differs: the original faults on the test agent (not testable offline)\n", fm->ovr[i].name); }
                break;
            }
            else { g_fs_guard_phase = 0; ff->cut = 1; ff->depth = 0; fm->stat[i].synth_cut++; }
            ff->synth_n = (unsigned)i * 7919u;
            fs_compare(c, ff, ff->cut);
            ff->synth = 0;
        }
    }
    *c = saved;
    long long eq = 0, df = 0;
    for (int i = 0; i < fm->ovr_count; i++) { if (fm->stat[i].synth_differ) df++; else if (fm->stat[i].synth_equal == 3) eq++; }
    printf("fighter synthetic differential: %s: %lld scripts equal on all 3 passes, %lld differing, of %d\n", m->info->name, eq, df, fm->ovr_count);
}

/* S3: SSBU_FIGHTER_LOG=1: evidence for edit proofs without looking at the screen. Whenever a function of the shared
 * state machine (so: a fighter's agent in x0) is entered, the fighter's damage percent and status kind are read with
 * the game's own getters; a change is one log line. `[fs] damage` lines give the percent each hit added,
 * `[fs] status` lines the sequence of statuses of each fighter. */
static void fs_state_log(Ctx *c, const char *at) {
    static uint64_t a_damage, a_status, boma_of[8];
    static float last_damage[8]; static int last_status[8], count; static long long line;
    if (!a_damage) {
        a_damage = hk_address_of("_ZN3app8lua_bind25DamageModule__damage_implEPNS_26BattleObjectModuleAccessorEi");
        a_status = hk_address_of("_ZN3app8lua_bind30StatusModule__status_kind_implEPNS_26BattleObjectModuleAccessorE");
        if (!a_damage || !a_status) { printf("[fs] log: getters not found\n"); a_damage = 1; }
    }
    if (a_damage == 1 || !c->x[0]) return;
    uint64_t boma = rd64(c->x[0] + 0x40);
    if (!boma) return;
    int k = 0;
    while (k < count && boma_of[k] != boma) k++;
    if (k == 8) return;
    Ctx saved = *c;
    if (k == count) {
        static uint64_t a_kind;
        if (!a_kind) a_kind = hk_address_of("_ZN3app7utility8get_kindEPKNS_26BattleObjectModuleAccessorE");
        boma_of[k] = boma; last_damage[k] = 0; last_status[k] = -1; count++;
        if (a_kind) { c->x[0] = boma; call_indirect(c, a_kind); printf("[fs] fighter %d is fighter kind %d (0 = Mario)\n", k, (int)c->x[0]); *c = saved; }
    }
    c->x[0] = boma; c->x[1] = 0; call_indirect(c, a_damage);
    float d = c->v[0].f[0];
    c->x[0] = boma; call_indirect(c, a_status);
    int s = (int)c->x[0];
    *c = saved;
    if (d != last_damage[k]) { printf("[fs] damage %lld: fighter %d: %.2f%% -> %.2f%% (%+.2f) seen at %s\n", ++line, k, last_damage[k], d, d - last_damage[k], at); last_damage[k] = d; }
    if (s != last_status[k]) { printf("[fs] status %lld: fighter %d: 0x%x -> 0x%x seen at %s\n", ++line, k, last_status[k], s, at); last_status[k] = s; }
}

/* nro_call_indirect: the game calls module address `addr`. Returns 1 if a source function handled it. */
static int fighter_dispatch(Ctx *c, NroModule *m, uint64_t addr, ImportFn lifted) {
    FsMod *fm = m->fighter;
    uint32_t off = (uint32_t)(addr - m->info->base);
    int lo = 0, hi = fm->ovr_count - 1, at = -1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        if (fm->ovr[mid].off == off) { at = mid; break; }
        if (fm->ovr[mid].off < off) lo = mid + 1; else hi = mid - 1;
    }
    if (at < 0 || fm->stat[at].lifted || !fm->dll) return 0;
    static int diff = -1;
    if (diff < 0) diff = getenv("SSBU_FIGHTER_DIFF") != NULL;
    FsFiber *ff = fs_fiber();
    FsStat *st = &fm->stat[at];
    if (ff->replay) return 0;
    static int statelog = -1;
    if (statelog < 0) statelog = getenv("SSBU_FIGHTER_LOG") != NULL && !g_fs_offline;
    if (statelog && fm == g_fs_export_mod && !ff->rec && strncmp(fm->ovr[at].name, "status_", 7) == 0) fs_state_log(c, fm->ovr[at].name);
    if (!fm->synth_done && !ff->rec) {
        fm->synth_done = 1;
        if (getenv("SSBU_FIGHTER_SYNTH")) fighter_synth(c, m, fm, ff);
    }
    if (ff->rec) {
        /* called from inside the function being recorded: runs lifted, uncompared. S3: with entry hooks this is also
         * reached by a TAIL call (same guest sp): then the recording's host frame is still below this one; in the
         * synthetic test nothing ever ends a function from outside. */
        if (c->x[31] < ff->rec_sp || ff->synth || (c->x[31] == ff->rec_sp && (uintptr_t)&at < ff->rec_host)) { st->calls++; return 0; }
        fs_compare(c, ff, 1);                                       /* that script was ended by the game (unwound): compare what it did */
    }
    st->calls++;
    static int every = 0;                               /* S4: SSBU_FIGHTER_REPORT_EVERY=<n> (probe.py reads the report as a progress counter) */
    if (!every) { const char *e = getenv("SSBU_FIGHTER_REPORT_EVERY"); every = e && atoi(e) > 0 ? atoi(e) : diff ? 20 : 2000; }
    if (++g_fs_dispatched % every == 0) fighter_report();
    if (!diff) {
        FsMod *saved_mod = ff->mod; const char *saved_script = ff->script; Ctx *saved_ctx = ff->ctx; uint64_t saved_lr = ff->lr;
        ff->mod = fm; ff->script = fm->ovr[at].name; ff->ctx = c; ff->lr = g_fs_hookmode ? c->x[30] : 0;
        fm->ovr[at].fn(c);
        ff = fs_fiber();
        ff->mod = saved_mod; ff->script = saved_script; ff->ctx = saved_ctx; ff->lr = saved_lr;
        return 1;
    }
    if (!ff->ev) ff->ev = malloc(sizeof(FsEvent) * FS_MAX_EVENTS);
    memcpy(ff->entry, c->x, sizeof ff->entry);
    ff->count = 0; ff->bad = 0; ff->depth = 0; ff->why[0] = 0;
    ff->rec_mod = fm; ff->rec_at = at; ff->rec_sp = c->x[31]; ff->rec_host = (uintptr_t)&at;
    fs_result_begin(ff, fm, c);
    ff->rec = 1;
    InterlockedIncrement(&g_fs_recording);
    lifted(c);                                      /* the real run; may take many game frames, may never come back */
    ff = fs_fiber();
    if (ff->rec && ff->rec_mod == fm && ff->rec_at == at) fs_compare(c, ff, 0);
    return 1;
}

/* SSBU_FIGHTER_OFFLINE=all | name1,name2: the synthetic differential test of every source script of the listed
 * modules WITHOUT starting the game (called once before the game's entry point, nnro.c module_coverage_start).
 * Each module is read from SSBU_FIGHTER_NRO_DIR (default ro_study\nro), loaded by the normal nn::ro path (its hash
 * is put in a one-entry NRR first), not initialised (no DT_INIT: nothing of the game exists), and every script of
 * fighters_bin\<name>.dll is compared with its lifted original as fighter_synth does. The constant table of
 * lua2cpp_common is filled with a distinct value per index, so a wrong constant index shows. Then the process ends. */
static void ro_LoadModule(Ctx *c);
static void ro_RegisterModuleInfo(Ctx *c);
static void ro_UnregisterModuleInfo(Ctx *c);
static int sha256(const void *data, size_t size, uint8_t out[32]);
static NroModule *module_of_image(uint64_t nro);
static NroModule *fs_offline_load(Ctx *c, const char *dir, const char *name) {
    static uint8_t nrr_page[0x2000];
    char path[MAX_PATH * 2];
    snprintf(path, sizeof path, "%s/%s.nro", dir, name);
    FILE *f = fopen(path, "rb");
    if (!f) { printf("fighter offline: cannot open %s\n", path); return NULL; }
    fseek(f, 0, SEEK_END); long size = ftell(f); fseek(f, 0, SEEK_SET);
    uint8_t *nro = VirtualAlloc(NULL, (size_t)size + 0x1000, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    if (!nro || fread(nro, 1, (size_t)size, f) != (size_t)size) { fclose(f); printf("fighter offline: cannot read %s\n", path); return NULL; }
    fclose(f);
    uint8_t h[32], info[0x20], out[0x40];
    uint64_t nrr = ((uint64_t)(uintptr_t)nrr_page + 0xfff) & ~(uint64_t)0xfff, lr = c->x[30];
    if (!sha256(nro, rd32((uint64_t)(uintptr_t)nro + 0x18), h)) { printf("fighter offline: no SHA-256\n"); return NULL; }
    memset((void *)(uintptr_t)nrr, 0, 0x1000);
    wr32(nrr, 0x3052524eu); wr32(nrr + 0x338, 0x1000); wr32(nrr + 0x340, 0x350); wr32(nrr + 0x344, 1);
    memcpy((void *)(uintptr_t)(nrr + 0x350), h, 32);
    memset(info, 0, sizeof info); memset(out, 0, sizeof out);
    c->x[0] = (uint64_t)(uintptr_t)info; c->x[1] = nrr; ro_RegisterModuleInfo(c);
    c->x[0] = (uint64_t)(uintptr_t)out; c->x[1] = (uint64_t)(uintptr_t)nro; c->x[2] = 0; c->x[3] = 0; c->x[4] = 2;
    ro_LoadModule(c);
    uint64_t r = c->x[0];
    c->x[0] = (uint64_t)(uintptr_t)info; ro_UnregisterModuleInfo(c);
    c->x[30] = lr;
    if (r != RO_OK) { printf("fighter offline: %s not loaded (0x%llx)\n", name, (unsigned long long)r); return NULL; }
    return module_of_image((uint64_t)(uintptr_t)nro);
}

static void fighter_offline(Ctx *c) {
    const char *list = getenv("SSBU_FIGHTER_OFFLINE");
    if (!list || !list[0]) return;
    const char *dir = getenv("SSBU_FIGHTER_NRO_DIR");
    if (!dir) dir = "ro_study/nro";
    g_fs_offline = getenv("SSBU_FIGHTER_OFFLINE_TRACE") ? 2 : 1;
    ro_init_tables();
    setvbuf(stdout, NULL, _IONBF, 0);
    NroModule *common = fs_offline_load(c, dir, "lua2cpp_common");
    if (!common) ExitProcess(3);
    const Export *tab = exp_find("_ZN7lua2cpp21L2CAgentGeneratedBase19const_value_table__E");
    if (!tab) { printf("fighter offline: no constant table\n"); ExitProcess(3); }
    for (int i = 0; i < 0x4c0d; i++) wr32(tab->value + 4ull * (unsigned)i, 1000u + (unsigned)i);
    static uint8_t agent[0x400], lua[0x400], boma[0x1000], variadic[0x100];
    wr64((uint64_t)(uintptr_t)agent + 8, (uint64_t)(uintptr_t)lua);
    wr64((uint64_t)(uintptr_t)agent + 0x40, (uint64_t)(uintptr_t)boma);
    int all = strcmp(list, "all") == 0;
    for (int i = 0; i < nro_registry_count; i++) {
        const char *name = nro_registry[i].name, *sh = strncmp(name, "lua2cpp_", 8) == 0 ? name + 8 : name;
        size_t len = strlen(sh);
        const char *hit = all ? list : strstr(list, sh);
        while (!all && hit && !((hit == list || hit[-1] == ',') && (hit[len] == 0 || hit[len] == ','))) hit = strstr(hit + 1, sh);
        if (!hit) continue;
        int is_common = strcmp(sh, "common") == 0;
        NroModule *m = is_common ? common : fs_offline_load(c, dir, name);
        if (!m) continue;
        FsMod *fm = m->fighter;
        if (!fm) { if (!is_common || !all) printf("fighter offline: %s has no fighters_bin DLL\n", name); continue; }
        Ctx saved = *c;
        static uint8_t nil_args[8][0x40];              /* L2CValue arguments of functions that take some: nil */
        memset(agent, 0, sizeof agent); memset(nil_args, 0, sizeof nil_args);
        wr64((uint64_t)(uintptr_t)agent + 8, (uint64_t)(uintptr_t)lua);
        wr64((uint64_t)(uintptr_t)agent + 0x40, (uint64_t)(uintptr_t)boma);
        c->x[0] = (uint64_t)(uintptr_t)agent; c->x[1] = (uint64_t)(uintptr_t)variadic;
        for (int k = 2; k < 8; k++) c->x[k] = (uint64_t)(uintptr_t)nil_args[k];
        c->x[8] = (uint64_t)(uintptr_t)nil_args[0];
        fm->synth_done = 1;
        fighter_synth(c, m, fm, fs_fiber());
        *c = saved;
        long long cut = 0;
        for (int k = 0; k < fm->ovr_count; k++) if (fm->stat[k].synth_cut) cut++;
        printf("fighter offline: %s done (%lld scripts were cut after %d calls on some pass)\n", name, cut, FS_SYNTH_CAP);
        m->fighter = NULL; fm->dll = NULL;             /* stays loaded: see fighter_detach */
    }
    fighter_report();
    printf("fighter offline: finished\n");
    ExitProcess(0);
}
