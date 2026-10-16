"""Track R1 round 5: check a RUN-AHEAD run (SSBU_RUNAHEAD=1) against a run without it, from the fighters' hash files.
    python tests/r1_ra_cmp.py <run-ahead hash> <run-ahead r1 log (SSBU_R1_LOG)> <reference hash (run-ahead off)>
The r1 log lists, per fight frame (one per call batch of the fighters' frame line), 'R' (real pass) or 'S' (speculative
pass, thrown away). The speculative frames' lines are taken out, the real ones renumbered; every real frame must equal the
reference frame of the same number (all fields of every fighter's line except the running hash H and the frame number).
No game content in this file."""
import re
import sys


def frames(path):
    out = {}
    for ln in open(path, errors='replace'):
        if not ln.startswith('F ') or ' H ' not in ln:
            continue
        f = int(ln.split()[1])
        out.setdefault(f, []).append(ln.split(' H ')[0].split(' ', 2)[2])
    return out


ra, log, ref = frames(sys.argv[1]), sys.argv[2], frames(sys.argv[3])
kinds = {}
for ln in open(log, errors='replace'):
    m = re.match(r'r1: RA kinds (\d+): ([RS]+)', ln)
    if m:
        for i, ch in enumerate(m.group(2)):
            kinds[int(m.group(1)) + i] = ch
nk = max(kinds) if kinds else 0
spec = sum(1 for v in kinds.values() if v == 'S')
real, n = [], 0
absent = ra and max(ra) < nk - spec // 2      # speculative frames skipped their frame line (SSBU_RUNAHEAD_SKIP bit 8): no lines of theirs
if absent:
    print('speculative frames have no hash lines (their fighters did not run): the hash frames are the real ones')
    kinds = {}
    nk = max(ra)
for f in sorted(ra):
    if f > nk:
        break                                   # (kinds known up to the last report)
    if kinds.get(f, 'R') == 'S':
        continue
    real.append((f, ra[f]))
same = 0
for i, (f, body) in enumerate(real, 1):
    if i not in ref:
        break
    if body != ref[i]:
        print('DIFFERS at real frame %d (run-ahead hash frame %d):\n  run-ahead: %s\n  reference: %s' % (i, f, body, ref[i]))
        break
    same += 1
print('%d fight frames with a known kind (%d speculative, %d real); %d real frames compared: %s' % (nk, spec, len(real), same, 'IDENTICAL to the reference' if same == min(len(real), len(ref)) else 'NOT identical'))
