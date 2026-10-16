"""UI texture file (.bntx): a picture written INTO an existing file of the same kind (the template keeps its
header, size, format and name table; only the pixel data of its one texture is replaced), so the result is never
larger than the template.

    python -I bntx.py info <file.bntx>
    python -I bntx.py check <file.bntx> <out .png>
        undoes the block layout of the template's data and decodes the blocks of the one block mode this tool
        writes (mode 6); other blocks are drawn grey. A picture for a person: if the template's own image shows,
        the layout and this tool's reading of mode 6 agree with the game's data.
    python -I bntx.py replace <template.bntx> <picture.png> <out.bntx> [--fit contain|cover]
        the PNG (8-bit RGBA or RGB, not interlaced) scaled into the template's size, block-compressed (BC7, mode 6
        only: two RGBA endpoints of 7 bits + a shared low bit each, 16 four-bit weights), laid out, written.

Template requirements: one texture, one mip level, format BC7 (0x2001 / 0x2006). This file contains no game content.
"""
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brawl import nutexb, tex0     # noqa: E402

WEIGHTS4 = (0, 4, 9, 13, 17, 21, 26, 30, 34, 38, 43, 47, 51, 55, 60, 64)


def info(d):
    if d[:4] != b'BNTX':
        raise ValueError('not a UI texture file')
    b = d.find(b'BRTI')
    if b < 0 or d.find(b'BRTI', b + 4) >= 0:
        raise ValueError('the file must hold exactly one texture')
    mips = struct.unpack_from('<H', d, b + 0x16)[0]
    fmt, _acc, w, h, _depth, _arr, bh_log2 = struct.unpack_from('<IIiiiii', d, b + 0x1C)
    size, align = struct.unpack_from('<II', d, b + 0x50)
    mip_ptr = struct.unpack_from('<Q', d, b + 0x70)[0]
    off = struct.unpack_from('<Q', d, mip_ptr)[0]
    return {'format': fmt, 'width': w, 'height': h, 'mips': mips, 'block_height_log2': bh_log2, 'data_size': size,
            'data_offset': off, 'alignment': align}


