> **Paths.** This guide was written for the tools' own single-folder layout (`recomp-study\`, `fighter_sdk\`, `tests\`, `mods_n*_src\`, `characters\`, `ssbu_*.exe`). `python scripts/setup.py` (step `stage`) builds that layout in `build/work/`: read `recomp-study\` as `build/work/`, run the commands from there. In the repository the runtime sources are in `runtime/`, the lifter in `tools/lifter/`, the test mods in `mods/`. Mentions of `plan\...` files refer to the author's private notes, which are not published.

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

## 6a. A fighter's own status source (session S8; WORK IN PROGRESS, offline only, not installed)

State 2026-10-12: generated and tested offline for all 97 fighter modules, never run in a match; numbers and limits
in `plan\phases\S1_fighter_source.md` section 13. Nothing of this is in `fighters_bin\`.

What a fighter's status source consists of (all under `fighters\<name>\`, made by
`python fighter_sdk\tools\fighter_status.py decompile <name>`):

| File | Content |
|---|---|
| `status\install.cpp` | one `<agent>_install` function per agent of the module (the fighter itself and each of its weapons, e.g. `mario`, `mario_fireball`, `mario_pump`): THE REGISTRATION. It sets the number of statuses, takes the shared table (`sub_set_fighter_common_table`) and binds every (status kind, line) to a function |
| `status\<agent>_<status>.cpp` | the functions registered for that status (`_pre`, `_main`, `_end`, `_init_status`, `_exec_status`, `_exit_status`, `_exec_stop`, `_check_attack`, `_calc_param` ...) and the main loops they hand to the shared state machine (`..._main_loop`) |
| `status\<name>_helpers.cpp` | helpers several statuses share (`<name>_sub_<offset>`: the game gives them no name) |
| `generated\status_local.h` | name -> place in the game's module for every function above (do not edit); `status_function(name)`, `local::name(agent, ...)` |
| `generated\status_bindings.inc` | which functions run as source (delete a line: that function runs the original again) |

The registration is the table a NEW fighter has to provide:

```cpp
L2C_VOID_FUNCTION(mario, mario_install) {
    agent->global_table[12] = L2CValue(FIGHTER_MARIO_STATUS_KIND_NUM);            // how many statuses this fighter has
    L2CAgentBase::reserve_status_data_array(agent, L2CValue(agent->global_table[12]).as_integer());
    L2CFighterCommon::sub_set_fighter_common_table(agent);                        // every status of the shared state machine
    L2CAgentBase::sv_set_status_func(agent, FIGHTER_STATUS_KIND_SPECIAL_N, LUA_SCRIPT_STATUS_FUNC_STATUS_PRE, status_function(mario_special_n_pre));
    L2CAgentBase::sv_set_status_func(agent, FIGHTER_STATUS_KIND_SPECIAL_N, LUA_SCRIPT_STATUS_FUNC_STATUS_MAIN, status_function(mario_special_n_main));
    L2CAgentBase::sv_set_status_func(agent, FIGHTER_STATUS_KIND_SPECIAL_N, LUA_SCRIPT_STATUS_FUNC_STATUS_END, status_function(mario_special_n_end));
    ...                                                                           // a status the fighter does not bind keeps the shared function
    L2CFighterCommon::sub_fighter_common_settings(agent);
}
L2C_FUNCTION(mario, mario_special_n_main) {                                       // "main" starts the status and names its per-frame loop
    return L2CFighterCommon::sub_shift_status_main(agent, L2CValue((void *)status_function(mario_special_n_main_loop)));
}
```

The lines (`LUA_SCRIPT_STATUS_FUNC_*`): STATUS_PRE 0, STATUS_MAIN 1, STATUS_END 2, INIT_STATUS 3, EXEC_STATUS 4, EXEC_STOP 5,
EXEC_STATUS_POST 6, EXIT_STATUS 7, MAP_CORRECTION 8, FIX_CAMERA 9, FIX_POS_SLOW 10, CHECK_DAMAGE 11, CHECK_ATTACK 12,
ON_CHANGE_LR 13, LEAVE_STOP 14, NOTIFY_EVENT_GIMMICK 15, CALC_PARAM 16. `python fighter_sdk\tools\fighter_status.py list <name>`
prints the whole table of a fighter (agent, status kind, line, function, size).

**Projectiles and articles ("weapon" agents).** A fighter's module holds one agent per object it owns: the fighter
and each of its weapons (Mario: `mario`, `mario_fireball`, `mario_hugeflame`, `mario_pump`, `mario_pumpwater`; in
the 97 fighter modules the census finds 590 agent classes, 498 of them not named like their module: weapons). What the game's own modules show, and so what a new
fighter must provide for a projectile:

1. **The agent.** The module's exported `create_agent_fighter_status_script_<fighter>(hash40 of the agent name,
   object, module accessor, lua state)` compares the hash and creates the script object: the fighter itself is a
   `lua2cpp::L2CFighterCommon` (0x228 bytes), every weapon a `lua2cpp::L2CWeaponCommon` (0x118 bytes), each with its
   own class (vtable) whose slot 9 is the install function. The same hash dispatch exists once more per ACMD
   category (`create_agent_fighter_animcmd_game_<fighter>`, `_effect_`, `_sound_`, `_expression_`).
2. **Its status table**, the weapon's install function, same form as the fighter's:
   ```cpp
   L2C_VOID_FUNCTION(mario, mario_fireball_install) {
       agent->global_table[12] = L2CValue(WEAPON_MARIO_FIREBALL_STATUS_KIND_NUM);
       L2CAgentBase::reserve_status_data_array(agent, L2CValue(agent->global_table[12]).as_integer());
       L2CAgentBase::sv_set_status_func(agent, WEAPON_MARIO_FIREBALL_STATUS_KIND_REGULAR, LUA_SCRIPT_STATUS_FUNC_STATUS_PRE, status_function(mario_fireball_regular_pre));
       L2CAgentBase::sv_set_status_func(agent, WEAPON_MARIO_FIREBALL_STATUS_KIND_REGULAR, LUA_SCRIPT_STATUS_FUNC_STATUS_MAIN, status_function(mario_fireball_regular_main));
       L2CAgentBase::sv_set_status_func(agent, WEAPON_MARIO_FIREBALL_STATUS_KIND_REGULAR, LUA_SCRIPT_STATUS_FUNC_EXEC_STATUS, status_function(mario_fireball_regular_exec_status));
       L2CWeaponCommon::sub_weapon_common_settings(agent);      // a weapon has NO shared table: every status it has is its own
   }
   ```
   A weapon's main starts its motion and names its loop with `L2CFighterBase::fastshift(agent, <loop>)` (the
   fighter uses `L2CFighterCommon::sub_shift_status_main`); its life is its own work value
   (`WorkModule::dec_int(boma, WEAPON_INSTANCE_WORK_ID_INT_LIFE)` in `mario_fireball_regular_exec_status`).
3. **Its ACMD scripts**: registered under the weapon's agent, named after its motions (`game_regular`,
   `effect_regular`, `sound_regular` for the fireball). In `fighters\<name>\acmd\*.cpp` a script name used by more
   than one agent of the module gets a suffix (`game_regular`, `game_regular__1`, `game_regular__2`).
4. **How the fighter spawns it**: by the article's number, from an ACMD script or a status function of the
   fighter: `ArticleModule::generate_article(boma, FIGHTER_MARIO_GENERATE_ARTICLE_FIREBALL, false, -1);`
   (`fighters\mario\acmd\game.cpp`, `game_specialn`). The game then asks the module for the agent of that article
   (step 1) and starts it in its first status. The link article number -> agent name -> model / parameters is DATA
   of the game (the fighter's parameter and model files), not script: for a new fighter it has to be added there
   (not looked at in this session). Other owner-side calls seen in the scripts: `ArticleModule::change_motion`,
   `set_visibility_whole`, `remove_exist`; the weapon reaches its owner with `Weapon::get_founder_id` /
   `WeaponSpecializer_*`.

The common ITEMS (`lua2cpp_item`, one module, 421 item classes) are bound differently: an item's install
function binds a status kind to a NAME STRING and a table member of the class through a helper of the module, and
the functions are values built by the class constructor. The census counts them; they are not source yet
(plan section 13).

Build and test (work folders; the default build of a fighter does NOT compile `status\`):

```
python fighter_sdk\tools\fighter_status.py cycle mario      decompile, SDK (fighters\sdk_generated_s8), build into fighters_bin_s8, offline test
set SSBU_FIGHTER_STATUS=1 & set SSBU_FIGHTER_SDK=sdk_generated_s8 & set SSBU_FIGHTER_BIN=fighters_bin_s8
python fighter_sdk\tools\build_fighter.py mario             after an edit
python fighter_sdk\tools\fighter_status.py test mario       every bound function against its original, made-up answers, 3 passes
python fighter_sdk\tools\signals.py mario                   static check: calls named in the binary vs in the source text
```

Limits: a function calls another function of the fighter directly as source (`local::name(agent, ...)`) only when
that one is source too, so a function whose callee was refused stays original; helpers the game calls as plain
functions (`L2CValue local::name(L2CAgent *agent, ...)`) are not bound and are tested only inside their callers;
the names `<agent>_<status>_<line>` are this project's (the game has none), status kinds and lines are the public
constant names. A new fighter also needs what section 7 lists (a module to load, a character slot, ACMD scripts,
parameters, model and animations): the registration is only the script side.

## 7. What is not possible yet

- `SSBU_FIGHTER_HOOK=1` (source reached through direct calls) is NOT the default: see section 8 of the plan file
  for the state of the match test. Without it, a source function of the state machine takes effect only where the
  game reaches it through a pointer or an import.
- Functions the decompiler refused stay original (counted per reason in `fighter_sdk\tools\out\`); they can still
  be replaced from a mod.
- New script names, new statuses, new fighters, more character slots: not built (what each needs is in section
  7.5 of the plan file).
- Per-fighter status scripts (each fighter's own state functions): source exists in work folders and is equal
  OFFLINE only (section 6a); it has never run in a match and is not installed. Until then hook them by address.
- Reloading a fighter DLL in the middle of a match; unloading a mod.
- Loose-file overrides (replacing game files from a folder) are a different piece of track M, not built.
- The hook mechanism is x86-64 Windows only, like the port.
