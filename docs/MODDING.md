# Modding the native port: fighters as C++ source, and the hook table

State: 2026-10-09, session S3 (details and every number: `plan\phases\S1_fighter_source.md`, sections 7 and 8).
Everything here works on the owner's PC with the owner's own dump of version 13.0.4; nothing is published.
All paths are relative to `Documents\SSBU\recomp-study`.

## 1. What can be changed, and how

| You want to change | Where | Rebuild |
|---|---|---|
| a move of a fighter (hitboxes, damage, angles, timing, effects, sounds) | `fighters\<name>\acmd\game.cpp`, `effect.cpp`, `sound.cpp`, `expression.cpp` | `python fighter_sdk\tools\build_fighter.py <name>` (about 1 s) |
| a rule of the shared fighter state machine (dash, turn, run, jump squat, air dodge, landing, transition checks ...) | `fighters\common\status\*.cpp` | `python fighter_sdk\tools\build_fighter.py common` |
| ANY function of the game (main executable or a script module), without having its source | a mod DLL using `fighter_sdk\include\hook.h` | `python fighter_sdk\tools\build_mod.py <mod.cpp> <folder>` |

Neither the exe nor the recompiled game code is ever rebuilt for a mod. A fighter DLL is loaded when the game
loads that fighter's script module (every match), so "edit, build, start the next match" picks it up inside one
run of the game.

## 2. Layout: what is the project's, what comes from your copy of the game

Two kinds of files, kept in different folders. The project consists of tools and a run-time only; everything
derived from the game is produced on your PC from your own dump by those tools and is NOT part of the project
(never publish or share it).

```
PROJECT (tools and run-time; contain nothing of the game)
fighter_sdk\tools\                    decompilers, SDK generator, build and test drivers (*.py)
fighter_sdk\include\fighter_sdk.h     L2CValue, L2CAgent, hash40("..."), the ACMD / L2C_FUNCTION macros
fighter_sdk\include\hook.h            the hook API for mods
fighter_sdk\src\fighter_rt.cpp        run-time linked into every fighter DLL
fighter_sdk\fighter_host.c            host side: loads fighter DLLs, switches functions, differential tests
fighter_sdk\hook_host.c               the hook table
fighter_sdk\examples\mod_example.cpp  a complete mod

GENERATED FROM YOUR GAME (by the tools; stays on your PC)
fighters\<name>\acmd\*.cpp            the moves of one fighter: one ACMD(<name>, <script>) { ... } block per script
fighters\common\status\*.cpp          the shared state machine: one L2C_FUNCTION(common, <name>) { ... } per function
fighters\<name>\generated\bindings.inc  script/function -> offset of its original in the game's module (do not edit)
fighters\sdk_generated\lua_bind.h     one wrapper per game function (AttackModule::..., WorkModule::...)
fighters\sdk_generated\lua_const.h    the game's named constants
fighters\sdk_generated\fs_syms.inc    the game symbols the wrappers bind to
fighters_bin\<name>.dll, obj_fighters\  what the game loads (SSBU_FIGHTER_BIN=<folder> selects another folder), objects
fighter_sdk\tools\out\                tables and refusal lists of the decompiler runs
```

