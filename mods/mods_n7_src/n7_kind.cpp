// n4_kind.cpp - TEST MOD for plan\phases\N4_own_fighter.md. NOT part of the port. Successor of mods_n3_src\n3_kind.cpp.
// New fighter kinds 0x5E.. whose engine-side things are a donor's (Mario), with the WEAPONS' OWNER RESOLVED FROM THE
// LIVE OWNER instead of the static table weapon kind -> fighter kind. Needs the game DLL built with patches\kinds.txt.
//   N3_NEWKIND=<name>[,<name2>...]   switches the mod on: kind 0x5E = <name>, 0x5F = <name2> ... (hash fighter_kind_<name>)
//   N4_A0_WORKAROUND=1               no donor dependency and no live owner for the weapons (to show what breaks)
//   N4_OWNNAME=1                     the name rows of the new kinds become their own strings, the kind-hash row their own hash
//   N4_WEAPON_LOG=<n>                log the first n weapon inits in full (default 12)
// Build:  python fighter_sdk\tools\build_mod.py mods_n4_src\n4_kind.cpp mods_n4        Run: SSBU_MODS=mods_n4
//
// Addresses of 13.0.4. Beyond n3_kind.cpp:
//   weapon init             0x71033b5640 (weapon object, init description; weapon kind at description + 0x9c)
//       reads the STATIC owner kind from the int table 0x710455d7e4[weapon kind] and takes A[owner] + 0x70
//   weapon agent dispatchers 0x71033abee0, 0x71033acde0, 0x71033add40, 0x71033aeca0 (weapon object; kind at + 0xc)
//       jump by the same table to the owner's script module
//   These five functions are the only code that refers to that table. The hooks run the original with the table
//   row of the weapon kind set to the LIVE owner's kind for the duration of the call (under one lock).
//   fireball article function 0x7100cb9de0 (article, owner's module accessor: battle object id at + 8): counted per owner kind
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <windows.h>
#include "hook.h"
#include "registry.h"

// N5 (plan\phases\N5_own_module.md): this is n4_kind.cpp as a COMPONENT OF THE FIGHTER REGISTRY. With
// SSBU_CHARACTERS the new kinds are the registry's fighters (names from the manifests, own names on), and every
// agent a donor factory makes for a new kind is handed to the runtime (agent_begin / agent_end), which moves it into
// the new fighter's own script module. Without a registry it behaves as n4_kind.cpp (N3_NEWKIND, N4_OWNNAME).
static const SsbuRegistry *g_reg;

static const HookApi *api;
static const uint64_t MASK40 = 0xffffffffffull;
// N6 (task 3): THE DONOR IS PER NEW KIND, from the manifest's "donor" (N5 had DONOR = 0 = Mario built in). The donor's
// kind number is found by its name in the engine's own name table (0x7104f80e20: one string pointer per kind, the
// table whose rows 0x5E.. this component writes): dk(new kind) = that row index. Without a registry (N3_NEWKIND) the
// donor is N3_DONOR, default mario.
static const int FIRST = 0x5E, MAXNEW = 4;
static const uint64_t NAME_TABLE = 0x7104f80e20ull;
static int g_donor[MAXNEW] = { -1, -1, -1, -1 };
static char g_donor_name[MAXNEW][32];
static const uint64_t NEW_B = 0x19a8;              // array B of the patched singleton (patches\kinds.txt)
static const uint64_t OWNER_TABLE = 0x710455d7e4ull;   // int32 per weapon kind (617 rows)
static const int WEAPON_KINDS = 617;
static int g_nnew;
static uint64_t g_hash[MAXNEW];
static char g_name[MAXNEW][32], g_upper[MAXNEW][32], g_sound[MAXNEW][32];
static volatile LONG g_data_done;
static int g_a0_workaround, g_ownname, g_weapon_log = 12;
static CRITICAL_SECTION g_lock;

static void logf(const char *fmt, ...) {
    char line[500]; va_list ap; va_start(ap, fmt); vsnprintf(line, sizeof line, fmt, ap); va_end(ap);
    api->log(line);
}
static uint32_t crc32(const char *s) {
    uint32_t c = 0xffffffffu;
    for (; *s; s++) { c ^= (uint8_t)*s; for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xedb88320u & (0u - (c & 1))); }
    return ~c;
}
static uint64_t hash40(const char *s) { return ((uint64_t)strlen(s) << 32) | crc32(s); }
static int readable(uint64_t a, size_t n) {
    MEMORY_BASIC_INFORMATION mi;
    if (a < 0x10000 || !VirtualQuery((void *)(uintptr_t)a, &mi, sizeof mi)) return 0;
    if (mi.State != MEM_COMMIT || (mi.Protect & (PAGE_NOACCESS | PAGE_GUARD))) return 0;
    return a + n <= (uint64_t)(uintptr_t)mi.BaseAddress + mi.RegionSize;
}
static int is_new(uint32_t kind) { return kind >= (uint32_t)FIRST && kind < (uint32_t)(FIRST + g_nnew); }
static void set_row(uint64_t table, int row, uint64_t value, const char *what) {
    uint64_t *t = (uint64_t *)(uintptr_t)table; DWORD old;
    if (!readable(table, 8 * (row + 1))) { logf("[n4] kind: table %s %llx not readable", what, (unsigned long long)table); return; }
    uint64_t was = t[row];
    VirtualProtect(&t[row], 8, PAGE_READWRITE, &old);
    t[row] = value;
    logf("[n4] kind: table %s %llx row 0x%x: %llx -> %llx", what, (unsigned long long)table, row, (unsigned long long)was, (unsigned long long)value);
}
// the donor's kind of new kind FIRST + n: the row of the engine's name table whose string is the donor's name
static void resolve_donors(void) {
    static volatile LONG done;
    if (done) return;
    if (!readable(NAME_TABLE, 8 * FIRST)) return;
    int all = 1;
    for (int n = 0; n < g_nnew; n++) {
        if (g_donor[n] >= 0) continue;
        for (int k = 0; k < FIRST; k++) {
            uint64_t s = ((uint64_t *)(uintptr_t)NAME_TABLE)[k];
            if (readable(s, 32) && strcmp((const char *)(uintptr_t)s, g_donor_name[n]) == 0) { g_donor[n] = k; break; }
        }
        if (g_donor[n] >= 0) logf("[n6] kind 0x%x (%s): donor %s = kind 0x%x (row of the engine's name table %llx)", FIRST + n, g_name[n], g_donor_name[n], g_donor[n], (unsigned long long)NAME_TABLE);
        else all = 0;
    }
    if (all) InterlockedExchange(&done, 1);
}
static int dk(uint32_t kind) {                     // donor kind of a new kind
    int n = (int)kind - FIRST;
    if (n < 0 || n >= g_nnew) return 0;
    if (g_donor[n] < 0) {
        resolve_donors();
        if (g_donor[n] < 0) {
            static long said;
            if (said++ < 4) logf("[n6] kind 0x%x (%s): the donor name %s is NOT in the engine's name table: kind 0 (mario) is used", kind, g_name[n], g_donor_name[n]);
            return 0;
        }
    }
    return g_donor[n];
}
static void ensure_data(void) {
    if (InterlockedCompareExchange(&g_data_done, 1, 0)) return;
    static const uint64_t tab[4] = { 0x7104f80e20ull, 0x7104f811d0ull, 0x7104f80a70ull, 0x710453b1c0ull };
    static const char *what[4] = { "names", "sound names", "upper-case names", "kind hashes" };
    resolve_donors();
    for (int n = 0; n < g_nnew; n++) {
        const int DONOR = dk(FIRST + n);
        for (int t = 0; t < 4; t++) {
            uint64_t v = ((uint64_t *)(uintptr_t)tab[t])[DONOR];
            // N4_OWNNAME is a bit mask: 1 name (files, script module), 2 sound name, 4 upper-case name, 8 kind hash.
            // The strings live in this DLL: host addresses, which the recompiled game reads as they are.
            if (t == 0 && (g_ownname & 1)) v = (uint64_t)(uintptr_t)g_name[n];
            if (t == 1 && (g_ownname & 2)) v = (uint64_t)(uintptr_t)g_sound[n];
            if (t == 2 && (g_ownname & 4)) v = (uint64_t)(uintptr_t)g_upper[n];
            if (t == 3 && (g_ownname & 8)) v = g_hash[n];
            set_row(tab[t], FIRST + n, v, what[t]);
        }
    }
    DWORD old;
    VirtualProtect((void *)(uintptr_t)OWNER_TABLE, 4 * WEAPON_KINDS, PAGE_READWRITE, &old);
}
// N5: the weapon agent dispatchers (0x71033abee0 ..) take the owner kind of the weapon kind from the same table that
// the weapon init is lent (the live owner), build the agent name "<owner's name>_<weapon>" from it and jump by it:
// for a new kind that is a name no factory knows and no case of the jump table, so the weapon got NO agents at all
// (found in N5: a new kind's fireball spawned, flew, and never ran a script or hit anything). During the dispatcher
// the row is the weapon kind's static owner again; the agent the donor's factory returns is then moved to the live
// owner's module by the registry.
static int static_owner(int wk) {
    static int32_t keep[617]; static volatile LONG have;
    if (!InterlockedCompareExchange(&have, 1, 0)) memcpy(keep, (void *)(uintptr_t)OWNER_TABLE, sizeof keep);
    return wk >= 0 && wk < WEAPON_KINDS ? keep[wk] : -1;
}

