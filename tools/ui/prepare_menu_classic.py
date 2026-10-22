"""The classic Arena menu: the game's own menus (main menu and its sub-menus) with their layout, buttons and navigation,
recoloured in the Arena palette (menu_recolor.py), the right-hand side bar hidden, and the main menu's buttons given
the Arena destinations (menu_actions_classic.py): Smash, Battle Arena, Online Ranked, Online LDN, Settings (the Vault)
and Exit (the eShop button). A loose-file override built from the owner's
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
# The right-hand tiles (layout units: 1920 x 1080, centre 0, y up). Online LDN is the Games & More tile as tall as Smash
# (same top and bottom) with Online Ranked's shape and frame flipped upside down: the cut for the centre circle at its
# bottom left, its right edge the curve of Online Ranked's mirrored upwards. Settings is the Vault tile in the column on
# its right, down to Exit, with Exit's shape flipped the same way (its left edge follows that curve, the same gap
# between them as between Online Ranked and Exit). Their selection cursors (window panes of the centre layout) are
# centred on the new tiles.
LDN_TOP, LDN_BOTTOM = 423, -63
RANKED_MASK = (-125, 747, 32)                        # Online Ranked's mask: left and right edges, its clear left margin
LDN_LEFT = -12                                       # right of Smash, as far as Online Ranked is right of Battle Arena
_ml = LDN_LEFT - RANKED_MASK[2]
_mw = RANKED_MASK[1] - _ml                           # LDN's mask (Online Ranked's right edge kept)
LDN_RIGHT = 712                                      # the frame's and hit box's right edge (where the curve is)
LDN_X = 505                                          # the button (its icon and name), right of the centre circle
EXIT_MASK = (780, 380)                               # Exit's mask: centre x (in the menu) and width
SET_LEFT, SET_RIGHT, SET_TOP, SET_BOTTOM = 680, 960, 423, -272
# the masks (and frames) are taller than what they show: (centre y, height) measured so the tiles show from
# LDN_TOP / SET_TOP down to LDN_BOTTOM / SET_BOTTOM
LDN_MASK, SET_MASK = (175.6, 573), (72.2, 1020)
SMALL = 0.5                                          # Settings' name (its offset)
FONT = [70, 146.9]                                   # every tile's name: Online Ranked's height, one narrower width
_lw, _lh = LDN_RIGHT - LDN_LEFT, LDN_TOP - LDN_BOTTOM
_lx, _ly = (LDN_LEFT + LDN_RIGHT) / 2, (LDN_TOP + LDN_BOTTOM) / 2
_sw, _sh = SET_RIGHT - SET_LEFT, SET_TOP - SET_BOTTOM
_sx, _sy = (SET_LEFT + SET_RIGHT) / 2, (SET_TOP + SET_BOTTOM) / 2


def _hits(hw, hh, x=0, y=0):
    """the button's six hit points (main_menu_btn3_00 hit_00..05) as a hw x hh half-size rectangle centred on (x, y): the
    d-pad selector compares them (a tile counts as above another only when it is wholly above its hit points)"""
    corners = [(-hw, hh), (hw, hh), (hw, 0), (hw, -hh), (0, -hh), (-hw, -hh)]
    return {'hit_%02d' % i: {'pos': [x + cx, y + cy]} for i, (cx, cy) in enumerate(corners)}


_font = {'txt_on': {'font_size': FONT}, 'txt_off': {'font_size': FONT}}
# Smash's button keeps the part's own text panes, drawn smaller: the same height there is 1.29 x FONT
EDIT_MAIN['main_menu_btn3_00.bflyt'].update({k: {'font_size': [v * 1.29 for v in FONT]} for k in ('txt_on', 'txt_off')})
# the half-circle beside each tile (lit white when selected, under the centre circle's ring in the game): none
EDIT_MAIN['main_menu_btn3_00.bflyt']['circle_position'] = {'scale': [0, 0]}
EDIT_MAIN['main_menu.bflyt'].update({
    'set_parts_btn_spirits': {'parts': _font},
    'set_parts_btn_online': {'parts': _font},
    'mask_other': {'material_like': ['main_menu.bflyt', 'mask_online'], 'pos': [_ml + _mw / 2, LDN_MASK[0]], 'size': [_mw, LDN_MASK[1]],
                   'scale': [1, -1]},
    'null_btn_other': {'pos': [LDN_X, _ly]},
    # the frame and hit box on the tile, offset from the button (which stays right of the centre circle)
    'set_parts_btn_other': {'parts': dict({'frame': {'pos': [_ml + _mw / 2 - LDN_X, LDN_MASK[0] - _ly], 'size': [_mw, LDN_MASK[1]], 'scale': [1, -1]},
                                                 'circle_position': {'scale': [0, 0]}},   # its half-circle lit the corner
                                          **_hits(_lw / 2, _lh / 2, _lx - LDN_X), **_font)},
    'mask_colle': {'material_like': ['main_menu.bflyt', 'mask_eshop'], 'pos': [EXIT_MASK[0], SET_MASK[0]],
                   'size': [EXIT_MASK[1], SET_MASK[1]], 'scale': [1, -1]},
    # Settings at scale 1, its frame the column; its icon (above the centre) and name (below) at SMALL inside the
    # button (the button's blink_scale is offset -17, 2 in this tile; the part's icon sits 149 above icon_positoin)
    'null_btn_colle': {'pos': [_sx, _sy]},
    'set_parts_btn_colle': {'pos': [0, 0], 'size': [_sw, _sh], 'parts': {
        'frame': {'pos': [EXIT_MASK[0] - _sx, SET_MASK[0] - _sy], 'size': [EXIT_MASK[1], SET_MASK[1]], 'scale': [1, -1]},
        'icon_positoin': {'pos': [40, 80 - 149 * 0.75], 'scale': [0.75, 0.75]},   # the gear larger than the name
        'txt_position': {'pos': [28, -90 + 7 * SMALL], 'scale': [0.42, 0.42]},   # right of the curved edge
        'txt_on': {'font_size': FONT, 'size': [600, 96]},
        'txt_off': {'font_size': FONT, 'size': [600, 96]},
        'circle_position': {'scale': [0, 0]},                       # the side half-circle: no room for it
        **_hits(_sw / 2, _sh / 2),          # its column only (rewritten while LDN's overlapped it, never picked)
    }},
    # Exit's hit points reached up over the free space (the shop tile's): now its visible tile only
    'set_parts_btn_eshop': {'parts': _hits(165, 65, 15, 5)},
})
# the cursors, centred on their tiles (the game's extend past the screen's edge)
EDIT_MAIN['main_menu_lct_center_00.bflyt'] = {
    'other_crs_square_01': {'pos': [_lx, _ly]},
    'sel_csr_blink_04': {'size': [_lw + 8, _lh + 8]}, 'sel_csr_hl_00_add_03': {'size': [_lw + 8, _lh + 8]},
    'sel_csr_hl_01_add_03': {'size': [_lw + 8, _lh + 8]},
    'other_crs_00': {'pos': [_lx, _ly], 'size': [_lw + 18, _lh + 18]},
    # (Settings' cursor drew 60 short at the bottom: measured)
    'collection_crs_square_01': {'pos': [_sx, _sy - 30]},
    'sel_csr_blink_07': {'size': [_sw + 8, _sh + 68]}, 'sel_csr_hl_00_add_06': {'size': [_sw + 8, _sh + 68]},
    'sel_csr_hl_01_add_06': {'size': [_sw + 8, _sh + 68]},
    'collection_crs_00': {'pos': [_sx, _sy - 30], 'size': [_sw + 18, _sh + 78]},
}
HIDE_SIDEBAR = {'pallet_menu.bflyt': {'RootPane': {'pos': [4000, 0]}}}
# the buttons' icons (BC4 masks, normal and glow): authored in menu_textures.icon, or another icon of the same archive
# (the online menu's Battle Arena door and options gear, read from the owner's dump)
ICONS = {'spirits': 'online_top_btn3_04_icon_off^s', 'online': 'ranked', 'other': 'wireless',
         'colle': 'online_top_btn3_02_icon_off^s', 'eshop': 'power'}
# names and help lines, by the message file's region (2 US English, 5 UK English, 10 Italian)
LABELS = {
    'it': {'mnu_top_spirits': 'Battle Arena', 'mnu_top_help_spirits': 'Battle Arena con i giocatori di SSBU Arena (presto disponibile).',
           'mnu_top_online': 'Online Ranked', 'mnu_top_help_online': 'Partite classificate online (presto disponibile).',
           'mnu_top_other': 'Online LDN', 'mnu_top_help_other': 'Stanze Local Wireless via internet, con il rollback.',
           'mnu_top_collection': 'Impostazioni', 'mnu_top_help_collection': 'Impostazioni del gioco. Dentro, premi + per le impostazioni di SSBU Arena.',
           'mnu_top_tip_eshop': 'Esci', 'mnu_top_help_eshop': 'Chiudi SSBU Arena.'},
    'en': {'mnu_top_spirits': 'Battle Arena', 'mnu_top_help_spirits': 'Battle Arena with SSBU Arena players (coming soon).',
           'mnu_top_online': 'Online Ranked', 'mnu_top_help_online': 'Ranked online matches (coming soon).',
           'mnu_top_other': 'Online LDN', 'mnu_top_help_other': 'Local Wireless rooms over the internet, with rollback.',
           'mnu_top_collection': 'Settings', 'mnu_top_help_collection': "The game's settings. Inside, press + for the SSBU Arena settings.",
           'mnu_top_tip_eshop': 'Exit', 'mnu_top_help_eshop': 'Close SSBU Arena.'},
}


# a button's frame drawn with another button's frame material (texture and colours): (button, from button)
FRAME_LIKE = (('set_parts_btn_other', 'set_parts_btn_online'), ('set_parts_btn_colle', 'set_parts_btn_eshop'))


def frame_like(data):
    """each FRAME_LIKE button's frame (its part property pane) given the other button's frame material index"""
    import struct
    d = bytearray(data)
    s, e = bflyt_patch.sarc_files(d)['blyt/main_menu.bflyt']
    idx = bflyt_patch.panes(d, s, e)

    def frame_prop(button):
        o = idx[button]
        for i in range(struct.unpack_from('<I', d, o + 0x54)[0]):
            r = o + 0x60 + 0x28 * i
            if d[r:r + 24].split(b'\0', 1)[0] == b'frame':
                prop = struct.unpack_from('<I', d, r + 28)[0]
                if not prop or d[o + prop:o + prop + 4] != b'pic1':
                    raise ValueError('no frame picture in ' + button)
                return o + prop
        raise ValueError('no frame in ' + button)
    for button, source in FRAME_LIKE:
        d[frame_prop(button) + 0x64:frame_prop(button) + 0x66] = d[frame_prop(source) + 0x64:frame_prop(source) + 0x66]
    return bytes(d)


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


def glow(icon):
    """the glow texture of an icon, like the game's: a soft halo around the symbol, the symbol itself left out (drawn
    dark under the icon it is its outline, bright when the tile is selected)"""
    from PIL import ImageChops, ImageFilter
    w = icon.width
    halo = icon.filter(ImageFilter.MaxFilter(2 * (w // 60) + 1)).filter(ImageFilter.GaussianBlur(w / 40))
    halo = halo.point(lambda v: min(255, int(v * 1.6)))
    return ImageChops.multiply(halo, ImageChops.invert(icon))


def icons(data):
    d = bytearray(data)
    s, e = bflyt_patch.sarc_files(d)['timg/__Combined.bntx']
    bntx = bytearray(d[s:e])
    for tile, design in ICONS.items():
        symbol = menu_textures.get_bc4(bntx, design) if '^' in design else menu_textures.icon(design)
        symbol = inset(symbol.resize((512, 512)))
        menu_textures.put_bc4(bntx, 'icon_main_menu_%s_normal^s' % tile, symbol)
        menu_textures.put_bc4(bntx, 'icon_main_menu_%s_glow^s' % tile, glow(symbol))
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
    main_arc = frame_like(icons(main_arc))
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
