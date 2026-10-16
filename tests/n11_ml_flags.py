"""N11 experiment: print or change the 16-bit flags of rows of a fighter's motion list, in a WORK COPY.
    python tests\\n11_ml_flags.py <motion_list.bin> <motion kind>[=<and mask hex>,<or mask hex>] ...
Layout as fighter_sdk\\tools\\brawl\\motion_list.py describes it (header 3 x u64; per row: u64 key, u64 game script,
u16 flags, u8 blend frames, u8 animation count n, u32 tail size, n x u64, n bytes padded to 4, the tail).
A key is length << 32 | CRC-32 of the lower-case motion kind name. No game content in this file."""
import struct
import sys
import zlib


def h40(s):
    return (len(s) << 32) | zlib.crc32(s.encode())


def main():
    path = sys.argv[1]
    want = {}
    for a in sys.argv[2:]:
        name, _, masks = a.partition('=')
        want[h40(name)] = (name, masks)
    d = bytearray(open(path, 'rb').read())
    count = struct.unpack_from('<Q', d, 16)[0]
    p, changed = 24, 0
    for _ in range(count):
        key = struct.unpack_from('<Q', d, p)[0] & 0xffffffffff
        flags, blend, n, tail = struct.unpack_from('<HBBI', d, p + 16)
        if key in want:
            name, masks = want[key]
            new = flags
            if masks:
                a, o = (int(x, 16) for x in masks.split(','))
                new = (flags & a) | o
                struct.pack_into('<H', d, p + 16, new)
                changed += new != flags
            print('%-14s flags 0x%04x%s, blend frames %d, %d animation file(s)' % (name, flags, (' -> 0x%04x' % new) if new != flags else '', blend, n))
        p += 24 + 8 * n + ((n + 3) & ~3) + tail
    assert p == len(d), 'the walk over the rows did not end at the file end (%d of %d)' % (p, len(d))
    if changed:
        open(path, 'wb').write(d)
        print('%d row(s) changed in %s' % (changed, path))


if __name__ == '__main__':
    main()
