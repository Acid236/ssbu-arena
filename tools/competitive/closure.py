"""Call-graph closure of a coverage list: every lifted function called DIRECTLY (f_<addr>(c) in the generated C) by a kept
function is kept too, until nothing changes. Rare branches inside used code then still find their callees; only code
that no used function can reach directly goes (indirect calls - virtual functions, callbacks, script modules - are
known only from the coverage runs).
    python tools/competitive/closure.py <coverage list> [...] --gen build/work/gen_eh_o2 --out <closed list>"""
import argparse
import os
import re

FN = re.compile(r'^void f_([0-9a-f]+)\(Ctx \*c\) \{\s*$')
CALL = re.compile(r'\bf_([0-9a-f]{10})\(c\)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('used', nargs='+')
    ap.add_argument('--gen', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    calls = {}
    for n in sorted(os.listdir(a.gen)):
        if not (n.startswith('c_') and n.endswith('.c')): continue
        cur = None
        for ln in open(os.path.join(a.gen, n)):
            m = FN.match(ln)
            if m: cur = int(m.group(1), 16); calls[cur] = set(); continue
            if cur is None: continue
            if ln.startswith('}'): cur = None; continue
            for c in CALL.findall(ln): calls[cur].add(int(c, 16))
    keep = set()
    for p in a.used:
        keep |= {int(l, 16) for l in open(p) if l.strip()}
    start = len(keep)
    todo = list(keep)
    while todo:
        f = todo.pop()
        for g in calls.get(f, ()):
            if g not in keep: keep.add(g); todo.append(g)
    with open(a.out, 'w') as f:
        for x in sorted(keep): f.write('%x\n' % x)
    print('functions %d; coverage %d -> closure %d (%.1f %%)' % (len(calls), start, len(keep), 100.0 * len(keep) / len(calls)))


if __name__ == '__main__':
    main()
