> **Paths.** This guide was written for the tools' own single-folder layout (`recomp-study\`, `fighter_sdk\`, `tests\`, `mods_n*_src\`, `characters\`, `ssbu_*.exe`). `python scripts/setup.py` (step `stage`) builds that layout in `build/work/`: read `recomp-study\` as `build/work/`, run the commands from there. In the repository the runtime sources are in `runtime/`, the lifter in `tools/lifter/`, the test mods in `mods/`. Mentions of `plan\...` files refer to the author's private notes, which are not published.

# A new fighter in the native port: what it consists of today

State: 2026-10-13, sixth version (session N9). This describes OUR runtime and tools; it contains nothing of the
game. Everything a fighter is made of that comes from a game (models, animations, parameters, sounds, scripts
decompiled from the game's modules) stays on your PC and is never published. Details, addresses and every proof
line: `plan\phases\N9_checklist.md` (the current checklist, section 12 there), `N8_first_frame.md`,
`N7_own_files2.md`, `N6_own_files.md`, `N5_own_module.md` (and `N2_real_slots.md`, `N3_new_kind.md`,
`N4_own_fighter.md` before them).

**What session N10 changed, in short** (section 14.2, last paragraph; `plan\phases\N10_custom_model.md`): the
question "does a CUSTOM MODEL work?" - **YES, shown once**: a new fighter whose body-model folder holds another
fighter's complete model (other mesh, materials, skeleton, textures with other names) loads, is drawn and fights.
The earlier attempt stalled because the engine reads a group's bytes with a running position; the replacement is a
"virtual record" for files the donor never had and for own copies of the skeleton and other shared files. Its
animations, parameters, moves, sounds, portrait and name are still copies of the donor's until the folder brings
others. Also new, NOT yet run: a guard that keeps the select screen from getting more than 91 entries. A launcher
for playing a new fighter exists (`recomp-study\gioca_personaggio_nuovo.bat`; see N10 section 5 for its state).

**What session N9 changed, in short** (sections 13 and 14): **one command starts a new fighter** -
`python fighter_sdk\tools\new_fighter.py <name> --donor <fighter>` makes the folder with the manifest, the donor's
files under the new name, the script sources with the new name and a one-command build; a fighter made that way
from a third donor plays bit-for-bit like its donor, and an edit in its source or its folder shows. Article files
are asked for under the fighter's own name. The donor's native callbacks are wrapped for any donor. Pictures and
name text of the roster row have inputs (section 14.4). NOT working: files the donor never had (section 14.2: the
"template" of session N8 stalls the load and is switched off); more than 91 select-screen entries (nothing built:
a fourth new fighter on a full roster cannot exist yet).

**What session N8 changed, in short** (section 12 has the detail; section 11 is "Porting a fighter from another
game" with the exact inputs): **a new fighter now FIGHTS on its own files.** The crash that stopped session N7 was a
missing path: files a costume group shares with other groups (the skeleton, shared textures) had no path under the
fighter's name, and the engine looks the files named inside a model file up by "<folder>/<name>". They now get an
alias path. A copy of a fighter that is loaded from its own folder through its own load group plays bit-for-bit like
its donor in the deterministic test, and a file replaced in the folder shows in the match. The load groups are the
default again for fighter folders (`SSBU_LOOSE_STAGE2=0` switches them off). Still open: a file the archive stores
uncompressed keeps the donor's bytes unless `SSBU_LOOSE_RAW=1` is set (one group file of the test folder: the sound
sequence file); shared files are the donor's unless the (built, unproven) template mechanism is used; sounds, article paths, own factories in a fight, the general callbacks wrap, lifecycle: built or prepared,
not run.

**What session N7 changed, in short** (section 10 has the detail; section 11 is "Porting a fighter from another
game"): a fighter folder now gets a LOAD GROUP of its own in the archive's tables, so the game's own loader reads
the fighter's costume group under the fighter's name and the files of the folder are what it gets; the "resident
files" shortcut of N6 is gone; the tables are grown the moment the game publishes them; the donor's native
callbacks are wrapped as a whole instead of one function; a fighter's own agent factories are called under its own
names. At the end of N7 none of this had reached the first frame of a match (a crash after the load, section 10.1)
and the load groups were opt-in; session N8 found the cause (section 12.1) and they are the default again.

**What session N6 changed, in short** (section 9 has the detail): the fighter's files now get ROWS OF THEIR OWN in
the archive's in-memory tables and the engine's lookups find them under the fighter's own name — built, but not
yet shown in a running match; a fighter's DLL can carry its status functions and its agent factories as source;
the donor is a working manifest field (a second donor was tried); what more than 91 select-screen entries need is
known.
All paths are relative to `Documents\SSBU`.

The aim is "one folder per fighter": a fighter ported from another game, or created from nothing, is a folder; the
engine's fixed tables are made larger by us where they stand in the way. What is written here is what WORKS today
and what does not; it is honest about the second part.

## 1. In one paragraph

A new fighter is a folder with a manifest. At start the runtime reads every manifest under the characters folder
and gives each fighter a fighter KIND number of its own (the engine has 94 kinds; we made room for 20 more), a
ROSTER ROW of its own, its own name in the engine's name tables, and a SCRIPT MODULE of its own that exists only as
our DLL: when the engine asks for the script module of the new name, our loader answers, with no module file of
the game behind that name. Everything the fighter does not bring it takes from a DONOR, an existing fighter named
in the manifest. Two test fighters that are copies of one donor, each with one edited move, fight each other, the
donor and a computer player; the unedited copy plays bit-for-bit like its donor in the deterministic test. Its two per-fighter PARAMETER FILES are read from its own folder. NOT yet: its
other files under its own name (they are asked for under the new name and answered with the donor's), articles
of its own, a fighter that is not a copy.

## 2. The folder

```
characters\
  <name>\                         one folder per fighter (or per file mod)
    fighter.json                  the manifest (section 3)
    <name>.dll                    the fighter's script DLL (built from its source, section 7)
    fighter\<name>\model\...      \
    fighter\<name>\motion\...      |  the fighter's files, in a tree that MIRRORS THE ARCHIVE'S PATHS
    fighter\<name>\param\...       |  (the game asks for a file by its path)
    effect\fighter\<name>\...      |
    sound\bank\fighter\...        /
    clone_files.json              written by the clone tool: every cloned file with its old and new path hash
```

- `SSBU_CHARACTERS=<folder>` switches the registry on (default: off; nothing of it runs and no hook is installed
  without the variable). The test exe is linked by `python tests\n5_link.py`.
- A folder WITHOUT a manifest is a plain file mod: with `SSBU_LOOSE_FILES=1` a file under
  `characters\<anything>\<path>` replaces the archive's file `<path>` when the archive has that path (stage 1 of the
  loose-file layer, session N4).
- A path with the new fighter's name is answered in one of two ways (section 10): with `SSBU_LOOSE_STAGE2=1` by a
  ROW OF THE FIGHTER'S OWN when the path belongs to its load group (the log says `OWN FILE`, `OWN FOLDER` or `OWN LOAD GROUP`), else by the
  DONOR'S path (`DONOR FALLBACK`, one log line per path). Independently of that:
- **`fighter\<name>\param\vl.prc` and `expression_vl.prc` in the fighter's folder ARE the fighter's own.** The
  engine parses these two files into a parameter object per kind. While the object of a new kind is being built,
  the engine's buffer of the donor's file points to our copy of the fighter's file, and to the archive's bytes
  again afterwards: the new fighter gets its own values, a real donor fighter in the same match keeps his.

## 3. The manifest (`fighter.json`)

Read at start by the registry (`recomp-study\fighter_sdk\newmodule_host.c`). Fields in use today: `name`, `donor`,
`dll`, `kind`, `own_name`. The others are accepted and not acted on yet.

```json
{
  "name": "myfighter",
  "kind": "auto",
  "donor": "<existing fighter>",
  "dll": "myfighter.dll",
  "own_name": true,
  "roster": { "id": "ui_chara_myfighter", "order": "last" },
  "parameter_row": { "copy_of": "<donor>" },
  "articles": "donor"
}
```

| Field | Meaning | State |
|---|---|---|
| `name` | lower-case name: the kind hash is the hash of `fighter_kind_<name>`, the script module is `lua2cpp_<name>`, the roster id `ui_chara_<name>`, files are asked for as `fighter/<name>/...` | works (files: answered with the donor's) |
| `kind` | the kind number; `"auto"` = the first free numbers in name order | works: 20 free numbers; 2 used at once in the tests |
| `donor` | the fighter that supplies what the folder does not bring | works for ONE donor (the test donor); another donor needs that fighter's rows in the kind component |
| `dll` | the fighter's script DLL in its folder; staged by the registry at start | works |
| `own_name` | `false` keeps the donor's name in the engine's name row (then no own module and no own paths) | works |
| `roster` | the row of the character database | row and position: work (in memory). Own name text / portrait: not done |
| `parameter_row` | the fighter's row of the general fighter parameters | a copy of the donor's row: works; **`"set": {"<name>": <number>, ...}`: works since N12** (names in the row table, section 16.1) |
| `articles` | the article list | the donor's list: works, and the articles and their scripts belong to the NEW fighter. `[{"name", "template", "max"}]`: own description record and generate ids written (N12, section 16.4); own weapon kinds in the engine: not done |

## 4. How the engine is extended (what "the table becomes ours" means here)

Mechanisms, in order of preference:

1. **Data rows written in memory** where the engine already has room: name rows, the kind-hash row, rows appended
   to the character database and to the fighter-parameter tables.
2. **The hook table** (`docs\MODDING.md` section 4): a function of the game is replaced by ours, by address. Used
   for every "kind -> something" lookup that is a `switch` over the 94 kinds. A replacement sees the whole register
   context of the calling game code, so a replaced CALLEE can act for one particular CALL SITE (it knows its return
   address and the caller's registers). This is how the loose-file layer learns which file is being decompressed,
   and how the registry answers the script-module request: the engine's module loader is a worker loop that cannot
   be replaced as a whole, but the string formatter it calls to build the module's file name can, and at that one
   return address the formatter's replacement has the request object in a register.
3. **The patch list** (`recomp-study\patches\kinds.txt`, applied when the game code is recompiled): for limits that
   are constants inside many functions. It changes constants; it cannot add code. Not changed in session N5.
4. **A module object of our own** (new in N5). The script-module loader keeps one record per module of the game.
   A new fighter's module is one more such record, with an address range of its own behind the game's modules.
   The range is reserved and never filled: its addresses are NAMES of functions. An address in it is answered by
   the function of the fighter's DLL bound at that offset, else by the donor module's function at the same offset.

Rules that came out of the experiments:

- **A donor is a dependency.** Its parameter objects (N4) and its script module image (N5: the class tables and
  constants the donor's factories use are data of that image) must be loaded when a fighter built on it is in a
  match. The registry turns the new fighter's module request into a request for the donor's image when that image
  is not loaded, and answers "loaded" when it is.
- **An agent belongs to the fighter it was made for.** The engine asks a script module for agents (one per script
  category, per fighter and per article). A donor's factory makes them with the donor's class table and registers
  the donor's function addresses. The registry moves each agent made for a new fighter into the new fighter's
  module: the class table is replaced by a copy whose donor-module entries are the new module's addresses, and the
  two registration functions of the engine register the new module's address when the agent is a new fighter's.
- **An article belongs to its live owner, not to a table** (N4), and N5 found the second half: the engine also
  builds the article's AGENT NAME from that table ("<owner's name>_<article>"). With the live owner in the table
  no factory knew the name and the article got no scripts at all: it spawned, flew, and never hit. During the
  agent factories the row is the static owner again; the agents are then moved to the live owner's module.
- **The computer player reads the kind from its own objects.** The AI's per-kind switches take the kind from a
  field of the AI objects. For a new fighter the field is given the donor's kind, so the AI uses the donor's rows.
  This also matters for the OPPONENT: a computer player that faces a new kind decides differently (fewer random
  calls) until the field says the donor's kind.
- **A copy must change nothing.** The regression test is the deterministic mode: the per-frame fight hash of an
  unedited copy of a fighter under a new name equals the donor's, line for line, random-number state included.

## 5. What a fighter needs, piece by piece

| Piece | What it is | Own today | From the donor today |
|---|---|---|---|
| kind number | index into every per-fighter table | yes | - |
| kind hash, name, upper-case and sound name | names by which data files and code refer to the kind | yes | - |
| script module | the object the engine asks for agents | yes: a module that exists only as our DLL | the factories (they are functions of the donor's module), the data of the donor's image |
| scripts (moves) | C++ source per fighter (`docs\MODDING.md`) | yes: every function the DLL has is the fighter's own; an edited move shows for this fighter only | every function the DLL does not have (fallback per function, by offset) |
| status scripts | the fighter's state machine functions | possible (the DLL can be built with them); not exercised in N5 | yes in the tests (the test DLLs carry the move scripts only) |
| articles / projectiles | weapon kinds, their parameters and scripts | owner, parameters, agents and scripts are the new fighter's | the weapon KINDS |
| files (model, animations, effects, sounds) | files | no: asked for under the new name, answered with the donor's | yes |
| fighter parameter row | weight, speeds, jump heights ... | yes (copy + edits) | - |
| per-fighter parameter files | the fighter's own values for its moves | yes: own instance, built from the files in its folder | the layout (the donor's parameter class) |
| description record, callbacks object | number of statuses, article list, native behaviour | no | yes |
| roster row | the entry on the select screen | yes | text and portrait |
| computer player | per-fighter tables of the AI | no | yes (it plays as the donor's computer player) |
| copy ability (the fighter that copies others) | a per-kind table of resource names | no | see the phase file |

## 6. Not supported yet

- **Files under the fighter's own name: built in session N6 as table rows, not yet shown in a match (section
  9.1).** The archive's lookup has TWO steps for a path string (a search table
  that knows folders and file names, then the file table), and both need rows for a new path, plus rows in the
  "loaded" tables that are sized when the archive is opened. What existed before: the list of every path the
  engine asks for with the new name (`[registry] path asked` in the log), and `tests\n5_clone_files.py`, which
  turns that list into a folder of the donor's files under the new name and a list of the new path hashes. (The
  archive stores hashes, not names; the new hash of a file whose name is unknown is still computable, because the
  checksum used is linear: checksum(new folder + name) follows from checksum(new folder), checksum(name) and the
  name's length. The tool checks this on every file.)
- **A fighter that is not a copy** (section 8).
- Own weapon kinds (four tables indexed by weapon kind that cannot grow in place); a parameter file with a layout
  of its own; a donor other than the test donor (the kind component has one donor's rows built in).
- A donor whose name is LONGER than the new fighter's name: the path fallback shortens the engine's string in place
  and cannot lengthen it.
- The select screen beyond 91 entries, the reward count that sees new roster rows (session N4), name text and
  portrait of the new row.
- The donor's module stays the donor's for the engine's unload: when the last match ends it is unloaded by the
  request that loaded it, whichever fighter that was.

## 7. Trying it (test set-up of session N5)

```
cd recomp-study
python tests\n5_clone_source.py <donor> <name>                (copies the donor's generated script sources to fighters\work_n5\<name>)
set SSBU_FIGHTERS_ROOT=work_n5& set SSBU_FIGHTER_BIN=fighters_bin_n5e& python fighter_sdk\tools\build_fighter.py <name>
copy fighters_bin_n5e\<name>.dll ..\characters\<name>\<name>.dll      (next to its fighter.json)
python fighter_sdk\tools\build_mod.py mods_n5_src\n5_kind.cpp   registry_bin      (the registry's components)
python fighter_sdk\tools\build_mod.py mods_n5_src\n5_roster.cpp registry_bin
python tests\n5_link.py                                        (ssbu_n5.exe)
python tests\n5_run.py <tag> "SSBU_CHARACTERS=..\characters" "SSBU_DEBUG_MATCH=p1=<name>,p2=<fighter>,p2=cpu,stage=end"
python tests\n5_clone_files.py tests\logs\n5_<tag>.log <name>  (the donor's files under the new name; local only)
```

`tests\n5_run.py` always runs the debug fast mode, deterministic, with a fresh copy of the save that it deletes
afterwards, on the patched game DLL. The log carries a line for every manifest read, every module request
answered, every agent moved into a new module, every path asked with a new name and what answered it.

## 8. A fighter that is NOT a copy: what it must bring, and what still falls back to the donor

| Piece | What a ported fighter brings | What falls back to the donor today |
|---|---|---|
| Agent factories | its own factories: construct the engine's base agent class, give it a class table whose install entry is the fighter's own, and compare the fighter's own agent names | all of them: the factories are the donor's, so the agent names, the number of agents and the article list are the donor's |
| Script registration | its own table "motion name -> function" for each script category; "status kind -> functions" in its install function | the donor's registrations, moved to the new module's addresses: a script of a motion the donor does not have is never asked for |
| Functions | every function, as source in its DLL, at offsets of its own choosing (the range is ours) | by offset in the donor's module: this only makes sense for a copy |
| Data of the module image | none (constants live in the source) | the donor's image must be loaded |
| Status kinds, work variables | its own count and ids (`FS_NEW_WORK_VAR`, session S11; the storage is not enlarged) | the donor's counts |
| Articles | its own weapon kinds, with parameters and agents | the donor's weapon kinds |
| Files | model, skeleton, animations with the motion list, effects, sounds, parameter files, under its own name | everything (section 6) |
| Parameter class, description record, callbacks | its own native object, or the base object | the donor's |
| Computer player | its own AI rows, or none | the donor's |

Order of work that follows from this: (1) the file rows, so that the folder is read; (2) factories and registration
as source, so that the donor's image is no longer needed; (3) own weapon kinds; (4) own parameter class.

## 9. Session N6: own files, the names inside, another donor, more icons

### 9.1 Files under the fighter's own name (the loose-file layer, stage 2)

With `SSBU_CHARACTERS` set the loose-file layer is on (`SSBU_LOOSE_FILES=0` switches it off). For every file under
`characters\<name>\<archive path>` whose path the archive does not have, in a folder with a manifest, the layer adds
rows to the archive's tables in memory, once, when the tables are first seen:

- **The mechanism is "grow by copy":** each table is copied into a larger block of ours, the new rows are appended,
  then the pointer and the count in the engine's own objects are switched; the two sorted lookups are switched
  last, so a new row becomes reachable only when everything behind it is in place. The old blocks are never freed.
- **Which tables:** the file-path rows, the rows that lead from a path to its file record, the file records, the
  sorted "hash -> path" lookup with its buckets, the two "loaded" tables that have one row per path and per file
  record, and the engine's second set of tables that knows FOLDERS and file names (one entry per new file, one per
  folder the archive does not have, each linked into its parent's list of children, plus the two sorted indexes).
- **A new file shares its donor file's location rows** (where the bytes are in the archive): only the identity of
  the file is new. Which archive file is the donor of a new path: the list the clone tool writes
  (`clone_files.json`: needed where a file's name is only known as a hash), else the same path with the fighter's
  name replaced by the donor's.
- **A live switch needs care:** a thread of the engine that took a pointer into an old "loaded" table just before
  the switch still writes there. A short-lived thread of ours carries such late writes over into the new table.
- **What we learned the hard way:** a file row alone is never READ. The engine counts a user for the file and
  waits; a fighter's files arrive with its LOAD GROUP, which is a row of a third kind (a directory row with its own
  list of file records). Two answers: (a) directory rows for the new fighter's groups (not built); (b) *resident
  files* (built): the layer reads the new files from the folder itself when it grows the tables and writes their
  "loaded" rows in the state the engine gives a file whose data is supplied from outside, with one user of ours so
  that the engine never frees a buffer that is not from its heap.
- **State:** the tables grow, the self-check finds every new path through the engine's two lookups, the engine's
  requests under the new name are answered by our rows (the log says `OWN FILE` / `OWN FOLDER`; a path without a
  row says `DONOR FALLBACK`, which is the fallback the manifest promises). **It does not work end to end yet:**
  without resident files the match load waits for ever; with them (as first written) the game does not leave the
  title screen. So "replace one file and see the effect" is not shown. Until this is solved, run a fighter folder
  that has new-path files with `SSBU_LOOSE_STAGE2=0`.

Switches: `SSBU_LOOSE_STAGE2=0` (no rows: every new-name path falls back to the donor, as in N5),
`SSBU_LOOSE_RESIDENT=0` (rows without loading the files).
Keep in mind: a file in a fighter's folder under a path the archive DOES know replaces that file for everybody.

### 9.2 Status functions and agent factories as source

- A fighter's DLL can be built with its status functions (`SSBU_FIGHTER_STATUS=1`, the status work's SDK folder in
  `SSBU_FIGHTER_SDK`). A copy with them plays bit-for-bit like its donor; an edit in a status function shows for
  the new fighter only. A status function's address handed to the engine is then the new module's.
- The agent factories (compare the agent's name, allocate, construct the base class, set the class table, register
  the scripts) can be generated as source that compares the NEW names and builds its class tables itself
  (`tests\n6_s_factories.py`). Nine of eleven are written; the two of the computer player are not. A real fighter
  whose agents are made by such source factories plays identically. The runtime does not call a new fighter's
  factories with the new names yet: that is the next change (phase file, section 3.2).
- `tests\n6_s_census.py` counts what a module still needs from its donor's image; for the test fighter: 263
  functions (the computer player's part is the largest block) and two class tables.

### 9.3 A donor other than the first test donor

`donor` works per fighter in the new kind component (`mods_n6_src\n6_kind.cpp`, used with
`SSBU_MODS=registry_bin_n6`): the donor's kind is found by its name. A clone of a second donor (a fighter with three
articles) loads, fights, equals its donor in the deterministic test, and its articles hit.
New rule from it: **a donor's native code can compare the fighter's kind.** A callback shared by several kinds
skipped a set-up for the unknown kind and the next one crashed. The component gives that one function the donor's
kind for the call; the general form (every native callback of the donor) is not built, so a new donor may need
such a line.

### 9.4 More than 91 entries on the select screen

Studied, not built. Needed: more rows in the two lists of the layout parameter file (the count is data), more panes
in the layout file (it has exactly 91 of each of the two kinds; names are searched by text, so copies with new
numbers are enough), and three loop bounds in the grid function through the patch list. The grid has at most 13
rows (a fixed array); 104 entries fit that. No run-time pane cloning is needed.

## 10. Session N7: the fighter's load group, early growth, the donor's callbacks as a whole

### 10.1 How the engine reads a fighter's files, and what the runtime adds for a fighter folder

The engine does not read a fighter's files one by one. It asks for a LOAD GROUP: a directory row of the archive
(the costume group of the fighter). Such a row names (a) one compressed stretch of the archive and (b) a range of
file records. Setting the group up counts one user for every file of the range; the engine's load thread then reads
the stretch and unpacks each file of the range into that file's own buffer. A file record that stands alone is
never read (this is what stopped session N6).

For every fighter folder that has a manifest and at least one file, the loose-file layer therefore adds, in memory:

- **one directory row**: a copy of the donor's costume-group row under the new fighter's path, pointing at the SAME
  stretch of the archive and at a NEW range of file records in the donor's order;
- **for every file of the group that is the group's own** (most of them): a new file with the fighter's name in its
  path - new path row, new record, new "loaded" rows, entries in the folder / file-name tables - which shares only
  the donor file's LOCATION in the archive. The engine unpacks the donor's bytes into the NEW file's buffer; when
  the folder brings that file, the layer then replaces the buffer's content with the folder's file. A file the
  folder does not bring keeps the donor's bytes, but under the fighter's own name and in its own buffer (this is the
  donor fallback for content, counted in the log);
- the new path of a file whose name is not known as text is computed from the donor's path hash (the checksum is
  linear, so "the same path with another beginning" needs no name);
- **records of the range that belong to other groups too** (files shared between costumes or fighters) are copied
  as they are: those files stay the donor's.

What still goes to the donor, each with a log line: the sound banks, the movie group, every costume other than the
first, and the article files asked under the donor's name. The two parameter files are also the fighter's own
through the older mechanism of section 2.

The tables are grown ONCE, and since N7 at the moment the game has published them, before it has requested its
first file (a thread of ours polls for them from process start). Growing them later, while files are in flight,
left some game object with a pointer into an old table now and then, and the game then waited for ever in its
opening. The log line `growth triggered by ...; rows in use ...` says which case a run was.

**State (end of N7), honestly:** the engine asks for the new fighter's group under its own name, finds our row,
its own load thread reads the group, and the folder's files are what lands in the buffers (332 files of the test
fighter's folder, in 7 groups); the load then runs on through parameters, script agents and the fighter's
set-up - and stops with a crash right after the engine takes the fighter's own model file, BEFORE the first frame of
the match. So "a fighter that fights on its own files" is NOT shown yet, and no file swap has been seen on screen.
Until it is, the groups are OPT-IN: `SSBU_LOOSE_STAGE2=1`. Without it every path with the new name falls back to
the donor's, as before, and the fighter fights.

Three more things the experiments taught:
- **The donor's group is a dependency too.** The engine builds the paths of a fighter's ARTICLE models from the
  donor's article list, with the donor's name. A new group therefore has the donor's group as a child: the engine
  loads both, and the donor's files answer what is still asked under the donor's name.
- **Only compressed files are replaced.** The layer swaps a file's content at the engine's decompress step. A file
  the archive stores uncompressed never passes that step and keeps the donor's bytes even when the folder brings it.
- **The common tree is cloned with the group** (`SSBU_LOOSE_TREE`): the per-fighter parameter files, the effect
  file and the computer player's parameters then have rows under the fighter's name as well; link rows of the
  donor that lead into its own tree get link rows of ours.

Switches: `SSBU_LOOSE_STAGE2=1` (ON: rows and groups; default off), `SSBU_LOOSE_GROUPS=0` (no
directory rows), `SSBU_LOOSE_TREE=0` (the costume group only), `SSBU_LOOSE_DONOR_DEP=0`, `SSBU_LOOSE_STANDALONE=1` (also give rows to folder files that are in no group; such a row is only
read when the engine requests the file singly), `SSBU_LOOSE_EARLY=0` (grow at the first unpacked file, as N6 did),
`SSBU_LOOSE_VERBOSE=1` (one log line per served file).

### 10.2 The donor's native callbacks

A donor's callbacks object is native code of the engine and may compare the fighter's kind with the donor's own
number. The kind component (`mods_n7_src\n7_kind.cpp`, used with `SSBU_MODS=registry_bin_n7`) now wraps EVERY
function of the donor's callbacks class table when a new kind asks for the object: while such a function runs for a
fighter of a new kind (the fighter object or its module accessor is one of the first four arguments), the
fighter's kind field holds the donor's number, and the new number again afterwards. A real donor fighter is not
touched. **Not proven yet, and the rule that recognises "this call is for a new kind's fighter" is not right yet**
(phase file, section 5): a donor whose callbacks compare the kind still needs the one-function line of section 9.3.
Limits by design:

### 10.3 The fighter's own agent factories at run time

The engine's script dispatchers pass the agent's name as a hash and jump to the donor module's factory. The runtime
now hooks a donor module's factories: while an agent is being made for a new fighter, the hash becomes the one of
the NEW name ("<donor>_<article>" -> "<name>_<article>", computed without the text) and the fighter's own DLL
makes the agent when it has that factory (section 9.2); otherwise the donor's factory makes it as before. Seen in
the log (most agents of the test fighter made by its own factories under its own names); not yet seen in a fight.
`SSBU_REG_FACTORY=0` switches it off.

Limits of the callbacks wrap: code that runs inside a wrapped callback also sees the donor's number; a native function reached
some other way (an article's own functions) is not covered by this wrap - articles get the donor's row lent as
before.

## 11. Porting a fighter from another game: the exact inputs (session N8)

"Port" here means: the fighter's content comes from somewhere else, and the engine runs it in a real slot. This
section says, piece by piece, WHAT A PORTER PUTS WHERE. "Convert" always means a tool on your PC that reads the other
game's file and writes the engine's format: no such converter is part of this project, the formats named are the
engine's own. `<name>` is the manifest's `name` (lower case), `<Name>` the same with a capital first letter,
`<donor>` the manifest's `donor`. Everything below `characters\<name>\` mirrors the archive's paths.

### 11.1 The manifest: `characters\<name>\fighter.json`

| Field | Must be | Read today |
|---|---|---|
| `name` | lower-case letters / digits. A path that has a row of its own has no length rule; the string fallback for a path WITHOUT a row needs the donor's name to be no longer than `name` | yes |
| `donor` | an existing fighter's name; it supplies every piece the folder does not bring and its files / script image are loaded with the fighter | yes |
| `dll` | file name of the script DLL in the folder | yes |
| `kind` | `"auto"` | yes (20 free numbers) |
| `own_name` | `true` | yes |
| `roster`, `parameter_row`, `articles` | as in section 3 | accepted, not acted on |

### 11.2 Files: names and formats under `characters\<name>\`

| Piece | Files (the engine's own formats) | Folder | Can it DIFFER from the donor today? |
|---|---|---|---|
| Body model | `model.numdlb` (the model description: it NAMES the mesh, skeleton and material files, and the engine looks those names up in the same folder), `model.numshb` (meshes), `model.numshexb`, `model.nusktb` (skeleton), `model.numatb` (materials), `model.nuhlpb` (helper bones), `model.nusrcmdlb`, `model.xmb`, one `<texture name>.nutexb` per texture the materials name | `fighter\<name>\model\body\c00\` | SHOWN for a file with the same name as one of the donor's OWN files of the group (three textures of another costume: the picture of session N8; a larger file works too). NOT YET for (a) the files the donor's group shares with other groups - the skeleton `model.nusktb`, `model.xmb`, the textures all costumes have in common: today they are aliases of the donor's files - and (b) files the donor does not have (other texture names): both go through the template of section 12.3, which is built and has not run. Limit there: the folder's file must not be smaller than the group's smallest file |
| Article models | the same file set per article | `fighter\<name>\model\<article>\c00\` | the files have paths under the fighter's name (own files of the group as copies, shared ones as aliases), but the engine still ASKS for them under the donor's name; the rewrite of that request is built, not run (section 12.4). The article KINDS are the donor's |
| Animations | one `<motion file>.nuanmb` per motion, `motion_list.bin` (motion name -> file, flags, script names), `update.prc` | `fighter\<name>\motion\body\c00\` | YES for a motion file the donor also has (shown: one replaced, longer animation is read back in the match, section 12.2). A motion the donor does not have: its file needs the template (12.3, built, not run), the motion list is the fighter's own file, and its SCRIPT needs the fighter's own factories (11.3) |
| Per-fighter parameters | `vl.prc`, `expression_vl.prc`, with the DONOR's layout | `fighter\<name>\param\` | values: YES; a parameter the donor's layout does not have: NO |
| Effects | `ef_<name>.eff` (one container of emitters, models and textures) | `effect\fighter\<name>\` | loaded under the fighter's name with its group; content swap not exercised |
| Sounds | `se_<name>_c00.nus3bank` / `.nus3audio` / `.tonelabel` (effects), `vc_<name>_c00.*`, `vc_<name>_cheer_c00.*` (voice), `<Name>.sqb` (the sequence file that maps sound names) | `sound\bank\fighter\`, `sound\bank\fighter_voice\`, `sound\sequence\fighter\` | the sequence file: with `SSBU_LOOSE_RAW=1` (it is stored uncompressed; without the switch it keeps the donor's bytes); a DIFFERENT sequence file was not tried. The nine bank files come from the donor (section 12.5) |
| AI parameters | the two files of `fighter\<name>\ai\` | `fighter\<name>\ai\` | loaded under the fighter's name; the AI CODE is the donor's |
| `clone_files.json` | written by `tests\n5_clone_files.py` / `tests\n7_model_swap.py`: for a file whose NAME is only known as a hash (`0x<hash>.<ext>` on disk) the donor file's path hash and the new path hash | `characters\<name>\` | needed only for files stored under a hash name; a file with a real name needs no entry |

A file is given as it is AFTER conversion to the engine's format: the runtime does not parse or convert anything, it
puts the folder's bytes where the engine expects the file's bytes.

### 11.3 Code: the script DLL built with the fighter SDK

| Piece | Input | Built by | Own today? |
|---|---|---|---|
| Move scripts (hitboxes, effects, sounds per frame) | one C++ function per motion and script category (`docs\MODDING.md`) | `fighter_sdk\tools\build_fighter.py <name>` -> `<name>.dll` | YES |
| Status functions (the state machine) | C++ source, built with `SSBU_FIGHTER_STATUS=1` | the same | YES for the donor's status kinds; a status kind the donor does not have: NO (the description record is the donor's) |
| Agent factories and script registration | generated C++ (`tests\n6_s_factories.py`): compares the fighter's OWN agent names, registers its own "motion -> function" table | the same | called at run time under the fighter's own names (section 12.6); the two factories of the computer player are not generated |
| Native callbacks (per-kind engine code) | none: the donor's native object is used, and it is shown the DONOR's kind number (section 12.7) | - | NO |
| Weapon (article) kinds | - | - | NO: the donor's kinds |

### 11.4 What a porter cannot supply yet (no input exists for it)

More than 91 select-screen entries; own weapon kinds; own status kinds; an own description record; own
computer-player code; costumes other than the first; a file that has no same-named file among the donor's own files
of the group (section 14.2). (Name text and pictures have inputs since session N9: section 14.4. The table of 11.2
is brought up to date per piece in section 14.7.)

### 11.5 The table of session N7 (kept for the reasoning behind each piece)

"Convert" as above; the states in this table are those of session N7, section 11.2 has today's.

| Piece | Form it must be brought in | Where it goes in the folder | State of the path |
|---|---|---|---|
| Model (meshes, materials, textures) | the engine's model files: model description, mesh, skeleton, material and texture files of its own formats | `fighter\<name>\model\body\c00\` (and one folder per article model) | the folder's files are loaded under the fighter's name by the engine's own loader (section 10.1; not yet to the first frame of a match). Limits today: only files that have a file of the same name in the donor's folder get a row (a model with other texture names has NO PATH YET), and only files the archive stores compressed are replaced. Nothing converts another game's model format |
| Skeleton | the engine's skeleton file with the bone names the engine's code asks for (the standard fighter bones: hip, waist, head, hands, feet, the "trans" / "rot" root, throw and item bones), plus the helper-bone and physics files if used | same folder | read like the model. A skeleton with other bone names plays no existing animation and breaks code that looks bones up by name: bones must be renamed or added at conversion |
| Animations | one animation file per motion in the engine's format, baked on the skeleton above, AND the motion list (name of each motion, its file, its flags, the script names started with it) | `fighter\<name>\motion\body\c00\` | loaded under the fighter's name like the model (same limits; the "one replaced file" proof is prepared, not run). A motion the donor does not have needs a row in the fighter's own motion list (the list file is one of the folder's files: own) and a script registered for it (next rows) |
| Moves (hitboxes, effects and sounds per frame) | C++ source of the move scripts (`docs\MODDING.md`): one function per motion and category | the fighter's script DLL | works: every function the DLL has is the fighter's own. For a motion name the donor does not have, the fighter's own factories must register it (section 9.2: generated, not yet called at run time) |
| Status logic (the state machine: what follows what, cancels, specials) | C++ source of the status functions, registered per status kind in the fighter's install function | the script DLL | works for a copy with its status sources; a status kind the donor does not have needs the fighter's own status count and description record: NO PATH YET (the record is the donor's) |
| Articles / projectiles | per article: a weapon kind, its model / animation files, parameters, move and status scripts | `fighter\<name>\model\<article>\`, the script DLL | the donor's weapon kinds with the fighter's own scripts and parameters: works. A NEW weapon kind: NO PATH YET (four fixed tables indexed by weapon kind) |
| Parameters | the two per-fighter parameter files with the DONOR's layout; the fighter's row of the general parameter table | `fighter\<name>\param\` | own values: works. A parameter the donor's layout does not have: NO PATH YET (keep such numbers as constants in the script source) |
| Effects | the engine's effect file (a container of emitters and textures) | `effect\fighter\<name>\` | the effect folder has rows under the fighter's name and its group is loaded (section 10.1; no finished match). Nothing converts another game's effects; the practical route is to reuse engine effects by name from the scripts |
| Sounds | the engine's sound bank files (effects, voice) and the sequence file that maps sound names | `sound\bank\fighter\`, `sound\bank\fighter_voice\`, `sound\sequence\fighter\` | NOT read from the folder yet (donor fallback, logged). The audio inside must be in the bank's own codec |
| UI (name, portrait, icon, select-screen entry) | a roster row (made by the runtime), name text, portrait and icon textures in the UI's texture format | - | the roster row works; own text and pictures: NO PATH YET; more than 91 entries on the select screen: studied, not built (section 9.4) |
| Computer player | the AI's per-fighter tables and scripts | - | the donor's; a fighter of its own shape plays as the donor's computer player would: NO PATH to own AI yet |

Order that follows for a real port: (1) model + skeleton + animations with the motion list (the visible fighter),
on a donor whose status logic is closest; (2) move scripts; (3) status functions for what differs; (4) the common
group, sounds and UI once they have rows; (5) own weapon kinds and own description record - the two pieces without
a path today that a fighter with new mechanics cannot do without.

## 12. Session N8: the first match on own files

### 12.1 Files a group shares, and why a new fighter needs paths for them

A costume group's range of file records has two kinds of entries: files that are the group's OWN (stored in the
group's stretch of the archive) and files it SHARES with other groups (the skeleton and the textures that are the
same for every costume, article files, sound banks): for a shared file the record only points at the place where
the one copy lives. The engine does not find the files of a model by walking a folder: the model description file
NAMES its skeleton and mesh files, and the engine looks up "<folder of the model>/<that name>" as a path. So every
file of the group, shared or not, must be a path under the fighter's own name. For a shared file the runtime adds
an ALIAS: a path under the new name that leads to the donor's file (one buffer, the donor's bytes). Without it the
skeleton was "not found", the model was empty and the engine crashed before the first frame (session N7's crash).

### 12.2 What is shown

- A copy of a fighter, loaded from its own folder through its own load group (model description, 325 animations,
  motion list, parameter files, effect file, AI parameters, sound sequence file from the folder; everything the
  folder does not bring from the donor's bytes under the fighter's own name), plays 300 frames with two forced
  specials exactly like its donor: the per-frame hash files are identical.
- "It is that file": see the phase file, section 4 (one animation of the folder replaced by another fighter's -
  the read-back differs for the new fighter; the body textures replaced by the donor's second costume - a picture).

### 12.3 Files the donor never had (built, not run)

A ported fighter brings files that have no counterpart in the donor's group (textures with other names, more
animations). Such a file needs a place in the fighter's group although the archive holds no bytes for it. The
runtime appends a record to the group's range that is loaded from a TEMPLATE - the smallest compressed file of the
donor's group - into a buffer of the folder file's size, with size rows of its own; the folder's file is then written
over it like any other. The same mechanism turns a shared file that the folder brings (an own skeleton) from an
alias into a file of the fighter's own. `SSBU_LOOSE_TEMPLATE=0` switches it off. Test files: `tests\n8_extra.py`.

### 12.4 Article paths (built, not run)

The engine builds the paths of article models with the donor's name. While a new fighter is being set up, the
registry now rewrites such a path to the fighter's own name when the fighter's group has a row for it (registry
function `owner_set`, called by the kind component `registry_bin_n8`). `SSBU_REG_OWNPATH=0` switches it off.

### 12.5 Sounds, uncompressed files

- The nine sound-bank files are asked for one by one, not through the group. With `SSBU_LOOSE_STANDALONE=1` each
  gets a row of its own: the engine then finds them under the fighter's name and the match is unchanged (shown).
  But the BYTES it gets are still the archive's: these files are not read at the step where the runtime swaps
  content, so a different sound bank in the folder would not be heard yet. Without the switch they come from the
  donor's path (one log line each).
- A file the archive stores uncompressed never passes the step where the runtime swaps content: such a folder file
  keeps the donor's bytes. In the test folder that is ONE of the 332 group files (the sound sequence file) and four
  of the nine sound-bank files; every model, animation, parameter and effect file is stored compressed and is
  served. (Earlier text of this file and of the N7 phase file said "62" / "32": a progress line of the log was read
  as a total.) The loader copies such a file instead of unpacking it, at one of three places; with
  `SSBU_LOOSE_RAW=1` the runtime hooks that copy and the folder's file is what the game gets (shown: the test
  fighter with all 332 group files from its folder still plays exactly like its donor). The switch is off by
  default because the hook sits on a copy function every part of the game uses and its cost is not measured.

### 12.6 Own factories at run time; 12.7 the donor's callbacks

Unchanged in what is proven (sections 10.2, 10.3). New in N8 for the callbacks: what a donor's native callback
receives is the engine's battle object of the fighter (object id, kind number, a pointer to the fighter's module
accessor, which carries the same object id). The wrap recognises exactly that shape with a new kind in the kind
field and shows the callback the donor's number for the call; the old rule demanded a non-zero object id and
player 1's is 0. The component can also only log what arrives (`N7_CBWRAP=2`) or be given object classes
(`N8_CB_VT`). Component: `registry_bin_n8`. Not run.

### 12.8 Running, practical

- On a machine that runs other games a start takes up to 15 minutes; give the test driver `N5_SECS=900`.
- The character-select screen draws more per frame with new roster rows: menu scripts that wait for a draw count
  need the wider range (`tests\seq_n6_link.txt`, `tests\n8_seq_list.txt`).

## 13. Starting a new fighter: one command, one folder (session N9)

```
cd recomp-study
python fighter_sdk\tools\new_fighter.py <name> --donor <existing fighter> [--display-name "<TEXT>"]
```

`<name>`: 2..16 lower-case letters / digits, at least as long as the donor's name. The tool makes
`characters\<name>\` (another root with `--characters <dir>`):

| In the folder | What it is | Made from |
|---|---|---|
| `fighter.json` | the manifest (section 3; `display_name` only when asked for) | written |
| `fighter\<name>\...`, `effect\fighter\<name>\`, `sound\...`, `clone_files.json` | the donor's files under the new name: model description, every animation and the motion list, the two parameter files, the effect file, the computer player's parameters, the nine sound-bank files and the sequence file | extracted from the archive on your PC |
| `src\<name>\acmd\*.cpp`, `src\<name>\status\*.cpp`, `src\<name>\generated\` | the fighter's script sources: move scripts, status functions, bindings. The fighter's name stands in the source macros and in the names of its own functions (text inside string literals is never touched: those are names of the game's resources) | copied from the generated source tree and renamed |
| `build.cmd` | ONE command that builds `src\` into `<name>.dll` in the folder (= `new_fighter.py <name> --build`) | written |
| `<name>.dll` | the script DLL (built at the end of the tool unless `--no-build`) | built |
| `README.txt` | which file to replace to change the moves, the state machine, the animations, the model, the parameters, the effects, the sounds | written |

The runtime skips `src\` when it looks for files of the archive in a fighter's folder. The tool contains nothing of
the game; what it copies is generated from the game or extracted from it and stays on your PC.

Working on the fighter afterwards:
- a move (damage, angle, timing): edit `src\<name>\acmd\game.cpp`, run `build.cmd`, start the game;
- an animation: replace the file of that motion in `fighter\<name>\motion\body\c00\` (files are named by the hash of
  the motion file's name: `0x<hash>.nuanmb`);
- everything else: section 11.

Not made by the tool (the donor's stay in use): the agent factories as source (`tests\n6_s_factories.py`, proven for
one donor only), the mesh / material / texture files of the model (the folder holds the model description; the
rest is served from the donor's bytes under the fighter's name), costumes other than the first.

**Shown (phase file `N9_checklist.md`, section 6):** a fighter made by the tool alone from a third donor loads,
fights 300 frames and plays bit-for-bit like its donor in the deterministic test (move scripts and status functions
from its own DLL, files from its own folder, the donor's native callbacks wrapped).
With ONE damage number changed in its `game.cpp` (rebuilt by `build.cmd`: one file compiled) the opponent takes the
new damage from that move and everything before the hit is unchanged; with ONE animation file replaced in its
folder the fighter's idle ends at the new file's length.

## 14. Session N9: what else changed

### 14.1 Article files are asked for under the fighter's own name (shown)

Section 12.4's mechanism ran: all 62 path questions for the six articles of the test fighter (animation folder and
model description each) arrive with the donor's name while the fighter is set up, are answered with the fighter's
own rows, none is left to the donor, and the match equals the donor's. Component: `registry_bin_n9` (or `_n8`).

### 14.2 Files the donor never had: the template does NOT work (two runs), and why

A load group is ONE compressed stretch of the archive that the engine's load thread reads front to back while it
walks the group's records; each record says where in the stretch its bytes are. A record made from a "template"
names another record's bytes: a place the thread has not reached yet or has already passed. In both runs the load
of the group never ended (every file before the record is read, then the loading screen stays). So section 12.3's
mechanism is switched OFF by default (`SSBU_LOOSE_TEMPLATE=1` turns it on for experiments). Until the replacement
exists: **a folder file that has no file of the same name among the donor's own files of the group gets no row**
(log: `NOT served`), and **a file the donor's group shares with other groups (the skeleton, textures common to all
costumes) stays the donor's** even when the folder brings it (log: `the folder's copy is NOT what the game gets`).
The replacement (not built): records the group load skips, each read by a single-file request of our own; the
engine has both pieces (it reads its sound banks that way), what is missing is our request.

**Session N10 (2026-10-13): the cause is exact now and a replacement is WRITTEN, not yet run**
(`plan\phases\N10_custom_model.md`). The load thread does not look a record's bytes up by their place: it keeps a
running position in the stretch and moves it forward by each record's stored (compressed) size. A template record
made it consume another record's size once more, at the wrong place. The replacement is a **virtual record**: a
record of the fighter's own at the end of its group, marked "stored raw" with stored size 0 and the folder file's
size as its real size - the thread allocates the buffer, consumes nothing, and the layer writes the folder's file
where the thread would copy. Nothing of such a record refers to the archive. It is made for (a) a folder file under
`fighter\<name>\` with a name the donor never had and (b) a file the donor's group shares (skeleton, `model.xmb`,
common textures) that the folder brings. On by default in the sources (`SSBU_LOOSE_TEMPLATE=0` = off); the log
lines to look for are `a VIRTUAL record of its own at the end of the group` and `VIRTUAL record served: ... crc32`.
**Shown in one finished run:** the new fighter's whole body-model folder was replaced by another fighter's of a
different shape (44 files: model description, mesh, materials, skeleton three times the donor's size, helper
bones, 33 textures with names the donor never had). All 36 files that needed a virtual record were served (each
read back from the engine's buffer with the folder file's checksum), all 388 files of the folder were served, the
match loaded, the other model was drawn in the new slot with its textures, and the fight ran its 300 test frames
without a trap. The fighter looks small and compressed: its animations, scale and parameters are still the small
donor's. With the other skeleton the fighter's position drifts from the unmodified copy's during a special (same
statuses, same damage). Not covered by that run: other moves, being hit, throws, the results screen.

### 14.3 The donor's native callbacks (shown for a third donor)

Section 12.7's rule runs: a callback of the donor's native object that receives the battle object of a NEW kind
(kind field = a new number, module accessor with the same object id) runs with the donor's number in that field.
The session-N8 build of the component could never match (a parsing mistake in its default setting); the fixed
component is `registry_bin_n9`. With it a tool-made copy of a fighter whose callbacks class is shared with another
fighter loads and plays exactly like its donor, with no per-donor line.

### 14.5 Sounds: how the bank files are read, and what the folder can change

The nine sound-bank files of a fighter are not read through the path the engine looks up by name. They are
"shared" records of the fighter's costume group (their bytes live elsewhere in the archive), and the loader reads
each of them by a single-file request made from that record. A new fighter's group copied those records as they
were, so the DONOR's files were loaded whatever the folder held. Now such a record becomes the fighter's own when
the folder brings the file (`SSBU_LOOSE_SOUNDROWS=0` switches that off): shown for six of the nine files - the
folder's bytes are what lands in the game's buffer, a bank replaced by another valid bank is read back there, and
the fight runs and equals the same fight without the mechanism (the tests are muted: nobody has listened yet). Four
of the six are stored uncompressed and are only replaced with `SSBU_LOOSE_RAW=1` (section 12.5), like the sound
sequence file. The three "cheer" files of the voice set are regional files (one copy per region) and stay the
donor's: the run that made them the fighter's own never finished loading.

### 14.6 A start that stands still

Growing the archive's tables at start (section 10.1) raced with the game's first file requests on a quiet machine:
rows the game took into use while the larger tables were being built were missing from them, and the game then
waited for ever before its first frame. The two tables in question are now copied again immediately before the
switch; the same situation passed in the two runs after that. If a start with `SSBU_CHARACTERS` shows no picture
for a minute, look for `rows in use at the switch` in the log and start again.

### 14.7 A port from another game: per piece, the exact input and whether it can differ from the donor TODAY

"Yes" = a finished run showed a difference from the donor taking effect; "served" = the folder's bytes are what the
engine loads, shown, but no deliberately different file was tried; "no" = the donor's is what you get.

| Piece | Exact input | Differs from the donor today? |
|---|---|---|
| Manifest | `characters\<name>\fighter.json` (made by `new_fighter.py`) | - |
| Move scripts | `src\<name>\acmd\*.cpp`, built by `build.cmd` | YES (a changed damage number hits with the new value; three donors) |
| Status functions | `src\<name>\status\*.cpp`, same build | YES for the donor's status kinds (N6); a new status kind: no |
| Animations | `fighter\<name>\motion\body\c00\0x<hash of the motion file's name>.nuanmb`, the engine's animation format, on the donor's skeleton | YES for a motion the donor has (shorter and longer files both shown); a motion the donor does not have: no (14.2) |
| Motion list | `...\motion\body\c00\0x<hash of "motion_list.bin">.bin` | served; a changed list not tried |
| Model description | `fighter\<name>\model\body\c00\model.numdlb` | served |
| Meshes, materials, the costume's own textures | the files the model description and the materials name, in the same folder, same names as the donor's | YES for textures (N8: another costume's textures, a picture); meshes / materials: same mechanism, not tried |
| Skeleton, textures common to all costumes | `model.nusktb`, `model.xmb`, `<name>.nutexb` in the fighter's model folder | YES (N10: another skeleton, helper-bone file and `model.xmb` loaded from the folder and used; 14.2). Common textures: same mechanism, not tried |
| Files with names the donor does not have (other texture names, more animations) | any file under `fighter\<name>\...` | YES for textures (N10: 33 of 33 served and drawn). An animation with a new name is served the same way but needs a row in the motion list and a script to be played: not tried |
| A whole model of another shape | every file of `fighter\<name>\model\body\c00\`: model description, mesh, materials, skeleton, helper bones, textures (the engine's formats; the standard fighter bone names) | YES: loads and draws in a fight (N10, one run, one picture). It is animated by the donor's animations until the folder brings its own; what a skeleton WITHOUT the standard bone names breaks was not tried |
| Article models and animations | `fighter\<name>\model\<article>\c00\`, `fighter\<name>\motion\<article>\c00\` | asked for under the fighter's name (14.1) and served like body files; a different file not tried; the article KINDS are the donor's |
| Per-fighter parameters | `fighter\<name>\param\vl.prc`, `expression_vl.prc`, the donor's layout | YES for values (N4 / N8) |
| Effects | `effect\fighter\<name>\0x<hash>.eff` | served; a different file not tried |
| Sound banks | `sound\bank\fighter\se_<name>_c00.*`, `sound\bank\fighter_voice\vc_<name>_c00.*` (6 files) | YES as bytes (14.5: a replaced bank is what the game holds, the fight runs; with `SSBU_LOOSE_RAW=1` for the uncompressed four); not listened to. The 3 `vc_<name>_cheer_c00.*`: no |
| Sound sequence | `sound\sequence\fighter\<name>.sqb` | served with `SSBU_LOOSE_RAW=1`; a different file not tried |
| Pictures | `ui\replace\chara\chara_<type>\chara_<type>_<name>_<cc>.bntx` | YES for types 1, 2, 4, 6, 7 (14.4); 0, 3, 5: same mechanism, not asked for in the test |
| Name text | `"display_name"` in the manifest | the labels are answered (14.4); read the warning there |
| Computer player | `fighter\<name>\ai\param\*` | served; the code is the donor's |
| Select-screen entry | made by the runtime | yes up to 91 entries in all; beyond: no |

### 14.4 Pictures and name text of the roster row

The select screen, the versus screen, the HUD and the results take a fighter's pictures from
`ui/replace/chara/chara_<type>/chara_<type>_<name_id>_<colour>.bntx` (types 0..7 exist for a fighter's first
colour) and its name from message labels `nam_chr<k>_<nn>_<name_id>`; `name_id` is a text field of the roster row,
and a new fighter's row is a copy of its donor's, so by default both are the donor's. Two inputs change that:

| Input | Where | Effect |
|---|---|---|
| picture files | `characters\<name>\ui\replace\chara\chara_<type>\chara_<type>_<name>_<cc>.bntx`, one per type and colour you want to replace (the engine's texture container format, not larger than the donor's file of that type) | the picture-path question of the new row is answered with the folder's file; a type the folder does not bring stays the donor's |
| `"display_name": "<TEXT>"` in `fighter.json` (ASCII) | the manifest | the row's `name_id` is answered with the fighter's own name: labels and picture paths are built with it, and a label that ends in the fighter's name is answered with the display name |

**State:** shown in one run with another fighter's pictures as the marker: the engine asks for the pictures of the
new row (types 1 and 7 on the select screen, 2 = the stock icon, 4 and 6 in the match) and gets the folder's files;
the picture of the match shows the other portrait and stock icons in the new slot's HUD; the labels
`nam_chr1_`, `nam_chr2_`, `nam_chr3_00_<name>` are answered with the display name. Not shown: types 0, 3 and 5
(not asked for in that run: results screen, full select screen); the name on a picture (the HUD of a human player
shows the player's tag). **Careful with `display_name`:** the row's `name_id` is used in about a hundred places of
the game; only the picture paths and the `nam_chr...` labels are covered. Anything else built from it (the
announcer's call is the likely one) is then asked for under the fighter's name and is missing, and whether a fight
with it still equals the donor's has not been measured. Without `display_name` nothing of this is active; pictures
alone do not need it.

## 15. Session N11: a fighter that is seen as its own (phase file `N11_visible_fighter.md`)

### 15.1 The tool: the whole body model in the folder

`new_fighter.py <name> --donor <fighter> --model donor` also puts the donor's WHOLE body model into the folder as the
fighter's own files (mesh, materials, skeleton, helper bones, every texture; the step `tests\n10_model.py swap`
did by hand before). This is the consistent starting point: the animations, the motion list, the parameters and the
scripts the tool copies were made for that skeleton, so the fighter has the right size and moves right, and every
model file can then be replaced or edited in place. `--model <fighter>[:cNN]` takes another fighter's or costume's
model instead: it loads and draws (section 14.2), but it is moved by the donor's animations and sized by the donor's
parameters, which is only right when the two are of one build. A folder file of the donor that is stored once per
region no longer stops the tool.

Shown: a fighter made this way from a sword fighter, with its colour textures edited in place
(`tests\n11_tint.py`: two colour channels exchanged block by block, no decoding), stands in a fight at the right
size beside another fighter in other colours than its donor; all of its 404 folder files are served, 38 of them as
virtual records (with this donor nearly the whole model is "shared" in the archive's sense).

### 15.2 A model converted from another game

A fighter folder whose `model\body\c00` holds a model converted from another game's package (96 bones: a root, the
package's own bones under their own names, the engine's standard bone names as extra bones; uncompressed one-mip
textures; an EMPTY helper-bone file; material entries copied from the donor's) loads, draws textured at the right
size and fights without a trap. Model files smaller than the donor's are no special case when the donor's files are
shared files of its group: each gets a virtual record of its exact size. Animations converted from that package
(the engine's packed format with a transform group only) play, including where they replace a donor file of the
older format version. What such a fighter still takes from its donor: every motion it does not bring, parameters,
scripts, hit and hurt boxes, effects, sounds.

### 15.3 The select screen and the pictures

- With `"display_name"` in the manifest the tile on the select screen reads the fighter's own name (shown on the
  full roster). Without it the tile reads the donor's name and the new slot looks like a duplicate of the donor.
- The pictures (tile, big portrait, HUD portrait, stock icon ...) are the donor's unless the folder brings
  `ui\replace\chara\chara_<type>\chara_<type>_<name>_00.bntx`. `python tests\n11_ui_placeholder.py <characters>
  <name>` writes GENERIC placeholders for the first colour so that no screen shows the donor's face: the game's own
  question-mark picture where it has one of that type (types 0, 1, 7), else the donor's container with its pixel
  data zeroed (types 2 - 6). A fighter's own pictures in those places are never overwritten. Other colours: the
  donor's.
- On a save with the whole roster the select screen draws about 530 times per frame; test sequences that wait for
  "175 - 260 draws" (the small test save) never see it. `tests\n11_seq_full.txt` is the sequence for such a save.

### 15.4 Starting the game with the fighter (the owner's launchers)

`gioca_personaggio_nuovo.bat` (player 1 is always the new fighter) and `gioca_personaggio_nuovo_scelta.bat` (pick
it by hand: the last tile). A test-named exe shows no window and plays no sound unless `SSBU_SHOW=1` /
`SSBU_VOLUME=100` are set: the launchers set them (when not already set from outside). State of what was verified:
the phase file, section 4.

## 16. Session N12: what a new fighter owns beyond the donor (phase file `N12_fighter_extensions.md`)

Needs an exe with `fighter_sdk\newmodule_host.c` of N12 (test exe `ssbu_n12.exe`) and the registry components of
`registry_bin_n12\` (`n12_kind.dll` replaces `n8_kind.dll`; `fighter_param_row.txt` beside it). Every switch below
acts only when `SSBU_CHARACTERS` gives a registry.

### 16.1 The parameter row from the manifest (shown)
```json
"parameter_row": { "copy_of": "<donor>", "set": { "walk_speed_max": 0.95, "jump_squat_frame": 4, "attack_combo_max": 3 } }
```
The kind component makes the new kind's row as a copy of the donor's and then writes each `set` value at the offset
the row table `fighter_param_row.txt` gives for the name (one line per field: name, `f32` or `i32`, byte offset; a new
field is a new line, no rebuild). An unknown name is skipped with a log line at run time and refused by
`new_fighter.py --build`. `N12_ROWSET=0`: off.

### 16.2 The fighter's own per-frame routine (shown)
A function `<name>_frame` in the fighter's sources, written as `L2C_VOID_FUNCTION(<name>, <name>_frame) { ... }`, is
called once per fight frame for that fighter, from the engine's per-fighter frame line, before the frame line itself,
whatever the status. The place for hold times, a charge kept across actions, flags cleared on landing.
`SSBU_REG_FRAME=0`: off.

### 16.3 Scripts under the fighter's own names (shown)
A move script that exists only in the fighter's sources (`ACMD(<name>, game_<motion>)` for a motion the donor does
not have) is registered by its name with the fighter's agents of its category (`game_`, `effect_`, `sound_`,
`expression_`), so the motion list's script name finds it like any other; no alias under a donor name is needed.
Article agents do not get them. `SSBU_REG_OWNSCRIPTS=0`: off.

### 16.4 Own articles (written, not shown in a match)
```json
"articles": [ { "name": "<article>", "template": "<owner>_<article of the game>", "max": 3 } ]
```
With `N12_ARTICLES=1` the fighter's description record is its own copy of the donor's with one row appended per
article {own weapon kind, max alive, the template's native functions}. `new_fighter.py --build` writes
`src\<name>\generated\fs_articles.h` with `FIGHTER_<NAME>_GENERATE_ARTICLE_<ARTICLE>` (= the donor's article count +
index), for `ArticleModule::generate_article`. Own weapon kinds are numbered from 640. NOT done: the engine's
per-weapon-kind lookups for those numbers, the article's agents (factories and status / move scripts as source),
its files. The engine builds an article's pool (its "max alive" objects) already at the fighter's set-up, so with
`N12_ARTICLES=1` today a match with such a fighter STOPS at its set-up unless the template's owner is in the match
and set up first (player 1); even then the generated weapon is removed at once (phase file 4.4d): leave it off.

### 16.5 Test aid
`SSBU_FIGHT_HASH_WORK=<int work id>` adds `w <value>` (that int variable of each fighter) to the end of every line of
the fight hash log; it is not part of the running hash.
