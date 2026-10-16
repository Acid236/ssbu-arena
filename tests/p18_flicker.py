"""Round 18: find "black in one frame, lit in the frames before and after" in bursts of consecutive pictures.
    python tests/p18_flicker.py <folder with burst_<fight present>_<presented frame>.bmp> [sheet folder]
For every picture t that has both neighbours t-1 and t+1 (consecutive fight presents): the pixels that are dark in t
(luma < 48) while t-1 and t+1 are both lit (luma > 96) and agree with each other (difference < 30), and the reverse
(lit in t, dark in both neighbours). Counted on a half-size picture; the largest 8x8-cell cluster is reported so that a
compact polygon stands out from edge noise of a moving camera. With a sheet folder: a PNG row t-1 | t | t+1 for the ten
worst pictures, and the box of the cluster. Test tool, no game content."""
import glob
import os
import re
import sys

import numpy as np
from PIL import Image


def luma(path):
    im = Image.open(path).convert('L')
    return np.asarray(im.resize((im.width // 2, im.height // 2)), dtype=np.int16)


def main():
    folder = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    files = {}
    for p in glob.glob(os.path.join(folder, 'burst_*.bmp')):
        m = re.search(r'burst_(\d+)_(\d+)\.bmp$', p)
        files[int(m.group(1))] = p
    res = []
    cache = {}

    def get(n):
        if n not in cache:
            cache[n] = luma(files[n])
        return cache[n]
    for n in sorted(files):
        if n - 1 not in files or n + 1 not in files:
            continue
        a, b, c = get(n - 1), get(n), get(n + 1)
        if os.environ.get('P18_FLICKER_ANY'):          # any one-frame change: darker / lighter by more than 40 than two agreeing neighbours
            agree = np.abs(a - c) < 16
            dark = agree & (b < a - 40)
            lit = agree & (b > a + 40)
        else:
            agree = np.abs(a - c) < 30
            dark = agree & (b < 48) & (a > 96) & (c > 96)
            lit = agree & (b > 96) & (a < 48) & (c < 48)
        best = (0, 0, 0, '')
        for name, mask in (('dark', dark), ('lit', lit)):
            h, w = mask.shape
            cells = mask[:h // 8 * 8, :w // 8 * 8].reshape(h // 8, 8, w // 8, 8).sum(axis=(1, 3))
            full = cells >= 48                                 # cells three quarters covered
            k = int(full.sum())
            if k > best[0]:
                ys, xs = np.nonzero(full)
                best = (k, int(xs.mean()) * 16 + 8, int(ys.mean()) * 16 + 8, name)
        res.append((best[0], int(dark.sum()), int(lit.sum()), n, best))
        cache.pop(n - 2, None)
    res.sort(reverse=True)
    print('%d pictures with both neighbours in %s' % (len(res), folder))
    print('pictures with a cluster of >= 4 full cells (64 x 64 pixels of the full picture or more): %d' % sum(1 for r in res if r[0] >= 4))
    for r in res[:25]:
        print('fight present %6d (%s): full 8x8 cells %4d (%s, around %d,%d of the full picture) | dark-in-one-frame pixels %6d, lit-in-one-frame %6d'
              % (r[3], os.path.basename(files[r[3]]), r[0], r[4][3], r[4][1], r[4][2], r[1], r[2]))
    if out:
        os.makedirs(out, exist_ok=True)
        for r in res[:10]:
            if r[0] < 2:
                break
            n = r[3]
            ims = [Image.open(files[k]).convert('RGB') for k in (n - 1, n, n + 1)]
            w, h = ims[0].size
            sheet = Image.new('RGB', (w // 2 * 3, h // 2))
            for i, im in enumerate(ims):
                sheet.paste(im.resize((w // 2, h // 2)), (i * (w // 2), 0))
            sheet.save(os.path.join(out, 'flicker_%06d.png' % n))
            cx, cy = r[4][1], r[4][2]
            box = (max(0, cx - 240), max(0, cy - 180), min(w, cx + 240), min(h, cy + 180))
            crop = Image.new('RGB', ((box[2] - box[0]) * 3, box[3] - box[1]))
            for i, im in enumerate(ims):
                crop.paste(im.crop(box), (i * (box[2] - box[0]), 0))
            crop.save(os.path.join(out, 'flicker_%06d_crop.png' % n))


main()
