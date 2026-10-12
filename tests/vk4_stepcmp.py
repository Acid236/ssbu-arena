"""Track V, session 4: step-aligned comparison of two renderers on the deterministic match.

    python tests/vk4_stepcmp.py <dir a> <dir b>

Both runs were made with SSBU_SHOT_STEPS=1 (tests/vk4_run.sh, SSBU_FIXED_SEED=1): step_<n>.bmp is the frame presented when
key step n of the input sequence began, counted in input polls, so both folders hold the same step of the same match.
Per step: mean absolute difference (0-255), share of pixels with a channel differing by more than 8 and by more than 32,
largest difference, and where the differing pixels (> 32) are: bounding box in per cent of the picture."""
import os, sys
import numpy as np
from PIL import Image

a, b = sys.argv[1], sys.argv[2]
names = sorted(set(os.listdir(a)) & set(os.listdir(b)))
print('step      mean   >8 %   >32 %   max   box of the pixels differing by more than 32 (x0-x1, y0-y1 in %)')
rows = []
for n in names:
    if not n.startswith('step_'):
        continue
    x = np.asarray(Image.open(os.path.join(a, n)).convert('RGB'), dtype=np.int16)
    y = np.asarray(Image.open(os.path.join(b, n)).convert('RGB'), dtype=np.int16)
    if x.shape != y.shape:
        print('%s  sizes differ: %s %s' % (n, x.shape, y.shape))
        continue
    d = np.abs(x - y).max(axis=2)
    big = d > 32
    box = ''
    if big.any():
        ys, xs = np.where(big)
        box = '%3.0f-%3.0f, %3.0f-%3.0f' % (100.0 * xs.min() / d.shape[1], 100.0 * xs.max() / d.shape[1], 100.0 * ys.min() / d.shape[0], 100.0 * ys.max() / d.shape[0])
    m = float(np.abs(x - y).mean())
    rows.append(m)
    print('%s  %6.3f  %5.2f  %6.2f  %4d   %s' % (n[5:8], m, 100.0 * (d > 8).mean(), 100.0 * big.mean(), int(d.max()), box))
if rows:
    rows.sort()
    print('%d steps: mean abs difference median %.3f, %d steps <= 1.0, %d steps <= 3.0, worst %.3f' % (len(rows), rows[len(rows) // 2], sum(r <= 1.0 for r in rows), sum(r <= 3.0 for r in rows), rows[-1]))
