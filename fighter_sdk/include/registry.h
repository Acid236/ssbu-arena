// registry.h - the fighter registry of the native port (plan\phases\N5_own_module.md, docs\NEW_FIGHTER.md).
//
// With SSBU_CHARACTERS=<folder> the runtime reads <folder>\<name>\fighter.json of every sub-folder at start; each
// manifest is one NEW fighter. The runtime itself answers the game's request for the script module lua2cpp_<name>
// (fighter_sdk\newmodule_host.c); the components that own the engine's per-kind tables (still built as DLLs with
// hook.h: the kind component and the roster component, in the folder registry_bin) ask the runtime for the list:
//
//     const SsbuRegistry *reg = ssbu_registry_get();      // NULL in an exe without the registry
//
// Contains nothing of the game.
#pragma once
#include <stdint.h>

typedef struct SsbuRegFighter {
    char name[32];                 // lower-case name: kind hash "fighter_kind_<name>", module "lua2cpp_<name>", roster id "ui_chara_<name>"
    char donor[32];                // the existing fighter that supplies what the folder does not bring
    char dll[64];                  // file name of the script DLL in the fighter's folder ("" = none)
    char folder[260];              // the fighter's folder
    int kind;                      // the fighter kind number given to it (0x5E, 0x5F, ...)
    int own_name;                  // 1: the engine's name row is the fighter's own name (own module, own file paths)
} SsbuRegFighter;

typedef struct SsbuRegistry {
    uint32_t size, version;        // sizeof(SsbuRegistry), 1
    int count;
    const SsbuRegFighter *fighters;
    // install the runtime's own hooks (module request, script registration); call once from mod_init
    void (*start)(void);
    // A factory of the DONOR's script module is about to create an agent for the new fighter `name` on this thread ...
    void (*agent_begin)(const char *name);
    // ... and has returned `agent`. From here on the agent belongs to the new fighter's module: its class table and
    // every script it registers are addresses of lua2cpp_<name>. name == NULL: `agent` is an ordinary fighter's
    // (an address that belonged to a new fighter's agent earlier is forgotten).
    void (*agent_end)(const char *name, uint64_t agent);
} SsbuRegistry;

#ifdef _WIN32
#include <windows.h>
static inline const SsbuRegistry *ssbu_registry_get(void) {
    typedef const SsbuRegistry *(*Fn)(void);
    Fn f = (Fn)(void *)GetProcAddress(GetModuleHandleA(NULL), "ssbu_registry");
    return f ? f() : NULL;
}
#endif
