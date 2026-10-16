# Debug / fast mode for scripted test runs (2026-10-12, exe `ssbu_dbg1.exe`, linked from build.py with `debug_mode.c`)

TEST ONLY. Everything is behind environment variables; none set = the code paths are not taken (one `getenv` at start
and, in display.c, one `getenv` per feature). Relink any test exe with `RECOMP_EXE=<name>.exe python build.py link`
(`debug_mode.c` is in `HOST_SOURCES`; `link_exe.py` of the fighter tools still adds the old `nvn_vk_draw.c` and fails
now: use build.py directly).

| variable | what it does |
|---|---|
| `SSBU_SPEED=<n>` | 2, 4, any number > 0: the refresh clock runs n times faster; `0` = uncapped; unset or 1 = normal. `display.c`: with n != 1 there is NO free-running vsync thread. In `display_wait_refresh` (the game's wait on the window texture's sync) the refresh the queued frame waits for is produced there: wall-clock gap 1/60/n s (none when uncapped), the guest's vsync event is signalled, and the call waits until the game's VSync Count Thread has counted it (window object + 0x138). So the game counts exactly one refresh per presented frame whatever the host speed: no frame is skipped, the logic is not touched. Interval 0 / 2 frames behave as before (0 = no wait, 2 = two refreshes). Log: one line `speed: frame N, K frames presented in the last T s` per second. Audio: NOT muted by this variable (the audio thread runs on wall time and will glitch; use `SSBU_AUDIO_MUTE=1` with it). |
| `SSBU_SKIP_MOVIES=1` | `nnmovie_mf.c` `ext_fill`: the extractor reports end of stream after 12 samples (`SSBU_SKIP_MOVIES=<n>`, n > 1: after n samples) instead of the real 130 s. The game's own player then ends the movie by its normal end-of-stream path (log `movie: SSBU_SKIP_MOVIES: end of stream after 12 samples`, decoders destroyed, title follows). 0 samples (immediate EOS) does NOT work: the player stays on the movie for ever. Applies to every movie that goes through this player (opening movie; the others were not exercised). |
| `SSBU_FRAMELOG=<k>` | `frame-mark: <n>` every k presented frames (to put log events on the game-frame axis). |
| `SSBU_DEBUG_MATCH="p1=<fighter>,p2=<fighter>,stage=<name>,form=normal\|battlefield\|omega,cpu=<1-9>,p2=cpu\|human,stock=<n>,items=on\|off,hazards=on\|off"` | **APPLIED since session 2 (2026-10-12, exe `ssbu_dbg2.exe`)**: see "Debug match" below. The scripted menus are still walked (they only confirm); the choice is replaced where the game turns the screens' choice into the match set-up. Works: both fighters, stage, form, CPU level, CPU / human for player 2, stock. Written but NOT verified: items, hazards. Not implemented: `time=`. |
| `SSBU_DEBUG_MATCH_LIST=<file>` | one setting per line (same syntax); every new match set-up of the process takes the next line (the last one stays). With `tests\seq_debug_list.txt` = three fights in one process. Example list: `tests\debug_match_list_example.txt`. |
| `SSBU_DEBUG_END=<n>s` or `<n>` | ends the run after n seconds of fight (n x 60 game frames) or n fight frames, counted per fight from the game's own ready-go flag (FighterManager + 0xd2): log `debug end: N fight frames reached at presented frame F (SSBU_DEBUG_END): exit request, normal shutdown`, then the exit path of a closed window (exit code 0, fighter report and health lines written). |
| `SSBU_DEBUG_RESEARCH=1\|2\|3`, `SSBU_DEBUG_WATCHENTRY=1` | research aids of session 2 (dumps of the panel state / match block, hardware watches with the GUEST frame chain: the watch handler finds the thread's guest context in a host register and walks x29). |
| `SSBU_DEBUG_DUMP=1`, `SSBU_DEBUG_SCAN=1`, `SSBU_DEBUG_WATCH=1` | research aids that found the facts below: dump of the first 0x400 bytes of each fighter information record, scan of memory for copies of a record, hardware write watchpoints (debug registers) on record fields with the guest functions on the writer's stack. |
| `PROBE_FAST=<speed>` (probe.py, optional) | sets `SSBU_SPEED`, `SSBU_SKIP_MOVIES=1` and uses `tests\seq_battle_play_fast.txt`. Since session 2 the same happens (uncapped) when `SSBU_DEBUG_MATCH`, `SSBU_DEBUG_MATCH_LIST` or `SSBU_DEBUG_END` is in the environment or given as `KEY=VALUE` (with a list: `tests\seq_debug_list.txt`); e.g. `python fighter_sdk\tools\probe.py health t1 "SSBU_DEBUG_MATCH=p1=kirby,p2=yoshi,stage=end,cpu=9" SSBU_DEBUG_END=40s` (probe.py edited, parses; NOT run by this session). Any `KEY=VALUE` argument or inherited variable already reached the game before this. The exe must be one linked with the new sources (probe's default `ssbu_s4.exe` is not). |

## Sequences (part 3)
`SSBU_SEQ` steps are counted in **polls of player 1 = game frames** (`@draws`, `@until`, `N:keys`), not wall time:
speed independent by construction. Only `SSBU_SCRIPT` / `SSBU_PRESS` (nnhid.c `g_script`, GetTickCount64) are wall time
(untouched; do not use them with `SSBU_SPEED`). One problem was found: `@until:36-44/30:Z/200` (press A every 200 polls
until the title logo is up) races with a skipped/short movie: when a press lands as the title appears the title is
passed and the sequence is lost (uncapped run f0: stuck for 25,000 polls in the menus, 193 draws). New
`tests\seq_battle_play_fast.txt` = the same sequence with `@draws:36-44/30` at that place (no presses; the movie ends by
itself with `SSBU_SKIP_MOVIES=1`). Use it with SKIP_MOVIES; the old file with the real movie.

## Measured (this PC, Vulkan renderer, other agents' games running at times; one run each, wall seconds from process start)
Boot to the first game frame is about 17-23 s in every mode (arc, shaders, modules): not touched.

| run | movie | speed | opening movie created -> destroyed | title (step 3 key press) | first battle frame (step 19) | fight rate |
|---|---|---|---|---|---|---|
| n1 normal | real, A presses | 1 | 20.8 -> 25.4 s (220 -> 440 frames) | 26.5 s | 53.2 s | 60 fps |
| f1 | skipped, A presses | 1 | 23.3 -> 27.4 s (200 -> 360 frames) | 27.4 s | 54.7 s | 60 fps |
| f2 | skipped, A presses | 2 | - | 19.9 s | 34.9 s | see below |
| f4 | skipped, A presses | 4 | 23.4 -> 28.0 s (760 -> 1480 frames) | 28.0 s | 44.6 s | 138 fps in the fight (menus 240) |
| g0 `_fast` seq | skipped | uncapped | 16.8 -> 20.9 s | 20.9 s | 34.0 s | 176 fps in the fight |
| g2 `_fast` seq | skipped | 2 | - | 20.4 s | 53.8 s (loading slow, other games running) | 83 fps |
| g1 `_fast` seq | skipped | 1 | 27.3 -> 32.5 s | 32.5 s | 69.3 s (machine busy) | 60 fps |
(f0, uncapped with the A-press sequence: lost in the menus, see above; g4 `_fast` at 4x: reached the fight, the match
never ended in 200 s: the sequence has no input left, Mario ended frozen/idle.)
Start -> first battle frame for `seq_battle_play`: 53 s at 1x (real movie), 34 s uncapped with skip + fast sequence,
44.6 s at 4x with the A-press sequence. The movie skip itself saves only 1-2 s at 1x (the sequence's A presses already
end the real movie after ~4.6 s; the player needs ~160 frames of pre-roll even for a skipped movie). The game's wall-time
waits (movie pre-roll, loader threads) do not scale with SSBU_SPEED: they take 4x more frames at 4x.
Speed achieved is limited by the host, not the clock: at 4x the fight ran at 138 fps (2.3x), uncapped 120-176 fps
(2-3x); menus reach 240 fps at 4x. CPU of the process: g0 uncapped 123 CPU-s in 50 s (2.5 cores); f1 (1x) 138 CPU-s in 95 s.

## Speed independence of the fight (part 1 check)
`clock:` lines (SSBU_CLOCKSTAT=1) in every speed-mode run read `game steps 600 = 10.00 s of match time` per 600 presented
frames and `refreshes counted between presents 0:600 1:0 2:0 3+:0` (the count is read before the refresh is counted, as
in the 1x runs): one game step per presented frame, no skipped steps, at 4x and uncapped. What was NOT achieved: a
comparison of "frames to the end of the same match". The fight itself is not reproducible even at 1x: frames from first
battle frame to the unload of the fighter modules were 2960 (n1, real movie), 2280 (f1, same speed), 2980 (f2), 2620 (f4)
(the S1 notes say the same about seq_battle_play: its fight diverges after ~15 s with the same seed, timing dependent).
With the `_fast` sequence (same input, one run each): first battle frame -> modules unloaded = 2280 frames at 1x (g1),
2620 at 2x (g2), 2660 uncapped (g0), 2620 at 4x with the A-press sequence (f4); g4 (4x, fast) never ended. So the spread
between speeds (2280-2660) is the same size as at 1x alone (2280-2960).
So differences between speeds are inside the 1x run-to-run spread; no conclusion about timing-dependent behaviour for
the rollback track can be drawn from these four runs. A deterministic check needs a sequence with scripted input to the end
and the fight length measured over several runs per speed.

## Before / after for normal runs
No variable set: `ssbu_dbg1.exe` (base1) and the old `ssbu_s4.exe` (o1) ran `seq_battle_play` through the same 22+ steps
in the same order (movie seen, title, menus, stage, character, fight), 0 traps; the poll numbers differ (194 vs 296 for
"movie seen", etc.) the way two runs of the same exe differ (movie/loader timing), so identical milestones, not identical counts.

## Debug match (session 2, 2026-10-12 evening): how the set-up is found and overwritten
All addresses are of the game's own 13.0.4 main (base 0x7100000000), found with a hardware write watch + the guest frame
chain, Ghidra (read only) and a disassembly of main.elf.
* **The match block**: a global at `0x71052c41b0` (accessor `0x7101388880`; `sv_global_parameter::melee_*` read it).
  Rule header at +0 (+0x54 "item appear" 0..4), stage block at +0x420 (+0 = stage id as the battle uses it), eight player
  records of 0x260 bytes from +0x580 (`0x71052c4730 + 0x260 * i`): +0 ui_chara id (`0xc1 << 56 | hash40("ui_chara_<name>")`),
  +8 fighter kind, +0xa type (0 human, 1 CPU, 2 none), +0x18 stocks, +0x19 colour, +0x79 CPU power (level 1..9 -> 0, 15, 21, 31, 42, 48, 60, 75, 100).
* **Players**: `0x7101788260(panel state, player index, x, record *)` builds one record from the select screen's panel state
  (called 8 times from `0x710178f498` <- `0x7102311914` when "Ready to fight" is confirmed). Panel state: +5 rule kind
  (1 = stock), +0xa stocks, +0x78 type (0 human, 1 CPU, 3 none), +0x88 ui_chara id, +0x90 colour, +0x91 CPU level 1..9
  (used when +0x224 is 0xffffffff). `debug_mode.c` hooks this function (hook table) and rewrites the STATE before the
  game's function runs, so the record and everything derived from it are the game's own work.
* **Stage**: the same caller reads the stage choice right after the players (`0x7102311a24..`): three entries of 0x20 bytes
  at `0x71053097c0`, current index at `0x7105309968`: +0 ui_stage id (`0x69 << 56 | hash40("ui_stage_<name>")`), +8 form
  (0 normal, 1 battlefield, 2 omega), +0xc flag word, +0x10 second id (a ui_bgm id); `0x710178ab60` then writes the stage
  block. The hook for player 0 overwrites id and form there. Names are the `ui_stage_*` names of `..\reference\param-labels`
  (`end`, `battle_field`, `mario_castle64`, ...; `fd` / `final_destination` / `battlefield` are accepted).
* **What the first session got wrong**: FighterInformation record + 0x30 is not the fighter kind; the entry's own copy of
  the kind is at FighterEntry + 0x88 (init parameter + 0x18, `0x7100653240` copies 0x70 bytes to entry + 0x70).
* Fighter names are the `FIGHTER_KIND_*` / `ui_chara_*` names (mario, donkey, kirby, yoshi, captain, ganon, ...).

Proof lines (game state at the game's ready-go; the `[health]` lines use the game's own getters and agree):
```
q1 p1=mario,p2=donkey,stage=end,form=normal,cpu=3            -> p1 kind 0, p2 kind 1 type 1 cpu power 21, stage id 0x3, ui_stage 6900000c40bf5050 form 0; 1300 fight frames, 0 traps, exit code 0
q2 p1=kirby,p2=yoshi,stage=mario_castle64,form=omega,cpu=9   -> p1 kind 6, p2 kind 5 type 1 cpu power 100, stage id 0x6, form 2; 1300 fight frames, 0 traps, exit code 0
q3 p1=captain,p2=ganon,stage=mario_castle64,form=normal,items=on,p2=human -> p1 kind 11, p2 kind 24 type 0, stage id 0x5, form 0, item appear 2; 1300 fight frames, 0 traps, exit code 0
```
Stage ids seen: battle_field 0x0, end 0x3, mario_castle64 normal 0x5 / omega 0x6; the stage the plain script picks is NOT
Battlefield (ui_stage 0x1d163699ac4b, stage id 0x50). Limits / not verified:
* the form is proven only by the stage id changing with it (0x5 -> 0x6); no screenshot was taken, so "0x6 is the omega
  form" rests on the field's use in the code (1 = the Battlefield special case, 2 = the other);
* `items=on` writes 2 to the rule's item-appear field after the header is filled: whether items then spawn was NOT checked
  (the item switches of the rule were not looked at); `hazards=` writes the byte `0x7105309985` that the stage call takes
  as a flag: its meaning is a guess, NOT verified (final destination and omega forms have no hazards anyway);
* `time=` is parsed and ignored; colour is not settable; players 1 and 2, and since 2026-10-13 (track V session 14)
  `p3=<fighter>,p4=<fighter>` = two more CPU players (an empty panel takes player 2's panel state as its template, own
  colour, same level and stock; `SSBU_DEBUG_P34=2` copies only the known fields). Proof: records 2 and 3 get the kinds
  asked for, type 1. A four-player match does not end when player 1 walks off: a list run plays one fight;
* `stock=1` verified by effect (match over after one KO, 245-259 fight frames); a line printed at ready-go still shows
  `stocks in the fighters' records 3 / 3`: that record field (+0xd8) is not the stock count either;
* route B (no screens at all) was not attempted: the caller at `0x71023119xx` is a scene step that is not a function in
  Ghidra; the pieces it needs are known now (fill the panel states / stage entry, then make that step run), the scene
  change itself is not. The screens cost about 16 s of a 38-45 s start (title key at 22 s, first battle frame at 38 s).

## Several fights in one process (session 2)
`SSBU_SEQ` from `tests\seq_debug_list.txt` + `SSBU_DEBUG_MATCH_LIST=tests\debug_match_list_example.txt` (use `stock=1`):
player 1 walks off the left edge, A through the results until the loading screen, the character select comes back
(the token has to be placed again: same hand moves as the first time), next line of the list. Run L2, one process:
fight 1 mario/donkey on `end` (id 0x3) ready-go at 51.5 s, over at 54.1 s; fight 2 kirby/yoshi on mario_castle64 omega
(id 0x6) ready-go at 77.8 s (**23.7 s** from the end of fight 1); fight 3 captain/ganon on battle_field (id 0x0) ready-go
at 106.6 s (**26.7 s**), ended by `SSBU_DEBUG_END=1200` at 126.4 s, exit code 0, 0 traps. A new process costs 38-51 s to
the first ready-go, so a fight in the same process is about 15-25 s cheaper. Limits: the file holds exactly three fights
(the sequence language has no loop: copy the block for more); fights 1 and 2 last only ~250 fight frames because the
walk-off ends them (a test that needs a long fight in the middle needs its own input there); of the 24-27 s about
7 s are the KO / GAME / results presentation and the rest loading.

## Boot time in test mode (session 2): profile, nothing cut
Wall seconds from process start, uncapped + skipped movie (runs a1, q1, q3, s3; other agents' games running at times):
| step | at |
|---|---|
| exe + game DLL loaded, Vulkan device, pipeline cache read (70 MB: 20-45 ms file, 25-70 ms driver), static constructors, nnMain entered | 1.2-1.9 s |
| pipelines made ahead by the renderer (16 threads) | +0.6 s |
| the game's own start until its first presented frame | 10.8-14.5 s |
| logo screens (frame based: 2,100 frames at 600 fps) | +2.5-3 s |
| wait until the game creates the movie player (wall time, loader threads) | 18.4-22 s |
| skipped movie ends (12 samples; the player's pre-roll) | +2.4-3.5 s |
| title accepts A (step 3) | 22.4-26.2 s |
| first battle frame | 38.4-43.6 s |
What the 9-13 s before the first frame are: the game creates its shader programs one by one (program #33 at 5.6 s,
#7,775 at 13.1 s in run a1) and reads its start-up files; that goes through the renderer's `nvnProgramSetShaders`
(Vulkan agent's files). The script modules are NOT loaded at boot: `lua2cpp_common` + `lua2cpp_item` are requested by the
game at the first frame (190-200 ms together), fighter modules on demand (45-55 ms each), so there is nothing of ours to
make lazy there. No cut was made in this session; candidates, all outside the files this task may edit: the program
creation loop (renderer), the 5 s wall-time wait before the movie (the game's loader threads). First run after the
Vulkan agent's new container store was linked in: 99 s to the movie (it read data.arc once, 28 s, and prepared for
70 s more); the next runs were as above.

## Fighter / stage choice without the screens (part 4, session 1 notes; superseded by "Debug match" above)
* Route A (overwrite the choice by data where the select screens hand over to the battle) was not found. What is known,
  from the game's own binary (Ghidra, read only) and from runs: `lib::Singleton<app::FighterManager>::instance_`
  (dynsym value 0x52b84f8) -> `*mgr` = impl; `impl + 0x20 + 8*entry` = FighterEntry; `entry + 0xf0` = FighterInformation;
  `*(information + 8)` = an information record (0x400+ bytes): +0x00 entry number, +0x30 **fighter kind + 1** (Mario 1, Pikachu 9),
  +0x38 HP 999.0, +0x51 colour, +0x92 CPU flag, +0xcc.. dead counts, +0xd8 stock, +0x3ac category.
  The record is created at battle load with +0x30 = 0 and the kind written a moment later (hardware watch: first write by
  `f_71037a4100` area, then `f_71006542d0`, which the decompilation does not support, so the attribution of the writer is
  unreliable). **Overwriting +0x30 in the record (run m1: wrote kinds 6 and 9) changes nothing**: the fight spawned the fighters
  chosen on the screens (health lines: kinds 0 and 8). The record is a copy; the source lives earlier (a second copy
  with the same layout exists in a heap region, see `SSBU_DEBUG_SCAN`; not followed). Scene classes seen in strings:
  `CharaSelectSceneParameter`, `StageSelectSceneParameter`, `MeleeRuleSceneParameter` (no cross-references in Ghidra to them).
* Route B (start the melee scene directly) was not looked at.
* Stage / omega form / items / time / stock / CPU level: not found either. The existing sequence picks the first stage
  (Battlefield) on the stage select; whether that screen has a key for the omega form was not tried (needs a screenshot).
* The hook table (`hook_install`) is usable from `debug_mode.c` (external function of nnro.c, hook_host.c included there).

## Headless (part 5): NOT DONE
`nvn_stub.c` has no null back end (it hands out the NVN names; drawing is in nvn_gl.c / nvn_vk.c, which this task may not
touch), so the game keeps issuing its graphics calls. Test exes (any name except ssbu_native.exe / ssbu_user.exe, unless
`SSBU_SHOW=1`) already get a window at (-32000,-32000) without taskbar entry, i.e. a hidden window. Presentation skipping
would need a change in the back end. CPU cost of a match: see the CPU-seconds above (uncapped: about 2.5 cores). Two
instances at once were not tried (one game at a time was the rule): each would need its own `SSBU_USERDATA` copy (run.py does that).
