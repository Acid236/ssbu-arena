// n3_kind.cpp - TEST MOD for plan\phases\N3_new_kind.md, experiment (ii). NOT part of the port.
// A NEW FIGHTER KIND NUMBER (0x5E) whose everything is Mario's. Needs the game DLL built with patches\kinds.txt
// (the parameter singleton with 0x72 kinds: ssbu_game_n3.dll, exe ssbu_n3k.exe); on the unpatched game the first
// bound check `kind < 0x5e` aborts.
//   N3_NEWKIND=<name>      switches the mod on; the kind's hash is hash40("fighter_kind_<name>") (n3_roster.cpp gives
//                          the roster row ui_chara_n3t0 that hash). Unset: the mod installs nothing.
// Build:  python fighter_sdk\tools\build_mod.py mods_n3_src\n3_kind.cpp mods_n3        Run: SSBU_MODS=mods_n3
//
// What it does (addresses of 13.0.4, from N2 section 1.3):
//   data rows 0x5E of the three name tables (0x7104f80e20, 0x7104f811d0, 0x7104f80a70) = Mario's pointers, and of
//       the kind-hash table 0x710453b1c0 = Mario's hash (data files keyed by that hash then answer as for Mario);
//   hash -> kind            0x710066cd40            the new hash -> 0x5E
//   description record      0x710064b730            0x5E -> Mario's record
//   callbacks object        0x710068d530            0x5E -> Mario's object
//   script agent dispatchers 0x710064bbd0 .. 0x710064eec0 (nine)   0x5E -> Mario's case
//   parameter objects       0x710070c580, 0x7100721ca0   0x5E -> Mario's case run on row 0x5E of array A
//   per-kind getters        0x710033ba50, 0x710033c510   0x5E -> Mario's case
//   parameter loader        0x7100709d60            afterwards row 0x5E of array B (now at +0x19a8) = Mario's row indexes
//   fighter init            0x71006867e0            log line only
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <windows.h>
#include "hook.h"

static const HookApi *api;
static const uint64_t MASK40 = 0xffffffffffull;
static const int NEW = 0x5E, DONOR = 0;
static const uint64_t NEW_B = 0x19a8;              // array B of the patched singleton (patches\kinds.txt)
static uint64_t g_hash;
static volatile LONG g_data_done;

