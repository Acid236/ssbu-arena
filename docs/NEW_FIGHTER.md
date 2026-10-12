> **Paths.** This guide was written for the tools' own single-folder layout (`recomp-study\`, `fighter_sdk\`, `tests\`, `mods_n*_src\`, `characters\`, `ssbu_*.exe`). `python scripts/setup.py` (step `stage`) builds that layout in `build/work/`: read `recomp-study\` as `build/work/`, run the commands from there. In the repository the runtime sources are in `runtime/`, the lifter in `tools/lifter/`, the test mods in `mods/`. Mentions of `plan\...` files refer to the author's private notes, which are not published.

# A new fighter in the native port: what it consists of today

State: 2026-10-12, first version (session N4). This describes OUR runtime and tools; it contains nothing of the
game. Everything a fighter is made of that comes from a game (models, animations, parameters, sounds, scripts
decompiled from the game's modules) stays on your PC and is never published. Details, addresses and every proof
line: `plan\phases\N4_own_fighter.md` (and `N2_real_slots.md`, `N3_new_kind.md` before it).
All paths are relative to `Documents\SSBU`.

The aim is "one folder per fighter": a fighter ported from another game, or created from nothing, is a folder; the
engine's fixed tables are made larger by us where they stand in the way. What is written here is what WORKS today
and what does not; it is honest about the second part.

## 1. In one paragraph

A new fighter gets a fighter KIND number of its own (the engine has 94 kinds; we made room for 20 more) and a
ROSTER ROW of its own. Everything it does not bring, it takes from a DONOR, an existing fighter named in its
manifest. Today a new kind can fight with: its own kind number, its own kind hash, its own row of fighter
parameters, its own instance of the donor's per-fighter parameter object, its own roster row; and with the donor's
file name, script module, native callbacks, article (projectile) kinds and model. A loose-file layer serves files
from the fighter's folder in place of archive files whose path the archive already knows. NOT yet: files under the
fighter's own name, a script DLL of its own, its own articles, computer-controlled play.

## 2. The folder

```
characters\
  <name>\                         one folder per fighter (or per file mod)
    fighter.json                  the manifest (section 3); not served to the game
    fighter\<name>\model\...      \
    fighter\<name>\motion\...      |  the fighter's files, in a tree that MIRRORS THE ARCHIVE'S PATHS
    fighter\<name>\param\...       |  (the game asks for a file by its path; the layer serves the file with the
    effect\fighter\<name>\...      |   same path under this folder)
    sound\bank\fighter\...         |
    ui\replace\chara\...          /
    src\                          the fighter's script source (C++; `docs\MODDING.md` sections 6 and 6a)
```

- The folder that holds the fighters is `characters\` next to `recomp-study\`; `SSBU_CHARACTERS=<folder>` selects
  another one. No folder = the layer installs nothing and the game is exactly as before.
- The layer is a source file of the runtime (`recomp-study\loose_files.c`, started by `loose_host.c`). While it is
  a first stage it is OPT-IN: `SSBU_LOOSE_FILES=1`, in an exe that was linked with it (`python tests\n4_link.py`);
  for any other exe the same code can be loaded as a mod (`mods_n4_src\n4_loose.cpp`).
- A file under `characters\<anything>\<path>` replaces the archive's file `<path>` when the archive has that path.
  This already works for a file mod of an existing fighter (TODAY the only kind of loose file that is served).
- A path the archive does not have (every `fighter\<new name>\...`) is listed in the log as "not in the archive:
  NOT served". Serving those needs new rows in the archive's in-memory tables (section 6).

## 3. The manifest (`fighter.json`) — proposed format, not read by any code yet

Today the same facts are given to the test mods by environment variables. The manifest is what they become.

```json
{
  "name": "myfighter",
  "kind": "auto",
  "donor": "<existing fighter>",
  "uses_from_donor": ["files", "script_module", "callbacks", "parameter_class", "articles", "ai"],
  "roster": { "id": "ui_chara_myfighter", "order": "last", "name_text": "MY FIGHTER", "portrait": "ui/replace/chara/..." },
  "parameter_row": { "copy_of": "<donor>", "set": { "<field name>": 1.0 } },
  "articles": [
    { "article": 0, "weapon_kind": "<donor's weapon kind>", "max_alive": 4, "function": "donor" }
  ],
  "scripts": "src"
}
```

| Field | Meaning | State |
|---|---|---|
| `name` | lower-case name; the kind hash is the hash of `fighter_kind_<name>`, files are `fighter/<name>/...` | kind hash: works. File name: NOT yet (the engine waits for a script module and files of that name) |
| `kind` | the kind number (the first free one) | works: 20 free numbers |
| `donor` | the fighter that supplies what is listed in `uses_from_donor` | works for every item listed (one donor tried) |
| `roster` | the row of the character database: id, position, name text, portrait | row and position: work (in memory). Own name text / portrait: not done |
| `parameter_row` | the fighter's row of the general fighter parameters: a copy of a row with changed fields | works for the two per-fighter tables (in memory; a changed jump height changes the new fighter's jump and nobody else's; fields are found by value today, not by name). A third table is a fighter x fighter matrix: there the new fighter still uses the donor's row and column |
| `articles` | the article list: per article number the weapon kind, how many may be alive, the native function | donor's list: works, and the articles belong to the NEW fighter (section 4). Own weapon kinds: not done |
| `scripts` | the fighter's own moves as source | NOT done for a fighter without an original module (section 6) |

## 4. How the engine is extended (what "the table becomes ours" means here)

Three mechanisms, in order of preference:

1. **Data rows written in memory** — where the engine already has room: the name rows and the kind-hash row of
   a new kind number; rows appended to the character database; rows appended to the fighter-parameter tables
   (a larger buffer from the game's own allocator).
2. **The hook table** (`docs\MODDING.md` section 4): a function of the game is replaced by ours, by address. Used
   for every "kind -> something" lookup that is a `switch` over the 94 kinds: hash -> kind, the description
   record, the callbacks object, the script-agent dispatchers, the parameter-object builders, the parameter
   loader, the weapon set-up. A replacement sees the whole register context of the calling game code, so a
   replaced CALLEE can act for one particular CALL SITE (it knows its return address and the caller's registers):
   this is how the loose-file layer learns which file is being decompressed without a hook in the middle of a
   function.
3. **The patch list** (`recomp-study\patches\kinds.txt`, applied when the game code is recompiled;
   `recomp_partial.py` rebuilds only the affected files, 1.5-3 minutes): for limits that are constants inside
   many functions (the bound "kind < 94" at 66 places, the offset of an array inside an object at 76 places, object
   sizes). It changes constants; it cannot add code. The patched game is a separate DLL; the unpatched one stays the
   default until the patch list is accepted.

Rules that came out of the experiments:

- **A donor is a dependency.** A fighter's native code (its callbacks) reads its OWN kind's parameter objects by a
  fixed position. A new kind that uses a donor's callbacks therefore needs the donor's objects loaded too, counted
  as a user, exactly as the game does for a second fighter of the same kind.
- **An article belongs to its live owner, not to a table.** The engine looks up the owner kind of a weapon kind in
  a static table (so a donor's projectile would always take the DONOR's parameters and script module). Our weapon
  set-up runs with the kind of the fighter that is actually creating the article.
- **A copy served from the folder must change nothing.** The regression test for all of this is the deterministic
  mode: the per-frame fight hash of a run with the layer serving an identical copy equals the run without it.

## 5. What a fighter needs, piece by piece

| Piece | What it is | Own today | From the donor today |
|---|---|---|---|
| kind number | index into every per-fighter table | yes | - |
| kind hash, upper-case and sound name | names by which data files and code refer to the kind | yes | - |
| file name | the `<name>` in every path and in the script module's name | no | yes |
| fighter parameter row | weight, speeds, jump heights ... (one row per fighter in a shared table) | yes (copy + edits) | - |
| per-fighter parameter file | the fighter's own values for its moves | own INSTANCE, donor's file and layout | yes |
| description record | number of statuses, article list | no | yes |
| callbacks object | the fighter's native behaviour (5 to 43 small functions per fighter) | no | yes (the base object also exists) |
| articles / projectiles | weapon kinds, their parameters and scripts | owned by the new fighter | weapon kinds, scripts |
| scripts (moves, statuses) | C++ source per fighter (`docs\MODDING.md`) | no | yes (the donor's module and DLL) |
| model, animations, effects, sounds | files | no | yes |
| roster row | the entry on the select screen | yes | text and portrait |
| computer player | per-fighter tables of the AI | no | no (it stands still) |

## 6. Not supported yet (each was tried or read; details in the phase file)

- Files under the fighter's own name: the archive's in-memory tables need new rows (file paths, the hash -> index
  table, file infos, directory lists) so that the game can ask for paths the archive never had.
- A script DLL without an original module: needs the agent factories (the objects the game asks a script module
  for) and the script registration as source, and a loader entry for a DLL that is not attached to a module.
- Own weapon kinds (articles that are not a donor's): four tables indexed by weapon kind that cannot grow in place.
- A parameter file with a layout of its own (a new parameter class).
- Computer-controlled play (the new fighter stands still); a match that has both Kirby and a new fighter (the
  game stops while loading); the announcer for the new name: see the list in the phase file.
- The select screen: up to 91 entries the game's own layout data places the icons (91 = 7 rows of 13); with 92
  the game stops itself. The list the select screen shows is the same list the game counts for its "fighters
  unlocked" rewards, so a new fighter that is simply "available" triggers those rewards: the roster needs an
  answer of its own for the reward count.
- The manifest is a proposal: nothing reads `fighter.json` yet.

## 7. Trying it (test set-up of session N4; all of it is test code, not the final form)

```
cd recomp-study
python fighter_sdk\tools\build_mod.py mods_n4_src\n4_kind.cpp   mods_n4
python fighter_sdk\tools\build_mod.py mods_n4_src\n4_roster.cpp mods_n4
python fighter_sdk\tools\build_mod.py mods_n4_src\n4_loose.cpp  mods_n4l     (the loose-file layer as a mod)
python tests\n4_run.py <tag> N3_ROWS=1 N3_NEWKIND=<name> "SSBU_DEBUG_MATCH=p1=n3t0,p2=<fighter>,p2=cpu,stage=end"
```

`tests\n4_run.py` always runs the debug fast mode, deterministic, with a fresh copy of the save that it deletes
afterwards, on the patched game DLL (`ssbu_n4k.exe`). The log (`tests\logs\n4_<tag>.log`) carries a line for every
table row written, every hook that answered for the new kind, and every loose file served with its size.
