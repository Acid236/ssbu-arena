/* loose_host.c - the loose-file layer (loose_files.c) as part of the exe (plan\phases\N4_own_fighter.md, section 3.3).
 * OPT-IN for now: nothing happens unless SSBU_LOOSE_FILES=1 is set (the layer is a first stage; the owner's default
 * build must not change because a characters\ folder exists). With it set: the hook on the per-file decompress is
 * installed as soon as the hook table can find the function, which is before the game opens its archive.
 * No other host file calls into this one: it starts itself from a constructor, so a link that leaves this file
 * out is simply a game without the layer. Contains nothing of the game. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include "runtime.h"
#include "hostrt.h"

typedef void (*HookFn)(Ctx *c, void *user);
typedef ImportFn HookOrig;
int hook_install(uint64_t addr, HookFn repl, void *user, ImportFn *orig);      /* fighter_sdk\hook_host.c (in nnro.c) */

#include "loose_files.c"

static void loose_host_log(const char *s) { printf("%s\n", s); fflush(stdout); trace_printf("%s\n", s); }

static DWORD WINAPI loose_host_wait(LPVOID arg) {
    (void)arg;
    /* the hook table answers "not the entry of a lifted function" until the game's function table is set up */
    if (!loose_files_scan(loose_host_log)) return 0;    /* no folder / no files: nothing to wait for */
    /* N7: the same thread polls every millisecond for the game's tables and grows them as soon as they are published
     * (loose_files_early), before the first file request when it wins; SSBU_LOOSE_EARLY=0: only the first decompress */
    const char *ee = getenv("SSBU_LOOSE_EARLY");
    int hooked = 0, early = !(ee && ee[0] == '0');
    for (int i = 0; i < 120000; i++) {
        if (!hooked && i % 10 == 0) hooked = loose_files_install(hook_install, 1);
        if (early && loose_files_early()) early = 0;
        if (hooked && !early) return 0;
        if (!hooked && i == 3000) loose_host_log("[loose] the hook could not be installed in 30 s: the layer is OFF");
        Sleep(1);
    }
    return 0;
}

extern int (*g_nm_stage2_has)(uint64_t path_hash);      /* fighter_sdk\newmodule_host.c: the registry's path fallback asks stage 2 */

__attribute__((constructor)) static void loose_host_start(void) {
    const char *e = getenv("SSBU_LOOSE_FILES"), *ch = getenv("SSBU_CHARACTERS");
    /* N6: the fighter registry (SSBU_CHARACTERS) switches the layer on too, unless SSBU_LOOSE_FILES=0 */
    if (e && e[0] == '0') return;
    if (!(e && e[0]) && !(ch && ch[0])) return;
    g_nm_stage2_has = loose_files_has;
    HANDLE h = CreateThread(NULL, 0, loose_host_wait, NULL, 0, NULL);
    if (h) CloseHandle(h);
}
