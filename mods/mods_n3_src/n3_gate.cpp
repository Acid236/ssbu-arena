// n3_gate.cpp - TEST MOD for plan\phases\N3_new_kind.md: the gate of the parameter-singleton patch. NOT part of the port.
// At the first two fighter initialisations of a match it prints the content of the parameter singleton for the 94
// original kinds: array B (three row indexes per kind) and which rows of array A hold parameter objects. The lines
// must be IDENTICAL between the unpatched game (N3_GATE_B=0x14f0) and the patched one (N3_GATE_B=0x19a8).
// Build:  python fighter_sdk\tools\build_mod.py mods_n3_src\n3_gate.cpp mods_n3gate      Run: SSBU_MODS=mods_n3gate
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include "hook.h"

static const HookApi *api;
static HookOrig o_init;
static uint64_t g_b = 0x14f0;
static int g_n;

static void h_init(Ctx *c, void *) {
    uint64_t d = c->x[1];
    int kind = *(int32_t *)(uintptr_t)(d + 0x9c);
    o_init(c);
    if (g_n++ >= 2) return;
    uint8_t *P = *(uint8_t **)(uintptr_t)0x71052bb3b0ull;
    char line[1200]; int n;
    uint32_t sum = 0;
    for (int k = 0; k < 0x5e; k += 16) {
        n = snprintf(line, sizeof line, "[n3gate] init %d (kind %d) B[0x%02x..]:", g_n, kind, k);
        for (int j = k; j < k + 16 && j < 0x5e; j++) {
            int32_t *b = (int32_t *)(P + g_b + 12 * j);
            sum = sum * 31 + (uint32_t)b[0]; sum = sum * 31 + (uint32_t)b[1]; sum = sum * 31 + (uint32_t)b[2];
            n += snprintf(line + n, sizeof line - n, " %d/%d/%d", b[0], b[1], b[2]);
        }
        api->log(line);
    }
    n = snprintf(line, sizeof line, "[n3gate] init %d (kind %d) B checksum %08x; kinds with parameter objects in A:", g_n, kind, sum);
    for (int j = 0; j < 0x5e; j++) {
        uint64_t *a = (uint64_t *)(P + 0x60 + 0x38 * j);
        if (a[2] || a[5]) n += snprintf(line + n, sizeof line - n, " %d(%d%d)", j, a[2] != 0, a[5] != 0);
    }
    api->log(line);
    uint64_t *m = (uint64_t *)(P + 0x1958);
    snprintf(line, sizeof line, "[n3gate] init %d members behind: +0x1958 %s +0x1960 %s +0x1968 %x +0x1970 %s +0x1978 %s +0x1980 %x", g_n, m[0] ? "set" : "0", m[1] ? "set" : "0",
             *(uint32_t *)(P + 0x1968), m[3] ? "set" : "0", m[4] ? "set" : "0", *(uint32_t *)(P + 0x1980));
    api->log(line);
}
extern "C" __declspec(dllexport) void mod_init(const HookApi *a) {
    api = a;
    const char *e = getenv("N3_GATE_B");
    if (e) g_b = strtoull(e, nullptr, 0);
    api->install(0x71006867e0ull, h_init, nullptr, &o_init);
    char line[100]; snprintf(line, sizeof line, "[n3gate] loaded: array B read at +0x%llx", (unsigned long long)g_b);
    api->log(line);
}
