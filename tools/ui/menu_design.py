"""Arena's native menu layout (1920 x 1080, origin centre, +y up).

Regenerate menu_four_tiles.json with: python tools/ui/menu_design.py.
The original button controllers, hit regions and transitions remain native.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOP, BOTTOM = 340, -420
SIDE, GAP = 64, 28
WIDTHS = (1024, 740)
CARD_H = (TOP - BOTTOM - GAP) // 2
COL_X = (-384, 526)
ROW_Y = (TOP - CARD_H / 2, BOTTOM + CARD_H / 2)
RADIUS, BORDER = 24, 5
FRAME = True
CARDS = {
    'melee': {'cell': (0, 0), 'title': 'SMASH', 'subtitle': 'Local battles', 'icon': 'smash'},
    'other': {'cell': (1, 0), 'title': 'SETTINGS', 'subtitle': 'Display  /  Audio  /  Controls', 'icon': 'settings'},
    'spirits': {'cell': (0, 1), 'title': 'ONLINE & FRIENDS', 'subtitle': 'Local Wireless', 'icon': 'friends'},
    'colle': {'cell': (1, 1), 'title': 'ONLINE RANKED', 'subtitle': 'Climb the ladder', 'icon': 'ranked'},
}
BG_LAYOUTS = {
    'melee': ('melee_bg.bflyt', 'bg', ('bg_00', 'emitters')),
    'other': ('other_bg.bflyt', 'bg', ('bg_00', 'bg_01', 'anim_panes')),
    'spirits': ('spirits_bg.bflyt', 'bg', ('bg_00', 'bg_01', 'anim_panes')),
    'colle': ('colle_bg.bflyt', 'bg_01', ('bg_00', 'bg_02', 'anim_panes_00')),
}


def linear(colour):
    out = []
    for i in range(3):
        c = int(colour[2*i:2*i+2], 16) / 255
        out.append(round(255 * (c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4)))
    return bytes(out).hex() + colour[6:8]


def texture_geometry(name='melee'):
    if name == 'splits':
        name = 'spirits'
    return dict(w=WIDTHS[CARDS[name]['cell'][0]], h=CARD_H, radius=RADIUS, border=BORDER)


def button_parts(name='melee'):
    w, h = texture_geometry(name)['w'], CARD_H
    hw, hh = w / 2, h / 2
    return {
        'blink_scale': {'pos': [0, 0], 'scale': [1, 1]},
        'txt_sdw': {'visible': False}, 'txt_off': {'visible': False}, 'txt_on': {'visible': False},
        'icon_sdw': {'visible': False}, 'icon_off': {'visible': False}, 'icon_on': {'visible': False},
        'frame': {'visible': True, 'alpha': 255, 'pos': [0, 0], 'size': [w, h], 'texture_uv': True,
                  'vertex_colors': ['ffffffff'] * 4},
        'circle_position': {'pos': [0, 0], 'scale': [1, 1]},
        'circle_off': {'visible': False, 'size': [w, h], 'pos': [0, 0], 'texture_uv': True},
        'circle_on': {'size': [w, h], 'pos': [0, 0], 'texture_uv': True},
        'hit_00': {'pos': [-hw, hh]}, 'hit_01': {'pos': [hw, hh]}, 'hit_02': {'pos': [hw, 0]},
        'hit_03': {'pos': [hw, -hh]}, 'hit_04': {'pos': [-hw, -hh]}, 'hit_05': {'pos': [-hw, 0]},
    }


def decoration_parts(w, h):
    """Only the authored frame is drawn; these parts are absent from the cursor table."""
    p = button_parts()
    p['frame'].update(size=[w, h])
    p['circle_off'] = {'visible': False}
    p['circle_on'] = {'visible': False}
    return p


def recipe():
    main = {
        'bg': {'vertex_colors': ['ffffffff'] * 4, 'texture': 'main_menu_btn3_00_online_frame^u',
               'material_like': ['main_menu_btn3_00.bflyt', 'frame'],
               'texture_uv': True, 'material_white': 'ffffffff', 'material_black': '00000000'},
        'set_parts_text_scroll': {'visible': False},
        'center': {'visible': False},
        'nul_menu_colle_record': {'visible': False}, 'null_menu_colle': {'visible': False},
    }
    for name in ('melee', 'colle', 'spirits', 'other', 'online'):
        main['nul_preview_' + name] = {'visible': False}
    out = {'main_menu.bflyt': main, 'main_menu_btn3_00.bflyt': button_parts()}
    for name, card in CARDS.items():
        cx, cy = card['cell']
        w, h = WIDTHS[cx], CARD_H
        pos = [COL_X[cx], ROW_Y[cy]]
        main['mask_' + name] = {'visible': False, 'pos': pos, 'size': [w, h]}
        main['null_btn_' + name] = {'pos': pos}
        main['set_parts_btn_' + name] = {'pos': [0, 0], 'size': [w, h], 'parts': button_parts(name)}
        layout, fill, hide = BG_LAYOUTS[name]
        out[layout] = {p: {'visible': False} for p in (fill,) + hide}
    # Reuse unused native parts as static decoration; they cannot receive focus.
    main.update({
        'eshop': {'visible': True, 'pos': [0, 0]},
        'mask_eshop': {'visible': False},
        'set_parts_btn_eshop': {'visible': True, 'pos': [-636, 450], 'size': [520, 128],
                               'parts': decoration_parts(520, 128)},
        'online': {'visible': False}, 'mask_online': {'visible': False},
        'set_parts_btn_online': {'visible': True, 'pos': [0, 0], 'size': [1920, 1080],
                                'parts': decoration_parts(1920, 1080)},
        'null_btn_online': {'pos': [0, 0]}, 'null_btn_eshop': {'pos': [0, 0]},
    })
    return out


if __name__ == '__main__':
    (HERE / 'menu_four_tiles.json').write_text(json.dumps(recipe(), indent=2) + '\n')
    print('Arena cards: %s x %s, rows %s' % (WIDTHS, CARD_H, ROW_Y))
