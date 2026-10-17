"""Minimal reader / in-place editor of the game's parameter files (.prc, "paracobn").

Layout (as tests/n4_prc_row.py): "paracobn", u32 hash table size, u32 reference table size, the hash table (u64 each),
the reference table, then the root parameter. Types: 1 bool, 2 i8, 3 u8, 4 i16, 5 u16, 6 i32, 7 u32, 8 float,
9 hash40 (u32 index into the hash table), 10 string (u32 offset into the reference table), 11 list (u32 count, u32
offsets from the list's own position), 12 struct (u32 count, u32 offset into the reference table of count pairs
{u32 hash index, u32 offset from the struct's own position}). Names are hash40 = crc32(lower-case name) | length << 32.

Values are edited IN PLACE (same type, same size): the file keeps its layout. No game content in this file.
"""
import struct
import zlib

SIZES = {1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 4, 7: 4, 8: 4, 9: 4, 10: 4}
FMT = {1: '<B', 2: '<b', 3: '<B', 4: '<h', 5: '<H', 6: '<i', 7: '<I', 8: '<f', 9: '<I', 10: '<I'}


def hash40(s):
    b = s.lower().encode()
    return (len(b) << 32) | (zlib.crc32(b) & 0xffffffff)


class Prc:
    def __init__(self, path):
        self.path = path
        self.d = bytearray(open(path, 'rb').read())
        assert self.d[:8] == b'paracobn', 'not a prc file'
        hsize, rsize = struct.unpack_from('<II', self.d, 8)
        self.hashes = [struct.unpack_from('<Q', self.d, 0x10 + 8 * i)[0] & 0xffffffffff for i in range(hsize // 8)]
        self.refs = 0x10 + hsize
        self.root = self.refs + rsize

    def node(self, off):
        """(type, value or children) of the parameter at off. Struct -> dict hash40 -> offset; list -> [offsets]."""
        t = self.d[off]
        if t in FMT:
            return t, struct.unpack_from(FMT[t], self.d, off + 1)[0]
        if t == 11:
            n, = struct.unpack_from('<I', self.d, off + 1)
            return t, [off + struct.unpack_from('<I', self.d, off + 5 + 4 * i)[0] for i in range(n)]
        if t == 12:
            n, r = struct.unpack_from('<II', self.d, off + 1)
            out = {}
            for i in range(n):
                hi, po = struct.unpack_from('<II', self.d, self.refs + r + 8 * i)
                out[self.hashes[hi]] = off + po
            return t, out
        raise ValueError('type %d at %x' % (t, off))

    def get(self, off):
        t, v = self.node(off)
        if t == 9: return self.hashes[v]
        if t == 10:
            s = self.refs + v
            return bytes(self.d[s:self.d.index(0, s)]).decode('utf-8', 'replace')
        return v

    def field(self, struct_off, name):
        t, kids = self.node(struct_off)
        return kids.get(hash40(name) if isinstance(name, str) else name)

    def set(self, off, value):
        t = self.d[off]
        assert t in FMT and t not in (9, 10), 'only numbers and bools are set in place'
        struct.pack_into(FMT[t], self.d, off + 1, value)

    def rows(self, list_name):
        off = self.field(self.root, list_name)
        t, kids = self.node(off)
        assert t == 11
        return kids

    def save(self, path):
        open(path, 'wb').write(bytes(self.d))
