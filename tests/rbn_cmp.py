"""R3 online rollback check: compare the finalized frame checksums of two games (SSBU_RB_NET_LOG files, lines "f <frame> h <hex>").
    python tests/rbn_cmp.py <file A> <file B>
Prints how many frames both files have, whether they are identical, and the first difference. (hs12) A file can hold several
matches of one session: a line "m <n> id <match id>" starts match n, whose frames count from 1 again; each match is compared
on its own (and the match ids too). Exit 0 = every match identical. No game content."""
import sys


def read(path):
    out, ids, m = {}, {}, 1
    for ln in open(path, errors='replace'):
        p = ln.split()
        if len(p) >= 2 and p[0] == 'm':
            m = int(p[1])
            ids[m] = p[3] if len(p) >= 4 else '-'
        elif len(p) == 4 and p[0] == 'f' and p[2] == 'h':
            out.setdefault(m, {})[int(p[1])] = p[3]
    return out, ids


def main():
    (a, ia), (b, ib) = read(sys.argv[1]), read(sys.argv[2])
    bad = 0
    for m in sorted(set(a) | set(b)):
        x, y = a.get(m, {}), b.get(m, {})
        common = sorted(set(x) & set(y))
        diff = [f for f in common if x[f] != y[f]]
        tag = 'match %d (id %s / %s)' % (m, ia.get(m, '-'), ib.get(m, '-')) if len(set(a) | set(b)) > 1 or ia or ib else 'match'
        print('%s: A: %d frames (%s..%s), B: %d frames (%s..%s), common %d' % (
            tag, len(x), min(x, default='-'), max(x, default='-'), len(y), min(y, default='-'), max(y, default='-'), len(common)))
        if not common:
            print('  NOTHING TO COMPARE')
            bad = max(bad, 2)
        elif diff:
            print('  DIFFER: %d frames, first at frame %d (A %s, B %s)' % (len(diff), diff[0], x[diff[0]], y[diff[0]]))
            bad = 1
        else:
            print('  IDENTICAL: all %d common frames (%d..%d)' % (len(common), common[0], common[-1]))
        if ia.get(m) != ib.get(m):
            print('  MATCH IDS DIFFER')
            bad = 1
    sys.exit(bad)


if __name__ == '__main__':
    main()
