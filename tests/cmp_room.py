"""(R3 pub2) compare the room MATCH of two games' fight-hash files (n11_<tag>.hash.txt): the last fight segment of each,
frame by frame, the per-process H column left out; stops at the results pose (the trailing block of status 107 lines: the winner's pose
motion is picked by each PC, cosmetic, the N3 tests saw it too). usage: python cmp_room.py <logdir> <tagA> <tagB>"""
import re, sys, os
def segs(p):
    out, cur, last = [], [], None
    for l in open(p, errors='replace'):
        m = re.match(r'F (\d+) (.*?) H [0-9a-f]+', l)
        if not m: continue
        f = int(m.group(1))
        if last is not None and f < last: out.append(cur); cur = []
        last = f; cur.append((f, 'F %d %s' % (f, m.group(2))))
    if cur: out.append(cur)
    return out
d = sys.argv[1]
A = segs(os.path.join(d, 'n11_%s.hash.txt' % sys.argv[2])); B = segs(os.path.join(d, 'n11_%s.hash.txt' % sys.argv[3]))
if len(A) < 2 or len(B) < 2: print('ROOM MATCH NOT REACHED (segments A %d, B %d)' % (len(A), len(B))); sys.exit(1)
a, b = A[-1], B[-1]
n = min(len(a), len(b))
def last_play(s):                                       # the results pose: the trailing block where every line is status 107
    k = len(s)
    while k > 0 and ' st 107 ' in s[k - 1][1]: k -= 1
    return k
end = min(n, last_play(a), last_play(b))
frames = sorted(set(x[0] for x in a[:end]))
diff = [i for i in range(end) if a[i][1] != b[i][1]]
if diff:
    i = diff[0]; print('DIFFER: %d of %d lines before the results pose, first at frame %d\n  A %s\n  B %s' % (len(diff), end, a[i][0], a[i][1][:160], b[i][1][:160]))
else:
    print('IDENTICAL: the room match, %d fight frames (%d lines) up to %s' % (len(frames), end, 'the results pose' if end < n else 'the shorter file\'s end'))