First use on a new PC: `python fighter_sdk\tools\batch.py all` (all fighters' moves, about 15 minutes) and
`python fighter_sdk\tools\batch.py status common L2CFighterCommon::` (the state machine) create the second group.

The C++ in `fighters\` was produced by a mechanical decompiler from the game's own modules and checked against
the originals (section 5). From then on it is source: edit it. Regenerating (`batch.py all`, `batch.py status`)
overwrites edits.

## 3. Source or original, per function, per run

| Environment | Effect |
|---|---|
| (nothing) | every script that exists as source runs as source; everything else runs the recompiled original |
| `SSBU_FIGHTER_SRC=0` | no fighter DLL is loaded: the game as it was |
| `SSBU_FIGHTER_LIFTED=1` / `=name1,name2` | all / the named scripts run the original |
| `SSBU_FIGHTER_HOOK=1` | source functions are installed with the hook table: they are reached by every call, including the direct calls inside the game's own code (needed for the state machine; see section 7 for the state) |
| `SSBU_FIGHTER_TRACE=<text>` | print every game call made by source scripts whose name contains the text |
| `SSBU_FIGHTER_LOG=1` | (with `SSBU_FIGHTER_HOOK=1`) one log line per change of a fighter's damage percent and status kind |
| `SSBU_MODS=<folder>` | load the mod DLLs of that folder |
| `SSBU_HOOK_COUNT=<address or name>,...` | count the calls of any game function; printed at exit |

To make a function permanently original again: delete its `ACMD(...)` / `L2C_FUNCTION(...)` block and its line in
`bindings.inc`.

## 4. The hook API (`hook.h`)

Every function of the main executable (112,890) and of the script modules can be replaced while the game runs,
by address or by exported name. The first hook on a function rewrites 5 bytes at its entry in memory (a jump);
a function without a hook is untouched, so no hook = the game exactly as before. A replacement sees the register
context of the calling game thread: integer and pointer arguments in `c->x[0..7]`, floats in `c->v[0..7]`, the
result buffer of a function returning an L2CValue in `c->x[8]`; `orig(c)` runs what the function did before.

```cpp
// fighter_sdk\examples\mod_example.cpp (shortened): count jump squats; optionally forbid ground jumps
#include <stdio.h>
#include "hook.h"
static const HookApi *api;
static HookOrig orig_jump_squat, orig_check_jump;      // static: written when lua2cpp_common is loaded
static int jump_squats;

static void my_jump_squat(Ctx *c, void *user) {        // L2CValue L2CFighterCommon::status_JumpSquat(): x0 = agent
    char line[96];
    snprintf(line, sizeof line, "[mod] jump squat number %d", ++jump_squats);
    api->log(line);
    orig_jump_squat(c);                                // the game's own function does the work
}
static void my_check_jump(Ctx *c, void *user) {        // "did the fighter start a jump?" -> always no
    uint64_t *result = (uint64_t *)c->x[8];
    result[0] = 1; result[1] = 0;                      // L2CValue(false); the original is not called
}
extern "C" __declspec(dllexport) void mod_init(const HookApi *a) {
    api = a;
    api->install_name("_ZN7lua2cpp16L2CFighterCommon16status_JumpSquatEv", my_jump_squat, nullptr, &orig_jump_squat);
    api->install_name("_ZN7lua2cpp16L2CFighterCommon38sub_transition_group_check_ground_jumpEv", my_check_jump, nullptr, &orig_check_jump);
}
```

Build and run: `python fighter_sdk\tools\build_mod.py fighter_sdk\examples\mod_example.cpp mods_s3`, then start the
game with `SSBU_MODS=mods_s3`. Functions: `install(address, fn, user, &orig)`, `install_name(name, ...)` (a name
of a module that is not loaded yet is installed when it is), `remove(id)` / `enable(id)` (one atomic word each,
safe at any time), `calls(id)`, `address(name)`, `call(ctx, address)`, `log(text)`, `error()`. Two hooks on one
function stack: the newer one's `orig` is the older one. Install from `mod_init`; a first hook installed later
must not race with a thread entering that function.

Names: exported functions of the modules are C++-mangled names (`python fighter_sdk\tools\nrodis.py common <offset>`
prints a function with names; the offsets are in `bindings.inc`). Functions of main without a name are hooked by
address (0x7100000000 + offset in main; Ghidra shows them).

## 5. Checking an edit without playing

```
set SSBU_FIGHTER_OFFLINE=mario          (or common, or all)
ssbu_s3.exe ..\binaries\13.0.4\main.elf 300
```

Runs every source script of the module against its recompiled original without starting the game (2-20 s): both
get the same arguments and the same made-up answers from every game call (all false / all true / a fixed random
pattern); the calls they make, the arguments, and (state machine) the value returned must be equal. An edited
script is reported by name with the changed value (`<script> differs: ... value 1 is type 3 <your float>,
original type 3 <the game's float>`): that is the expected report for your edit, and anything else it names is a
mistake. `python fighter_sdk\tools\batch.py test <name>` does the same and keeps a table.
What it does not prove: behaviour on real values (the answers are made up) - `SSBU_FIGHTER_DIFF=1` in a match
compares source and original on the real calls of that match.

## 6. Writing source

```cpp
ACMD(<fighter>, <script name>) {                   // one animation-command script; agent, boma in scope
    frame(agent, <frame>);
    if (is_excute(agent)) {
        ATTACK(agent, <id>, <part>, hash40("<bone>"), <damage>, <angle>, ...);
    }
}
L2C_FUNCTION(common, <function name>) {            // a function of lua2cpp::L2CFighterCommon; agent, boma in scope
    if (L2CValue(StatusModule::status_kind_next(boma)) == L2CValue(<status kind constant>)) { ... }
    return L2CValue(0);
}
```

- Types are fixed width (`int32_t`, `uint64_t`, `float`): the game is LP64, Windows is not. Never `long`.
- `L2CValue` is the game's own script value (16 bytes, used in place); arithmetic and comparison go through the
  game's operators, so integer/float rules are the game's. `agent->global_table[i]` is the fighter's status table.
- Game functions are called by name through `lua_bind.h`; constants by name through `lua_const.h`.
- A script does not run to its end in one call: `frame()` / `wait()` suspend it (fibers), and the game may end it
  there. Do not hold resources (heap memory, locks) across such calls.

## 7. What is not possible yet

- `SSBU_FIGHTER_HOOK=1` (source reached through direct calls) is NOT the default: see section 8 of the plan file
  for the state of the match test. Without it, a source function of the state machine takes effect only where the
  game reaches it through a pointer or an import.
- Functions the decompiler refused stay original (counted per reason in `fighter_sdk\tools\out\`); they can still
  be replaced from a mod.
- New script names, new statuses, new fighters, more character slots: not built (what each needs is in section
  7.5 of the plan file).
- Per-fighter status scripts (each fighter's own state functions) are not source yet; hook them by address.
- Reloading a fighter DLL in the middle of a match; unloading a mod.
- Loose-file overrides (replacing game files from a folder) are a different piece of track M, not built.
- The hook mechanism is x86-64 Windows only, like the port.
