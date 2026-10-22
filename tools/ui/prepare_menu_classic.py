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
import menu_shapes
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
# The tiles (layout units: 1920 x 1080, centre 0, y up), drawn by menu_shapes.py. Online LDN is Smash's tile mirrored
# (its cut for the centre circle on the left), cut straight on the right; Online Ranked is cut straight on the right
# too. Settings and Exit are rectangles in the column on their right, Settings level with LDN (and Smash), Exit with
# Online Ranked. A pane is (centre x, centre y, width, height); their selection cursors (window panes of the centre
# layout) are centred on the new tiles.
RIGHT_EDGE = 690                                     # LDN's and Online Ranked's right edge
COL_LEFT, COL_RIGHT = 720, 940                       # the Settings / Exit column
TOP, MID_BOTTOM, LOW_TOP, BOTTOM = 423, -63, -115, -432   # Smash's top and bottom, Online Ranked's
CIRCLE_X = 6                                         # the centre circle's x (the centre of Smash's cut, measured)
LDN_PANE = (2 * CIRCLE_X + 514, 178, 1000, 560)      # Smash's mask (-514, 178) mirrored about the circle
LDN_LEFT = 2 * CIRCLE_X + 45                         # (Smash's visible right edge is -45)
RANKED_PANE = (311, -274, 872, 384)                  # the game's
_cw, _cx = COL_RIGHT - COL_LEFT, (COL_LEFT + COL_RIGHT) / 2
SET_PANE = (_cx, (TOP + MID_BOTTOM) / 2, _cw, TOP - MID_BOTTOM)
EXIT_PANE = (_cx, (LOW_TOP + BOTTOM) / 2, _cw, LOW_TOP - BOTTOM)
EXIT_CURSOR = 20                                     # Exit's bright border: this much larger than the tile
ESHOP_GROUP = (158, -615)                            # the eShop group's offset (Exit's panes are inside it)
LDN_X = 515                                          # LDN's button (its icon and name), right of the centre circle
RANKED_LEFT = -93                                    # Online Ranked's visible left edge
FONT = [62, 146.9]                                   # every tile's name: Online Ranked's height, narrower
_lx, _ly, _lw, _lh = (LDN_LEFT + RIGHT_EDGE) / 2, (TOP + MID_BOTTOM) / 2, RIGHT_EDGE - LDN_LEFT, TOP - MID_BOTTOM
_sx, _sy, _sw, _sh = SET_PANE
_ex, _ey, _ew, _eh = EXIT_PANE
_rx, _rw = (RANKED_LEFT + RIGHT_EDGE) / 2, RIGHT_EDGE - RANKED_LEFT


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
    'mask_other': {'pos': LDN_PANE[:2], 'size': LDN_PANE[2:]},
    'null_btn_other': {'pos': [LDN_X, _ly]},
    # the frame and hit box on the tile, offset from the button (which stays right of the centre circle)
    'set_parts_btn_other': {'parts': dict({'frame': {'pos': [LDN_PANE[0] - LDN_X, LDN_PANE[1] - _ly], 'size': LDN_PANE[2:]},
                                           'circle_position': {'scale': [0, 0]}},
                                          **_hits(_lw / 2, _lh / 2, _lx - LDN_X), **_font)},
    'mask_colle': {'pos': [_sx, _sy], 'size': [_sw, _sh]},
    # Settings at scale 1, its frame the tile; its icon (above the centre) and name (below) smaller inside the button
    # (the button's blink_scale is offset -17, 2 in this tile; the part's icon sits 149 above icon_positoin)
    'null_btn_colle': {'pos': [_sx, _sy]},
    'set_parts_btn_colle': {'pos': [0, 0], 'size': [_sw, _sh], 'parts': {
        'frame': {'pos': [0, 0], 'size': [_sw, _sh]},
        'icon_positoin': {'pos': [17, 50 - 149 * 0.75], 'scale': [0.75, 0.75]},
        'txt_position': {'pos': [17, -100], 'scale': [0.38, 0.38]},
        'txt_on': {'font_size': FONT, 'size': [600, 96]},
        'txt_off': {'font_size': FONT, 'size': [600, 96]},
        'circle_position': {'scale': [0, 0]},
        **_hits(_sw / 2, _sh / 2),
    }},
    # Exit: its mask and button on the rectangle (inside the eShop group), the frame and hit box the tile's
    'mask_eshop': {'pos': [_ex - ESHOP_GROUP[0], _ey - ESHOP_GROUP[1]], 'size': [_ew, _eh]},
    'set_parts_btn_eshop': {'pos': [_ex - ESHOP_GROUP[0], _ey - ESHOP_GROUP[1]], 'parts': {
        'frame': {'pos': [0, 0], 'size': [_ew, _eh]}, 'icon_positoin': {'pos': [45, -76]},   # the icon centred
        **_hits(_ew / 2, _eh / 2)}},
    # Online Ranked: the frame is redrawn on its own pane (menu_shapes); its hit box ends at the straight edge
    'set_parts_btn_online': {'parts': dict(_font, **_hits(_rw / 2, 155, _rx - RANKED_PANE[0], 5))},
})
# the help line above the tiles: the footer moved up by its height plus the screen's (its bar then fills the top band)
EDIT_FOOTER = {'main_menu_footer.bflyt': {'RootPane': {'pos': [0, 966]}}}
# the cursors, centred on their tiles (the game's extend past the screen's edge)
EDIT_MAIN['main_menu_lct_center_00.bflyt'] = {
    # (LDN's drew 40 narrower: measured)
    'other_crs_square_01': {'pos': [_lx, _ly]},
    'sel_csr_blink_04': {'size': [_lw + 48, _lh + 8]}, 'sel_csr_hl_00_add_03': {'size': [_lw + 48, _lh + 8]},
    'sel_csr_hl_01_add_03': {'size': [_lw + 48, _lh + 8]},
    'other_crs_00': {'pos': [_lx, _ly], 'size': [_lw + 58, _lh + 18]},
    # (Settings' cursor drew 30 narrower and 60 shorter, 9 right of and 30 above its centre: measured)
    'collection_crs_square_01': {'pos': [_sx - 9, _sy - 30]},
    'sel_csr_blink_07': {'size': [_sw + 38, _sh + 68]}, 'sel_csr_hl_00_add_06': {'size': [_sw + 38, _sh + 68]},
    'sel_csr_hl_01_add_06': {'size': [_sw + 38, _sh + 68]},
    'collection_crs_00': {'pos': [_sx - 9, _sy - 30], 'size': [_sw + 48, _sh + 78]},
    # Online Ranked's (scaled 1.05 in the game) ends at the straight edge
    'online_crs_square_00': {'pos': [_rx, -297]},
    'sel_csr_blink_09': {'size': [(_rw + 8) / 1.05, 380]}, 'sel_csr_hl_00_add_09': {'size': [(_rw + 8) / 1.05, 380]},
    'sel_csr_hl_00_add_08': {'size': [(_rw + 8) / 1.05, 380]},
    'online_crs': {'pos': [_rx, -300], 'size': [_rw + 18, 380]},
    # Exit's cursor: its windows (at (493, -95) in their square, scaled 1.05) its dark rim, one-frame windows like
    # Settings' (cursor_like; measured 20 x 24 smaller and 10, 30 off); its bright border the eshop_crs picture, its
    # texture redrawn as a rectangle (tile_shapes); its glow and name balloon are not used
    'echop_crs_square_01': {'pos': [_ex - 493 - 10, _ey + 95 - 30]},
    **{w: {'size': [(_ew + 28) / 1.05, (_eh + 32) / 1.05], 'window_frames': [32, 32, 32, 32]}
       for w in ('sel_csr_blink_11', 'sel_csr_hl_00_add_11', 'sel_csr_hl_00_add_12')},
    'eshop_crs': {'pos': [_ex - 10, _ey - 30], 'size': [_ew + EXIT_CURSOR, _eh + EXIT_CURSOR],   # (10, 30 off: measured)
                  'material_white': '2a9bffff', 'texture_uv': True},    # Settings' cursor colour (measured)
    'eshop_glow': {'scale': [0, 0]},
    'bg_bln': {'scale': [0, 0]}, 'txt_eshop': {'scale': [0, 0]},     # (nul_bln's own scale is animated)
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


# Exit's cursor windows (a slanted left and right frame) drawn as Settings' (one rectangular frame): (window, from)
CURSOR_LIKE = (('sel_csr_blink_11', 'sel_csr_blink_07'), ('sel_csr_hl_00_add_11', 'sel_csr_hl_00_add_06'),
               ('sel_csr_hl_00_add_12', 'sel_csr_hl_01_add_06'))


def cursor_like(data):
    """each CURSOR_LIKE window gets the other's frame count and flags (wnd1, at 0x64: one frame for the four corners), and
    its frame's and content's materials the other's (texture, colours, texture SRT: the records are the same size);
    the materials stay its own, so they follow Exit's selection animations"""
    import struct
    d = bytearray(data)
    s, e = bflyt_patch.sarc_files(d)['blyt/main_menu_lct_center_00.bflyt']
    idx = bflyt_patch.panes(d, s, e)
    materials = bflyt_patch.material_offsets(d, s, e) + [None]

    def used(o):
        """(content material, first frame material) indices of a window"""
        table = o + struct.unpack_from('<I', d, o + 0x6C)[0]
        return (struct.unpack_from('<H', d, o + struct.unpack_from('<I', d, o + 0x68)[0] + 16)[0],
                struct.unpack_from('<H', d, o + struct.unpack_from('<I', d, table)[0])[0])
    for window, source in CURSOR_LIKE:
        o, src = idx[window], idx[source]
        d[o + 0x64:o + 0x66] = d[src + 0x64:src + 0x66]
        for dst_i, src_i in zip(used(o), used(src)):
            dm, sm = materials[dst_i], materials[src_i]
            length = sm and (materials[src_i + 1] - sm)
            if materials[dst_i + 1] - dm != length:
                raise ValueError('cursor materials differ in size: %d, %d' % (dst_i, src_i))
            d[dm + 28:dm + length] = d[sm + 28:sm + length]
    return bytes(d)


def tile_shapes(data):
    """the tiles' masks and frames (menu_shapes.py) into the archive's BNTX"""
    files = bflyt_patch.sarc_files(data)
    s, e = files['timg/__Combined.bntx']
    bntx = data[s:e]
    masks = {'other': menu_shapes.game_mask(bntx, 'melee', LDN_PANE, mirror=True, right=RIGHT_EDGE),
             'online': menu_shapes.game_mask(bntx, 'online', RANKED_PANE, right=RIGHT_EDGE),
             'colle': menu_shapes.rectangle(SET_PANE), 'eshop': menu_shapes.rectangle(EXIT_PANE)}
    bntx, frames = menu_shapes.write(bntx, masks)
    frames['main_menu_btn3_00_eshop_crs_00^t'] = menu_shapes.outline((_ew + EXIT_CURSOR, _eh + EXIT_CURSOR), 14)
    return replace_sarc_member(bytearray(data[:s] + bntx + data[e:]), 'timg/__Combined.bntx', replace_rgba(bntx, frames))


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
    main_arc = cursor_like(tile_shapes(icons(main_arc)))
    main_arc, m, t = recolour_archive(main_arc)
    outputs[MAIN], cur = menu_recolor.accent_windows(main_arc, 'main_menu_lct_center_00.bflyt')   # after: kept bright
    print('main menu: %d material colours, %d textures recoloured, %d cursor colours -> accent, %d icons' % (m, t, cur, 2 * len(ICONS)))
    outputs[SIDEBAR], _ = bflyt_patch.apply(arc.get(SIDEBAR), HIDE_SIDEBAR)
    outputs[FOOTER], m, t = recolour_archive(bflyt_patch.apply(arc.get(FOOTER), EDIT_FOOTER)[0])
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
