"""Project-authored vector icons and card masks, encoded into local BC4 slots.

Colour artwork uses native-resolution uncompressed RGBA8 surfaces appended
inside BNTX. Texture names and resource pointers are preserved. The Tegra
block layout uses the project's existing nutexb tool.
BC4 is two endpoints followed by sixteen 3-bit indices (the standard RGTC1
format). No texture data from the game is embedded in this source.
"""
import math
from pathlib import Path
import struct
import sys
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'fighter_sdk' / 'tools'))
from brawl.nutexb import swizzle, swizzled_size, block_height
from bflyt_patch import sarc_files
import menu_design


def icon(name, size=512):
    """Rasterise authored 128-unit vector geometry, at 4x for clean edges."""
    im = Image.new('L', (size, size))
    d = ImageDraw.Draw(im)
    s = size / 128
    box = lambda p: tuple(round(x * s) for x in p)
    if name == 'smash':
        d.ellipse(box((17,17,111,111)), fill=255)
        d.rectangle(box((56,10,65,118)), fill=0)
        d.rectangle(box((10,76,118,85)), fill=0)
    elif name == 'settings':
        points = []
        for i in range(80):
            a = math.tau * i / 80
            r = 47 if i % 8 in (0, 1, 6, 7) else 38
            points.append((round((64 + math.cos(a) * r) * s), round((64 + math.sin(a) * r) * s)))
        d.polygon(points, fill=255)
        d.ellipse(box((47, 47, 81, 81)), fill=0)
    elif name == 'friends':
        for bounds in ((37, 55, 63, 81), (69, 55, 95, 81)):
            d.ellipse(box(bounds), fill=255)
        for bounds in ((25, 84, 73, 113), (61, 84, 109, 113)):
            d.rounded_rectangle(box(bounds), radius=12*s, fill=255)
        for r in (17, 31, 45):
            d.arc(box((64-r, 52-r, 64+r, 52+r)), 222, 318, fill=255, width=round(7*s))
    elif name == 'ranked':
        d.arc(box((17, 28, 57, 72)), 80, 280, fill=255, width=round(9*s))
        d.arc(box((71, 28, 111, 72)), 260, 100, fill=255, width=round(9*s))
        d.polygon([box(p) for p in ((37,24),(91,24),(87,57),(78,72),(50,72),(41,57))], fill=255)
        d.rounded_rectangle(box((58, 66, 70, 99)), radius=3*s, fill=255)
        d.rounded_rectangle(box((39, 99, 89, 110)), radius=4*s, fill=255)
    elif name == 'power':                                    # exit: the power symbol
        d.arc(box((24, 26, 104, 106)), 300, 240, fill=255, width=round(11*s))
        d.rounded_rectangle(box((58, 12, 70, 66)), radius=6*s, fill=255)
    elif name == 'wireless':                                  # local wireless: a console with waves
        d.rounded_rectangle(box((30, 70, 98, 112)), radius=8*s, fill=255)
        d.rounded_rectangle(box((40, 78, 88, 104)), radius=4*s, fill=0)
        for r in (14, 28, 42):
            d.arc(box((64-r, 60-r, 64+r, 60+r)), 220, 320, fill=255, width=round(8*s))
    elif name == 'arena':                                     # the Arena mark: an A with a cut bar
        d.polygon([box(p) for p in ((64, 14), (112, 112), (88, 112), (64, 60), (40, 112), (16, 112))], fill=255)
        d.polygon([box(p) for p in ((44, 86), (84, 86), (90, 98), (38, 98))], fill=255)
    else:
        raise ValueError('unknown icon ' + name)
    return im


def put_bc4(bntx, name, im):
    """an authored greyscale image into one existing single-mip BC4 slot of a BNTX (bytearray, in place)"""
    b = texture_slots(bntx)[name]
    fmt = struct.unpack_from('<I', bntx, b+0x1c)[0]
    w, h = struct.unpack_from('<II', bntx, b+0x24)
    mips = struct.unpack_from('<H', bntx, b+0x16)[0]
    size = struct.unpack_from('<I', bntx, b+0x50)[0]
    bh = struct.unpack_from('<I', bntx, b+0x34)[0]
    ptr = struct.unpack_from('<Q', bntx, b+0x70)[0]
    offset = struct.unpack_from('<Q', bntx, ptr)[0]
    bw, hh = (w+3)//4, (h+3)//4
    if fmt != 0x1d01 or mips != 1 or (1 << bh) != block_height(hh) or swizzled_size(bw*8, hh, 1 << bh) != size:
        raise ValueError('unsupported BC4 slot ' + name)
    pixels = swizzle(encode_bc4(im.resize((w, h), Image.Resampling.LANCZOS)), bw, hh, bpp=8)
    if len(pixels) != size:
        raise ValueError('texture size changed')
    bntx[offset:offset+size] = pixels


