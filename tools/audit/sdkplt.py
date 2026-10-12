"""python tools_audit/sdkplt.py <plt stub addr hex> ...   -> the SDK symbol each PLT stub of sdk.elf jumps to"""
import struct, sys
import os
d = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..', 'binaries', '13.0.4', 'sdk.elf'), 'rb').read()
OFF = 0x1000
dyn = {}
o = 0xc2a8f8
while True:
    tag, val = struct.unpack_from('<qQ', d, o); o += 16
    if tag == 0: break
    dyn[tag] = val
def symname(i):
    no, info, other, shndx, value, size = struct.unpack_from('<IBBHQQ', d, OFF + dyn[6] + i * 24)
    s = OFF + dyn[5] + no
    return d[s:d.index(b'\0', s)].decode('latin-1'), value
slots = {}
for i in range(dyn[2] // 24):
    off, info, addend = struct.unpack_from('<QQq', d, OFF + dyn[23] + i * 24)
    slots[off] = symname(info >> 32)
def plt_target(a):
    w0, w1 = struct.unpack_from('<II', d, OFF + a)
    if (w0 & 0x9f00001f) != 0x90000010: return None
    imm = ((w0 >> 5) & 0x7ffff) << 2 | ((w0 >> 29) & 3)
    if imm & (1 << 20): imm -= 1 << 21
    page = (a & ~0xfff) + (imm << 12)
    return slots.get(page + (((w1 >> 10) & 0xfff) << 3))
if __name__ == '__main__':
    for a in sys.argv[1:]:
        print(a, plt_target(int(a, 16)))