# ------------------------------------------------------------------ PNG reader (8-bit RGB / RGBA)
def read_png(path):
    with open(path, 'rb') as f:
        d = f.read()
    if d[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('not a PNG')
    p = 8
    idat = b''
    w = h = ctype = None
    while p < len(d):
        n, tag = struct.unpack_from('>I4s', d, p)
        body = d[p + 8:p + 8 + n]
        if tag == b'IHDR':
            w, h, depth, ctype, _c, _f, inter = struct.unpack('>IIBBBBB', body)
            if depth != 8 or ctype not in (2, 6) or inter:
                raise ValueError('PNG kind not handled (depth %d, colour type %d, interlace %d)' % (depth, ctype, inter))
        elif tag == b'IDAT':
            idat += body
        p += 12 + n
    raw = zlib.decompress(idat)
    bpp = 4 if ctype == 6 else 3
    stride = w * bpp
    out = bytearray(w * h * 4)
    prev = bytearray(stride)
    q = 0
    for y in range(h):
        ft = raw[q]
        line = bytearray(raw[q + 1:q + 1 + stride])
        q += 1 + stride
        if ft == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif ft == 3:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
        elif ft == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        prev = line
        if bpp == 4:
            out[y * w * 4:(y + 1) * w * 4] = line
        else:
            for x in range(w):
                out[(y * w + x) * 4:(y * w + x) * 4 + 4] = bytes(line[x * 3:x * 3 + 3]) + b'\xff'
    return w, h, out


def fit(src_w, src_h, rgba, w, h, mode):
    """Scales (bilinear) into a w x h canvas; 'contain' keeps everything (transparent bars), 'cover' fills."""
    sx, sy = w / src_w, h / src_h
    s = min(sx, sy) if mode == 'contain' else max(sx, sy)
    nw, nh = max(1, int(round(src_w * s))), max(1, int(round(src_h * s)))
    ox, oy = (w - nw) // 2, (h - nh) // 2
    out = bytearray(w * h * 4)
    for y in range(max(0, oy), min(h, oy + nh)):
        fy = (y - oy + 0.5) / s - 0.5
        y0 = min(src_h - 1, max(0, int(fy)))
        y1 = min(src_h - 1, y0 + 1)
        wy = min(1.0, max(0.0, fy - y0))
        for x in range(max(0, ox), min(w, ox + nw)):
            fx = (x - ox + 0.5) / s - 0.5
            x0 = min(src_w - 1, max(0, int(fx)))
            x1 = min(src_w - 1, x0 + 1)
            wx = min(1.0, max(0.0, fx - x0))
            a = (y0 * src_w + x0) * 4
            b = (y0 * src_w + x1) * 4
            c = (y1 * src_w + x0) * 4
            e = (y1 * src_w + x1) * 4
            o = (y * w + x) * 4
            for k in range(4):
                top = rgba[a + k] * (1 - wx) + rgba[b + k] * wx
                bot = rgba[c + k] * (1 - wx) + rgba[e + k] * wx
                out[o + k] = int(top * (1 - wy) + bot * wy + 0.5)
    return out


# ------------------------------------------------------------------ BC7 mode 6
def encode_block(px):
    """px: 16 (r, g, b, a). -> 16 bytes."""
    if all(p[3] == 0 for p in px):
        return b'\0' * 16                         # as the game's own empty blocks
    lo = min(px, key=lambda p: p[0] + p[1] + p[2] + p[3])
    hi = max(px, key=lambda p: p[0] + p[1] + p[2] + p[3])
    ends = []
    for e in (lo, hi):
        best = None
        for pbit in (0, 1):
            q = [max(0, min(127, (c - pbit + 1) >> 1)) for c in e]
            err = sum(((v << 1 | pbit) - c) ** 2 for v, c in zip(q, e))
            if best is None or err < best[0]:
                best = (err, q, pbit)
        ends.append(best)
    e0 = [v << 1 | ends[0][2] for v in ends[0][1]]
    e1 = [v << 1 | ends[1][2] for v in ends[1][1]]
    d = [b - a for a, b in zip(e0, e1)]
    dd = sum(x * x for x in d)
    idx = []
    for p in px:
        if dd == 0:
            idx.append(0)
        else:
            t = sum((p[k] - e0[k]) * d[k] for k in range(4)) / dd
            idx.append(max(0, min(15, int(t * 15 + 0.5))))
    q0, p0, q1, p1 = ends[0][1], ends[0][2], ends[1][1], ends[1][2]
    if idx[0] >= 8:                               # the first weight is stored with 3 bits
        q0, p0, q1, p1 = q1, p1, q0, p0
        idx = [15 - i for i in idx]
    v = 1 << 6
    pos = 7
    for k in range(4):
        v |= q0[k] << pos
        pos += 7
        v |= q1[k] << pos
        pos += 7
    v |= p0 << pos
    pos += 1
    v |= p1 << pos
    pos += 1
    v |= idx[0] << pos
    pos += 3
    for i in idx[1:]:
        v |= i << pos
        pos += 4
    return v.to_bytes(16, 'little')


def decode_block(b):
    """-> 16 (r, g, b, a), or None when the block is not mode 6."""
    v = int.from_bytes(b, 'little')
    if v == 0:
        return [(0, 0, 0, 0)] * 16
    if v & 0x7F != 0x40:
        return None
    pos = 7
    q0, q1 = [], []
    for _k in range(4):
        q0.append(v >> pos & 127)
        pos += 7
        q1.append(v >> pos & 127)
        pos += 7
    p0 = v >> pos & 1
    p1 = v >> (pos + 1) & 1
    pos += 2
    e0 = [x << 1 | p0 for x in q0]
    e1 = [x << 1 | p1 for x in q1]
    out = []
    for i in range(16):
        n = 3 if i == 0 else 4
        w = WEIGHTS4[v >> pos & ((1 << n) - 1)]
        pos += n
        out.append(tuple(((64 - w) * a + w * c + 32) >> 6 for a, c in zip(e0, e1)))
    return out


def encode_image(w, h, rgba):
    bw, bh = (w + 3) // 4, (h + 3) // 4
    out = bytearray()
    for by in range(bh):
        for bx in range(bw):
            px = []
            for y in range(4):
                yy = min(h - 1, by * 4 + y)
                for x in range(4):
                    o = (yy * w + min(w - 1, bx * 4 + x)) * 4
                    px.append((rgba[o], rgba[o + 1], rgba[o + 2], rgba[o + 3]))
            out += encode_block(px)
    return bytes(out), bw, bh


def decode_image(blocks, bw, bh, w, h):
    img = bytearray(b'\x80\x80\x80\xff' * (w * h))
    n6 = 0
    for by in range(bh):
        for bx in range(bw):
            px = decode_block(blocks[(by * bw + bx) * 16:(by * bw + bx) * 16 + 16])
            if px is None:
                continue
            n6 += 1
            for i, c in enumerate(px):
                x, y = bx * 4 + i % 4, by * 4 + i // 4
                if x < w and y < h:
                    img[(y * w + x) * 4:(y * w + x) * 4 + 4] = bytes(c)
    return img, n6


def _blocks_of(d, i):
    bw, bh = (i['width'] + 3) // 4, (i['height'] + 3) // 4
    data = d[i['data_offset']:i['data_offset'] + i['data_size']]
    if nutexb.block_height(bh) != 1 << i['block_height_log2']:
        raise ValueError('block height of the template differs from the layout rule of this tool')
    if nutexb.swizzled_size(bw * 16, bh, nutexb.block_height(bh)) != i['data_size']:
        raise ValueError('data size of the template differs from the layout rule of this tool')
    return data, bw, bh


def check(path, out_png):
    with open(path, 'rb') as f:
        d = f.read()
    i = info(d)
    data, bw, bh = _blocks_of(d, i)
    lin = nutexb.swizzle(data, bw, bh, bpp=16, to_linear=True)
    back = nutexb.swizzle(lin, bw, bh, bpp=16)
    img, n6 = decode_image(lin, bw, bh, i['width'], i['height'])
    tex0.write_png(out_png, i['width'], i['height'], img)
    # the layout written again must reproduce every byte that belongs to a block
    same = all(back[k] == data[k] for k in range(len(data)) if back[k] or data[k]) and len(back) == len(data)
    print('%s: %dx%d format %#x, %d blocks, %d of them mode 6 (decoded), layout undone and applied again: %s; '
          'picture %s' % (os.path.basename(path), i['width'], i['height'], i['format'], bw * bh, n6,
                          'identical' if same else 'DIFFERENT', out_png))


def replace(template, png, out, mode='contain'):
    with open(template, 'rb') as f:
        d = bytearray(f.read())
    i = info(d)
    if i['mips'] != 1 or i['format'] not in (0x2001, 0x2006):
        raise SystemExit('template: one mip level of BC7 expected (format %#x, %d levels)' % (i['format'], i['mips']))
    _data, bw, bh = _blocks_of(d, i)
    sw, sh, rgba = read_png(png)
    canvas = fit(sw, sh, rgba, i['width'], i['height'], mode)
    blocks, ebw, ebh = encode_image(i['width'], i['height'], canvas)
    assert (ebw, ebh) == (bw, bh)
    # error of the encoding, through this tool's decoder
    dec, _n = decode_image(blocks, bw, bh, i['width'], i['height'])
    worst = total = 0
    for k in range(0, len(canvas), 4):
        if canvas[k + 3] == 0 and dec[k + 3] == 0:
            continue
        e = max(abs(canvas[k + j] - dec[k + j]) for j in range(4))
        worst = max(worst, e)
        total += e
    laid = nutexb.swizzle(blocks, bw, bh, bpp=16)
    if len(laid) != i['data_size']:
        raise SystemExit('laid-out size %d differs from the template\'s %d' % (len(laid), i['data_size']))
    d[i['data_offset']:i['data_offset'] + i['data_size']] = laid
    with open(out, 'wb') as f:
        f.write(d)
    print('%s <- %s (%dx%d %s into %dx%d): %d bytes (template %d); encoding error through own decoder: worst %d, '
          'mean %.2f of 255' % (os.path.basename(out), os.path.basename(png), sw, sh, mode, i['width'], i['height'],
                                len(d), os.path.getsize(template), worst, total / (i['width'] * i['height'])))


if __name__ == '__main__':
    a = sys.argv
    if len(a) == 3 and a[1] == 'info':
        with open(a[2], 'rb') as f:
            print(info(f.read()))
    elif len(a) == 4 and a[1] == 'check':
        check(a[2], a[3])
    elif len(a) >= 5 and a[1] == 'replace':
        replace(a[2], a[3], a[4], a[6] if len(a) > 6 and a[5] == '--fit' else 'contain')
    else:
        print(__doc__)
