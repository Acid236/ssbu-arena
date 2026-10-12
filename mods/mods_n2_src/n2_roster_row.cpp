// n2_roster_row.cpp - TEST MOD for plan\phases\N2_real_slots.md, experiment (i). NOT part of the port.
// Adds ONE row to the game's character database (ui_chara_db) in memory: a copy of Mario's row with a new
// ui_chara_id ("ui_chara_n2test") and disp_order 87, and logs what the roster builder and the select-screen grid do.
// Nothing on disk is changed. Build:  python fighter_sdk\tools\build_mod.py mods_n2_src\n2_roster_row.cpp mods_n2
// Run:    SSBU_MODS=mods_n2   (expected log lines: "[n2] ..." ; see the plan file)
//
// What it relies on (all read in the 13.0.4 binary, see N2 section 3 and 5):
//   database object  D = *(*(*(0x710532e730) + 8) + 0x168);  inner = *(D + 8)
//   inner + 0x18 -> parsed file: +0x20 = hash table (u64[]), +0x28 = reference table ({u32 hash index, i32 offset}[])
//   inner + 0x20 -> root param (type byte 0x0c struct: u32 field count, i32 offset of its entries in the reference table)
//   inner + 0x48 =  hash40 of the root list ("db_root"); list = type 0x0b, u32 count, i32 offsets[count] from the list start
//   every accessor walks these three pointers again on each call (0x7103269e30, 0x7103262130): no cached row pointers.
#include <stdio.h>
#include <string.h>
#include <windows.h>
#include "hook.h"

static const HookApi *api;
static HookOrig orig_roster, orig_grid;
static int patched;                 // 0 not yet, 1 done, -1 gave up
static const uint64_t MASK40 = 0xffffffffffull;

static void logf(const char *fmt, ...) {
    char line[400]; va_list ap; va_start(ap, fmt); vsnprintf(line, sizeof line, fmt, ap); va_end(ap);
    api->log(line);
}
static int readable(uint64_t a, size_t n) {
    MEMORY_BASIC_INFORMATION mi;
    if (a < 0x10000 || !VirtualQuery((void *)(uintptr_t)a, &mi, sizeof mi)) return 0;
    if (mi.State != MEM_COMMIT || (mi.Protect & (PAGE_NOACCESS | PAGE_GUARD))) return 0;
    return a + n <= (uint64_t)(uintptr_t)mi.BaseAddress + mi.RegionSize;
}
static uint64_t r64(uint64_t a) { uint64_t v; memcpy(&v, (void *)(uintptr_t)a, 8); return v; }
static uint32_t r32(uint64_t a) { uint32_t v; memcpy(&v, (void *)(uintptr_t)a, 4); return v; }
static int32_t ri32(uint64_t a) { int32_t v; memcpy(&v, (void *)(uintptr_t)a, 4); return v; }
static uint8_t r8(uint64_t a) { return *(uint8_t *)(uintptr_t)a; }
static uint32_t crc32(const char *s) {
    uint32_t c = 0xffffffffu;
    for (; *s; s++) { c ^= (uint8_t)*s; for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xedb88320u & (0u - (c & 1))); }
    return ~c;
}
static uint64_t hash40(const char *s) { return ((uint64_t)strlen(s) << 32) | crc32(s); }

