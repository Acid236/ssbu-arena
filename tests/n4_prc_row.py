"""N4 test tool: print named fields of the row of a list-of-structs parameter file whose key field has a given value.

    python tests\\n4_prc_row.py <file.prc> <list name> <key field> <key value name> <field> [<field> ...]
    e.g.  python tests\\n4_prc_row.py work_n4\\fighter_param.prc fighter_param_table fighter_kind fighter_kind_mario walk_speed_max jump_y

Names are hashed (hash40 = crc32 of the lower-case name, length in bits 32-39). Prints the row index, the number of
rows, and for each field its type, value and (for a float) the bit pattern. No game content in this file.
"""
import struct
import sys
import zlib


def h40(s):
    b = s.lower().encode()
    return (len(b) << 32) | (zlib.crc32(b) & 0xffffffff)


def main():
    path, list_name, key, key_value = sys.argv[1:5]
    fields = sys.argv[5:]
    d = open(path, 'rb').read()
    hsize, rsize = struct.unpack_from('<II', d, 8)
    hashes = [struct.unpack_from('<Q', d, 0x10 + 8 * i)[0] & 0xffffffffff for i in range(hsize // 8)]
    refs = 0x10 + hsize
    root = refs + rsize

    def members(off):
        n, ref = struct.unpack_from('<Ii', d, off + 1)
        out = {}
        for i in range(n):
            h, o = struct.unpack_from('<Ii', d, refs + ref + 8 * i)
            out[hashes[h]] = off + o
        return out

    def value(off):
        t = d[off]
        if t == 8:
            return 'float', struct.unpack_from('<f', d, off + 1)[0], struct.unpack_from('<I', d, off + 1)[0]
        if t in (6, 7):
            return 'int', struct.unpack_from('<i', d, off + 1)[0], None
        if t == 9:
            return 'hash', hashes[struct.unpack_from('<I', d, off + 1)[0]], None
        if t in (1, 2, 3):
            return 'byte', d[off + 1], None
        if t in (4, 5):
            return 'short', struct.unpack_from('<h', d, off + 1)[0], None
        return 'type %d' % t, None, None

    lst = members(root)[h40(list_name)]
    n = struct.unpack_from('<I', d, lst + 1)[0]
    want = h40(key_value)
    for i in range(n):
        row = lst + struct.unpack_from('<I', d, lst + 5 + 4 * i)[0]
        m = members(row)
        if value(m[h40(key)])[1] != want:
            continue
        print('row %d of %d, %d fields' % (i, n, len(m)))
        for f in fields:
            t, v, bits = value(m[h40(f)])
            print('  %s: %s %s%s' % (f, t, v, '  bits %08x' % bits if bits is not None else ''))
        return
    print('no row with %s = %s among %d rows' % (key, key_value, n))


if __name__ == '__main__':
    main()
