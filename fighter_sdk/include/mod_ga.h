// mod_ga.h: GA() for mods. A mod names game addresses by their 13.0.4 value; MOD_GA(a) gives the address of the same
// thing in the build that runs (identity on 13.0.4), like the runtime's GA() (runtime/hostrt.c).
//
// Which build runs: main's MOD0 header (its offset is the word at main + 4) gives the start of bss, which is one page
// later in 13.0.5. On 13.0.5 a code address goes through the function map <mod folder>\ga_13_0_5.txt, lines
//     F <13.0.4 offset> <13.0.5 offset> <size>     one function (offsets from main's base, hex)
//     S <13.0.4 start> <13.0.4 end> <delta>        a whole segment moved by delta (read-only data, data, bss)
// (made on the user's PC from the two main.elf files; it holds offsets only, no code or data of the game).
// A code address outside every mapped function stops nothing: it is kept and named once in the log.
// Works from static initialisers too: mods are loaded after main is in memory (hook_host.c hook_start).
#pragma once
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

namespace mod_ga_detail {
static const uint64_t BASE = 0x7100000000ull;
struct Fn { uint32_t old_, new_, size; };
static Fn *g_fn;
static int g_nfn, g_state;                  // g_state: 0 not looked, 1 = 13.0.4 (identity), 2 = 13.0.5 with a map, 3 = unknown / no map
static struct { uint32_t lo, hi; int32_t d; } g_seg[8];
static int g_nseg;

static int cmp_fn(const void *a, const void *b) { uint32_t x = ((const Fn *)a)->old_, y = ((const Fn *)b)->old_; return x < y ? -1 : x > y; }

static void say(const char *t) { printf("mod_ga: %s\n", t); fflush(stdout); }

static void load_map(void) {
    char path[MAX_PATH * 2];
    HMODULE self = NULL;
    GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCSTR)(void *)&load_map, &self);
    GetModuleFileNameA(self, path, MAX_PATH);
    char *s = strrchr(path, '\\');
    strcpy(s ? s + 1 : path, "ga_13_0_5.txt");
    FILE *f = fopen(path, "r");
    if (!f) { char m[MAX_PATH * 2 + 80]; snprintf(m, sizeof m, "13.0.5 runs but %s is missing: game addresses of this mod stay 13.0.4's", path); say(m); g_state = 3; return; }
    int cap = 131072;
    g_fn = (Fn *)malloc(sizeof(Fn) * cap);
    char line[256];
    while (fgets(line, sizeof line, f)) {
        unsigned a, b, c;
        if (line[0] == 'F' && sscanf(line + 1, "%x %x %x", &a, &b, &c) == 3 && g_nfn < cap) { g_fn[g_nfn].old_ = a; g_fn[g_nfn].new_ = b; g_fn[g_nfn].size = c; g_nfn++; }
        else if (line[0] == 'S' && sscanf(line + 1, "%x %x %x", &a, &b, &c) == 3 && g_nseg < 8) { g_seg[g_nseg].lo = a; g_seg[g_nseg].hi = b; g_seg[g_nseg].d = (int32_t)c; g_nseg++; }
    }
    fclose(f);
    qsort(g_fn, g_nfn, sizeof(Fn), cmp_fn);
    char m[160]; snprintf(m, sizeof m, "13.0.5: %d functions, %d segments from ga_13_0_5.txt", g_nfn, g_nseg); say(m);
    g_state = 2;
}

static void look(void) {
    uint32_t m = *(volatile uint32_t *)(uintptr_t)(BASE + 4);
    uint32_t off = m + (uint32_t)*(volatile int32_t *)(uintptr_t)(BASE + m + 8);       // MOD0: magic, dynamic, bss start, ...
    if (*(volatile uint32_t *)(uintptr_t)(BASE + m) != 0x30444f4du) { say("no MOD0 at main's start: game addresses stay 13.0.4's"); g_state = 3; }
    else if (off == 0x52a9000u) g_state = 1;
    else if (off == 0x52aa000u) load_map();
    else { char t[120]; snprintf(t, sizeof t, "unknown build (bss at main + %x): game addresses stay 13.0.4's", off); say(t); g_state = 3; }
}
}  // namespace mod_ga_detail

static inline uint64_t mod_ga(uint64_t a) {
    using namespace mod_ga_detail;
    if (!g_state) look();
    if (g_state != 2 || a < BASE || a >= BASE + 0x8000000ull) return a;
    uint32_t o = (uint32_t)(a - BASE);
    for (int i = 0; i < g_nseg; i++) if (o >= g_seg[i].lo && o < g_seg[i].hi) return a + g_seg[i].d;
    int lo = 0, hi = g_nfn - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        if (o < g_fn[mid].old_) hi = mid - 1;
        else if (o >= g_fn[mid].old_ + g_fn[mid].size) lo = mid + 1;
        else return BASE + g_fn[mid].new_ + (o - g_fn[mid].old_);
    }
    char t[120]; snprintf(t, sizeof t, "13.0.4 code address %llx is in no mapped function: kept as it is", (unsigned long long)a); say(t);
    return a;
}
#define MOD_GA(a) mod_ga(a)
