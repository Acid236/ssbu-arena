"""The resource directory ("bres") inside an archive entry: groups by resource class, each a name -> data index.

Header: "bres", u16 byte-order mark, u16 version, u32 size, u16 root offset, u16 section count. Root: "root", u32
size, then a group. Group: u32 size, u32 count, (count + 1) 16-byte entries {u16 id, u16 flag, u16 left, u16 right,
s32 name offset, s32 data offset}, offsets relative to the group; entry 0 is the tree's root placeholder.
"""
import struct


def cstr(data, off):
    end = data.index(b'\0', off)
    return data[off:end].decode('ascii', 'replace')


def read_group(data, off):
    """-> list of (name, absolute data offset)."""
    size, count = struct.unpack_from('>II', data, off)
    out = []
    for i in range(1, count + 1):
        e = off + 8 + i * 16
        _id, _f, _l, _r, s, d = struct.unpack_from('>HHHHii', data, e)
        out.append((cstr(data, off + s) if s else '', off + d))
    return out


class Brres:
    def __init__(self, data):
        if data[:4] != b'bres':
            raise ValueError('not a resource directory')
        self.data = data
        bom, ver, size, root, nsec = struct.unpack_from('>HHIHH', data, 4)
        if bom != 0xFEFF:
            raise ValueError('unexpected byte order mark %#x' % bom)
        self.size = size
        self.sections = nsec
        if data[root:root + 4] != b'root':
            raise ValueError('no root section')
        self.groups = {}      # group name -> list of (name, offset)
        for name, off in read_group(data, root + 8):
            self.groups[name] = read_group(data, off)

    def find(self, prefix):
        for g, items in self.groups.items():
            if g.startswith(prefix):
                return items
        return []

    def models(self):
        return self.find('3DModels')

    def textures(self):
        return self.find('Textures')

    def palettes(self):
        return self.find('Palettes')

    def chr(self):
        return self.find('AnmChr')

    def counts(self):
        return {g.split('(')[0]: len(v) for g, v in self.groups.items()}

    def tag(self, off):
        return self.data[off:off + 4].decode('ascii', 'replace')
