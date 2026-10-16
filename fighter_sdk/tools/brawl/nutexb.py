"""Native texture file (.nutexb): image data in the console GPU's block-linear layout, then a 0xB0-byte footer
(16 mip sizes, " XNT", 64-byte name, width, height, depth, format byte, 4, 4, mip count, alignment 0x1000, array
count, data size, " XET", version 1.2). This writer emits uncompressed RGBA8 with one mip level.
"""
import struct

FMT_RGBA8_UNORM = 0x00
FMT_RGBA8_SRGB = 0x05
FOOTER = 0xB0


def block_height(height):
    h = height + height // 2
    if h >= 128:
        return 16
    if h >= 64:
        return 8
    if h >= 32:
        return 4
    if h >= 16:
        return 2
    return 1


def swizzled_size(width_bytes, height, bh):
    gobs = (width_bytes + 63) // 64
    rows = (height + bh * 8 - 1) // (bh * 8)
    return gobs * rows * 512 * bh


def _address(x, y, gobs, bh):
    a = (y // (8 * bh)) * 512 * bh * gobs + (x // 64) * 512 * bh + ((y % (8 * bh)) // 8) * 512
    return a + ((x % 64) // 32) * 256 + ((y % 8) // 2) * 64 + ((x % 32) // 16) * 32 + (y % 2) * 16 + (x % 16)


def swizzle(data, width, height, bpp=4, to_linear=False):
    wb = width * bpp
    bh = block_height(height)
    gobs = (wb + 63) // 64
    size = swizzled_size(wb, height, bh)
    out = bytearray(wb * height if to_linear else size)
    for y in range(height):
        row = y * wb
        for x in range(0, wb, 16):
            n = min(16, wb - x)
            a = _address(x, y, gobs, bh)
            if to_linear:
                out[row + x:row + x + n] = data[a:a + n]
            else:
                out[a:a + n] = data[row + x:row + x + n]
    return bytes(out)


def scale_nearest(rgba, w, h, nw, nh):
    out = bytearray(nw * nh * 4)
    for y in range(nh):
        sy = y * h // nh
        for x in range(nw):
            s = (sy * w + x * w // nw) * 4
            o = (y * nw + x) * 4
            out[o:o + 4] = rgba[s:s + 4]
    return out


def build(name, width, height, rgba, srgb=True):
    """rgba: width*height*4 bytes, top row first. Sizes below 16 are enlarged (the block layout of smaller
    surfaces carries padding this writer does not produce)."""
    if width & (width - 1) or height & (height - 1):
        raise ValueError('texture sizes must be powers of two (%dx%d)' % (width, height))
    if width < 16 or height < 16:
        nw, nh = max(16, width), max(16, height)
        rgba = scale_nearest(rgba, width, height, nw, nh)
        width, height = nw, nh
    if len(rgba) != width * height * 4:
        raise ValueError('pixel data size')
    data = swizzle(bytes(rgba), width, height)
    if len(data) != width * height * 4:
        raise ValueError('unexpected block-layout size')
    nm = name.encode('ascii')
    if len(nm) > 63:
        raise ValueError('texture name too long')
    mips = [len(data)] + [0] * 15
    foot = struct.pack('<16I', *mips) + b' XNT' + nm.ljust(0x40, b'\0')
    foot += struct.pack('<IIIBBHIIIII', width, height, 1, FMT_RGBA8_SRGB if srgb else FMT_RGBA8_UNORM, 4, 0, 4, 1,
                        0x1000, 1, len(data))
    foot += b' XET' + struct.pack('<HH', 1, 2)
    assert len(foot) == FOOTER
    return data + foot


def read_footer(buf):
    f = buf[-FOOTER:]
    if f[0x40:0x44] != b' XNT' or f[0xA8:0xAC] != b' XET':
        raise ValueError('not a native texture file')
    name = f[0x44:0x84].split(b'\0')[0].decode('ascii', 'replace')
    width, height, depth, fmt, unk, _p, unk2, mips, align, arrays, size = struct.unpack_from('<IIIBBHIIIII', f, 0x84)
    return {'name': name, 'width': width, 'height': height, 'depth': depth, 'format': fmt, 'mips': mips,
            'alignment': align, 'arrays': arrays, 'data_size': size,
            'mip_sizes': struct.unpack_from('<16I', f, 0)[:mips]}