def get_bc4(bntx, name):
    """one single-mip BC4 slot of a BNTX as a greyscale image (the reverse of put_bc4)"""
    b = texture_slots(bntx)[name]
    if struct.unpack_from('<I', bntx, b+0x1c)[0] != 0x1d01:
        raise ValueError('not a BC4 slot ' + name)
    w, h = struct.unpack_from('<II', bntx, b+0x24)
    size = struct.unpack_from('<I', bntx, b+0x50)[0]
    offset = struct.unpack_from('<Q', bntx, struct.unpack_from('<Q', bntx, b+0x70)[0])[0]
    bw, hh = (w+3)//4, (h+3)//4
    linear = swizzle(bytes(bntx[offset:offset+size]), bw, hh, bpp=8, to_linear=True)
    return Image.frombytes('L', (bw*4, hh*4), linear[:bw*hh*8], 'bcn', 4).crop((0, 0, w, h))


def card(geo, border=False):
    """The card shape at twice its screen size (menu_design.py geometry): the mask is the filled rounded rectangle;
    the border texture is a solid outline over a faint fill (the selected card's light wash)."""
    w, h, r, b = 2 * geo['w'], 2 * geo['h'], 2 * geo['radius'], 2 * geo['border']
    im = Image.new('L', (w, h))
    d = ImageDraw.Draw(im)
    if border:
        d.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=255)
        d.rounded_rectangle((b, b, w - 1 - b, h - 1 - b), radius=max(r - b, 0), fill=0)
    else:
        d.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=255)
    return im


