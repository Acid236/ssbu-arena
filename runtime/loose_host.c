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

static void loose_host_log(const char *s) { printf("%s\n", s); trace_printf("%s\n", s); }

static DWORD WINAPI loose_host_wait(LPVOID arg) {
    (void)arg;
    /* the hook table answers "not the entry of a lifted function" until the game's function table is set up */
    if (!loose_files_scan(loose_host_log)) return 0;    /* no folder / no files: nothing to wait for */
    for (int i = 0; i < 3000; i++) {
        if (loose_files_install(hook_install, 1)) return 0;
        Sleep(10);
    }
    loose_host_log("[loose] the hook could not be installed in 30 s: the layer is OFF");
    return 0;
}

__attribute__((constructor)) static void loose_host_start(void) {
    const char *e = getenv("SSBU_LOOSE_FILES");
    if (!e || e[0] == '0' || !e[0]) return;
    HANDLE h = CreateThread(NULL, 0, loose_host_wait, NULL, 0, NULL);
    if (h) CloseHandle(h);
}
