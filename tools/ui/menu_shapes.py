"""Masks and frames for the classic Arena menu's tiles, drawn from the game's own (prepare_menu_classic.py).

A tile is a mask (its shape, BC4 in its existing slot) and a frame (the mask's outline: a LINE-wide line in the colour
of Smash's frame line with a dark rim just outside, like the game's). Online LDN is Smash's mask mirrored, Online Ranked
keeps its own; both are cut by a straight right edge. Settings and Exit are plain rectangles. Read from the owner's dump
at build time; no game data here.

Coordinates are layout units (1920 x 1080, centre 0, y up); a pane is (centre x, centre y, width, height), its mask one
texel per unit.
"""
import numpy as np
from PIL import Image, ImageFilter

import menu_recolor
import menu_textures

LINE = 5                                           # Smash's frame line, in units


def _xs(pane):
    cx, cy, w, h = pane
    return np.broadcast_to(cx - w / 2 + np.arange(w) + 0.5, (h, w))


def game_mask(bntx, tile, pane, mirror=False, right=None):
    """a game tile's mask (main_menu_btn3_00_<tile>_mask) at the pane's size, mirrored; with right, each row filled out
    to x = right and cut there (a straight right edge)"""
    m = np.asarray(menu_textures.get_bc4(bntx, 'main_menu_btn3_00_%s_mask^s' % tile).resize(
        (pane[2], pane[3]), Image.Resampling.BILINEAR)) > 128
    if mirror:
        m = m[:, ::-1]
    if right is not None:
        first = np.where(m.any(axis=1), m.argmax(axis=1), m.shape[1])
        m = (np.arange(m.shape[1])[None, :] >= first[:, None]) & (_xs(pane) <= right)
    return m


def cut_rectangle(pane, left, right, top, bottom, circle):
    """a rectangle (layout units) less a disc (x, y, r): a tile whose corner follows the centre circle's ring"""
    xs = _xs(pane)
    ys = np.broadcast_to((pane[1] + pane[3] / 2 - np.arange(pane[3]) - 0.5)[:, None], xs.shape)
    x0, y0, r = circle
    return (xs >= left) & (xs <= right) & (ys <= top) & (ys >= bottom) & (np.hypot(xs - x0, ys - y0) > r)


def rectangle(pane):
    return np.ones((pane[3], pane[2]), bool)


def frame(mask, colour):
    """the outline of a mask (a LINE-wide line inside its edge, a dark rim just outside), RGBA"""
    pad = LINE + 2                                  # the image's own edges are the tile's edges too
    m = Image.fromarray(np.pad(mask, pad).astype(np.uint8) * 255)
    inner = (np.asarray(m.filter(ImageFilter.MinFilter(2 * LINE + 1))) > 128)[pad:-pad, pad:-pad]
    outer = (np.asarray(m.filter(ImageFilter.MaxFilter(3))) > 128)[pad:-pad, pad:-pad]
    out = np.zeros(mask.shape + (4,), np.uint8)
    out[outer & ~mask] = (0, 0, 0, 255)
    out[mask & ~inner] = colour
    return Image.fromarray(out, 'RGBA')


def outline(size, width):
    """a rectangle's border, `width` wide, as a mask in every channel (for a material that reads its texture as a
    mask, like the game's BC5 cursor shapes: its colour is the material's)"""
    w, h = (int(v) for v in size)
    out = np.full((h, w, 4), 255, np.uint8)
    out[width:h - width, width:w - width] = 0
    return Image.fromarray(out, 'RGBA')


def read_bc5(bntx, name):
    """one single-mip BC5 slot of a BNTX as RGBA (its two channels in R and G, A opaque)"""
    from brawl.nutexb import swizzle
    import struct
    b = menu_textures.texture_slots(bntx)[name]
    if struct.unpack_from('<I', bntx, b + 0x1c)[0] != 0x1e01:
        raise ValueError('not a BC5 slot ' + name)
    w, h = struct.unpack_from('<II', bntx, b + 0x24)
    size = struct.unpack_from('<I', bntx, b + 0x50)[0]
    offset = struct.unpack_from('<Q', bntx, struct.unpack_from('<Q', bntx, b + 0x70)[0])[0]
    bw, bh = (w + 3) // 4, (h + 3) // 4
    linear = swizzle(bytes(bntx[offset:offset + size]), bw, bh, bpp=16, to_linear=True)
    return Image.frombytes('RGB', (bw * 4, bh * 4), linear[:bw * bh * 16], 'bcn', 5).crop((0, 0, w, h)).convert('RGBA')


def line_colour(bntx):
    """Smash's frame line colour (the game's, before the Arena recolour)"""
    im, _ = menu_recolor.decode(bntx, menu_textures.texture_slots(bntx)['main_menu_btn3_00_melee_frame^u'])
    a = np.asarray(im)
    rgb = a[..., :3][a[..., 3] > 200]
    return tuple(int(v) for v in np.median(rgb[rgb.max(axis=1) > 120], axis=0)) + (255,)


def write(bntx, masks):
    """{slot tile: mask} -> (bntx with the masks in their BC4 slots, {frame slot: RGBA frame in the Arena colours})"""
    bntx = bytearray(bntx)
    colour = line_colour(bntx)
    frames = {}
    for tile, m in masks.items():
        menu_textures.put_bc4(bntx, 'main_menu_btn3_00_%s_mask^s' % tile, Image.fromarray(m.astype(np.uint8) * 255))
        frames['main_menu_btn3_00_%s_frame^u' % tile] = menu_recolor.recolour(
            frame(m, colour), menu_recolor.target_for('_frame^u'))
    return bytes(bntx), frames
