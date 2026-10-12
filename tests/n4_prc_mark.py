"""N4 test tool: list the float values of a parameter file (.prc), or write a copy in which float values carry a mark.

    python tests\\n4_prc_mark.py list <file.prc>
    python tests\\n4_prc_mark.py mark <in.prc> <out.prc> [every]     mark every <every>-th float (default 1 = all)
    python tests\\n4_prc_mark.py set <in.prc> <out.prc> <float index> <value>

"Mark" = the low 12 bits of the float's bit pattern become 0x5a5 (the value changes by less than 0.05 %): a marked
value is recognisable in a hex dump of the game's memory and cannot be confused with a value of the original file
(the tool prints how many floats of the ORIGINAL already end in 5a5: these are not counted as proof).
The file is walked by its structure (types: 1 bool, 2 i8, 3 u8, 4 i16, 5 u16, 6 i32, 7 u32, 8 float, 9 hash, 10 string,
11 list, 12 struct), so only real float values are touched. No game content in this file.
"""
import struct
import sys


def walk(data, off, floats, refs_base):
    t = data[off]
    if t in (1, 2, 3):
        return
    if t in (4, 5):
        return
    if t in (6, 7, 9, 10):
        return
    if t == 8:
        floats.append(off + 1)
        return
    if t == 11:
        n = struct.unpack_from('<I', data, off + 1)[0]
        for i in range(n):
            o = struct.unpack_from('<I', data, off + 5 + 4 * i)[0]
            walk(data, off + o, floats, refs_base)
        return
    if t == 12:
        n, ref = struct.unpack_from('<Ii', data, off + 1)
        for i in range(n):
            h, o = struct.unpack_from('<Ii', data, refs_base + ref + 8 * i)
            walk(data, off + o, floats, refs_base)
        return
    raise SystemExit('unknown type %d at 0x%x' % (t, off))


def floats_of(data):
    if data[:8] != b'paracobn':
        raise SystemExit('not a parameter file')
    hsize, rsize = struct.unpack_from('<II', data, 8)
    refs = 0x10 + hsize
    root = refs + rsize
    out = []
    walk(data, root, out, refs)
    return sorted(set(out))


def main():
    cmd = sys.argv[1]
    data = bytearray(open(sys.argv[2], 'rb').read())
    fl = floats_of(data)
    already = sum(1 for o in fl if struct.unpack_from('<I', data, o)[0] & 0xfff == 0x5a5)
    if cmd == 'list':
        print('%d float values; %d of them already end in 5a5' % (len(fl), already))
        for i, o in enumerate(fl):
            bits = struct.unpack_from('<I', data, o)[0]
            print('%4d  offset 0x%04x  %08x  %g' % (i, o, bits, struct.unpack_from('<f', data, o)[0]))
        return
    if cmd == 'mark':
        every = int(sys.argv[4]) if len(sys.argv) > 4 else 1
        n = 0
        for i, o in enumerate(fl):
            if i % every:
                continue
            bits = struct.unpack_from('<I', data, o)[0]
            if bits & 0x7fffffff == 0:
                continue                                    # 0.0 stays 0.0
            struct.pack_into('<I', data, o, (bits & ~0xfff) | 0x5a5)
            n += 1
        open(sys.argv[3], 'wb').write(data)
        print('%d of %d float values marked (the original had %d ending in 5a5); wrote %s, %d bytes' % (n, len(fl), already, sys.argv[3], len(data)))
        return
    if cmd == 'set':
        i, v = int(sys.argv[4]), float(sys.argv[5])
        old = struct.unpack_from('<f', data, fl[i])[0]
        struct.pack_into('<f', data, fl[i], v)
        open(sys.argv[3], 'wb').write(data)
        print('float %d at offset 0x%x: %g -> %g; wrote %s' % (i, fl[i], old, v, sys.argv[3]))


if __name__ == '__main__':
    main()
