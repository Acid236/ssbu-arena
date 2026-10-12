// n4_loose.cpp - the loose-file layer (recomp-study\loose_files.c) built as a mod DLL for the N4 tests, so that it
// can be tried without relinking an exe. The layer itself is runtime code, not a mod: see loose_files.c.
// Build:  python fighter_sdk\tools\build_mod.py mods_n4_src\n4_loose.cpp mods_n4l      Run: SSBU_MODS=mods_n4l (or copy next to the other mods)
#include <stdint.h>
#include "hook.h"
#include "../loose_files.c"

extern "C" __declspec(dllexport) void mod_init(const HookApi *api) {
    loose_files_start(api->install, api->log);
}