// ---- live fighters and weapons ---------------------------------------------------------------------------------
struct Seen { uint64_t obj; int kind; };
static Seen g_fighter[16], g_weapon[512];
static int g_nfighter, g_nweapon;
static __declspec(thread) int t_init_kind = -1;        // kind of the fighter init running on this thread
static int trace_kind(void) { return t_init_kind; }
static int entry_kind(int slot) {                     // FighterManager -> entry[slot] + 0x88 (tests\DEBUG_MODE.md)
    if (slot < 0 || slot > 7) return -1;
    uint64_t mgr = *(uint64_t *)(uintptr_t)0x71052b84f8ull;
    if (!readable(mgr, 8)) return -2;
    uint64_t impl = *(uint64_t *)(uintptr_t)mgr;
    if (!readable(impl + 0x20 + 8 * slot, 8)) return -3;
    uint64_t e = *(uint64_t *)(uintptr_t)(impl + 0x20 + 8 * slot);
    if (!readable(e + 0x88, 4)) return -4;
    return *(int32_t *)(uintptr_t)(e + 0x88);
}
static void remember(Seen *tab, int *n, int cap, uint64_t obj, int kind) {
    for (int i = 0; i < *n; i++) if (tab[i].obj == obj) { tab[i].kind = kind; return; }
    if (*n < cap) { tab[*n].obj = obj; tab[*n].kind = kind; (*n)++; }
}
static int recall(Seen *tab, int n, uint64_t obj) {
    for (int i = 0; i < n; i++) if (tab[i].obj == obj) return tab[i].kind;
    return -1;
}

static HookOrig o_hash, o_record, o_callbacks, o_disp[9], o_build[2], o_get[2], o_loader, o_init, o_setup, o_winit, o_wdisp[4], o_fireball;
static long g_n_hash, g_n_record, g_n_callbacks, g_n_disp[9], g_n_build[2], g_n_get[2], g_n_init, g_n_winit, g_n_wdisp[4], g_n_swap, g_n_fire[0x80];

