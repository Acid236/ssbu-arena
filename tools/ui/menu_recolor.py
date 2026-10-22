"""Arena colours for the game's own menu art (the classic menu: the original layout, recoloured).

The colour surfaces of a layout archive's BNTX (BC7 / BC3 sRGB) are decoded from the owner's dump, recoloured and
written back as RGBA8 surfaces (texture_surface.replace_rgba: names and pointers kept). Recolouring keeps each pixel's
lightness and the texture's own shading and patterns; only the hue moves to the Arena palette (the launcher's navy and
blue), and grey or white pixels (outlines, text, highlights) stay as they are. The lightness of each texture is brought
to one level per kind (tiles navy, glows bright blue), so tiles that were red, green, yellow or pink look alike.
Artwork (mode previews, the centre picture, logos) is left alone. No game content in this file.
"""
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'fighter_sdk' / 'tools'))
from brawl.nutexb import swizzle
from menu_textures import texture_slots

# lightness -> colour stops (sRGB): the launcher's background, panels, accent and its light tint
PALETTE = ((0.00, (4, 10, 22)), (0.25, (10, 36, 84)), (0.50, (22, 86, 170)), (0.75, (79, 184, 245)), (1.00, (214, 240, 255)))
SKIP = ('preview', 'center_image', 'logo_ami', 'vip_star', 'badge', 'icon_color')   # artwork: kept
FORMATS = {0x2006: 7, 0x2001: 7, 0x1c06: 3, 0x1c01: 3}                                 # BC7 / BC3 (sRGB, unorm) -> bcn n


def wanted(name):
    return not any(s in name for s in SKIP)


def decode(bntx, base):
    """(RGBA image, format) of one BC3 / BC7 single-mip surface, or None"""
    fmt = struct.unpack_from('<I', bntx, base + 0x1c)[0]
    if fmt not in FORMATS or struct.unpack_from('<H', bntx, base + 0x16)[0] != 1:
        return None
    w, h = struct.unpack_from('<II', bntx, base + 0x24)
    size = struct.unpack_from('<I', bntx, base + 0x50)[0]
    ptr = struct.unpack_from('<Q', bntx, base + 0x70)[0]
    offset = struct.unpack_from('<Q', bntx, ptr)[0]
    bw, bh = (w + 3) // 4, (h + 3) // 4
    linear = swizzle(bytes(bntx[offset:offset + size]), bw, bh, bpp=16, to_linear=True)
    im = Image.frombytes('RGBA', (bw * 4, bh * 4), linear[:bw * bh * 16], 'bcn', FORMATS[fmt])
    return im.crop((0, 0, w, h)), fmt


def colourfulness(mx, mn):
    """0 for greys, whites and black, 1 for clear colours, dark ones too (a deep red 180000 counts as red):
    the saturation (chroma / brightest channel), faded out near black"""
    sat = (mx - mn) / np.maximum(mx, 1e-6)
    return np.clip((sat - 0.12) / 0.28, 0.0, 1.0) * np.clip(mx / 0.04, 0.0, 1.0)


def recolour(im, target):
    """Arena hue, lightness moved so the coloured pixels average `target`; grey pixels kept"""
    a = np.asarray(im.convert('RGBA'), dtype=np.float32) / 255.0
    rgb, alpha = a[..., :3], a[..., 3]
    mx, mn = rgb.max(axis=2), rgb.min(axis=2)
    light = (mx + mn) / 2
    f = colourfulness(mx, mn)
    sel = (alpha > 16 / 255) & (f > 0.5)
    shift = target - (float(light[sel].mean()) if sel.any() else target)
    l2 = np.clip(light + shift, 0.0, 1.0)
    stops = np.array([p for p, _ in PALETTE], dtype=np.float32)
    cols = np.array([c for _, c in PALETTE], dtype=np.float32) / 255.0
    mapped = np.stack([np.interp(l2, stops, cols[:, i]) for i in range(3)], axis=2)
    out = rgb * (1 - f[..., None]) + mapped * f[..., None]
    res = np.concatenate([out, alpha[..., None]], axis=2)
    return Image.fromarray((np.clip(res, 0, 1) * 255 + 0.5).astype(np.uint8), 'RGBA')


MATERIAL_LIGHT, VERTEX_LIGHT, ANIM_LIGHT = 1.0, 0.55, 0.8   # lightness kept for materials (text, icons); backgrounds darker


def recolour_rgb(r, g, b, scale=1.0):
    """one colour of a material (0..255): Arena hue at the same lightness (a little darker), greys kept"""
    c = np.array([[[r, g, b]]], dtype=np.float32) / 255.0
    mx, mn = c.max(), c.min()
    f = float(colourfulness(mx, mn))
    if f <= 0:
        return r, g, b
    l = (mx + mn) / 2 * scale
    stops = [p for p, _ in PALETTE]
    m = [np.interp(l, stops, [col[i] for _, col in PALETTE]) for i in range(3)]
    return tuple(int(round((1 - f) * v + f * mv)) for v, mv in zip((r, g, b), m))


