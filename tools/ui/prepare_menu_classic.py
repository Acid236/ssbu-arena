"""The classic Arena menu: the game's own menus (main menu and its sub-menus) with their layout, buttons, navigation and
scripts untouched, recoloured in the Arena palette (menu_recolor.py); the eShop button and the right-hand side bar are
hidden. A loose-file override built from the owner's dump (nothing of the game in this repository), like prepare_menu.py.

    python tools/ui/prepare_menu_classic.py [--out DIR]
    python tools/ui/menu_probe.py --tag classic --loose build/characters_ui_classic
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import bflyt_patch
import menu_recolor
from prepare_menu import Arc
from texture_surface import replace_rgba, replace_sarc_member

MAIN = 'ui/layout/menu/main_menu/main_menu/layout.arc'
SIDEBAR = 'ui/layout/menu/pallet_menu/pallet_menu/layout.arc'
FOOTER = 'ui/layout/menu/main_menu_footer/main_menu_footer/layout.arc'
NAVY = '0a1424ff'                                     # the launcher's page background
HIDE_MAIN = {'main_menu.bflyt': {'set_parts_btn_eshop': {'visible': False}, 'mask_eshop': {'visible': False},
                                 'bg': {'material_white': NAVY, 'material_black': NAVY, 'vertex_colors': [NAVY] * 4}}}
HIDE_SIDEBAR = {'pallet_menu.bflyt': {'RootPane': {'visible': True, 'alpha': 0}, 'pallet_bg': {'visible': False}, 'mask': {'visible': False},
                                      'bg_line': {'visible': False}, 'set_txt_key': {'visible': False}, 'anim_R_00': {'visible': False}}}


def recolour_archive(data):
    """materials of every layout, then the colour surfaces of the archive's BNTX"""
    data, mats = menu_recolor.recolour_materials(data)
    data, keys = menu_recolor.recolour_animations(data)
    mats += keys
    files = bflyt_patch.sarc_files(data)
    if 'timg/__Combined.bntx' not in files:
        return data, mats, 0
    s, e = files['timg/__Combined.bntx']
    images = menu_recolor.recolour_bntx(data[s:e])
    if images:
        data = replace_sarc_member(bytearray(data), 'timg/__Combined.bntx', replace_rgba(data[s:e], images))
    return bytes(data), mats, len(images)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--arc', type=Path)
    ap.add_argument('--out', type=Path, default=REPO / 'build' / 'characters_ui_classic' / 'ui_menu')
    a = ap.parse_args()
    state = json.loads((REPO / 'build' / 'state.json').read_text()) if not a.arc else None
    arc = Arc(str(a.arc or Path(state['dump']['romfs']) / 'data.arc'))
    outputs = {}
    main_arc, _ = bflyt_patch.apply(arc.get(MAIN), HIDE_MAIN)
    outputs[MAIN], m, t = recolour_archive(main_arc)
    print('main menu: %d material colours, %d textures recoloured; eShop hidden' % (m, t))
    outputs[SIDEBAR], _ = bflyt_patch.apply(arc.get(SIDEBAR), HIDE_SIDEBAR)
    outputs[FOOTER], m, t = recolour_archive(arc.get(FOOTER))
    print('footer: %d material colours, %d textures recoloured; side bar hidden' % (m, t))
    for relative, content in outputs.items():
        dest = a.out / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + '.tmp')
        tmp.write_bytes(content)
        tmp.replace(dest)
        print('%s: %d bytes, sha256 %s' % (dest, len(content), hashlib.sha256(content).hexdigest()[:16]))


if __name__ == '__main__':
    main()
