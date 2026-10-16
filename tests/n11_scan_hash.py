"""N11: find where the game's main.elf builds given 40-bit name hashes as immediates (AArch64 MOVZ / MOVK sequences
on one register within 4 instructions). Read only; prints virtual addresses per name.
    python tests\\n11_scan_hash.py <main.elf> <name> [<name> ...]
A hash is len << 32 | CRC-32(name). No game content in this file."""
import struct
import sys
import zlib


def main():
    path, names = sys.argv[1], sys.argv[2:]
    d = open(path, 'rb').read()
    phoff, = struct.unpack_from('<Q', d, 0x20)
    phentsize, phnum = struct.unpack_from('<HH', d, 0x36)
    want = {}
    for n in names:
        h = (len(n) << 32) | zlib.crc32(n.encode())
        want[(h & 0xffff, (h >> 16) & 0xffff)] = (n, h)
    found = {n: [] for n in names}
    for i in range(phnum):
        ptype, flags, foff, vaddr, _, fsz = struct.unpack_from('<IIQQQQ', d, phoff + i * phentsize)
        if ptype != 1 or not flags & 1:
            continue
        words = struct.unpack_from('<%dI' % (fsz // 4), d, foff)
        for k, w in enumerate(words):
            if w & 0x7fe00000 != 0x52800000:          # MOVZ, hw = 0
                continue
            rd, lo = w & 31, (w >> 5) & 0xffff
            for j in range(k + 1, min(k + 5, len(words))):
                v = words[j]
                if v & 0x7fe00000 == 0x72a00000 and v & 31 == rd:     # MOVK, hw = 1
                    key = (lo, (v >> 5) & 0xffff)
                    if key in want:
                        found[want[key][0]].append(0x7100000000 + vaddr + 4 * k)
                    break
    for n in names:
        print('%-8s %s: %d place(s) %s' % (n, hex((len(n) << 32) | zlib.crc32(n.encode())), len(found[n]), ' '.join(hex(a) for a in found[n][:12])))


if __name__ == '__main__':
    main()
