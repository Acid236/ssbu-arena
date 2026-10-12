"""python dis.py <module> <offset hex> [max insns]   -- disassemble one module function with import names."""
import sys
from nrolib import Nro, demangle_simple


def main():
    n = Nro(sys.argv[1])
    off = int(sys.argv[2], 16)
    if off >= n.base:
        off -= n.base
    size = n.func_size(off) or 0x200
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 100000
    print('function +0x%x size 0x%x' % (off, size))
    for k, i in enumerate(n.disasm(off, size)):
        if k >= limit:
            break
        note = ''
        if i.mnemonic in ('bl', 'b'):
            t = i.operands[0].imm
            if t in n.plt:
                note = '   ; ' + demangle_simple(n.plt[t])
        print('%6x  %-7s %s%s' % (i.address, i.mnemonic, i.op_str, note))


main()
