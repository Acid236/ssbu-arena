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
#include <windows.h>
#include "runtime.h"
#include "hostrt.h"

typedef void (*HookFn)(Ctx *c, void *user);
int hook_install(uint64_t addr, HookFn repl, void *user, ImportFn *orig);      /* fighter_sdk\hook_host.c */

static const uint64_t k_rules[] = {0x710530454cull, 0x7105309924ull, 0x710530f49cull};
static ImportFn g_battle_orig;
static long g_battles;

static void comp_battle(Ctx *c, void *user) {
    (void)user;
    int changed = 0;
    for (int i = 0; i < 3; i++) {
        volatile uint8_t *r = (volatile uint8_t *)(uintptr_t)k_rules[i];
        if (r[0x5f] || r[0x68]) changed++;
        r[0x5f] = 0;            /* charge: Final Smash meter */
        r[0x68] = 0;            /* item_switch */
    }
    if (++g_battles <= 20) printf("competitive: battle %ld: FS meter and items off (%d of 3 rule copies had one on)\n", g_battles, changed);
    g_battle_orig(c);
}

static void comp_clear(void) {
    for (int i = 0; i < 3; i++) {
        volatile uint8_t *r = (volatile uint8_t *)(uintptr_t)k_rules[i];
        if (r[0x5f]) r[0x5f] = 0;
        if (r[0x68]) r[0x68] = 0;
    }
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
