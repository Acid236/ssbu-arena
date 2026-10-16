"""Round 18: the tagged draws (SSBU_DRAWTAG=1) of the same fight frame in TWO VULKAN logs (two GPUs, or two frames).
    python tests/p18_dtvk.py <log A> <log B> <fight frame A> [<fight frame B>]
DT lines: command data and guest-memory hashes (addresses and program serials left out). DTV lines: what the back end
bound and the state (ring offsets and ring generation left out). Prints every draw whose DT or DTV fields differ, and
the vertex formats a GPU does not take as vertex-buffer formats. Test tool, no game content."""
import re
import sys


def load(path, fight):
    dt, dtv = {}, {}
    with open(path, errors='replace') as f:
        for line in f:
            try:                                              # another thread's line can be printed into one of these
                if line.startswith('DT vk %d ' % fight):
                    dt[int(line.split()[3])] = line.strip()
                elif line.startswith('DTV %d ' % fight):
                    dtv[int(line.split()[2])] = line.strip()
            except ValueError:
                pass
    return dt, dtv


def norm(line):
    s = re.sub(r'^(DT vk|DTV) \d+ ', '', line)
    s = re.sub(r'=[0-9a-f]+\+(\d+)', r'=+\1', s)             # guest address+size -> +size
    s = re.sub(r'(vs|fs)=#\d+:', r'\1=', s)
    s = re.sub(r'_bound=(ring|cb)@\d+', r'_bound=\1', s)
    s = re.sub(r' ring_gen=\d+', '', s)
    s = re.sub(r'ds=[0-9a-f]+', 'ds=', s)
    return s


def fields(line):
    out = {}
    for t in line.split():
        if '=' in t:
            k, v = t.split('=', 1)
            out[k] = v
        elif ':' in t:
            k, v = t.split(':', 1)
            out['fmt' + k] = v
    return out


def main():
    fa = int(sys.argv[3])
    fb = int(sys.argv[4]) if len(sys.argv) > 4 else fa
    a, av = load(sys.argv[1], fa)
    b, bv = load(sys.argv[2], fb)
    print('A: %d draws, B: %d draws' % (len(a), len(b)))
    nd = 0
    notfmt = set()
    for i in sorted(set(a) | set(b)):
        if i not in a or i not in b:
            print('draw %d only in %s' % (i, 'B' if i not in a else 'A'))
            nd += 1
            continue
        for name, x, y in (('DT', a[i], b[i]), ('DTV', av.get(i, ''), bv.get(i, ''))):
            for side, l in (('A', x), ('B', y)):
                for m in re.finditer(r'(\d+):(\d+)\(NOT a vertex format on this GPU\)', l):
                    notfmt.add((side, m.group(2)))
            if norm(x) != norm(y):
                fx, fy = fields(norm(x)), fields(norm(y))
                d = [k for k in sorted(set(fx) | set(fy)) if fx.get(k) != fy.get(k)]
                nd += 1
                print('draw %d %s differs in: %s' % (i, name, ', '.join('%s (A %s | B %s)' % (k, fx.get(k), fy.get(k)) for k in d[:6])))
    print('%d differing lines; vertex formats not accepted as vertex-buffer formats: %s' % (nd, sorted(notfmt) or 'none'))


main()
