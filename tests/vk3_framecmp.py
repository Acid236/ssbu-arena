"""Track V, session 3: frame comparison of two back ends on the same scripted path (M2's second test).

    python tests/vk3_framecmp.py <dir A (vk)> <dir B (gl)> [--out report.txt] [--window 6]

Both folders hold frame_<n>.bmp taken every k frames (SSBU_SHOT_EVERY). The two runs do not load at the same speed, so
frame n of one run is not frame n of the other: every frame of A is compared with the frames of B whose index (position in
the sorted list) is within +-window of its own, and the best match is kept. For a still menu screen the best match is the
same picture, and what remains is the rendering difference; for moving content it is an upper bound.
Per frame: mean absolute difference (0..255, all channels), share of pixels differing by more than 8, and the 4x4 grid
cell with the largest mean difference (where on the screen the difference sits)."""
import os, re, sys
import numpy as np
from PIL import Image


def frames(d):
    out = []
    for f in os.listdir(d):
        m = re.match(r'frame_(\d+)\.bmp$', f)
        if m:
            out.append((int(m.group(1)), os.path.join(d, f)))
    return sorted(out)


def load(p):
    return np.asarray(Image.open(p).convert('RGB').resize((480, 270), Image.BOX), dtype=np.int16)


def main():
    a, b = frames(sys.argv[1]), frames(sys.argv[2])
    win = int(sys.argv[sys.argv.index('--window') + 1]) if '--window' in sys.argv else 6
    out = open(sys.argv[sys.argv.index('--out') + 1], 'w') if '--out' in sys.argv else sys.stdout
    small_b = [load(p) for _, p in b]
    print('frame_A best_frame_B mean_abs share_over_8 worst_cell(row,col) cell_mean', file=out)
    stats = []
    for i, (na, pa) in enumerate(a):
        sa = load(pa)
        best = None
        for j in range(max(0, i - win), min(len(b), i + win + 1)):
            d = float(np.abs(sa - small_b[j]).mean())
            if best is None or d < best[0]:
                best = (d, j)
        if best is None:
            continue
        # full resolution numbers for the best pair
        fa = np.asarray(Image.open(pa).convert('RGB'), dtype=np.int16)
        fb = np.asarray(Image.open(b[best[1]][1]).convert('RGB'), dtype=np.int16)
        if fa.shape != fb.shape:
            print('%d %d size differs %s %s' % (na, b[best[1]][0], fa.shape, fb.shape), file=out)
            continue
        diff = np.abs(fa - fb)
        mean = float(diff.mean())
        over = float((diff.max(axis=2) > 8).mean())
        h, w = diff.shape[0] // 4, diff.shape[1] // 4
        cells = [(float(diff[r * h:(r + 1) * h, c * w:(c + 1) * w].mean()), r, c) for r in range(4) for c in range(4)]
        cm, cr, cc = max(cells)
        stats.append(mean)
        print('%6d %6d %7.3f %6.2f%% (%d,%d) %7.3f' % (na, b[best[1]][0], mean, over * 100, cr, cc, cm), file=out)
    if stats:
        s = sorted(stats)
        print('frames %d: mean abs diff median %.3f, min %.3f, max %.3f; frames at <= 1.0: %d' % (len(s), s[len(s) // 2], s[0], s[-1], sum(1 for x in s if x <= 1.0)), file=out)


if __name__ == '__main__':
    main()
