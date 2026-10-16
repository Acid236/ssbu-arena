"""Track V session 13: numeric comparison of two pictures of the SAME fight frame.
    python tests/vk13_diff.py <a.bmp> <b.bmp> <out prefix> [threshold=12]
Prints: percentage of pixels that differ at all / by more than the threshold (largest channel difference), mean absolute
difference, and the three largest connected regions of differing 8x8 blocks (a block differs when more than 4 of its
pixels are over the threshold) with their bounding boxes. Writes <out>_map.png (the difference, x4, clipped) and, for the
largest regions, <out>_r<k>.png = crop of a | crop of b | their difference side by side. b is resized to a's size when the
sizes differ. No game content in this file."""
import sys
import numpy as np
from PIL import Image


def main():
    a = Image.open(sys.argv[1]).convert('RGB')
    b = Image.open(sys.argv[2]).convert('RGB')
    out = sys.argv[3]
    thr = int(sys.argv[4]) if len(sys.argv) > 4 else 12
    if b.size != a.size:
        b = b.resize(a.size, Image.BILINEAR)
    A = np.asarray(a).astype(np.int16)
    B = np.asarray(b).astype(np.int16)
    d = np.abs(A - B).max(axis=2)
    h, w = d.shape
    print('%s vs %s: %dx%d | pixels that differ at all %.3f%% | by more than %d: %.3f%% | mean abs difference %.3f | largest %d' % (
        sys.argv[1], sys.argv[2], w, h, 100.0 * (d > 0).mean(), thr, 100.0 * (d > thr).mean(), np.abs(A - B).mean(), d.max()))
    Image.fromarray(np.clip(d * 4, 0, 255).astype(np.uint8)).save(out + '_map.png')
    bs = 8
    hb, wb = h // bs, w // bs
    blk = (d[:hb * bs, :wb * bs] > thr).reshape(hb, bs, wb, bs).sum(axis=(1, 3)) > 4
    lab = np.zeros((hb, wb), np.int32)
    regs = []
    for y in range(hb):
        for x in range(wb):
            if blk[y, x] and not lab[y, x]:
                k = len(regs) + 1
                st = [(y, x)]
                lab[y, x] = k
                n = 0
                x0 = x1 = x
                y0 = y1 = y
                while st:
                    cy, cx = st.pop()
                    n += 1
                    x0 = min(x0, cx); x1 = max(x1, cx); y0 = min(y0, cy); y1 = max(y1, cy)
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = cy + dy, cx + dx
                            if 0 <= ny < hb and 0 <= nx < wb and blk[ny, nx] and not lab[ny, nx]:
                                lab[ny, nx] = k
                                st.append((ny, nx))
                regs.append((n, x0 * bs, y0 * bs, (x1 + 1) * bs, (y1 + 1) * bs))
    regs.sort(reverse=True)
    print('  differing regions: %d; blocks differing: %d of %d' % (len(regs), int(blk.sum()), hb * wb))
    for k, (n, x0, y0, x1, y1) in enumerate(regs[:3]):
        sub = d[y0:y1, x0:x1]
        print('  region %d: %d blocks, box x %d..%d y %d..%d (%dx%d), mean difference inside %.1f, largest %d' % (k, n, x0, x1, y0, y1, x1 - x0, y1 - y0, sub.mean(), sub.max()))
        m = 24
        bx = (max(0, x0 - m), max(0, y0 - m), min(w, x1 + m), min(h, y1 + m))
        ca, cb = a.crop(bx), b.crop(bx)
        cd = Image.fromarray(np.clip(d[bx[1]:bx[3], bx[0]:bx[2]] * 4, 0, 255).astype(np.uint8)).convert('RGB')
        strip = Image.new('RGB', (ca.width * 3 + 8, ca.height))
        strip.paste(ca, (0, 0)); strip.paste(cb, (ca.width + 4, 0)); strip.paste(cd, (ca.width * 2 + 8, 0))
        if strip.width > 1800:
            strip = strip.resize((1800, max(1, strip.height * 1800 // strip.width)), Image.BILINEAR)
        strip.save('%s_r%d.png' % (out, k))


main()
