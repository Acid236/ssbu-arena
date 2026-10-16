"""Track R1: check a save / restore run (SSBU_R1) from its fighters' hash file.
    python tests/r1_cmp.py <r1 hash> <r1 log (SSBU_R1_LOG)> <K> [<reference hash of a run without SSBU_R1>]
For each cycle: the K fight frames of the re-run must equal the K frames of the first pass (all fields of every
fighter's line except the running hash H and the frame number); with a reference: the R1 run with the re-run blocks
taken out must equal the reference line for line (the fight continued exactly as without the save / restore).
No game content in this file."""
import re
import sys


def frames(path):
    out = {}
    for ln in open(path, errors='replace'):
        if not ln.startswith('F ') or ' H ' not in ln:
            continue
        p = ln.split()
        f = int(p[1])
        body = ln.split(' H ')[0].split(' ', 2)[2]       # 'e ... rng xxxxxxxx'
        out.setdefault(f, []).append(body)
    return [out[f] for f in sorted(out)]


def first_diff(a, b):
    for x, y in zip(a, b):
        if x != y:
            xs, ys = x.split(), y.split()
            fl = [xs[i] for i in range(0, min(len(xs), len(ys)) - 1, 2) if xs[i + 1] != ys[i + 1]]
            return '%s | %s (fields %s)' % (x, y, ','.join(fl))
    return None


r1, log, k = frames(sys.argv[1]), open(sys.argv[2], errors='replace').read(), int(sys.argv[3])
ref = frames(sys.argv[4]) if len(sys.argv) > 4 else None
saves = [int(m) for m in re.findall(r'SAVE at fight frame (\d+) \(marks\)', log)] or [int(m) for m in re.findall(r'SAVE at fight frame (\d+)', log)]
if 'MARK on' in log: saves = [int(re.search(r'cycle 0 SAVE at fight frame (\d+)', log).group(1))] + saves
ks = [int(m) for m in re.findall(r'first pass (\d+) frames', log)]
restores = len(re.findall(r'RESTORE at fight frame', log)) if 'MARK on' not in log else len(re.findall(r'RESTORE at fight frame \d+ \(marks\)', log))
print('r1 frames %d, saves %d, restores %d, K %d%s' % (len(r1), len(saves), restores, k, ', reference frames %d' % len(ref) if ref else ''))
best = None
for d in range(-3, 4):
    ok, bad = 0, None
    for c, s in enumerate(saves[:restores]):
        k = ks[c]
        p = s + sum(ks[:c]) + d                      # index of the first frame after the save in the R1 run (0-based list)
        if p < 0 or p + 2 * k > len(r1):
            continue
        a, b = r1[p:p + k], r1[p + k:p + 2 * k]
        if a == b:
            ok += 1
        elif bad is None:
            bad = (c, s, first_diff(sum(a, []), sum(b, [])))
    if best is None or ok > best[1]:
        best = (d, ok, bad)
d, ok, bad = best
print('offset %d: %d of %d cycles: re-run == first pass for all frames of the cycle (K per cycle %s)%s' % (d, ok, restores, ks, '' if bad is None else '; first failing cycle %d (save %d): %s' % bad))
if ref:
    cut = list(r1)
    for c in reversed(range(restores)):
        p = saves[c] + sum(ks[:c]) + d + ks[c]
        del cut[p:p + ks[c]]
    n = min(len(cut), len(ref))
    diff = next((i for i in range(n) if cut[i] != ref[i]), None)
    print('R1 run without the re-run blocks vs reference: %d frames compared, %s' % (n, 'IDENTICAL' if diff is None else 'first difference at frame index %d: %s' % (diff, first_diff(cut[diff], ref[diff]))))