def recolour_materials(archive):
    """the black and white colours of every material of every layout in the archive (bflyt_patch.material_colours'
    offsets), recoloured in place: the tiles' and buttons' fills, which tint grey masks"""
    from bflyt_patch import sarc_files, material_offsets, panes
    d = bytearray(archive)
    n = 0

    def fix(at, scale=MATERIAL_LIGHT):
        nonlocal n
        r, g, b = d[at:at + 3]
        nr = recolour_rgb(r, g, b, scale)
        if nr != (r, g, b):
            d[at:at + 3] = bytes(nr)
            n += 1
    for name, (s, e) in sarc_files(d).items():
        if not name.startswith('blyt/'):
            continue
        for mat in material_offsets(d, s, e):
            fix(mat + 36); fix(mat + 40)
        for o in panes(d, s, e).values():               # pictures' vertex colours (the tiles' backgrounds are gradients)
            if d[o:o + 4] == b'pic1':
                for i in range(4):
                    fix(o + 0x54 + 4 * i, VERTEX_LIGHT)
    return bytes(d), n


def recolour_animations(archive):
    """colour curves of every animation (BFLAN pai1: FLVC vertex colours, FLMC material colours), recoloured in place
    where the R, G and B curves of one colour have keys at the same frames (hermite: frame, value, slope as f32; step:
    frame f32, value u16). Animation layout after the public BFLAN documentation (Switch Toolbox's reader)."""
    from bflyt_patch import sarc_files
    d = bytearray(archive)
    n = 0
    for name, (s, e) in sarc_files(d).items():
        if not name.endswith('.bflan') or d[s:s + 4] != b'FLAN':
            continue
        o = s + struct.unpack_from('<H', d, s + 6)[0]      # header size
        while o + 8 <= e:
            mag, size = d[o:o + 4], struct.unpack_from('<I', d, o + 4)[0]
            if mag == b'pai1':
                n += _recolour_pai1(d, o)
            if size < 8:
                break
            o += size
    return bytes(d), n


def _recolour_pai1(d, pai):
    n = 0
    count = struct.unpack_from('<H', d, pai + 0xE)[0]
    table = pai + struct.unpack_from('<I', d, pai + 0x10)[0]
    for i in range(count):
        entry = pai + struct.unpack_from('<I', d, table + 4 * i)[0]
        tags = d[entry + 28]
        for t in range(tags):
            tag = entry + struct.unpack_from('<I', d, entry + 32 + 4 * t)[0]
            magic = bytes(d[tag:tag + 4])
            if magic not in (b'FLVC', b'FLMC'):
                continue
            curves = {}
            for k in range(d[tag + 4]):
                tg = tag + struct.unpack_from('<I', d, tag + 8 + 4 * k)[0]
                target, ctype, keys = d[tg + 1], d[tg + 2], struct.unpack_from('<H', d, tg + 4)[0]
                curves[target] = (tg + struct.unpack_from('<I', d, tg + 8)[0], ctype, keys)
            # one colour = targets base+0, +1, +2 (R, G, B): FLVC corners 0, 4, 8, 12; FLMC black 0, white 4
            for base in (0, 4, 8, 12):
                if not any(base + c in curves for c in range(3)):
                    continue
                # each channel's keys, read before any is changed: (address of the value, frame, value, is hermite);
                # a channel the animation does not move counts as 0 (a red-only pulse is read as pure red)
                chans = []
                for c in range(3):
                    if base + c not in curves:
                        chans.append([])
                        continue
                    kp, ctype, keys = curves[base + c]
                    step = 12 if ctype == 2 else 8
                    ks = []
                    for k in range(keys):
                        a = kp + step * k
                        v = struct.unpack_from('<f', d, a + 4)[0] if ctype == 2 else struct.unpack_from('<H', d, a + 4)[0]
                        ks.append((a + 4, struct.unpack_from('<f', d, a)[0], float(v), ctype == 2))
                    chans.append(ks)
                # every key of one channel: the other two channels at that frame (linear between their keys)
                for c, ks in enumerate(chans):
                    for addr, frame, v, herm in ks:
                        rgb = [v if cc == c else _at(chans[cc], frame) for cc in range(3)]
                        col = [int(max(0, min(255, round(x)))) for x in rgb]
                        nv = recolour_rgb(*col, ANIM_LIGHT)[c]
                        if nv == col[c]:
                            continue
                        if herm:
                            struct.pack_into('<f', d, addr, float(nv))
                        else:
                            struct.pack_into('<H', d, addr, nv)
                        n += 1
    return n


def _at(keys, frame):
    """a channel's value at a frame, linear between its keys (constant outside)"""
    if not keys:
        return 0.0
    if frame <= keys[0][1]:
        return keys[0][2]
    for (_, f0, v0, _), (_, f1, v1, _) in zip(keys, keys[1:]):
        if frame <= f1:
            return v0 + (v1 - v0) * ((frame - f0) / (f1 - f0) if f1 > f0 else 0)
    return keys[-1][2]


def target_for(name):
    if 'glow' in name:
        return 0.80
    if name.endswith('_frame^u') or ('crs' in name and 'base' in name):       # tile outlines, the selected button's fill
        return 0.66
    return 0.30


def recolour_bntx(bntx):
    """-> {texture name: recoloured RGBA image} for every colour surface worth recolouring"""
    out = {}
    for name, base in texture_slots(bntx).items():
        if not wanted(name):
            continue
        got = decode(bntx, base)
        if got:
            out[name] = recolour(got[0], target_for(name))
    return out
