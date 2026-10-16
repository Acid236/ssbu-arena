"""N11: list the instructions of the game's main.elf that load or store a byte at a given field offset (AArch64 LDRB /
STRB, unsigned immediate form), to find who reads a module flag. Read only; prints virtual addresses.
    python tests\\n11_scan_ldrb.py <main.elf> <field offset hex> [base 0x7100000000]
No game content in this file."""
import struct
import sys


def main():
    path, off = sys.argv[1], int(sys.argv[2], 16)
    base = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x7100000000
    d = open(path, 'rb').read()
    phoff, = struct.unpack_from('<Q', d, 0x20)
    phentsize, phnum = struct.unpack_from('<HH', d, 0x36)
    want = {0x39400000 | (off << 10): 'ldrb', 0x39000000 | (off << 10): 'strb'}
    hits = []
    for i in range(phnum):
        ptype, flags, foff, vaddr, paddr, fsz = struct.unpack_from('<IIQQQQ', d, phoff + i * phentsize)
        if ptype != 1 or not flags & 1:          # PT_LOAD, executable
            continue
        for o in range(foff, foff + fsz - 3, 4):
            w, = struct.unpack_from('<I', d, o)
            k = w & 0xFFFFFC00
            if k in want:
                hits.append((base + vaddr + (o - foff), want[k], (w >> 5) & 31, w & 31))
    for va, op, rn, rt in hits:
        print('0x%x %s w%d, [x%d, #0x%x]' % (va, op, rt, rn, off))
    print('%d hits' % len(hits))


if __name__ == '__main__':
    main()
