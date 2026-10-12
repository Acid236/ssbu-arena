"""python tests/blrefs.py <addr hex> ...  -- every BL / B in main's code that targets the address, and data words / relative relocations pointing at it"""
import struct, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import recomp
d, base, fo = recomp.IMG, recomp.BASE, recomp.FILE_OFF
text = recomp.TEXT_SIZE
import numpy as np
w = np.frombuffer(d, '<u4', text // 4, fo).astype(np.int64)
isb = (w & 0x7c000000) == 0x14000000
imm = w & 0x3ffffff
imm = np.where(imm & 0x2000000, imm - 0x4000000, imm)
dest = base + np.arange(len(w)) * 4 + imm * 4
for a in sys.argv[1:]:
    target = int(a, 16)
    for i in np.nonzero(isb & (dest == target))[0]:
        print('%x: %s %x' % (base + i * 4, 'bl' if w[i] >> 31 else 'b', target))
    for i in range(recomp.RELASZ // 24):
        off, info, addend = struct.unpack_from('<QQq', d, fo + recomp.RELA + i * 24)
        if info == 0x403 and addend == target - base: print('%x: data pointer (relocation) to %x' % (base + off, target))