static void logf(const char *fmt, ...) {
    char line[400]; va_list ap; va_start(ap, fmt); vsnprintf(line, sizeof line, fmt, ap); va_end(ap);
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
static void copy_row(uint64_t table, const char *what) {       // table[NEW] = table[DONOR], 8-byte rows
    uint64_t *t = (uint64_t *)(uintptr_t)table; DWORD old;
    if (!readable(table, 8 * (NEW + 1))) { logf("[n3] kind: table %s %llx not readable", what, (unsigned long long)table); return; }
    uint64_t was = t[NEW];
    VirtualProtect(&t[NEW], 8, PAGE_READWRITE, &old);
    t[NEW] = t[DONOR];
    logf("[n3] kind: table %s %llx row 0x%x: %llx -> %llx", what, (unsigned long long)table, NEW, (unsigned long long)was, (unsigned long long)t[NEW]);
}
static void ensure_data(void) {
    if (InterlockedCompareExchange(&g_data_done, 1, 0)) return;
    copy_row(0x7104f80e20ull, "names");
    copy_row(0x7104f811d0ull, "sound names");
    copy_row(0x7104f80a70ull, "upper-case names");
    copy_row(0x710453b1c0ull, "kind hashes");
}

static HookOrig o_hash, o_record, o_callbacks, o_disp[9], o_build[2], o_get[2], o_loader, o_init;
static long g_n_hash, g_n_record, g_n_callbacks, g_n_disp[9], g_n_build[2], g_n_get[2], g_n_init;

static void h_hash(Ctx *c, void *) {               // hash40 -> kind
    ensure_data();
    if ((c->x[0] & MASK40) == g_hash) { if (!g_n_hash++) logf("[n3] kind: hash -> kind: the new hash -> 0x%x", NEW); c->x[0] = NEW; return; }
    o_hash(c);
}
static void h_w0(Ctx *c, HookOrig o, long *n, const char *what) {      // functions taking the kind in w0
    if ((uint32_t)c->x[0] == (uint32_t)NEW) { if (!(*n)++) logf("[n3] kind: %s asked for kind 0x%x -> Mario's", what, NEW); c->x[0] = DONOR; }
    o(c);
}
static void h_record(Ctx *c, void *) { h_w0(c, o_record, &g_n_record, "description record"); }
static void h_callbacks(Ctx *c, void *) { h_w0(c, o_callbacks, &g_n_callbacks, "callbacks object"); }
static void h_get(Ctx *c, void *u) { int i = (int)(intptr_t)u; h_w0(c, o_get[i], &g_n_get[i], i ? "getter 0x710033c510" : "getter 0x710033ba50"); }
static void h_disp(Ctx *c, void *u) {              // dispatchers 0..4: kind at [x0 + 0xc]; 5..8: kind in w0
    int i = (int)(intptr_t)u;
    if (i >= 5) { h_w0(c, o_disp[i], &g_n_disp[i], "script dispatcher (share)"); return; }
    uint32_t *k = (uint32_t *)(uintptr_t)(c->x[0] + 0xc);
    if (*k == (uint32_t)NEW) {
        if (!g_n_disp[i]++) logf("[n3] kind: script dispatcher %d asked for kind 0x%x -> Mario's agent", i, NEW);
        *k = DONOR; o_disp[i](c); *k = NEW; return;
    }
    o_disp[i](c);
}
static void h_build(Ctx *c, void *u) {             // (this, kind, x2): the case builds the kind's parameter object and stores it in A[kind]
    int i = (int)(intptr_t)u;
    if ((uint32_t)c->x[1] != (uint32_t)NEW) { o_build[i](c); return; }
    uint8_t *P = (uint8_t *)(uintptr_t)c->x[0], *a0 = P + 0x60 + 0x38 * DONOR, *an = P + 0x60 + 0x38 * NEW, keep[0x38];
    // Run ii2/ii3: the WEAPON init 0x71033b5640 takes the parameter object of the weapon's owner kind from a static
    // table weapon kind -> fighter kind (it reads A[owner] + 0x70 unchecked), so Mario's weapons need A[0] although no
    // fighter of kind 0 is in the match: build the donor's own objects too when they are missing.
    uint64_t arg[8]; memcpy(arg, c->x, sizeof arg);
    if (*(uint64_t *)(a0 + (i ? 0x30 : 0x18)) == 0) {
        c->x[1] = DONOR; o_build[i](c);
        logf("[n3] kind: parameter object builder %d: built the donor's objects as well (A[0] was empty; its weapons look there)", i);
        memcpy(c->x, arg, sizeof arg);
    }
    memcpy(keep, a0, 0x38); memcpy(a0, an, 0x38);          // Mario's case works on row 0: lend it row 0x5E for the call
    c->x[1] = DONOR; o_build[i](c);
    memcpy(an, a0, 0x38); memcpy(a0, keep, 0x38);
    if (!g_n_build[i]++) logf("[n3] kind: parameter object builder %d ran Mario's case for kind 0x%x: A[0x%x] = %llx %llx | %llx %llx", i, NEW, NEW,
                              *(unsigned long long *)(an + 0x10), *(unsigned long long *)(an + 0x18), *(unsigned long long *)(an + 0x28), *(unsigned long long *)(an + 0x30));
}
static void h_loader(Ctx *c, void *) {             // loads fighter_param: writes B[0..0x5D]; the row of the new kind is ours
    uint8_t *P = (uint8_t *)(uintptr_t)c->x[0];
    ensure_data();
    o_loader(c);
    int32_t *b = (int32_t *)(P + NEW_B);
    memcpy(b + 3 * NEW, b + 3 * DONOR, 12);
    logf("[n3] kind: parameter loader done: B[0x%x] = B[0] = %d %d %d (B[1] = %d %d %d)", NEW, b[0], b[1], b[2], b[3], b[4], b[5]);
}
// 0x710066ee40 creates the parameter singleton and, among others, the SECOND per-kind container *(0x71052bb3a8):
// list heads {prev, next, count} of 0x18 bytes per kind. Its constructor is unrolled for 0x5E rows; the patched game
// allocates 0x72 rows (zero-filled). Rows 0x5E.. become empty lists here (a head points at itself).
static HookOrig o_setup;
static void h_setup(Ctx *c, void *) {
    o_setup(c);
    uint64_t *p = *(uint64_t **)(uintptr_t)0x71052bb3a8ull;
    if (!p) return;
    int done = 0;
    for (int k = 0x5e; k < 0x72; k++) {
        uint64_t *row = p + 3 * k;
        if (row[0] == 0 && row[1] == 0) { row[0] = row[1] = (uint64_t)(uintptr_t)row; row[2] = 0; done++; }
    }
    if (done) logf("[n3] kind: second per-kind container %p: %d rows from 0x5e made empty lists (lock byte at +0xab0 = %d)", (void *)p, done, *((uint8_t *)p + 0xab0));
}
static void h_init(Ctx *c, void *) {               // fighter init: x1 = init description, kind at +0x9c
    uint64_t d = c->x[1];
    int kind = readable(d + 0x9c, 4) ? *(int32_t *)(uintptr_t)(d + 0x9c) : -99;
    if (g_n_init++ < 16) logf("[n3] kind: fighter init 0x71006867e0: kind 0x%x (%d), slot %d", kind, kind, readable(d + 0xa8, 4) ? *(int32_t *)(uintptr_t)(d + 0xa8) : -1);
    o_init(c);
    if (kind == NEW) logf("[n3] kind: fighter init for kind 0x%x returned", NEW);
}
extern "C" __declspec(dllexport) void mod_init(const HookApi *a) {
    api = a;
    const char *e = getenv("N3_NEWKIND");
    if (!e || !*e) { api->log("[n3] kind mod: N3_NEWKIND not set, nothing installed"); return; }
    char kn[80]; snprintf(kn, sizeof kn, "fighter_kind_%s", e); g_hash = hash40(kn);
    static const uint64_t disp[9] = { 0x710064bbd0ull, 0x710064c310ull, 0x710064c930ull, 0x710064cf50ull, 0x710064d570ull, 0x710064db90ull, 0x710064e2a0ull, 0x710064e8b0ull, 0x710064eec0ull };
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
    logf("[n3] kind mod loaded: kind 0x%x = %s (hash %llx), a copy of Mario; %d of %d hooks", NEW, kn, (unsigned long long)g_hash, ok, all);
}
