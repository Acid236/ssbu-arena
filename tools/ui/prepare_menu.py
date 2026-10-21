"""Build an isolated four-tile menu preview from your own game dump.

    python tools/ui/prepare_menu.py [--layout <original layout.arc>]

Default output: build/characters_ui_test/ui_menu. The recipe contains authored
Arena art and layout changes; original resources come from the owner's dump.
Colour surfaces are expanded inside BNTX, with unmodified archive members
preserved byte for byte. Optional labels use an explicit language region.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import bflyt_patch
import msbt_patch
import menu_textures
import menu_actions
from lua_chunk import Chunk


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / 'tools' / 'nro'))
from arc_extract import Arc


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--arc', type=Path)
    ap.add_argument('--layout', type=Path)
    ap.add_argument('--out', type=Path, default=REPO / 'build' / 'characters_ui_test' / 'ui_menu')
    ap.add_argument('--labels', type=Path, help='optional labelled replacements, e.g. menu_labels_en.json')
    ap.add_argument('--region', type=int, choices=range(1, 15), default=2, help='dump region row (2 US English, 5 UK English, 10 Italian)')
    a = ap.parse_args()
    state = json.loads((REPO / 'build' / 'state.json').read_text()) if not a.arc else None
    arc_path = a.arc or Path(state['dump']['romfs']) / 'data.arc'
    arc = Arc(str(arc_path))
    layout_path = 'ui/layout/menu/main_menu/main_menu/layout.arc'
    original = a.layout.read_bytes() if a.layout else arc.get(layout_path)
    edits = json.loads((HERE / 'menu_four_tiles.json').read_text())
    patched, count = bflyt_patch.apply(original, edits)
    patched, textures = menu_textures.patch(patched)
    original_files = bflyt_patch.sarc_files(original)
    updated_files = bflyt_patch.sarc_files(patched)
    if updated_files.keys() != original_files.keys():
        raise ValueError('layout archive member names changed')
    changed = []
    for name, (start, end) in original_files.items():
        new_start, new_end = updated_files[name]
        if patched[new_start:new_end] != original[start:end]:
            if name.removeprefix('blyt/') not in edits and name != 'timg/__Combined.bntx':
                raise ValueError('unrequested archive member changed: ' + name)
            changed.append(name)
    outputs = {layout_path: patched}
    sidebar_path = 'ui/layout/menu/pallet_menu/pallet_menu/layout.arc'
    sidebar, _ = bflyt_patch.apply(arc.get(sidebar_path), {'pallet_menu.bflyt': {
        'RootPane': {'visible': True, 'alpha': 0},
        'pallet_bg': {'visible': False}, 'mask': {'visible': False},
        'bg_line': {'visible': False}, 'set_txt_key': {'visible': False}, 'anim_R_00': {'visible': False}
    }})
    outputs[sidebar_path] = sidebar
    footer_path = 'ui/layout/menu/main_menu_footer/main_menu_footer/layout.arc'
    outputs[footer_path], _ = bflyt_patch.apply(arc.get(footer_path), {
        'main_menu_footer.bflyt': {'RootPane': {'visible': False}}})
    for name, transform in (('main_menu', menu_actions.main_menu),
                            ('main_menu_layer_top', menu_actions.top),
                            ('main_menu_common', menu_actions.common),
                            ('main_menu_footer', menu_actions.footer)):
        script_path = 'ui/script/menu/main/' + name + '.lc'
        source = arc.get(script_path)
        if Chunk(source).dump() != source:
            raise ValueError('Lua chunk round-trip changed ' + name)
        outputs[script_path] = transform(source)
        if Chunk(outputs[script_path]).dump() != outputs[script_path]:
            raise ValueError('invalid transformed Lua chunk ' + name)
    if a.labels:
        msg_path = 'ui/message/msg_menu.msbt'
        outputs[msg_path] = msbt_patch.apply(arc.get(msg_path, a.region), json.loads(a.labels.read_text(encoding='utf-8')))
    # All validation above completes before any existing preview file is replaced.
    for relative, content in outputs.items():
        dest = a.out / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        temporary = dest.with_suffix(dest.suffix + '.tmp')
        temporary.write_bytes(content)
        temporary.replace(dest)
        print('%s: %d bytes, sha256 %s' % (dest, len(content), hashlib.sha256(content).hexdigest()))
    # The owner replaced the experimental A spinner with the host's Kirby loader.
    (a.out / 'ui/layout/system/loading/loading/layout.arc').unlink(missing_ok=True)
    print('%d panes patched; changed archive members: %s' % (count, ', '.join(changed)))
    print('Authored textures: %d menu; sidebar hidden' % len(textures))


if __name__ == '__main__':
    main()
