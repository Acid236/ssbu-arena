"""R3 online rollback check: compare the finalized frame checksums of two games (SSBU_RB_NET_LOG files, lines "f <frame> h <hex>").
    python tests/rbn_cmp.py <file A> <file B>
Prints how many frames both files have, whether they are identical, and the first difference. No game content."""
import sys


def read(path):
    out = {}
    for ln in open(path, errors='replace'):
        p = ln.split()
        if len(p) == 4 and p[0] == 'f' and p[2] == 'h':
            out[int(p[1])] = p[3]
    return out


def main():
    a, b = read(sys.argv[1]), read(sys.argv[2])
    common = sorted(set(a) & set(b))
    diff = [f for f in common if a[f] != b[f]]
    print('A: %d frames (%s..%s), B: %d frames (%s..%s), common %d' % (
        len(a), min(a, default='-'), max(a, default='-'), len(b), min(b, default='-'), max(b, default='-'), len(common)))
    if not common:
        print('NOTHING TO COMPARE')
        sys.exit(2)
    if diff:
        print('DIFFER: %d frames, first at frame %d (A %s, B %s)' % (len(diff), diff[0], a[diff[0]], b[diff[0]]))
        sys.exit(1)
    print('IDENTICAL: all %d common frames (%d..%d)' % (len(common), common[0], common[-1]))


if __name__ == '__main__':
    main()
