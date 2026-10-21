# Arena native menu

The 2026-10-21 art revision uses uncompressed RGBA8 sRGB surfaces: the background
is rendered at 3840×2160, and cards and their text at twice their layout size.
This replaces the original 872×384 background slot that was stretched over the
whole window. The navy background has a soft gradient and thin separators;
the large watermark and dotted texture have been removed.

`texture_surface.py` appends pixel data inside BRTD, updates BNTX relocation
metadata, and resizes the SARC member while preserving other members exactly.
Texture names, pointer tables and native button controllers are preserved.
Only colour art grows; existing BC4 masks retain their allocation except the
previously corrected Spirits focus-strip geometry.

`media/arena.ico` shares the launcher's multi-resolution Arena mark. The game
window is named **SSBU Arena**. Frame counters are shown only when the frame-time
overlay or `SSBU_TITLE_STATS=1` is explicitly enabled.

Verified by booting the native UI host to the menu, inspecting its window title
and icon, and checking full-resolution RGBA pixel samples. Captures are in
`../ui_work/runs/arena_hd_20261021_160254/`. Normal, UI and rollback hosts are
built with the same display branding. Online & Friends routing remains pending;
the visual check does not establish multiplayer functionality.

The notes below document the initial preview and remain useful for its tools.

Recovered and continued on 2026-10-20 from the local `ui_work` experiments.
These tools contain no game content. They build a loose-file override from
the owner's installed dump; no game DLL or archive needs rebuilding.

The four tiles are Smash (upper left), Settings (upper right), Online & Friends
(lower left), and Online Ranked (lower right). Vault and eShop are hidden. The
right tiles extend into their former space. Pane overrides resize frames and
hit polygons separately from text and icons. Selection decorations whose
original shape crossed the enlarged tiles are hidden; the circular selection
highlight and the rectangular glow remain.

**This is a visual preview.** Button actions and controller navigation still
belong to the original menu. Settings does not yet open a new settings screen;
the online tiles do not implement friends or ranked play. Full controller
traversal is not yet verified. The help line explicitly
calls the renamed tiles previews. Original icons and centre previews remain.

## Run

From the repository root, double-click `Preview UI.bat`, or run:

```powershell
python tools/ui/prepare_menu.py --labels tools/ui/menu_labels_en.json
python tools/ui/menu_probe.py --tag preview --visible --play
```

The local default setup is `<repo>/build`, with `dump/romfs_light`, `cache/vk_light`
and a disposable save template `cov_save_snap` beside the repository. The probe
accepts `--workspace`, `--build`, `--save-template` and `--loose` for other locations.
Each run copies the template into a new `ui_work/runs/<tag>_<timestamp>/userdata`
folder, captures `menu.png`, and writes `game.log`. It stops only the process it
started and removes its temporary executable. `--play` leaves that process open
until its window is closed. Keyboard input is enabled in this mode.

For an automatic capture that then exits:

```powershell
python tools/ui/menu_probe.py --tag settings --select other
python tools/ui/menu_probe.py --tag friends --select spirits
```

The probe skips the full game's shader preparation for quicker UI iterations;
this switch applies only to that process. It uses the renderer's own capture,
so it does not need the old `drive.ps1` helper or a desktop screenshot script.
Pillow exports the BMP as PNG. These captures establish visual behaviour only;
they are not match, network, or renderer performance tests.

## Edit and regenerate

- `menu_four_tiles.json`: positions, sizes, visibility and part overrides.
- `menu_labels_en.json`: six replacements in `msg_menu`, including preview help.
- `bflyt.py`: read-only layout archive listing and pane tree.
- `bflyt_patch.py`: fixed-size edits of panes and existing PRT1 overrides.
- `msbt_patch.py`: labelled text replacements within existing TXT2 capacity.
- `prepare_menu.py`: reads `build/state.json` and the dump, validates changes,
  then writes `build/characters_ui_test/ui_menu/ui/...`.

`prepare_menu.py --layout <original layout.arc>` can reuse an extracted source.
Otherwise it extracts the layout itself. Text overrides are opt-in with
`--labels`; `--region` selects their source language (2 = US English, 5 = UK
English, 10 = Italian, measured in this dump). The generated MSBT overrides the
whole message file for the preview process, so its language should match the
chosen game language. Only US English has been run through the game here.
Omitting `--labels` does not remove a previously generated message override;
use a separate `--out` directory for a geometry-only variant.

The BFLYT and message patchers preserve member size. The layout builder verifies
that only requested BFLYT members and the BNTX colour surfaces change; SARC
member offsets after the expanded BNTX are updated with alignment preserved.
The text patcher checks byte preservation for unchanged messages and their
embedded tags. Binary outputs, captures and save copies remain local and ignored.

The PRT1 record structure is documented by the open-source
[SwitchThemeInjector reader](https://github.com/exelix11/SwitchThemeInjector/blob/master/SwitchThemesCommon/Bflyt/Prt1Pane.cs)
and [Switch-Toolbox reader](https://github.com/KillzXGaming/Switch-Toolbox/blob/master/File_Format_Library/FileFormats/Layout/CAFE/Panes/PRT1.cs).
Basic pane-info offsets and usage bits were inferred from the owner's dump and
checked in the game. Text font offsets follow Switch-Toolbox's TXT1 reader.

## Continue

Verified locally on 2026-10-20: menu boot and captures with Smash, Settings,
Online & Friends, and Online Ranked selected; the interactive batch launcher
also booted, captured, and exited when its game window was closed. The patchers
passed no-op / repeat-application checks, exact replacement-text checks,
unchanged-message checks, and rejection of missing labels and oversized text.
No action-routing or multiplayer test is claimed.

The next functional change needs the main menu's action and navigation code:
verify Vault/eShop are excluded from all focus paths, route Settings to the chosen settings
UI, and route the online tiles to their actual destinations. Keep those actions
behind an explicit preview option until they are implemented and tested.
Custom icons and centre preview art are still needed for the new destinations.
Rollback work is outside this UI iteration.

To discard the preview, remove only the generated `build/characters_ui_test/ui_menu`
folder, or launch normally without selecting that loose root. The old experiments
and screenshots remain in `../ui_work`.
