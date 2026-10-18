/* competitive.c - the competitive 1v1 mode, code side (SSBU_COMPETITIVE=1; the launcher sets it with "Modalita'
 * competitiva"). The data side (6 stages, no item in the item switch, preset rules) is tools/competitive/make_competitive.py
 * through the loose-file layer. Contains nothing of the game.
 *
 * The Final Smash meter is a rule (ui_rule_db "charge", rule struct + 0x5f; read off the rule loader 0x7103297784).
 * A battle is built by guest 0x71014e58f0 from the current rule, which lives in three globals of 13.0.4
 * (0x710530454c, 0x7105309924, 0x710530f49c: found by the rule struct's shape; writing charge = 1 into them before a
 * battle made the meter appear). The battle takes its copy before 0x71014e58f0 runs (clearing them there was too late),
 * so a thread clears charge and item_switch (+ 0x68) in all three every 2 ms from the start (the rule editor then shows
 * the meter off too), and once more when a battle is built: no FS meter and no random items, whatever ruleset the
 * player picked or the room host sent. Every player of a local-wireless room must use the mode (same rules). */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <windows.h>
#include "runtime.h"
#include "hostrt.h"

typedef void (*HookFn)(Ctx *c, void *user);
int hook_install(uint64_t addr, HookFn repl, void *user, ImportFn *orig);      /* fighter_sdk\hook_host.c */

static const uint64_t k_rules[] = {0x710530454cull, 0x7105309924ull, 0x710530f49cull};
#define MATCH_ITEM_APPEAR 0x71052c4204ull     /* the global match block 0x71052c41b0 + 0x54: item frequency (0 none; tests/DEBUG_MODE.md).
                                                 A saved ruleset keeps its own frequency and item list: a Poke Ball still came out
                                                 with item_switch 0 and the item switch list empty. */
static ImportFn g_battle_orig;
static long g_battles;

/* The stage choice: three entries of 0x20 bytes at 0x71053097c0, the current one's index at 0x7105309968; +0 the ui_stage
 * id (0x69 << 56 | hash40("ui_stage_<name>")) (runtime/debug_mode.c). "Random" (ui_stage_random...) is resolved by the game
 * from ALL its stages, not from the list ui_stage_db shows, and the light archive has only the 6: a choice that is not one
 * of them becomes one of them. The pick depends only on the choice entry itself (both games of a local-wireless room
 * hold the same one), so both sides get the same stage. */
static const char *const k_stages[6] = {"battle_field", "battle_field_s", "end", "poke_stadium2", "animal_village", "animal_city"};
static uint64_t comp_h40(const char *s) {
    uint32_t crc = 0xffffffffu; size_t n = strlen(s);
    for (size_t i = 0; i < n; i++) { crc ^= (uint8_t)s[i]; for (int k = 0; k < 8; k++) crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1))); }
    return ((uint64_t)n << 32) | (uint32_t)~crc;
}
static void comp_stage(void) {
    uint32_t cur = *(volatile uint32_t *)(uintptr_t)0x7105309968ull;
    for (uint32_t e = 0; e < 3; e++) {
        volatile uint64_t *id = (volatile uint64_t *)(uintptr_t)(0x71053097c0ull + 0x20ull * e);
        uint64_t h = *id & 0xffffffffffull;
        if (!h) continue;
        int ok = 0; char nm[48];
        for (int k = 0; k < 6; k++) { snprintf(nm, sizeof nm, "ui_stage_%s", k_stages[k]); if (h == comp_h40(nm)) ok = 1; }
        if (ok) continue;
        uint64_t mix = *id ^ (uint64_t)e * 0x9e3779b97f4a7c15ull ^ *(volatile uint64_t *)(uintptr_t)(0x71053097c0ull + 0x20ull * e + 0x10);
        mix ^= mix >> 29; mix *= 0xbf58476d1ce4e5b9ull; mix ^= mix >> 32;
        int k = (int)(mix % 6);
        snprintf(nm, sizeof nm, "ui_stage_%s", k_stages[k]);
        *id = 0x6900000000000000ull | comp_h40(nm);
        *(volatile uint32_t *)(uintptr_t)(0x71053097c0ull + 0x20ull * e + 8) = 0;      /* normal form */
        if (e == cur || cur >= 3) printf("competitive: stage choice %llx is not one of the 6 (random?): %s instead\n", (unsigned long long)h, k_stages[k]);
    }
}

static void comp_battle(Ctx *c, void *user) {
    (void)user;
    int changed = 0;
    comp_stage();
    for (int i = 0; i < 3; i++) {
        volatile uint8_t *r = (volatile uint8_t *)(uintptr_t)k_rules[i];
        if (r[0x5f] || r[0x68]) changed++;
        r[0x5f] = 0;            /* charge: Final Smash meter */
        r[0x68] = 0;            /* item_switch */
    }
    int items_were_on = *(volatile uint32_t *)(uintptr_t)MATCH_ITEM_APPEAR != 0;
    *(volatile uint32_t *)(uintptr_t)MATCH_ITEM_APPEAR = 0;
    if (++g_battles <= 20) printf("competitive: battle %ld: FS meter and items off (%d of 3 rule copies had one on%s)\n", g_battles, changed, items_were_on ? ", item frequency was on" : "");
    g_battle_orig(c);
}

static void comp_clear(void) {
    for (int i = 0; i < 3; i++) {
        volatile uint8_t *r = (volatile uint8_t *)(uintptr_t)k_rules[i];
        if (r[0x5f]) r[0x5f] = 0;
        if (r[0x68]) r[0x68] = 0;
    }
    if (*(volatile uint32_t *)(uintptr_t)MATCH_ITEM_APPEAR) *(volatile uint32_t *)(uintptr_t)MATCH_ITEM_APPEAR = 0;
}
static int comp_mapped(uint64_t a) {        /* the game's .bss is mapped by the loader some time after the hook table works */
    MEMORY_BASIC_INFORMATION mi;
    return VirtualQuery((const void *)(uintptr_t)a, &mi, sizeof mi) && mi.State == MEM_COMMIT && (mi.Protect & (PAGE_READWRITE | PAGE_EXECUTE_READWRITE));
}
static DWORD WINAPI comp_keep(LPVOID arg) {
    (void)arg;
    for (;;) {
        int ok = 1;
        for (int i = 0; i < 3; i++) ok &= comp_mapped(k_rules[i]) && comp_mapped(k_rules[i] + 0x68);
        ok &= comp_mapped(MATCH_ITEM_APPEAR);
        if (ok) break;
        Sleep(20);
    }
    for (;;) { comp_clear(); Sleep(2); }
    return 0;
}
static DWORD WINAPI comp_wait(LPVOID arg) {
    (void)arg;
    for (int i = 0; i < 3000; i++) {        /* the hook table answers once the game's function table is set up */
        if (hook_install(0x71014e58f0ull, comp_battle, NULL, &g_battle_orig)) {      /* the game image (and its globals) is there */
            HANDLE k = CreateThread(NULL, 0, comp_keep, NULL, 0, NULL);
            if (k) CloseHandle(k);
            printf("competitive: ON (no FS meter, no random items)\n");
            return 0;
        }
        Sleep(10);
    }
    printf("competitive: the hook could not be installed: OFF\n");
    return 0;
}

__attribute__((constructor)) static void comp_start(void) {
    const char *e = getenv("SSBU_COMPETITIVE");
    if (!e || e[0] != '1') return;
    HANDLE h = CreateThread(NULL, 0, comp_wait, NULL, 0, NULL);
    if (h) CloseHandle(h);
}
