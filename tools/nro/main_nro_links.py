"""How main refers to symbols that live in the NRO modules, and the reverse.

  python main_nro_links.py

Prints: relocation types main uses for its undefined symbols that an NRO exports (JUMP_SLOT = calls through
main's PLT, GLOB_DAT/ABS64 = data/address references), which module provides them, and for the NRO side the
kinds of main symbols they import (FUNC/OBJECT), with data symbols listed.
"""
import os, sys, struct, collections, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nro_info
os.chdir(os.path.join(HERE, '..')); sys.path.insert(0, os.getcwd())
import recomp
R = recomp
IMG = R.IMG

def sym(i):
    name_off, info, other, shndx, value, size = struct.unpack_from('<IBBHQQ', IMG, R.FILE_OFF + R.SYMTAB + i * 24)
    p = R.FILE_OFF + R.STRTAB + name_off
    return IMG[p:IMG.index(b'\0', p)].decode('latin-1'), info & 0xf, shndx, value, size

mods = [nro_info.Nro(os.path.join(HERE, 'nro', f)) for f in sorted(os.listdir(os.path.join(HERE, 'nro'))) if f.endswith('.nro')]
nro_exp = {}
for m in mods:
    for s in m.exports(): nro_exp.setdefault(s[0], []).append((m.name, s[1], s[4]))

by_type = collections.Counter(); prov = collections.Counter(); names = collections.defaultdict(set)
for tab, size in ((R.RELA, R.RELASZ), (R.JMPREL, R.PLTRELSZ)):
    for i in range(size // 24):
        off, info, addend = struct.unpack_from('<QQq', IMG, R.FILE_OFF + tab + i * 24)
        t = info & 0xffffffff
        if t == 0x403: continue
        nm, st, shndx, value, _ = sym(info >> 32)
        if shndx == 0 and nm in nro_exp:
            tn = nro_info.RTYPE.get(t, hex(t))
            by_type[tn] += 1; names[tn].add(nm)
            for p in nro_exp[nm]: prov[p[0]] += 1
print('main relocations against symbols exported by an NRO:', dict(by_type))
for t, s in names.items(): print('   %-10s distinct symbols %d  e.g. %s' % (t, len(s), sorted(s)[:3]))
print('providers:', dict(collections.Counter(prov).most_common(6)), '... %d modules' % len(prov))
kinds = collections.Counter(p[0][1] for nm, p in nro_exp.items() if any(nm in s for s in names.values()))
print('symbol types of those NRO exports (1=OBJECT 2=FUNC):', dict(kinds))

# NRO -> main: types of the main symbols used
nsym = (R.STRTAB - R.SYMTAB) // 24
main_exp = {}
for i in range(nsym):
    nm, st, shndx, value, size = sym(i)
    if shndx: main_exp[nm] = (st, value, size)
used = collections.Counter(); data_syms = collections.Counter()
rel_kind = collections.Counter()
for m in mods:
    for tab, a in m.relocs():
        for off, info, addend in a.tolist():
            t = info & 0xffffffff
            if t == 0x403: continue
            nm = m.syms[info >> 32][0]
            if m.syms[info >> 32][3] != 0:
                rel_kind['internal ' + nro_info.RTYPE.get(t, hex(t))] += 1; continue
            if nm in main_exp:
                st = main_exp[nm][0]
                rel_kind['main %s %s' % ('FUNC' if st == 2 else 'OBJECT' if st == 1 else 'T%d' % st, nro_info.RTYPE.get(t, hex(t)))] += 1
                if st != 2: data_syms[nm] += 1
            elif nm in nro_exp:
                rel_kind['nro %s %s' % ('FUNC' if nro_exp[nm][0][1] == 2 else 'OBJECT', nro_info.RTYPE.get(t, hex(t)))] += 1
            else:
                rel_kind['other ' + nro_info.RTYPE.get(t, hex(t))] += 1
print('NRO relocation targets:')
for k, v in sorted(rel_kind.items()): print('   %-28s %d' % (k, v))
print('distinct main DATA symbols referenced by NROs: %d' % len(data_syms))
for nm, k in data_syms.most_common(25): print('   %5d %s (size %#x at %#x)' % (k, nm, main_exp[nm][2], main_exp[nm][1]))
st_main = collections.Counter(v[0] for v in main_exp.values())
print('main exports by type (1=OBJECT 2=FUNC):', dict(st_main))