static void h_hash(Ctx *c, void *) {               // hash40 -> kind
    ensure_data();
    uint64_t h = c->x[0] & MASK40;
    for (int n = 0; n < g_nnew; n++)
        if (h == g_hash[n]) { if (!g_n_hash++) logf("[n4] kind: hash -> kind: %s -> 0x%x", g_name[n], FIRST + n); c->x[0] = FIRST + n; return; }
    o_hash(c);
}
static void h_w0(Ctx *c, HookOrig o, long *n, const char *what) {      // functions taking the kind in w0
    if (is_new((uint32_t)c->x[0])) {
        int d = dk((uint32_t)c->x[0]);
        if ((*n)++ < 2) logf("[n4] kind: %s asked for kind 0x%x -> the donor's (kind 0x%x)", what, (unsigned)c->x[0], d);
        c->x[0] = (uint64_t)d;
    }
    o(c);
}
static void h_record(Ctx *c, void *) { h_w0(c, o_record, &g_n_record, "description record"); }
// ---- N7: THE GENERAL WRAP OF A DONOR'S NATIVE CALLBACKS (plan\phases\N7_own_files2.md, task 3).
// A donor's callbacks object is a C++ object of the game; its functions (the entries of its class table) are native
// code that may compare the fighter's kind field with the donor's own constant (N6: one such compare made a clone of
// link crash). When the callbacks getter is asked for a NEW kind, every function of the donor object's class table is
// hooked once with h_cb: when one of its first four arguments is the fighter object of a new kind, or that fighter's
// module accessor, the fighter's kind field [object + 0xc] holds the DONOR's kind for the duration of the call, and
// the new kind again afterwards. A real donor fighter passes through untouched (pointer compares only).
// What this does not cover: native code reached some other way (article functions: the weapon table row is lent,
// N4), and code that runs INSIDE a wrapped callback sees the donor's kind too (by design).  N7_CBWRAP=0: off.
struct NewLive { uint64_t obj, acc; uint32_t id; };
static NewLive g_live[16]; static volatile LONG g_nlive;
static HookOrig o_cb[512]; static uint64_t g_cb_addr[512]; static int g_ncb; static long g_n_cb_swap, g_n_cb_logged; static int g_cbwrap = 1;
static uint64_t g_cb_done_vt[8]; static int g_ncb_vt;
static void h_cb(Ctx *c, void *u) {
    int i = (int)(intptr_t)u;
    /* Run n7l1: matching the argument against the pointer the fighter init got found nothing (the callbacks get another
     * object of the fighter, as N6's one-function hook did: it read [x1 + 0xc]). So the test is on the argument itself:
     * a readable object whose kind field (+ 0xc) is a new kind and which either carries the object id (+ 8) of a live
     * new-kind fighter or arrives while the init of that new kind runs on this thread. */
    LONG n = g_nlive;
    if (n || is_new((uint32_t)t_init_kind)) for (int a = 0; a < 4; a++) {
        uint64_t v = c->x[a];
        if (v < 0x10000 || (v & 7) || (v >> 47) || IsBadReadPtr((void *)(uintptr_t)v, 16)) continue;
        uint32_t *p = (uint32_t *)(uintptr_t)(v + 0xc);
        uint32_t was = *p, id = *(uint32_t *)(uintptr_t)(v + 8);
        if (!is_new(was)) continue;
        int mine = (int)was == t_init_kind;
        for (LONG f = 0; f < n && !mine; f++) mine = g_live[f].obj && g_live[f].id == id && id != 0;
        if (!mine) continue;
        g_n_cb_swap++;
        if (g_n_cb_logged < 8) { g_n_cb_logged++; logf("[n7] donor native callback %llx (class-table function %d) called for the new kind 0x%x (argument %d = object %llx, object id %x): the kind field is the donor's (0x%x) for the call",
                                                       (unsigned long long)g_cb_addr[i], i, was, a, (unsigned long long)v, id, dk(was)); }
        else if (g_n_cb_swap % 20000 == 0) logf("[n7] donor native callbacks: %ld calls so far ran with the donor's kind for a new kind's fighter", g_n_cb_swap);
        *p = (uint32_t)dk(was); o_cb[i](c); *p = was;
        return;
    }
    o_cb[i](c);
}
static void wrap_callbacks(uint64_t object, uint32_t kind) {
    if (!g_cbwrap || !readable(object, 8)) return;
    uint64_t vt = *(uint64_t *)(uintptr_t)object;
    EnterCriticalSection(&g_lock);
    for (int k = 0; k < g_ncb_vt; k++) if (g_cb_done_vt[k] == vt) { LeaveCriticalSection(&g_lock); return; }
    if (g_ncb_vt < 8) g_cb_done_vt[g_ncb_vt++] = vt;
    int entries = 0, fresh = 0, known = 0, failed = 0;
    for (int s = 0; s < 400 && readable(vt + 8ull * s, 8); s++) {
        uint64_t e = *(uint64_t *)(uintptr_t)(vt + 8ull * s);
        if (e < 0x7100000000ull || e >= 0x7104000000ull) break;      /* the end of the class table (the next table's header) */
        entries++;
        int have = 0;
        for (int k = 0; k < g_ncb; k++) if (g_cb_addr[k] == e) { have = 1; break; }
        if (have) { known++; continue; }
        if (g_ncb >= 512) { failed++; continue; }
        g_cb_addr[g_ncb] = e;
        if (api->install(e, h_cb, (void *)(intptr_t)g_ncb, &o_cb[g_ncb])) { g_ncb++; fresh++; } else failed++;
    }
    LeaveCriticalSection(&g_lock);
    logf("[n7] callbacks object %llx of the donor of kind 0x%x (donor kind 0x%x): class table %llx with %d functions: %d wrapped now, %d wrapped before (shared with another table), %d not hookable; %d wrapped functions in all",
         (unsigned long long)object, kind, dk(kind), (unsigned long long)vt, entries, fresh, known, failed, g_ncb);
}
static void h_callbacks(Ctx *c, void *) {
    uint32_t kind = (uint32_t)c->x[0];
    h_w0(c, o_callbacks, &g_n_callbacks, "callbacks object");
    if (is_new(kind)) wrap_callbacks(c->x[0], kind);
}
// N6: 0x71006cdd20(w0 = fighter kind, x1, x2 = the fighter's module accessor): a 95-way jump table by kind
// (`cmp w0, #94 ; b.hi default`, table 0x71044be758) that sets up per-kind things of the fighter's modules. N2 listed
// it as not examined; Mario's case never mattered. For the donor link the default taken for 0x5F left the collision
// objects of its shield group unmade, and the donor's callback 0x7100c28280 (shield module, group 1) then read a null
// pointer (run l_a: HOST EXCEPTION reading 0xc in 0x71004c6b20, return address 0x7100c282ac). The donor's case runs.
static HookOrig o_setup2; static long g_n_setup2;
static void h_setup2(Ctx *c, void *) { h_w0(c, o_setup2, &g_n_setup2, "per-kind module setup 0x71006cdd20"); }
// N6_TRACE=<hex address>[,..]: debugging aid: log the callers of up to 8 game functions (return address, x0..x3, the
// kind of the fighter init running on the thread), the first N6_TRACE_MAX (default 60) calls of each.
static HookOrig o_trace[8]; static uint64_t g_trace_addr[8]; static long g_n_trace[8]; static long g_trace_max = 60;
static int trace_kind(void);
static void h_trace(Ctx *c, void *u) {
    int i = (int)(intptr_t)u;
    if (g_n_trace[i]++ < g_trace_max)
        logf("[n6trace] %llx called from %llx: x0 %llx x1 %llx x2 %llx x3 %llx, fighter init on this thread: kind 0x%x", (unsigned long long)g_trace_addr[i], (unsigned long long)c->x[30],
             (unsigned long long)c->x[0], (unsigned long long)c->x[1], (unsigned long long)c->x[2], (unsigned long long)c->x[3], trace_kind());
    // N6_TRACE_SET=1: x0 is a collision set (0x71004c5780 ..): its group count [x0+0x48] and, per 0x2d0-byte group
    // element at [x0+0x50], first index / count (+8, +0xc) and the first collision object pointer (+0x30)
    static int set_dump = -1; if (set_dump < 0) set_dump = getenv("N6_TRACE_SET") != nullptr;
    if (set_dump && g_n_trace[i] <= g_trace_max && readable(c->x[0] + 0x48, 16)) {
        uint32_t ng = *(uint32_t *)(uintptr_t)(c->x[0] + 0x48); uint64_t el = *(uint64_t *)(uintptr_t)(c->x[0] + 0x50);
        char t[300]; int k = 0; t[0] = 0;
        for (uint32_t g = 0; g < ng && g < 6 && readable(el + 0x2d0ull * g, 0x38); g++) {
            uint8_t *e2 = (uint8_t *)(uintptr_t)(el + 0x2d0ull * g);
            k += snprintf(t + k, sizeof t - k, " [%u: first %d count %d object %llx]", g, *(int32_t *)(e2 + 8), *(int32_t *)(e2 + 12), *(unsigned long long *)(e2 + 0x30));
        }
        logf("[n6trace]    set %llx: %u groups, elements at %llx:%s", (unsigned long long)c->x[0], ng, (unsigned long long)el, t);
    }
    o_trace[i](c);
}
// N6: THE DONOR'S NATIVE CODE COMPARES THE FIGHTER'S KIND WITH ITS OWN. Found with the donor link (run l_a): its
// callback 0x7100c280f0(this, x1 = fighter object) is shared by link (2), younglink (23) and toonlink (46); it reads
// the kind at [x1 + 0xc], takes A[that kind] by a constant offset and SKIPS the set-up of the shield group for any
// other kind (0x7100c28164..0x7100c28178 -> 0x7100c28230); the next callback 0x7100c28280 then uses the collision
// object that was never taken from the pool (null). Mario's callbacks have no such compare. Not general yet: only
// the functions listed here (N6_KINDFIELD=<hex,..>, default 7100c280f0) run with the kind field [x1 + 0xc] set to the
// donor's kind for the call; the general fix is a wrapper on every entry of the donor's callbacks object.
static HookOrig o_kf[8]; static long g_n_kf[8]; static uint64_t g_kf_addr[8];
static void h_kindfield(Ctx *c, void *u) {
    int i = (int)(intptr_t)u;
    uint32_t *p = (uint32_t *)(uintptr_t)(c->x[1] + 0xc);
    if (readable(c->x[1] + 0xc, 4) && is_new(*p)) {
        uint32_t was = *p;
        if (g_n_kf[i]++ < 3) logf("[n6] donor native function %llx called for a fighter object with kind 0x%x: the kind field is the donor's (0x%x) for the call", (unsigned long long)g_kf_addr[i], was, dk(was));
        *p = (uint32_t)dk(was); o_kf[i](c); *p = was;
        return;
    }
    o_kf[i](c);
}
static void h_get(Ctx *c, void *u) { int i = (int)(intptr_t)u; h_w0(c, o_get[i], &g_n_get[i], i ? "getter 0x710033c510" : "getter 0x710033ba50"); }
static void h_disp(Ctx *c, void *u) {              // dispatchers 0..4: kind at [x0 + 0xc]; 5..8: kind in w0
    int i = (int)(intptr_t)u;
    if (i >= 5) {
        uint32_t kind = (uint32_t)c->x[0];
        if (g_reg && is_new(kind)) g_reg->agent_begin(g_name[kind - FIRST]);
        h_w0(c, o_disp[i], &g_n_disp[i], "script dispatcher (share)");
        if (g_reg) g_reg->agent_end(is_new(kind) ? g_name[kind - FIRST] : nullptr, c->x[0]);
        return;
    }
    uint32_t *k = (uint32_t *)(uintptr_t)(c->x[0] + 0xc);
    uint32_t kind = *k;
    if (is_new(kind)) {
        const int DONOR = dk(kind);
        if (g_n_disp[i]++ < 2) logf("[n4] kind: script dispatcher %d asked for kind 0x%x -> the donor's factory (kind 0x%x)%s", i, kind, DONOR, g_reg ? ", the agent goes to the new fighter's own module" : "");
        if (g_reg) g_reg->agent_begin(g_name[kind - FIRST]);
        *k = DONOR; o_disp[i](c); *k = kind;
        if (g_reg) g_reg->agent_end(g_name[kind - FIRST], c->x[0]);
        return;
    }
    o_disp[i](c);
    if (g_reg) g_reg->agent_end(nullptr, c->x[0]);
}
// ---- N5: THE FIGHTER'S OWN PARAMETER FILES, read by the parameter-object builders from its folder.
// The builders parse the donor's two per-fighter parameter files out of the archive's "loaded data" buffers (the
// path of the new name is answered with the donor's file: one file, one buffer, shared with a real donor). When
// <fighter folder>\fighter\<name>\param\<file> exists, the loaded-data entry of the donor's file points to OUR copy
// of that file for the duration of the builder call made for the new kind (under the lock that serialises the
// builders), and to the archive's buffer again afterwards: the new kind's parameter object is built from its own
// file, the donor's from the archive's. Tables (reference\smash-arc; offsets as in loose_files.c): filesystem info
// *(0x7105331f20): +0x08 loaded file paths (8 bytes: loaded data index, flags), +0x10 loaded datas (0x18 bytes: +0
// buffer), +0x78 -> { archive tables }: +0x50 buckets, +0x58 hash -> file path index entries.
static const char *const OWN_PARAM[2] = { "vl.prc", "expression_vl.prc" };
static struct { uint8_t *data; long size; int tried; } g_own[MAXNEW][2];
static struct { uint64_t *slot; uint64_t was; } g_lent[2]; static int g_nlent;
static long g_n_own;
static int64_t arc_file_index(const char *path) {
    uint64_t h = hash40(path);
    uint64_t fsinfo = *(uint64_t *)(uintptr_t)0x7105331f20ull;
    if (!readable(fsinfo + 0x78, 8)) return -1;
    uint64_t holder = *(uint64_t *)(uintptr_t)(fsinfo + 0x78);
    if (!readable(holder, 8)) return -1;
    uint64_t tab = *(uint64_t *)(uintptr_t)holder;
    if (!readable(tab + 0x50, 16)) return -1;
    uint64_t buckets = *(uint64_t *)(uintptr_t)(tab + 0x50), entries = *(uint64_t *)(uintptr_t)(tab + 0x58);
    if (!readable(buckets, 8)) return -1;
    uint32_t nb = *(uint32_t *)(uintptr_t)(buckets + 4);
    if (!nb) return -1;
    uint32_t *b = (uint32_t *)(uintptr_t)(buckets + 8 + (h % nb) * 8);
    for (uint32_t k = 0; k < b[1]; k++) {
        uint64_t e = *(uint64_t *)(uintptr_t)(entries + 8ull * (b[0] + k));
        if ((e & MASK40) == h) return (int64_t)(e >> 40);
    }
    return -1;
}
static void own_param_begin(uint32_t kind) {
    g_nlent = 0;
    if (!g_reg || !is_new(kind)) return;
    int n = (int)kind - FIRST;
    const SsbuRegFighter *f = &g_reg->fighters[n];
    for (int k = 0; k < 2; k++) {
        if (!g_own[n][k].tried) {
            g_own[n][k].tried = 1;
            char path[600]; snprintf(path, sizeof path, "%s\\fighter\\%s\\param\\%s", f->folder, f->name, OWN_PARAM[k]);
            FILE *fp = fopen(path, "rb");
            if (fp) {
                fseek(fp, 0, SEEK_END); long sz = ftell(fp); fseek(fp, 0, SEEK_SET);
                uint8_t *d = (uint8_t *)VirtualAlloc(nullptr, (size_t)sz + 0x1000, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
                if (d && sz > 8 && fread(d, 1, (size_t)sz, fp) == (size_t)sz) { g_own[n][k].data = d; g_own[n][k].size = sz; }
                fclose(fp);
            }
        }
        if (!g_own[n][k].data) continue;
        char donor[200]; snprintf(donor, sizeof donor, "fighter/%s/param/%s", f->donor, OWN_PARAM[k]);
        int64_t fi = arc_file_index(donor);
        uint64_t fsinfo = *(uint64_t *)(uintptr_t)0x7105331f20ull;
        if (fi < 0 || !readable(fsinfo + 8, 16)) continue;
        uint64_t lfp = *(uint64_t *)(uintptr_t)(fsinfo + 8), ld = *(uint64_t *)(uintptr_t)(fsinfo + 0x10);
        if (!readable(lfp + 8ull * fi, 8)) continue;
        uint32_t ldi = *(uint32_t *)(uintptr_t)(lfp + 8ull * fi);
        if (ldi == 0xffffffffu || !readable(ld + 0x18ull * ldi, 0x18)) continue;
        uint64_t *slot = (uint64_t *)(uintptr_t)(ld + 0x18ull * ldi);
        // both must be parameter files (the same 8-byte magic at the start), or nothing is lent
        if (!readable(*slot, 8) || memcmp((void *)(uintptr_t)*slot, g_own[n][k].data, 8) != 0) {
            if (g_n_own++ < 4) logf("[n5] own parameter file %s of %s: the archive's buffer of %s is not there or not the same kind of file: NOT lent", OWN_PARAM[k], f->name, donor);
            continue;
        }
        g_lent[g_nlent].slot = slot; g_lent[g_nlent].was = *slot; g_nlent++;
        *slot = (uint64_t)(uintptr_t)g_own[n][k].data;
        if (g_n_own++ < 8) logf("[n5] kind 0x%x: parameter builder reads %s\\fighter\\%s\\param\\%s (%ld bytes) instead of the archive's %s (file path index 0x%llx, loaded data %u, buffer %llx): for this call only",
                                kind, f->folder, f->name, OWN_PARAM[k], g_own[n][k].size, donor, (unsigned long long)fi, ldi, (unsigned long long)g_lent[g_nlent - 1].was);
    }
}
static void own_param_end(void) {
    for (int k = 0; k < g_nlent; k++) *g_lent[k].slot = g_lent[k].was;
    g_nlent = 0;
}
static void h_build(Ctx *c, void *u) {             // (this, kind, x2): the case builds the kind's parameter object and stores it in A[kind]
    int i = (int)(intptr_t)u;
    uint32_t kind = (uint32_t)c->x[1];
    if (!is_new(kind)) { o_build[i](c); return; }
    const int DONOR = dk(kind);
    uint8_t *P = (uint8_t *)(uintptr_t)c->x[0], *a0 = P + 0x60 + 0x38 * DONOR, *an = P + 0x60 + 0x38 * kind, keep[0x38];
    uint64_t arg[8]; memcpy(arg, c->x, sizeof arg);
    // THE DONOR AS A DEPENDENCY. The donor's native code (its callbacks object, e.g. 0x7100cb9620) reads the donor's
    // own row of array A with a CONSTANT offset (singleton + 0x70 = A[0] + 0x10), whatever fighter it runs for. A new
    // kind that uses a donor's callbacks therefore needs the donor's parameter objects to exist. The game's caller
    // (0x7100607b2c..) builds a kind's objects when the row's use counter (row + 0) is 0 and then counts one user;
    // we do the same for the donor: build once, count one user, so that a real donor fighter arriving later shares
    // the objects instead of building them a second time (N3's workaround did not count: run ii5).
    // N6: the constant offset is the DONOR's row (A[donor] + 0x10), so the dependency is per donor kind.
    static int dep_pending_k[FIRST];
    int &dep_pending = dep_pending_k[DONOR];
    uint32_t *cnt = (uint32_t *)a0;
    if (!g_a0_workaround && ((i == 0 && *cnt == 0 && *(uint64_t *)(a0 + 0x18) == 0) || (i == 1 && dep_pending))) {
        c->x[1] = DONOR; o_build[i](c);
        memcpy(c->x, arg, sizeof arg);
        if (i == 0) dep_pending = 1;
        else { dep_pending = 0; (*cnt)++; logf("[n4] kind: donor kind %d loaded as a dependency of kind 0x%x: A[%d] = %llx | %llx, use counter %u", DONOR, kind, DONOR,
                                               *(unsigned long long *)(a0 + 0x10), *(unsigned long long *)(a0 + 0x28), *cnt); }
    }
    EnterCriticalSection(&g_lock);
    memcpy(keep, a0, 0x38); memcpy(a0, an, 0x38);          // the donor's case works on row 0: lend it the new row for the call
    own_param_begin(kind);                                 // N5: the fighter's OWN parameter files, when its folder has them
    c->x[1] = DONOR; o_build[i](c);
    own_param_end();
    memcpy(an, a0, 0x38); memcpy(a0, keep, 0x38);
    LeaveCriticalSection(&g_lock);
    if (g_n_build[i]++ < 6) logf("[n4] kind: parameter object builder %d ran the donor's case for kind 0x%x: A[0x%x] = %llx %llx | %llx %llx ; A[donor 0x%x] = %llx | %llx", i, kind, kind,
                              *(unsigned long long *)(an + 0x10), *(unsigned long long *)(an + 0x18), *(unsigned long long *)(an + 0x28), *(unsigned long long *)(an + 0x30),
                              DONOR, *(unsigned long long *)(a0 + 0x10), *(unsigned long long *)(a0 + 0x28));
}
// A REAL ROW PER NEW KIND in the three row vectors the loader fills from fighter_param.prc / fighter_param_motion.prc
// (holders at singleton + 0, + 0x10, + 0x20: begin at holder + 8, end at + 0x10; rows of 0x628, 0x218, 0x68 bytes; the
// row's first 8 bytes are its fighter_kind hash: read in 0x710070a464..0x710070a540). N4_ROW=1: each vector gets one
// more row per new kind (a copy of the donor's row with the new kind's hash) in a buffer from the game's own
// allocator (0x710392dce0(align, size)), and B[new kind] = the new indexes.
// N4_ROW_FIND=<hex bits> N4_ROW_SET=<hex bits>: in the new 0x628-byte row every 32-bit word equal to FIND becomes SET.
static int g_row, g_row_off[8], g_row_noff; static uint32_t g_row_find, g_row_set;
static uint64_t game_call2(Ctx *c, uint64_t addr, uint64_t a0, uint64_t a1) {
    uint64_t keep[31]; memcpy(keep, c->x, sizeof keep);
    c->x[0] = a0; c->x[1] = a1;
    api->call(c, addr);
    uint64_t r = c->x[0];
    memcpy(c->x, keep, sizeof keep);
    return r;
}
static int add_rows(Ctx *c, uint8_t *P, int holder_off, size_t row, int32_t *idx_out) {
    uint64_t holder = *(uint64_t *)(P + holder_off);
    if (!readable(holder + 8, 0x18)) return 0;
    uint64_t *v = (uint64_t *)(uintptr_t)(holder + 8);              // begin, end, capacity end
    uint8_t *b = (uint8_t *)(uintptr_t)v[0], *e = (uint8_t *)(uintptr_t)v[1];
    size_t n = (size_t)(e - b) / row;
    int donor_row[MAXNEW];
    for (int k = 0; k < g_nnew; k++) {                  // N6: the donor's row of EACH new kind
        int donor = -1;
        uint64_t dh = ((uint64_t *)(uintptr_t)0x710453bc58ull)[dk(FIRST + k)] & MASK40;       // the loader's own list of kind hashes
        for (size_t i = 0; i < n; i++) if ((*(uint64_t *)(b + i * row) & MASK40) == dh) { donor = (int)i; break; }
        if (donor < 0) { logf("[n6] kind: row vector of 0x%x-byte rows: no row with the kind hash %llx of the donor %s: no rows added", (unsigned)row, (unsigned long long)dh, g_donor_name[k]); return 0; }
        donor_row[k] = donor;
    }
    uint8_t *nb = (uint8_t *)(uintptr_t)game_call2(c, 0x710392dce0ull, 0x10, (n + g_nnew) * row);
    if (!nb) return 0;
    memcpy(nb, b, n * row);
    for (int k = 0; k < g_nnew; k++) {
        uint8_t *r = nb + (n + k) * row;
        memcpy(r, nb + donor_row[k] * row, row);
        uint64_t h = *(uint64_t *)r; h = (h & ~MASK40) | g_hash[k]; memcpy(r, &h, 8);
        idx_out[k] = (int32_t)(n + k);
        if (row == 0x628 && g_row_find)
            for (size_t o = 8; o + 4 <= row; o += 4)
                if (*(uint32_t *)(r + o) == g_row_find) { *(uint32_t *)(r + o) = g_row_set; if (k == 0 && g_row_noff < 8) g_row_off[g_row_noff++] = (int)o; }
    }
    v[0] = (uint64_t)(uintptr_t)nb; v[1] = (uint64_t)(uintptr_t)(nb + (n + g_nnew) * row);
    if (v[2] >= (uint64_t)(uintptr_t)e && v[2] - (uint64_t)(uintptr_t)e < 0x100000) v[2] = v[1];      // capacity end, if this is one
    // the old buffer is NOT given back (who allocated it was not checked): a leak of n rows, once per run
    {
        char rows[120]; int rk = 0; rows[0] = 0;
        for (int k = 0; k < g_nnew; k++) rk += snprintf(rows + rk, sizeof rows - rk, "%s%d (%s)", k ? ", " : "", donor_row[k], g_donor_name[k]);
        logf("[n4] kind: row vector of 0x%x-byte rows: %d -> %d rows (donor's row %s copied with the new kind hash; new buffer %p from the game's allocator)",
             (unsigned)row, (int)n, (int)n + g_nnew, rows, (void *)nb);
    }
    return 1;
}
static void h_loader(Ctx *c, void *) {             // loads fighter_param: writes B[0..0x5D]; the rows of the new kinds are ours
    uint8_t *P = (uint8_t *)(uintptr_t)c->x[0];
    ensure_data();
    o_loader(c);
    int32_t *b = (int32_t *)(P + NEW_B);
    for (int n = 0; n < g_nnew; n++) memcpy(b + 3 * (FIRST + n), b + 3 * dk(FIRST + n), 12);
    if (g_row) {
        int32_t i0[MAXNEW], i1[MAXNEW], i2[MAXNEW];
        // The third table (0x68-byte rows) is a KIND x KIND matrix: each row holds four vectors with 3 floats per
        // OPPONENT kind, indexed with B[opponent] (accessor 0x7100720f90). A row index 94 there means element 282 of
        // vectors that have 282 elements: std::out_of_range (run H1). Growing it needs a column per new kind in
        // every row; until then a new kind keeps the donor's row AND column there (N4_ROW=2 shows the failure).
        int ok0 = add_rows(c, P, 0x00, 0x628, i0), ok1 = add_rows(c, P, 0x10, 0x218, i1), ok2 = g_row >= 2 ? add_rows(c, P, 0x20, 0x68, i2) : 0;
        for (int n = 0; n < g_nnew; n++) {
            if (ok0) b[3 * (FIRST + n) + 0] = i0[n];
            if (ok1) b[3 * (FIRST + n) + 1] = i1[n];
            if (ok2) b[3 * (FIRST + n) + 2] = i2[n];
        }
        char offs[120]; int k = 0; offs[0] = 0;
        for (int i = 0; i < g_row_noff; i++) k += snprintf(offs + k, sizeof offs - k, " +0x%x", g_row_off[i]);
        for (int n = 0; n < g_nnew; n++) {
            int K = FIRST + n, D = dk(K);
            logf("[n4] kind: OWN ROWS: B[0x%x] = %d %d %d (the donor's, kind 0x%x: %d %d %d); edit %08x -> %08x made in the new 0x628 row at:%s", K,
                 b[3 * K], b[3 * K + 1], b[3 * K + 2], D, b[3 * D], b[3 * D + 1], b[3 * D + 2], g_row_find, g_row_set, g_row_noff ? offs : " (nowhere)");
        }
    }
    logf("[n4] kind: parameter loader done: B[0x%x] = %d %d %d, B[0] = %d %d %d (B[1] = %d %d %d)", FIRST, b[3 * FIRST], b[3 * FIRST + 1], b[3 * FIRST + 2], b[0], b[1], b[2], b[3], b[4], b[5]);
}
// read-back of the edited value through the game's own index: singleton -> row vector -> row B[kind]
static void row_readback(int kind, const char *when) {
    uint8_t *P = *(uint8_t **)(uintptr_t)0x71052bb3b0ull;
    if (!P || !g_row_noff) return;
    int32_t idx = ((int32_t *)(P + NEW_B))[3 * kind];
    uint64_t holder = *(uint64_t *)P, beg = *(uint64_t *)(uintptr_t)(holder + 8), end = *(uint64_t *)(uintptr_t)(holder + 0x10);
    uint64_t r = beg + (uint64_t)idx * 0x628;
    if (idx < 0 || r + 0x628 > end) { logf("[n4] row read-back %s: kind 0x%x has row index %d outside the vector", when, kind, idx); return; }
    uint32_t w = *(uint32_t *)(uintptr_t)(r + g_row_off[0]);
    logf("[n4] row read-back %s: kind 0x%x -> row %d of %d (fighter_kind hash %llx), value at +0x%x = %08x (%g)", when, kind, idx, (int)((end - beg) / 0x628),
         (unsigned long long)(*(uint64_t *)(uintptr_t)r & MASK40), g_row_off[0], w, *(float *)&w);
}
static void h_setup(Ctx *c, void *) {              // second per-kind container: rows 0x5E.. become empty lists
    o_setup(c);
    uint64_t *p = *(uint64_t **)(uintptr_t)0x71052bb3a8ull;
    if (!p) return;
    int done = 0;
    for (int k = 0x5e; k < 0x72; k++) {
        uint64_t *row = p + 3 * k;
        if (row[0] == 0 && row[1] == 0) { row[0] = row[1] = (uint64_t)(uintptr_t)row; row[2] = 0; done++; }
    }
    if (done) logf("[n4] kind: second per-kind container %p: %d rows from 0x5e made empty lists", (void *)p, done);
}
static void h_init(Ctx *c, void *) {               // fighter init: x0 = fighter object, x1 = init description, kind at +0x9c
    uint64_t d = c->x[1], obj = c->x[0];
    int kind = readable(d + 0x9c, 4) ? *(int32_t *)(uintptr_t)(d + 0x9c) : -99;
    int slot = readable(d + 0xa8, 4) ? *(int32_t *)(uintptr_t)(d + 0xa8) : -1;
    remember(g_fighter, &g_nfighter, 16, obj, kind);
    int was = t_init_kind; t_init_kind = kind;
    {   /* N7: the live new-kind fighters, for the wrap of the donor's callbacks: this object leaves the list when it is
         * initialised again as another kind; a new kind's object and its module accessor (object + 0x20, checked by
         * the object id both carry at + 8) enter it BEFORE the init runs (callbacks are called inside it) */
        LONG n = g_nlive; int at = -1;
        for (LONG f = 0; f < n; f++) if (g_live[f].obj == obj) at = (int)f;
        if (is_new((uint32_t)kind)) {
            if (at < 0 && n < 16) { at = (int)n; g_live[at].acc = 0; g_live[at].obj = obj; InterlockedExchange(&g_nlive, n + 1); }
        } else if (at >= 0) g_live[at].obj = 0, g_live[at].acc = 0;
    }
    o_init(c);
    t_init_kind = was;
    if (is_new((uint32_t)kind) && readable(obj + 0x20, 8)) {
        uint64_t acc = *(uint64_t *)(uintptr_t)(obj + 0x20);
        int ok = readable(acc + 8, 4) && *(uint32_t *)(uintptr_t)(acc + 8) == *(uint32_t *)(uintptr_t)(obj + 8);
        for (LONG f = 0; f < g_nlive; f++) if (g_live[f].obj == obj) { g_live[f].acc = ok ? acc : 0; g_live[f].id = *(uint32_t *)(uintptr_t)(obj + 8); }
        static long said; if (said++ < 4) logf("[n7] new kind 0x%x: fighter object %llx, module accessor %llx (%s): the donor's wrapped callbacks see the donor's kind for this fighter", kind,
                                               (unsigned long long)obj, (unsigned long long)acc, ok ? "same object id" : "NOT recognised: only the object pointer is matched");
    }
    if (g_n_init++ < 16) logf("[n4] kind: fighter init 0x71006867e0 returned: object %llx kind 0x%x, slot %d, object id %x, object kind field %x",
                              (unsigned long long)obj, kind, slot, *(uint32_t *)(uintptr_t)(obj + 8), *(uint32_t *)(uintptr_t)(obj + 0xc));
    if (g_row && kind >= 0 && kind < 0x72) row_readback(kind, "after the fighter init");
}

// ---- weapons: the live owner -----------------------------------------------------------------------------------
static int with_owner(Ctx *c, HookOrig o, int wk, int live) {      // run o with OWNER_TABLE[wk] = live
    int32_t *t = (int32_t *)(uintptr_t)OWNER_TABLE;
    static_owner(0);                                    // N5: the table as the game has it, before the first row is lent
    if (wk < 0 || wk >= WEAPON_KINDS || live < 0 || t[wk] == live || !is_new((uint32_t)live)) { o(c); return 0; }
    EnterCriticalSection(&g_lock);
    int32_t was = t[wk];
    t[wk] = live; o(c); t[wk] = was;
    LeaveCriticalSection(&g_lock);
    g_n_swap++;
    return 1;
}
static void h_winit(Ctx *c, void *) {              // weapon init (weapon object, description)
    ensure_data();
    uint64_t w = c->x[0], d = c->x[1];
    int wk = *(int32_t *)(uintptr_t)(d + 0x9c);
    int32_t a8 = *(int32_t *)(uintptr_t)(d + 0xa8);
    int stat = (wk >= 0 && wk < WEAPON_KINDS) ? ((int32_t *)(uintptr_t)OWNER_TABLE)[wk] : -1;
    int by_slot = entry_kind(a8 >= 0 ? (a8 & 7) : -1), by_init = t_init_kind;
    int live = by_init >= 0 ? by_init : by_slot;
    remember(g_weapon, &g_nweapon, 512, w, live);
    int sw = g_a0_workaround ? (o_winit(c), 0) : with_owner(c, o_winit, wk, live);
    if (g_n_winit++ < g_weapon_log) {
        // 0x71033babd0 stores the owner's first parameter object (shared pointer) at weapon + 0x38d0 + 8
        uint8_t *P = *(uint8_t **)(uintptr_t)0x71052bb3b0ull;
        unsigned long long got = *(unsigned long long *)(uintptr_t)(w + 0x38d8);
        unsigned long long a_stat = (P && stat >= 0) ? *(unsigned long long *)(P + 0x60 + 0x38 * stat + 0x10) : 0;
        unsigned long long a_live = (P && live >= 0) ? *(unsigned long long *)(P + 0x60 + 0x38 * live + 0x10) : 0;
        logf("[n4] weapon init: object %llx weapon kind 0x%x, static owner kind 0x%x, live owner (the fighter init running on this thread) 0x%x%s; the weapon's parameter object %llx; A[static owner] %llx, A[live owner] %llx -> %s",
             (unsigned long long)w, wk, stat, live, sw ? " (table row lent)" : "", got, a_stat, a_live,
             got == a_live ? (a_live == a_stat ? "same object" : "THE LIVE OWNER'S") : got == a_stat ? "the static owner's" : "neither");
    }
    (void)by_slot;
}
// 0x71017e88d0(out, x1, fighter kind, file type): builds the path of one of the kind's files and looks it up; the
// first word of `out` is what 0x710353e4e0 turns into a file index (0xffffff = the archive has no such path).
static HookOrig o_path; static long g_n_path;
static void h_path(Ctx *c, void *) {
    uint64_t out = c->x[0]; uint32_t kind = (uint32_t)c->x[2], type = (uint32_t)c->x[3];
    o_path(c);
    if (is_new(kind) && g_n_path++ < 40)
        logf("[n4] file path asked for kind 0x%x, file type 0x%x (caller %llx): result words %x %x %x %x", kind, type, (unsigned long long)c->x[30],
             *(uint32_t *)(uintptr_t)out, *(uint32_t *)(uintptr_t)(out + 4), *(uint32_t *)(uintptr_t)(out + 8), *(uint32_t *)(uintptr_t)(out + 12));
}
static void h_wdisp(Ctx *c, void *u) {             // weapon agent dispatcher (weapon object, ...)
    int i = (int)(intptr_t)u;
    uint64_t w = c->x[0];
    int wk = *(int32_t *)(uintptr_t)(w + 0xc);
    int live = recall(g_weapon, g_nweapon, w);
    // N5: the dispatchers run INSIDE the weapon init, which runs inside the owner's fighter init on this thread (the
    // object in x0 is not the one the weapon init got: nothing was ever recalled in N4): the live owner is that fighter
    if (live < 0 && t_init_kind >= 0) live = t_init_kind;
    { static long seen; if (seen++ < 8) logf("[n5] weapon agent dispatcher %d called: x0 %llx (weapon kind field 0x%x), x1 %llx, recorded live owner 0x%x, %d weapons recorded",
                                              i, (unsigned long long)w, wk, (unsigned long long)c->x[1], live, g_nweapon); }
    if (is_new((uint32_t)live)) {
        // the agent comes from the donor's script module: the table row stays the donor's for this call
        if (g_n_wdisp[i]++ < 2) logf("[n4] weapon agent dispatcher %d: weapon kind 0x%x of live owner 0x%x -> the donor module's factory%s", i, wk, live,
                                     g_reg ? ", the agent goes to the live owner's own module" : "");
        if (g_reg) {
            int32_t *t = (int32_t *)(uintptr_t)OWNER_TABLE;
            int so = static_owner(wk);
            g_reg->agent_begin(g_name[live - FIRST]);
            EnterCriticalSection(&g_lock);              // the weapon init above us on this thread holds it already
            int32_t was = (wk >= 0 && wk < WEAPON_KINDS) ? t[wk] : 0;
            if (so >= 0) t[wk] = so;
            o_wdisp[i](c);
            if (so >= 0) t[wk] = was;
            LeaveCriticalSection(&g_lock);
            g_reg->agent_end(g_name[live - FIRST], c->x[0]);
            return;
        }
    }
    o_wdisp[i](c);
    if (g_reg) g_reg->agent_end(nullptr, c->x[0]);
}
// ---- N5: the computer player. The eight AI functions N2 lists switch on a fighter kind they read from memory:
//   0x71002c5cf0, 0x71002c9900                 kind at [x0 + 0xc04]
//   0x710034b310, 0x7100351630, 0x710035fc50    kind at [x0 + 0x28]
//   0x7100362df0, 0x710036c1c0, 0x71003719c0    kind at [[[x0 - 8] + 0x168] + 0x28]   (script functions: x0 = lua state)
// A new kind takes the default branch everywhere (N4: the CPU stands still). Here the kind FIELD of such an object
// is given the donor's kind when one of these functions is entered with it: the AI then uses the donor's rows for
// the new fighter. N5_AI=0 switches it off. What else reads these fields was not examined.
static HookOrig o_ai[8]; static long g_n_ai[8]; static int g_ai = 1;
static void h_ai(Ctx *c, void *u) {
    int i = (int)(intptr_t)u;
    uint64_t p = 0;
    if (i < 2) p = c->x[0] + 0xc04;
    else if (i < 5) p = c->x[0] + 0x28;
    else if (readable(c->x[0] - 8, 8)) {
        uint64_t a = *(uint64_t *)(uintptr_t)(c->x[0] - 8);
        if (readable(a + 0x168, 8)) p = *(uint64_t *)(uintptr_t)(a + 0x168) + 0x28;
    }
    if (g_ai && p && readable(p, 4) && is_new(*(uint32_t *)(uintptr_t)p)) {
        uint32_t was = *(uint32_t *)(uintptr_t)p;
        const int DONOR = dk(was);
        *(uint32_t *)(uintptr_t)p = DONOR;
        if (g_n_ai[i]++ < 3) logf("[n5] AI function %d: the kind field at %llx was 0x%x -> the donor's kind %d (written once per object)", i, (unsigned long long)p, was, DONOR);
    }
    o_ai[i](c);
}
// ---- N5: Kirby's copy resources. 0x71017f0bd0(x0, x1 -> fighter kind, ...) takes a row of the pointer table
// 0x710509ece0[kind] (8 bytes per kind; row -> the kind's copy-ability name strings) and builds resource paths from
// it (0x71017f06e0); the table has no row for a new kind (N4 run r2: the crash while loading). For the call the
// kind the function reads is the donor's: Kirby gets the DONOR's copy ability for a new fighter. N5_KIRBY=0: off.
static HookOrig o_kirby; static long g_n_kirby; static int g_kirby = 1;
static void h_kirby(Ctx *c, void *) {
    uint32_t *p = (uint32_t *)(uintptr_t)c->x[1];
    if (g_kirby && readable(c->x[1], 4) && is_new(*p)) {
        uint32_t was = *p;
        if (g_n_kirby++ < 4) logf("[n5] copy-ability resources asked for kind 0x%x (caller %llx): the donor's row of the table is used", was, (unsigned long long)c->x[30]);
        *p = (uint32_t)dk(was); o_kirby(c); *p = was;
        return;
    }
    o_kirby(c);
}
static void h_fireball(Ctx *c, void *) {           // (article, owner's module accessor)
    uint64_t acc = c->x[1];
    uint32_t id = readable(acc + 8, 4) ? *(uint32_t *)(uintptr_t)(acc + 8) : 0;
    int kind = 0x7f;
    for (int i = 0; i < g_nfighter; i++) if (*(uint32_t *)(uintptr_t)(g_fighter[i].obj + 8) == id) kind = g_fighter[i].kind & 0x7f;
    long n = ++g_n_fire[kind];
    if (n <= 3 || n % 10 == 0) logf("[n4] fireball article function: owner object id %x, owner kind 0x%x: number %ld of that kind", id, kind, n);
    if (n == 1 && kind < 0x72 && getenv("N4_PARAM_DUMP")) {
        // read-back for the loose-file proof: the kind's first parameter object (A[kind] + 0x10; the donor's class, 0x1c8 bytes)
        uint8_t *P = *(uint8_t **)(uintptr_t)0x71052bb3b0ull;
        uint64_t obj = P ? *(uint64_t *)(P + 0x60 + 0x38 * kind + 0x10) : 0;
        for (int off = 0; obj && readable(obj, 0x1c8) && off < 0x1c8; off += 0x40) {
            char line[400]; int k = 0;
            for (int j = 0; j < 0x40 && off + j < 0x1c8; j += 4) k += snprintf(line + k, sizeof line - k, " %08x", *(uint32_t *)(uintptr_t)(obj + off + j));
            logf("[n4] parameter object of kind 0x%x +0x%03x:%s", kind, off, line);
        }
        // the object is a row of vectors {begin, end, capacity}: count the 32-bit words of their contents that carry
        // the test mark (low 12 bits 0x5a5, tests\n4_prc_mark.py) and show the first ones
        int words = 0, marked = 0, shown = 0; char first[400]; int fk = 0; first[0] = 0;
        for (int off = 8; obj && readable(obj, 0x1c8) && off + 16 <= 0x1c8; off += 8) {
            uint64_t b = *(uint64_t *)(uintptr_t)(obj + off), e = *(uint64_t *)(uintptr_t)(obj + off + 8);
            if (b < 0x10000 || e <= b || e - b > 0x4000 || !readable(b, (size_t)(e - b))) continue;
            for (uint64_t p = b; p + 4 <= e; p += 4) {
                uint32_t w = *(uint32_t *)(uintptr_t)p; words++;
                if ((w & 0xfff) == 0x5a5) { marked++; if (shown++ < 10) fk += snprintf(first + fk, sizeof first - fk, " [+0x%x][%d]=%08x (%g)", off, (int)(p - b) / 4, w, *(float *)(uintptr_t)p); }
            }
            off += 16;
        }
        logf("[n4] parameter object of kind 0x%x: %d words in its vectors, %d carry the mark 5a5:%s", kind, words, marked, first);
    }
    o_fireball(c);
}
extern "C" __declspec(dllexport) void mod_init(const HookApi *a) {
    api = a;
    const char *e = getenv("N3_NEWKIND");
    char reglist[200] = "";
    g_reg = ssbu_registry_get();
    if (g_reg && g_reg->count > 0) {
        for (int k = 0; k < g_reg->count && k < MAXNEW; k++) {
            size_t n = strlen(reglist); snprintf(reglist + n, sizeof reglist - n, "%s%s", k ? "," : "", g_reg->fighters[k].name);
            snprintf(g_donor_name[k], 32, "%s", g_reg->fighters[k].donor);      // N6: the donor of THIS fighter
        }
        e = reglist;
        g_reg->start();
    } else g_reg = nullptr;
    if (!e || !*e) { api->log("[n4] kind mod: no fighter registry and N3_NEWKIND not set, nothing installed"); return; }
    InitializeCriticalSection(&g_lock);
    char list[200]; snprintf(list, sizeof list, "%s", e);
    for (char *p = strtok(list, ","); p && g_nnew < MAXNEW; p = strtok(nullptr, ",")) {
        char kn[80]; snprintf(kn, sizeof kn, "fighter_kind_%s", p);
        g_hash[g_nnew] = hash40(kn);
        snprintf(g_name[g_nnew], 32, "%s", p); snprintf(g_upper[g_nnew], 32, "%s", p); snprintf(g_sound[g_nnew], 32, "%s", p);
        for (char *q = g_upper[g_nnew]; *q; q++) if (*q >= 'a' && *q <= 'z') *q -= 32;
        if (g_sound[g_nnew][0] >= 'a' && g_sound[g_nnew][0] <= 'z') g_sound[g_nnew][0] -= 32;
        if (!g_donor_name[g_nnew][0]) { const char *d = getenv("N3_DONOR"); snprintf(g_donor_name[g_nnew], 32, "%s", d && *d ? d : "mario"); }
        g_nnew++;
    }
    resolve_donors();                                   // when the game's data is mapped already; else at the first hook
    g_a0_workaround = (e = getenv("N4_A0_WORKAROUND")) && atoi(e);
    g_ownname = (e = getenv("N4_OWNNAME")) ? atoi(e) : g_reg ? (g_reg->fighters[0].own_name ? 15 : 14) : 0;
    g_row = (e = getenv("N4_ROW")) ? atoi(e) : g_reg ? 1 : 0;
    if ((e = getenv("N4_ROW_FIND"))) g_row_find = (uint32_t)strtoul(e, nullptr, 16);
    if ((e = getenv("N4_ROW_SET"))) g_row_set = (uint32_t)strtoul(e, nullptr, 16);
    if ((e = getenv("N4_WEAPON_LOG"))) g_weapon_log = atoi(e);
    static const uint64_t disp[9] = { 0x710064bbd0ull, 0x710064c310ull, 0x710064c930ull, 0x710064cf50ull, 0x710064d570ull, 0x710064db90ull, 0x710064e2a0ull, 0x710064e8b0ull, 0x710064eec0ull };
    static const uint64_t wdisp[4] = { 0x71033abee0ull, 0x71033acde0ull, 0x71033add40ull, 0x71033aeca0ull };
    int ok = 0, all = 0;
    all++; ok += !!api->install(0x710066cd40ull, h_hash, nullptr, &o_hash);
    all++; ok += !!api->install(0x710064b730ull, h_record, nullptr, &o_record);
    all++; ok += !!api->install(0x710068d530ull, h_callbacks, nullptr, &o_callbacks);
    for (int i = 0; i < 9; i++) { all++; ok += !!api->install(disp[i], h_disp, (void *)(intptr_t)i, &o_disp[i]); }
    all++; ok += !!api->install(0x710070c580ull, h_build, (void *)0, &o_build[0]);
    all++; ok += !!api->install(0x7100721ca0ull, h_build, (void *)1, &o_build[1]);
    all++; ok += !!api->install(0x710033ba50ull, h_get, (void *)0, &o_get[0]);
    all++; ok += !!api->install(0x710033c510ull, h_get, (void *)1, &o_get[1]);
    all++; ok += !!api->install(0x7100709d60ull, h_loader, nullptr, &o_loader);
    all++; ok += !!api->install(0x71006867e0ull, h_init, nullptr, &o_init);
    all++; ok += !!api->install(0x710066ee40ull, h_setup, nullptr, &o_setup);
    all++; ok += !!api->install(0x71033b5640ull, h_winit, nullptr, &o_winit);
    for (int i = 0; i < 4; i++) { all++; ok += !!api->install(wdisp[i], h_wdisp, (void *)(intptr_t)i, &o_wdisp[i]); }
    all++; ok += !!api->install(0x7100cb9de0ull, h_fireball, nullptr, &o_fireball);
    all++; ok += !!api->install(0x71017e88d0ull, h_path, nullptr, &o_path);
    {
        e = getenv("N6_KINDFIELD");
        g_cbwrap = !(getenv("N7_CBWRAP") && getenv("N7_CBWRAP")[0] == '0');
        /* N7: no default any more (N6: 7100c280f0): the general wrap of the donor's callbacks covers it */
        char kl[300]; snprintf(kl, sizeof kl, "%s", e ? e : ""); int nk = 0;
        for (char *p = strtok(kl, ","); p && nk < 8; p = strtok(nullptr, ","), nk++) {
            g_kf_addr[nk] = strtoull(p, nullptr, 16);
            if (!g_kf_addr[nk]) continue;
            all++; ok += !!api->install(g_kf_addr[nk], h_kindfield, (void *)(intptr_t)nk, &o_kf[nk]);
        }
    }
    if ((e = getenv("N6_TRACE_MAX"))) g_trace_max = atol(e);
    if ((e = getenv("N6_TRACE")) && *e) {
        char tl[300]; snprintf(tl, sizeof tl, "%s", e); int nt = 0;
        for (char *p = strtok(tl, ","); p && nt < 8; p = strtok(nullptr, ","), nt++) {
            g_trace_addr[nt] = strtoull(p, nullptr, 16);
            if (!api->install(g_trace_addr[nt], h_trace, (void *)(intptr_t)nt, &o_trace[nt])) logf("[n6trace] hook on %llx failed", (unsigned long long)g_trace_addr[nt]);
        }
    }
    if (!((e = getenv("N6_SETUP2")) && e[0] == '0')) { all++; ok += !!api->install(0x71006cdd20ull, h_setup2, nullptr, &o_setup2); }
    static const uint64_t ai[8] = { 0x71002c5cf0ull, 0x71002c9900ull, 0x710034b310ull, 0x7100351630ull, 0x710035fc50ull, 0x7100362df0ull, 0x710036c1c0ull, 0x71003719c0ull };
    g_kirby = !((e = getenv("N5_KIRBY")) && e[0] == '0');
    if (g_kirby) { all++; ok += !!api->install(0x71017f0bd0ull, h_kirby, nullptr, &o_kirby); }
    g_ai = !((e = getenv("N5_AI")) && e[0] == '0');
    if (g_ai) for (int i = 0; i < 8; i++) { all++; ok += !!api->install(ai[i], h_ai, (void *)(intptr_t)i, &o_ai[i]); }
    char donors[200]; int dn = 0; donors[0] = 0;
    for (int k = 0; k < g_nnew; k++) dn += snprintf(donors + dn, sizeof donors - dn, "%s%s<-%s", k ? ", " : "", g_name[k], g_donor_name[k]);
    logf("[n4] kind mod loaded (n7_kind: donor per kind, donor callbacks wrapped): %d new kind(s) from 0x%x (first: %s, hash %llx), donors: %s; weapons: %s; own names %d; %d of %d hooks",
         g_nnew, FIRST, g_name[0], (unsigned long long)g_hash[0], donors, g_a0_workaround ? "N3 workaround (A[0])" : "live owner", g_ownname, ok, all);
}
