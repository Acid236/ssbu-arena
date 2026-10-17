"""The reduced ("competitive") game DLL: only the lifted functions that the coverage runs executed keep their code.

    python tools/competitive/prune.py <used list> [<used list> ...] [--gen build/work/gen_eh_o2] [--out build/work/gen_comp]

<used list>: files written by runtime/coverage.c (SSBU_COVERAGE), one guest address (hex) per line; several are merged.
Every other function of the generated sources becomes a stub that stops the game with its name:
    void f_<addr>(Ctx *c) { guest_trap("competitive build: removed function", 0x<addr>); }
The function table, the headers and the imports stay as they are, so every call and every indirect call still links;
only the bodies go. Then:
    cd build/work && set RECOMP_GEN=gen_comp && set RECOMP_OBJ=obj_comp && set RECOMP_DLL=ssbu_game_comp.dll
    python build.py compile && python build.py link
and ssbu_game_comp.dll replaces ssbu_game_eh_o1.dll (same exports) in a competitive package.
A run that reaches a removed function says which one (guest trap with its address): add that run's coverage
(SSBU_COVERAGE) to the lists and prune again. No game content in this file; the output is generated from your dump.
"""
import argparse
import os
import re
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
FN = re.compile(r'^void f_([0-9a-f]+)\(Ctx \*c\) \{\s*$')
STUB = 'void f_%s(Ctx *c) { guest_trap("competitive build: removed function (not in the coverage lists)", 0x%sULL); }\n'


def main():
    root = os.path.normpath(os.path.join(HERE, '..', '..'))
    ap = argparse.ArgumentParser()
    ap.add_argument('used', nargs='+')
    ap.add_argument('--gen', default=os.path.join(root, 'build', 'work', 'gen_eh_o2'))
    ap.add_argument('--out', default=os.path.join(root, 'build', 'work', 'gen_comp'))
    ap.add_argument('--margin', type=int, default=0, help='also keep N functions on each side of every used one (by address order)')
    a = ap.parse_args()
    keep = set()
    for p in a.used:
        for ln in open(p):
            ln = ln.strip()
            if ln: keep.add(int(ln, 16))
    os.makedirs(a.out, exist_ok=True)
    total = kept = 0
    bytes_in = bytes_out = 0
    all_fns = []
    files = sorted(n for n in os.listdir(a.gen) if n.endswith('.c') or n.endswith('.h'))
    if a.margin:
        for n in files:
            if not n.startswith('c_'): continue
            for ln in open(os.path.join(a.gen, n)):
                m = FN.match(ln)
                if m: all_fns.append(int(m.group(1), 16))
        all_fns.sort()
        idx = {f: i for i, f in enumerate(all_fns)}
        extra = set()
        for f in keep:
            i = idx.get(f)
            if i is None: continue
            for j in range(max(0, i - a.margin), min(len(all_fns), i + a.margin + 1)): extra.add(all_fns[j])
        keep |= extra
    for n in files:
        src = os.path.join(a.gen, n); dst = os.path.join(a.out, n)
        if not n.startswith('c_'):
            if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src): shutil.copy2(src, dst)
            continue
        out, skipping = [], False
        with open(src) as f:
            text = f.readlines()
        bytes_in += sum(len(l) for l in text)
        for ln in text:
            if skipping:
                if ln.startswith('}'): skipping = False
                continue
            m = FN.match(ln)
            if m:
                total += 1
                addr = m.group(1)
                if int(addr, 16) in keep:
                    kept += 1
                else:
                    out.append(STUB % (addr, addr))
                    skipping = True
                    continue
            out.append(ln)
        data = ''.join(out)
        bytes_out += len(data)
        old = open(dst).read() if os.path.exists(dst) else None
        if old != data:
            with open(dst, 'w') as f: f.write(data)
    print('functions: %d, kept %d (%.1f %%), removed %d; generated C %.0f MB -> %.0f MB -> %s' % (
        total, kept, 100.0 * kept / max(total, 1), total - kept, bytes_in / 1048576.0, bytes_out / 1048576.0, a.out))


if __name__ == '__main__':
    main()
