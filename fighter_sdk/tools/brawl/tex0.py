"""TEX0 textures and PLT0 palettes -> RGBA8 (bytes, row major, top row first). Also a minimal PNG writer / reader.

Block layouts (width x height of a block): I4 8x8, I8 8x4, IA4 8x4, IA8 4x4, RGB565 4x4, RGB5A3 4x4, RGBA8 4x4 (two
32-byte halves: A,R then G,B), CI4 8x8, CI8 8x4, CI14X2 4x4, CMPR 8x8 made of four 4x4 two-colour-endpoint blocks.
"""
import struct
import zlib

from .brres import cstr

FORMATS = {0: 'I4', 1: 'I8', 2: 'IA4', 3: 'IA8', 4: 'RGB565', 5: 'RGB5A3', 6: 'RGBA8', 8: 'CI4', 9: 'CI8',
           10: 'CI14X2', 14: 'CMPR'}
PALETTE_FORMATS = {0: 'IA8', 1: 'RGB565', 2: 'RGB5A3'}
_BLOCK = {0: (8, 8), 1: (8, 4), 2: (8, 4), 3: (4, 4), 4: (4, 4), 5: (4, 4), 6: (4, 4), 8: (8, 8), 9: (8, 4),
          10: (4, 4), 14: (8, 8)}
_BPP = {0: 4, 1: 8, 2: 8, 3: 16, 4: 16, 5: 16, 6: 32, 8: 4, 9: 8, 10: 16, 14: 4}


def _565(v):
    r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
    return (r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2, 255)


def _5a3(v):
    if v & 0x8000:
        r, g, b = (v >> 10) & 31, (v >> 5) & 31, v & 31
        return (r << 3 | r >> 2, g << 3 | g >> 2, b << 3 | b >> 2, 255)
    a, r, g, b = (v >> 12) & 7, (v >> 8) & 15, (v >> 4) & 15, v & 15
    return (r * 17, g * 17, b * 17, a << 5 | a << 2 | a >> 1)


def _ia8(v):
    a, i = v >> 8, v & 255
    return (i, i, i, a)


def level_size(fmt, w, h):
    bw, bh = _BLOCK[fmt]
    return ((w + bw - 1) // bw) * ((h + bh - 1) // bh) * bw * bh * _BPP[fmt] // 8


def read_palette(data, off):
    if data[off:off + 4] != b'PLT0':
        raise ValueError('not a palette')
    _size, _ver, _bres, hl, _so, fmt, n = struct.unpack_from('>IIiiiIH', data, off + 4)
    conv = {0: _ia8, 1: _565, 2: _5a3}[fmt]
    vals = struct.unpack_from('>%dH' % n, data, off + hl)
    return [conv(v) for v in vals], fmt


class Tex0:
    def __init__(self, data, off):
        if data[off:off + 4] != b'TEX0':
            raise ValueError('not a texture')
        self.data, self.off = data, off
        self.size, self.version, _bres, self.header_len = struct.unpack_from('>IIii', data, off + 4)
        p = off + 0x14
        if self.version >= 2:
            p += 4          # extra offset in later versions
        so, self.has_palette, self.width, self.height, self.format, self.levels = struct.unpack_from(
            '>iIHHII', data, p)
        self.name = cstr(data, off + so) if so else ''
        if self.format not in FORMATS:
            raise ValueError('unknown texture format %d' % self.format)
        if not (0 < self.width <= 4096 and 0 < self.height <= 4096):
            raise ValueError('implausible texture size %dx%d' % (self.width, self.height))

    @property
    def format_name(self):
        return FORMATS[self.format]

    def decode(self, palette=None, level=0):
        """-> (width, height, bytearray RGBA8)."""
        d, fmt = self.data, self.format
        pos = self.off + self.header_len
        w, h = self.width, self.height
        for _ in range(level):
            pos += level_size(fmt, w, h)
            w, h = max(1, w // 2), max(1, h // 2)
        if pos + level_size(fmt, w, h) > self.off + self.size:
            raise ValueError('texture data beyond the end of the resource')
        out = bytearray(w * h * 4)
        bw, bh = _BLOCK[fmt]

        def put(x, y, c):
            if x < w and y < h:
                o = (y * w + x) * 4
                out[o], out[o + 1], out[o + 2], out[o + 3] = c

        if fmt in (8, 9, 10) and palette is None:
            raise ValueError('palette needed')
        for by in range(0, h, bh):
            for bx in range(0, w, bw):
                if fmt == 0 or fmt == 8:
                    for y in range(8):
                        for x in range(8):
                            v = d[pos + y * 4 + x // 2]
                            v = (v >> 4) if x % 2 == 0 else (v & 15)
                            put(bx + x, by + y, (v * 17, v * 17, v * 17, 255) if fmt == 0 else palette[v])
                    pos += 32
                elif fmt in (1, 2, 9):
                    for y in range(4):
                        for x in range(8):
                            v = d[pos + y * 8 + x]
                            if fmt == 1:
                                c = (v, v, v, 255)
                            elif fmt == 2:
                                c = ((v & 15) * 17,) * 3 + ((v >> 4) * 17,)
                            else:
                                c = palette[v]
                            put(bx + x, by + y, c)
                    pos += 32
                elif fmt in (3, 4, 5, 10):
                    vals = struct.unpack_from('>16H', d, pos)
                    for k, v in enumerate(vals):
                        if fmt == 3:
                            c = _ia8(v)
                        elif fmt == 4:
                            c = _565(v)
                        elif fmt == 5:
                            c = _5a3(v)
                        else:
                            c = palette[v & 0x3FFF]
                        put(bx + k % 4, by + k // 4, c)
                    pos += 32
                elif fmt == 6:
                    for k in range(16):
                        put(bx + k % 4, by + k // 4,
                            (d[pos + k * 2 + 1], d[pos + 32 + k * 2], d[pos + 33 + k * 2], d[pos + k * 2]))
                    pos += 64
                elif fmt == 14:
                    for sub in range(4):
                        c0, c1, bits = struct.unpack_from('>HHI', d, pos)
                        pos += 8
                        p0, p1 = _565(c0), _565(c1)
                        if c0 > c1:
                            p2 = tuple((2 * a + b) // 3 for a, b in zip(p0, p1))
                            p3 = tuple((a + 2 * b) // 3 for a, b in zip(p0, p1))
                        else:
                            p2 = tuple((a + b) // 2 for a, b in zip(p0, p1))
                            p3 = (p2[0], p2[1], p2[2], 0)
                        pal = (p0, p1, p2, p3)
                        sx, sy = bx + (sub % 2) * 4, by + (sub // 2) * 4
                        for k in range(16):
                            put(sx + k % 4, sy + k // 4, pal[(bits >> (30 - 2 * k)) & 3])
        return w, h, out


def write_png(path, w, h, rgba):
    def chunk(tag, body):
        c = struct.pack('>I', len(body)) + tag + body
        return c + struct.pack('>I', zlib.crc32(tag + body) & 0xFFFFFFFF)
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += rgba[y * w * 4:(y + 1) * w * 4]
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) +
                chunk(b'IDAT', zlib.compress(bytes(raw), 6)) + chunk(b'IEND', b''))
