"""P3 round 4: match the slow first draws of a SSBU_FDLOG=1 log with the warm draws of the workers.
   python tests/p4_fdmatch.py <log>"""
import sys
warm = {}; slow = []; state = None; lines = open(sys.argv[1], errors='replace').read().split('\n')
for i, l in enumerate(lines):
    if l.startswith('fd-warm:'):
        p = l.split(); warm[(p[1], p[2], p[3], p[4], p[6])] = (float(p[9]), p[8], int(p[12]))
    elif l.startswith('fd-slow:'):
        p = l.split(); st = lines[i + 1] if lines[i + 1].startswith('fd-state:') else ''
        slow.append(((p[1], p[2], p[3], p[4], p[6]), p[8].strip('()'), float(p[9]), int(p[12]), st))
inw = [s for s in slow if s[0] in warm]
names = {}
for k in warm: names.setdefault(k[:4], []).append(k[4])
print('slow draws %d (%.0f ms): warmed with the same names and mask %d (%.0f ms); same names, another mask %d; not warmed %d' % (
    len(slow), sum(s[2] for s in slow), len(inw), sum(s[2] for s in inw), len([s for s in slow if s[0] not in warm and s[0][:4] in names]), len([s for s in slow if s[0][:4] not in names])))
for s in inw: print(' ', s[0][0][:8], s[0][2][:8], 'mask', s[0][4], '%.0f ms frame %d' % (s[2], s[3]), '| warm: %.0f ms kind %s frame %d' % warm[s[0]], '|', s[4][10:])