// field of a struct param by hash: address of the value (its type byte), 0 if absent
static uint64_t field(uint64_t st, uint64_t hashes, uint64_t refs, uint64_t h) {
    if (r8(st) != 0x0c) return 0;
    uint32_t n = r32(st + 1); uint64_t e = refs + (int64_t)ri32(st + 5);
    for (uint32_t i = 0; i < n; i++)
        if (((r64(hashes + 8ull * r32(e + 8ull * i)) ^ h) & MASK40) == 0) { int32_t o = ri32(e + 8ull * i + 4); return o < 0 ? 0 : st + o; }
    return 0;
}
static uint64_t field_entry(uint64_t st, uint64_t hashes, uint64_t refs, uint64_t h) {      // address of the reference entry
    uint32_t n = r32(st + 1); uint64_t e = refs + (int64_t)ri32(st + 5);
    for (uint32_t i = 0; i < n; i++)
        if (((r64(hashes + 8ull * r32(e + 8ull * i)) ^ h) & MASK40) == 0) return e + 8ull * i;
    return 0;
}
static void *alloc_below(uint64_t top, size_t size) {       // memory below `top`, less than 1 GB away: offsets stay positive 31-bit
    for (uint64_t a = (top & ~0xffffull) - 0x100000; a > 0x10000 && top - a < 0x40000000ull; a -= 0x100000) {
        void *p = VirtualAlloc((void *)(uintptr_t)a, size, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
        if (p) return p;
    }
    return nullptr;
}

static void try_patch(void) {
    if (patched) return;
    uint64_t g = r64(0x710532e730ull);
    if (!readable(g, 16)) return;
    uint64_t mgr = r64(g + 8);
    if (!readable(mgr + 0x168, 8)) return;
    uint64_t D = r64(mgr + 0x168);
    if (!readable(D, 16)) return;
    uint64_t inner = r64(D + 8);
    if (!readable(inner, 0x50)) return;
    uint64_t prc = r64(inner + 0x18), root = r64(inner + 0x20), root_hash = r64(inner + 0x48) & MASK40;
    if (!readable(prc, 0x30) || !readable(root, 9) || r8(root) != 0x0c) return;          // not loaded yet: try again at the next call
    uint64_t hashes = r64(prc + 0x20), refs = r64(prc + 0x28);
    if (!readable(hashes - 0x10, 0x18) || !readable(refs, 8)) return;
    patched = -1;
    if (memcmp((void *)(uintptr_t)(hashes - 0x10), "paracobn", 8) != 0) { logf("[n2] GIVE UP: no file header in front of the hash table (%llx)", (unsigned long long)hashes); return; }
    uint32_t nh = r32(hashes - 8) / 8;
    uint64_t list = field(root, hashes, refs, root_hash);
    if (!list || r8(list) != 0x0b) { logf("[n2] GIVE UP: root list not found"); return; }
    uint32_t n = r32(list + 1);
    const uint64_t H_ID = hash40("ui_chara_id"), H_ORDER = hash40("disp_order"), H_MARIO = hash40("ui_chara_mario"), H_NEW = hash40("ui_chara_n2test");
    uint64_t mario = 0, next = ~0ull; int max_order = -1;
    for (uint32_t i = 0; i < n; i++) {
        uint64_t row = list + (int64_t)ri32(list + 5 + 4ull * i);
        uint64_t id = field(row, hashes, refs, H_ID);
        if (id && r8(id) == 9 && ((r64(hashes + 8ull * r32(id + 1)) ^ H_MARIO) & MASK40) == 0) mario = row;
        uint64_t od = field(row, hashes, refs, H_ORDER);
        if (od && r8(od) == 2) { int v = (int8_t)r8(od + 1); if (v > max_order && v < 99) max_order = v; }
    }
    if (!mario) { logf("[n2] GIVE UP: Mario's row not found among %u rows", n); return; }
    for (uint32_t i = 0; i < n; i++) { uint64_t row = list + (int64_t)ri32(list + 5 + 4ull * i); if (row > mario && row < next) next = row; }
    if (next == ~0ull || next - mario > 0x4000) { logf("[n2] GIVE UP: extent of Mario's row unknown"); return; }
    size_t row_size = (size_t)(next - mario);
    size_t need = 0x10 + 5 + 4ull * (n + 1) + 16 + row_size + 16 + 8ull * (nh + 1);
    uint8_t *mem = (uint8_t *)alloc_below(root < list ? root : list, need + 0x1000);
    if (!mem) { logf("[n2] GIVE UP: no memory below the database"); return; }
    uint8_t *root2 = mem, *list2 = mem + 0x10, *row2 = list2 + ((5 + 4ull * (n + 1) + 15) & ~15ull), *hash2 = row2 + ((row_size + 15) & ~15ull);
    memcpy(root2, (void *)(uintptr_t)root, 9);
    list2[0] = 0x0b; uint32_t n1 = n + 1; memcpy(list2 + 1, &n1, 4);
    for (uint32_t i = 0; i < n; i++) {
        int64_t o = (int64_t)(list + (int64_t)ri32(list + 5 + 4ull * i)) - (int64_t)(uintptr_t)list2;
        if (o <= 0 || o > 0x7fffffff) { logf("[n2] GIVE UP: row %u is out of reach (%lld)", i, (long long)o); return; }
        int32_t o32 = (int32_t)o; memcpy(list2 + 5 + 4ull * i, &o32, 4);
    }
    int32_t onew = (int32_t)(row2 - list2); memcpy(list2 + 5 + 4ull * n, &onew, 4);
    memcpy(row2, (void *)(uintptr_t)mario, row_size);
    memcpy(hash2, (void *)(uintptr_t)hashes, 8ull * nh); memcpy(hash2 + 8ull * nh, &H_NEW, 8);
    uint64_t id2 = field((uint64_t)(uintptr_t)row2, hashes, refs, H_ID), od2 = field((uint64_t)(uintptr_t)row2, hashes, refs, H_ORDER);
    uint64_t entry = field_entry(root, hashes, refs, root_hash);
    if (!id2 || !od2 || r8(od2) != 2 || !entry) { logf("[n2] GIVE UP: fields of the copied row not found (disp_order type %d)", od2 ? r8(od2) : -1); return; }
    memcpy((void *)(uintptr_t)(id2 + 1), &nh, 4);                               // ui_chara_id -> the new hash (index nh of the new hash table)
    *(int8_t *)(uintptr_t)(od2 + 1) = (int8_t)(max_order + 1);                  // last in the order
    int32_t olist = (int32_t)(list2 - root2);
    // switch over: hash table, then the root list entry, then the root
    *(uint64_t *)(uintptr_t)(prc + 0x20) = (uint64_t)(uintptr_t)hash2;
    memcpy((void *)(uintptr_t)(entry + 4), &olist, 4);
    *(uint64_t *)(uintptr_t)(inner + 0x20) = (uint64_t)(uintptr_t)root2;
    patched = 1;
    logf("[n2] ui_chara_db patched: rows %u -> %u, new row = copy of Mario's (%u bytes), ui_chara_id ui_chara_n2test (hash index %u), disp_order %d", n, n1, (unsigned)row_size, nh, max_order + 1);
}

static void my_roster(Ctx *c, void *) {            // 0x710326f0f0(out vector, w1..w6 options)
    uint64_t out = c->x[0]; unsigned mode = (unsigned)c->x[1];
    try_patch();
    orig_roster(c);
    static int shown;
    if (shown < 40 && readable(out, 16)) { shown++; logf("[n2] roster builder: %lld entries (w1=%u, patched=%d)", (long long)((r64(out + 8) - r64(out)) / 8), mode, patched); }
}
static void my_grid(Ctx *c, void *) {              // 0x71019eb840(this, x1, x2, flags, vector of roster ids)
    uint64_t self = c->x[0], vec = c->x[4]; long long in = readable(vec, 16) ? (long long)((r64(vec + 8) - r64(vec)) / 8) : -1;
    orig_grid(c);
    if (!readable(self + 0x1d0, 0x48)) return;
    int rows[13], sum = 0; char txt[120]; int k = 0;
    for (int i = 0; i < 13; i++) { rows[i] = (int)r32(self + 0x1d4 + 4 * i); sum += rows[i]; k += snprintf(txt + k, sizeof txt - k, "%d,", rows[i]); }
    logf("[n2] grid: %lld roster entries in; rows %s sum %d; rows used %d", in, txt, sum, (int)r32(self + 0x208));
}
extern "C" __declspec(dllexport) void mod_init(const HookApi *a) {
    api = a;
    if (!api->install(0x710326f0f0ull, my_roster, nullptr, &orig_roster)) logf("[n2] roster hook failed: %s", api->error());
    if (!api->install(0x71019eb840ull, my_grid, nullptr, &orig_grid)) logf("[n2] grid hook failed: %s", api->error());
    api->log("[n2] test mod loaded: one extra ui_chara_db row (copy of Mario's)");
}
