"""The classic Arena menu: the game's own menus (main menu and its sub-menus) with their layout, buttons and navigation,
recoloured in the Arena palette (menu_recolor.py), the right-hand side bar hidden, and the main menu's buttons given
the Arena destinations (menu_actions_classic.py): Smash, Arena, Online Ranked, Online LDN, Settings (the eShop button)
and Exit (the Games & More button, not part of the competitive build). A loose-file override built from the owner's
dump (nothing of the game in this repository), like prepare_menu.py.

    python tools/ui/prepare_menu_classic.py [--out DIR] [--region N]
    python tools/ui/menu_probe.py --tag classic --loose build/characters_ui_classic
"""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import bflyt_patch
import menu_actions_classic
import menu_recolor
import menu_textures
import msbt_patch
from lua_chunk import Chunk
from prepare_menu import Arc
from texture_surface import replace_rgba, replace_sarc_member

MAIN = 'ui/layout/menu/main_menu/main_menu/layout.arc'
SIDEBAR = 'ui/layout/menu/pallet_menu/pallet_menu/layout.arc'
FOOTER = 'ui/layout/menu/main_menu_footer/main_menu_footer/layout.arc'
MESSAGES = 'ui/message/msg_menu.msbt'
SCRIPTS = 'ui/script/menu/main/'
NAVY = '0a1424ff'                                     # the launcher's page background


def _accent_hex():
    r, g, b = menu_recolor._accent_linear()             # materials are linear values (menu_recolor.recolour_rgb)
    return '%02x%02x%02xff' % (r, g, b)


EDIT_MAIN = {
    'main_menu.bflyt': {'bg': {'material_white': NAVY, 'material_black': NAVY, 'vertex_colors': [NAVY] * 4},
                        'set_parts_text_scroll': {'visible': False}},     # the news ticker (it named the side bar's ZR)
    # the selected tile's highlight (white in the game, shown by main_menu_btn3_00_OnOff): the launcher's accent
    'main_menu_btn3_00.bflyt': {'high_light': {'material_white': _accent_hex()}},
}
# the side bar is moved off the screen, not hidden: its native controller still runs the Local Wireless and Options
# commands for the Arena buttons (competitive.c), and it reports them done only after its own animations
# The right-hand tiles (layout units: 1920 x 1080, centre 0, y up). Online LDN is the Games & More tile made taller down
# over the Vault's place; Settings is the Vault tile, small, in the top-right corner above it (up from LDN); Exit is the
# eShop button, left where it is. Their selection cursors (window panes of the centre layout) follow.
LDN_TOP, LDN_BOTTOM = 315, -83                       # below Settings' corner, down to the Vault tile's bottom
SET_X, SET_Y, SMALL = 842, 410, 0.28                 # Settings' centre (top-right corner) and the scale of its text and icon
SET_W, SET_H = 236, 160                              # its frame, background and cursor
_h = LDN_TOP - LDN_BOTTOM
_cy = (LDN_TOP + LDN_BOTTOM) / 2


def _hits(hw, hh, x=0, y=0):
    """the button's six hit points (main_menu_btn3_00 hit_00..05) as a hw x hh half-size rectangle centred on (x, y): the
    d-pad selector compares them (a tile counts as above another only when it is wholly above its hit points)"""
    corners = [(-hw, hh), (hw, hh), (hw, 0), (hw, -hh), (0, -hh), (-hw, -hh)]
    return {'hit_%02d' % i: {'pos': [x + cx, y + cy]} for i, (cx, cy) in enumerate(corners)}


