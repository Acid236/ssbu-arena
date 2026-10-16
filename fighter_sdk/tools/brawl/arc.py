"""The archive container of the Wii predecessor's fighter files (.pac, .pcs) and its LZ77 compression.

Container: 0x40-byte header ("ARC\\0", u16 version, u16 entry count, 8 bytes, 48-byte name), then per entry a
0x20-byte header (s16 type, s16 index, u32 size, u8 group, u8 pad, s16 redirect) and the data, each aligned to 0x20.
A whole file or a single entry can be LZ77-compressed (first byte 0x10 or 0x11, 24-bit little-endian size).
"""
import struct

ENTRY_TYPES = {0: 'none', 1: 'misc data', 2: 'model data', 3: 'texture data', 4: 'animation data', 5: 'scene data',
               6: 'type 6', 7: 'grouped archive', 8: 'effect data'}


def is_lz77(data):
    if len(data) < 8 or data[0] not in (0x10, 0x11):
        return False
    size = data[1] | data[2] << 8 | data[3] << 16
    if size == 0:
        size = struct.unpack_from('<I', data, 4)[0]
    # a compressed stream cannot expand more than ~ 4370 times and the first flag byte follows the header
    return 0 < size < 0x8000000 and size >= len(data) // 2


def lz77_decompress(data):
    kind = data[0]
    if kind not in (0x10, 0x11):
        raise ValueError('not LZ77 (first byte %#x)' % kind)
    size = data[1] | data[2] << 8 | data[3] << 16
    pos = 4
    if size == 0:
        size = struct.unpack_from('<I', data, 4)[0]
        pos = 8
    out = bytearray(size)
    o = 0
    n = len(data)
    ext = kind == 0x11
    while o < size:
        if pos >= n:
            raise ValueError('LZ77 stream ends early at output %d of %d' % (o, size))
        flags = data[pos]
        pos += 1
        for bit in range(8):
            if o >= size:
                break
            if flags & (0x80 >> bit):
                b1 = data[pos]
                if ext:
                    ind = b1 >> 4
                    if ind == 0:
                        b2, b3 = data[pos + 1], data[pos + 2]
                        length = ((b1 & 0xF) << 4 | b2 >> 4) + 0x11
                        disp = ((b2 & 0xF) << 8 | b3) + 1
                        pos += 3
                    elif ind == 1:
                        b2, b3, b4 = data[pos + 1], data[pos + 2], data[pos + 3]
                        length = ((b1 & 0xF) << 12 | b2 << 4 | b3 >> 4) + 0x111
                        disp = ((b3 & 0xF) << 8 | b4) + 1
                        pos += 4
                    else:
                        b2 = data[pos + 1]
                        length = ind + 1
                        disp = ((b1 & 0xF) << 8 | b2) + 1
                        pos += 2
                else:
                    b2 = data[pos + 1]
                    length = (b1 >> 4) + 3
                    disp = ((b1 & 0xF) << 8 | b2) + 1
                    pos += 2
                if disp > o:
                    raise ValueError('LZ77 back reference before the start (output %d, distance %d)' % (o, disp))
                length = min(length, size - o)
                src = o - disp
                if disp >= length:
                    out[o:o + length] = out[src:src + length]
                else:
                    for k in range(length):
                        out[o + k] = out[src + k]
                o += length
            else:
                out[o] = data[pos]
                pos += 1
                o += 1
    return bytes(out)


def maybe_decompress(data):
    """Returns (data, was_compressed)."""
    if data[:4] not in (b'ARC\0', b'bres') and is_lz77(data):
        return lz77_decompress(data), True
    return data, False


class ArcEntry:
    __slots__ = ('type', 'index', 'size', 'group', 'redirect', 'offset', 'data', 'compressed', 'stored_size')

    def kind(self):
        d = self.data
        if d[:4] == b'bres':
            return 'BRRES'
        if d[:4] == b'ARC\0':
            return 'ARC'
        if d[:4] == b'EFLS':
            return 'EFLS'
        return ENTRY_TYPES.get(self.type, 'type %d' % self.type)


class Arc:
    def __init__(self, data):
        self.raw_size = len(data)
        data, self.compressed = maybe_decompress(data)
        self.size = len(data)
        if data[:4] != b'ARC\0':
            raise ValueError('not an ARC container')
        self.version, count = struct.unpack_from('>HH', data, 4)
        self.name = data[0x10:0x40].split(b'\0')[0].decode('ascii', 'replace')
        self.entries = []
        pos = 0x40
        for _ in range(count):
            if pos + 0x20 > len(data):
                raise ValueError('entry header beyond the end of the container')
            e = ArcEntry()
            e.type, e.index, e.stored_size, e.group, _pad, e.redirect = struct.unpack_from('>hhIBBh', data, pos)
            e.offset = pos + 0x20
            if e.offset + e.stored_size > len(data):
                raise ValueError('entry data beyond the end of the container')
            raw = data[e.offset:e.offset + e.stored_size]
            e.data, e.compressed = maybe_decompress(raw) if raw else (raw, False)
            e.size = len(e.data)
            self.entries.append(e)
            pos = (e.offset + e.stored_size + 0x1F) & ~0x1F

    def by_type(self, t):
        return [e for e in self.entries if e.type == t]


def load(path):
    with open(path, 'rb') as f:
        return Arc(f.read())