def encode_bc4(im):
    w, h = im.size
    px = im.load()
    out = bytearray()
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            values = [px[min(w-1,x+dx), min(h-1,y+dy)] for dy in range(4) for dx in range(4)]
            hi, lo = max(values), min(values)
            if hi == lo:
                out += bytes((hi, lo)) + bytes(6)
                continue
            palette = [hi,lo] + [((7-i)*hi+i*lo)//7 for i in range(1,7)]
            indices = 0
            for i, v in enumerate(values):
                k = min(range(8), key=lambda k: abs(palette[k]-v))
                indices |= k << (3*i)
            out += bytes((hi,lo)) + indices.to_bytes(6,'little')
    return bytes(out)


def texture_slots(data):
    if data[:4] != b'BNTX' or data[0x20:0x24] != b'NX  ':
        raise ValueError('expected Switch BNTX')
    count = struct.unpack_from('<I', data, 0x24)[0]
    array = struct.unpack_from('<Q', data, 0x28)[0]
    result = {}
    for i in range(count):
        b = struct.unpack_from('<Q', data, array+8*i)[0]
        if data[b:b+4] != b'BRTI':
            raise ValueError('invalid texture pointer')
        p = struct.unpack_from('<Q', data, b+0x60)[0]
        length = struct.unpack_from('<H',data,p)[0]
        name = data[p+2:p+2+length].decode('utf-8')
        result[name] = b
    return result


def patch(archive, colour_images=None):
    d = bytearray(archive)
    start, end = sarc_files(d)['timg/__Combined.bntx']
    bntx = bytearray(d[start:end])
    slots = texture_slots(bntx)
    replacements = {}
    for dest, design in (('melee','smash'), ('other','settings'), ('spirits','friends'), ('colle','ranked')):
        for state in ('normal','glow'):
            replacements['icon_main_menu_%s_%s^s' % (dest,state)] = icon(design)
    # the label's soft shadow: empty (it reached outside the cards once the label moved to the left)
    replacements['main_menu_btn3_00_txt_sdw^s'] = Image.new('L', (8, 8))
    for tile in ('melee','splits','other','colle'):
        geo = menu_design.texture_geometry(tile)
        replacements['main_menu_btn3_00_%s_mask^s' % tile] = card(geo)
        replacements['main_menu_btn3_00_%s_circle^s' % tile] = card(geo, border=True)
    frames = {}
    if menu_design.FRAME:
        from menu_art import card_art, brand, chrome_art
        for tile in ('melee','splits','other','colle'):
            frames['main_menu_btn3_00_%s_frame^u' % tile] = card_art('spirits' if tile == 'splits' else tile)
        frames['main_menu_btn3_00_eshop_frame^u'] = brand()
        frames['main_menu_btn3_00_online_frame^u'] = chrome_art()
    if colour_images is not None:
        replacements, frames = {}, colour_images
    for name, im in replacements.items():
        b = slots[name]
        fmt = struct.unpack_from('<I', bntx, b+0x1c)[0]
        w,h = struct.unpack_from('<II',bntx,b+0x24)
        mips = struct.unpack_from('<H',bntx,b+0x16)[0]
        size = struct.unpack_from('<I',bntx,b+0x50)[0]
        bh = struct.unpack_from('<I',bntx,b+0x34)[0]
        # The original Spirits highlight is a narrow vertical strip. Give the authored horizontal
        # card a balanced surface within exactly the same allocation, instead of stretching 98 pixels.
        if name == 'main_menu_btn3_00_splits_circle^s' and (w,h) == (98,340) and size == 32768:
            w,h,bh = 512,128,2
            struct.pack_into('<II',bntx,b+0x24,w,h)
            struct.pack_into('<I',bntx,b+0x34,bh)
        ptr = struct.unpack_from('<Q',bntx,b+0x70)[0]
        offset = struct.unpack_from('<Q',bntx,ptr)[0]
        bw,hh = (w+3)//4, (h+3)//4
        if fmt != 0x1d01 or mips != 1 or (1 << bh) != block_height(hh) or swizzled_size(bw*8,hh,1 << bh) != size:
            raise ValueError('unsupported BC4 slot ' + name)
        mask = im.resize((w,h),Image.Resampling.LANCZOS)
        linear = encode_bc4(mask)
        pixels = swizzle(linear,bw,hh,bpp=8)
        if len(pixels) != size:
            raise ValueError('texture size changed')
        bntx[offset:offset+size] = pixels
    if frames:
        from texture_surface import replace_rgba, replace_sarc_member
        bntx = replace_rgba(bntx, frames)
        d = replace_sarc_member(d, 'timg/__Combined.bntx', bntx)
    else:
        d[start:end] = bntx
    return bytes(d), sorted(replacements) + sorted(frames)


BC7_WEIGHTS4 = (0, 4, 9, 13, 17, 21, 26, 30, 34, 38, 43, 47, 51, 55, 60, 64)


def encode_bc7_mode6(im):
    """RGBA image -> BC7 blocks, mode 6 only (one subset, RGBA endpoints of 7 bits + a shared p-bit each, 4-bit
    indices). Enough for flat colours with soft alpha edges (BC7 layout per the public Khronos format spec)."""
    w, h = im.size
    px = im.load()
    out = bytearray()
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            vals = [px[min(w-1, x+dx), min(h-1, y+dy)] for dy in range(4) for dx in range(4)]
            lo = [min(v[c] for v in vals) for c in range(4)]
            hi = [max(v[c] for v in vals) for c in range(4)]
            # 8-bit endpoint = 7 bits << 1 | p-bit; p-bit 0 for the low end, 1 for the high end
            e0 = [c >> 1 for c in lo]; e1 = [c >> 1 for c in hi]
            q0 = [(c << 1) | 0 for c in e0]; q1 = [(c << 1) | 1 for c in e1]
            pal = [[(q0[c] * (64 - wt) + q1[c] * wt + 32) >> 6 for c in range(4)] for wt in BC7_WEIGHTS4]
            idx = [min(range(16), key=lambda k: sum((pal[k][c] - v[c]) ** 2 for c in range(4))) for v in vals]
            if idx[0] >= 8:                  # the anchor index has its top bit implied 0: swap the ends
                e0, e1 = e1, e0
                idx = [15 - i for i in idx]
                p0, p1 = 1, 0
            else:
                p0, p1 = 0, 1
            bits, n = 1 << 6, 7              # mode 6: six zero bits, then a one
            for c in range(4):
                bits |= e0[c] << n; n += 7
                bits |= e1[c] << n; n += 7
            bits |= p0 << n; n += 1
            bits |= p1 << n; n += 1
            for i, v in enumerate(idx):
                width = 3 if i == 0 else 4
                bits |= v << n; n += width
            out += bits.to_bytes(16, 'little')
    return bytes(out)


def frame_texture(geo):
    """The selected card's outline: white, rounded like the card, transparent inside."""
    w, h, r, b = 2 * geo['w'], 2 * geo['h'], 2 * geo['radius'], 2 * geo['border']
    alpha = Image.new('L', (w, h))
    d = ImageDraw.Draw(alpha)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=255)
    d.rounded_rectangle((b, b, w - 1 - b, h - 1 - b), radius=max(r - b, 0), fill=0)
    im = Image.new('RGBA', (w, h), (255, 255, 255, 0))
    im.putalpha(alpha)
    return im