EDIT_MAIN['main_menu.bflyt'].update({
    'mask_other': {'pos': [484, _cy], 'size': [1004, _h]},
    'null_btn_other': {'pos': [484, _cy - 0.5]},
    'mask_colle': {'pos': [SET_X, SET_Y], 'size': [SET_W, SET_H]},
    # Settings at scale 1, its frame the corner's size; only its icon, name and circle are made SMALL inside the button
    'null_btn_colle': {'pos': [SET_X, SET_Y]},
    'set_parts_btn_colle': {'pos': [0, 0], 'size': [SET_W, SET_H], 'parts': dict({
        'frame': {'size': [SET_W, SET_H]},
        'icon_positoin': {'pos': [19.6 * SMALL, 93.8 * SMALL], 'scale': [SMALL, SMALL]},
        'txt_position': {'pos': [10.3 * SMALL, -108.2 * SMALL], 'scale': [SMALL, SMALL]},
        'circle_position': {'scale': [0, 0]},                       # the side half-circle: no room for it
    })},                    # its own hit points stay: rewritten, the selector never picked it
    # Exit's hit points reached up over the free space (the shop tile's): now its visible tile only
    'set_parts_btn_eshop': {'parts': _hits(165, 65, 15, 5)},
    # Online LDN's hit box follows its taller tile
    'set_parts_btn_other': {'parts': dict({'frame': {'size': [1004, _h]}}, **_hits(490, _h / 2))},
})
EDIT_MAIN['main_menu_lct_center_00.bflyt'] = {
    'other_crs_square_01': {'pos': [478, _cy - 14]},
    'sel_csr_blink_04': {'size': [1064, _h - 6]}, 'sel_csr_hl_00_add_03': {'size': [1064, _h - 6]}, 'sel_csr_hl_01_add_03': {'size': [1064, _h - 6]},
    'other_crs_00': {'pos': [505, _cy - 4], 'size': [1114, _h + 16]},
    'collection_crs_square_01': {'pos': [SET_X, SET_Y]},
    'sel_csr_blink_07': {'size': [SET_W + 8, SET_H + 8]}, 'sel_csr_hl_00_add_06': {'size': [SET_W + 4, SET_H + 4]},
    'sel_csr_hl_01_add_06': {'size': [SET_W + 4, SET_H + 4]},
    'collection_crs_00': {'pos': [SET_X, SET_Y], 'size': [SET_W + 14, SET_H + 14]},
}
HIDE_SIDEBAR = {'pallet_menu.bflyt': {'RootPane': {'pos': [4000, 0]}}}
# the buttons' icons (BC4 masks, normal and glow): authored in menu_textures.icon
ICONS = {'spirits': 'arena', 'online': 'ranked', 'other': 'wireless', 'colle': 'settings', 'eshop': 'power'}
# names and help lines, by the message file's region (2 US English, 5 UK English, 10 Italian)
LABELS = {
    'it': {'mnu_top_spirits': 'Arena', 'mnu_top_help_spirits': 'Battle Arena con i giocatori di SSBU Arena (presto disponibile).',
           'mnu_top_online': 'Online Ranked', 'mnu_top_help_online': 'Partite classificate online (presto disponibile).',
           'mnu_top_other': 'Online LDN', 'mnu_top_help_other': 'Stanze Local Wireless via internet, con il rollback.',
           'mnu_top_collection': 'Impostazioni', 'mnu_top_help_collection': 'Impostazioni del gioco. Dentro, premi + per le impostazioni di SSBU Arena.',
           'mnu_top_tip_eshop': 'Esci', 'mnu_top_help_eshop': 'Chiudi SSBU Arena.'},
    'en': {'mnu_top_spirits': 'Arena', 'mnu_top_help_spirits': 'Battle Arena with SSBU Arena players (coming soon).',
           'mnu_top_online': 'Online Ranked', 'mnu_top_help_online': 'Ranked online matches (coming soon).',
           'mnu_top_other': 'Online LDN', 'mnu_top_help_other': 'Local Wireless rooms over the internet, with rollback.',
           'mnu_top_collection': 'Settings', 'mnu_top_help_collection': "The game's settings. Inside, press + for the SSBU Arena settings.",
           'mnu_top_tip_eshop': 'Exit', 'mnu_top_help_eshop': 'Close SSBU Arena.'},
}


def default_region():
    """10 (Italian) when Windows shows Italian, else 2 (US English): the language the game picks (nnmisc.c GetDesiredLanguage)"""
    try:
        lang = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3ff
    except (AttributeError, OSError):
        return 2
    return 10 if lang == 0x10 else 2


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


def inset(im, scale=0.6, lift=0.04):
    """the icon smaller inside its square, a little high: the game's own icons leave that margin around the symbol"""
    from PIL import Image
    w, h = im.size
    small = im.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    out = Image.new('L', (w, h))
    out.paste(small, ((w - small.width) // 2, (h - small.height) // 2 - int(h * lift)))
    return out


def icons(data):
    d = bytearray(data)
    s, e = bflyt_patch.sarc_files(d)['timg/__Combined.bntx']
    bntx = bytearray(d[s:e])
    for tile, design in ICONS.items():
        for state in ('normal', 'glow'):
            menu_textures.put_bc4(bntx, 'icon_main_menu_%s_%s^s' % (tile, state), inset(menu_textures.icon(design)))
    d[s:e] = bntx                                       # BC4 slots keep their size
    return bytes(d)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--arc', type=Path)
    ap.add_argument('--out', type=Path, default=REPO / 'build' / 'characters_ui_classic' / 'ui_menu')
    ap.add_argument('--region', type=int, default=default_region(), help='message file region (2 US English, 10 Italian)')
    a = ap.parse_args()
    state = json.loads((REPO / 'build' / 'state.json').read_text()) if not a.arc else None
    arc = Arc(str(a.arc or Path(state['dump']['romfs']) / 'data.arc'))
    outputs = {}
    main_arc, _ = bflyt_patch.apply(arc.get(MAIN), EDIT_MAIN)
    main_arc = icons(main_arc)
    main_arc, m, t = recolour_archive(main_arc)
    outputs[MAIN], cur = menu_recolor.accent_windows(main_arc, 'main_menu_lct_center_00.bflyt')   # after: kept bright
    print('main menu: %d material colours, %d textures recoloured, %d cursor colours -> accent, %d icons' % (m, t, cur, 2 * len(ICONS)))
    outputs[SIDEBAR], _ = bflyt_patch.apply(arc.get(SIDEBAR), HIDE_SIDEBAR)
    outputs[FOOTER], m, t = recolour_archive(arc.get(FOOTER))
    print('footer: %d material colours, %d textures recoloured; side bar hidden' % (m, t))
    for name, transform in (('main_menu_layer_top', menu_actions_classic.top), ('main_menu_common', menu_actions_classic.common)):
        source = arc.get(SCRIPTS + name + '.lc')
        if Chunk(source).dump() != source:
            raise ValueError('Lua chunk round-trip changed ' + name)
        outputs[SCRIPTS + name + '.lc'] = transform(source)
    outputs[MESSAGES] = msbt_patch.apply_grow(arc.get(MESSAGES, a.region), LABELS['it' if a.region == 10 else 'en'])
    print('routes: Arena, Online Ranked (not yet), Online LDN, Settings, Exit; labels for region %d' % a.region)
    for relative, content in outputs.items():
        dest = a.out / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + '.tmp')
        tmp.write_bytes(content)
        tmp.replace(dest)
        print('%s: %d bytes, sha256 %s' % (dest.relative_to(a.out), len(content), hashlib.sha256(content).hexdigest()[:16]))


if __name__ == '__main__':
    main()
