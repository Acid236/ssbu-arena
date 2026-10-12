"""python main_adrp.py <vaddr hex> : code sites in main.elf that form the address with adrp + add."""
import struct
import sys
import numpy as np

MAIN = r'<project>/binaries\13.0.4\main.elf'
TEXT_OFF, TEXT_VA, TEXT_SIZE = 0x1000, 0x0, 0x39c7e90


def find(target):
    d = open(MAIN, 'rb').read()
    w = np.frombuffer(d, dtype='<u4', count=TEXT_SIZE // 4, offset=TEXT_OFF)
    pc = np.arange(len(w), dtype=np.int64) * 4 + TEXT_VA
    is_adrp = (w & 0x9f000000) == 0x90000000
    imm = (((w >> 5) & 0x7ffff).astype(np.int64) << 2) | ((w >> 29) & 3)
    imm = np.where(imm & (1 << 20), imm - (1 << 21), imm)
    page = (pc & ~0xfff) + (imm << 12)
    hits = np.nonzero(is_adrp & (page == (target & ~0xfff)))[0]
    out = []
    for i in hits:
        rd = int(w[i]) & 31
        for j in range(i + 1, min(i + 8, len(w))):
            x = int(w[j])
            if (x & 0xffc00000) == 0x91000000 and ((x >> 5) & 31) == rd and ((x >> 10) & 0xfff) == (target & 0xfff):
                out.append(int(pc[j]))
                break
    return out


if __name__ == '__main__':
    for a in find(int(sys.argv[1], 16)):
        print(hex(a + 0x7100000000))
