"""Track V session 5: compute outputs of two back ends for dispatches with the SAME inputs (SSBU_COMPUTE_CMP=<folder> runs).
    python tests/vk5_ccmp.py <folder a> <folder b>
Files are <hash of the dispatch's inputs>_<storage index>.bin = the written storage range after it landed in guest memory.
Per common file: bytes equal or not; as float32: largest absolute and largest relative difference (finite values)."""
import os, sys
import numpy as np

a, b = sys.argv[1], sys.argv[2]
names = sorted(set(os.listdir(a)) & set(os.listdir(b)))
print('files: %d in a, %d in b, %d with the same name (same inputs)' % (len(os.listdir(a)), len(os.listdir(b)), len(names)))
same = sized = 0
worst_abs = worst_rel = 0.0
nbytes = ndiffw = nwords = 0
big = []
for n in names:
    x = open(os.path.join(a, n), 'rb').read()
    y = open(os.path.join(b, n), 'rb').read()
    if len(x) != len(y):
        sized += 1
        continue
    nbytes += len(x)
    if x == y:
        same += 1
        continue
    k = len(x) // 4 * 4
    xi, yi = np.frombuffer(x[:k], '<u4'), np.frombuffer(y[:k], '<u4')
    d = xi != yi
    ndiffw += int(d.sum())
    xf, yf = xi.view('<f4')[d].astype(np.float64), yi.view('<f4')[d].astype(np.float64)
    ok = np.isfinite(xf) & np.isfinite(yf)
    if ok.any():
        ab = np.abs(xf[ok] - yf[ok])
        rel = ab / np.maximum(np.maximum(np.abs(xf[ok]), np.abs(yf[ok])), 1e-6)
        worst_abs = max(worst_abs, float(ab.max()))
        worst_rel = max(worst_rel, float(rel.max()))
        if ab.max() > 1e-3:
            big.append((n, float(ab.max()), int(d.sum()), len(xi)))
    nwords += len(xi)
print('byte-identical: %d of %d; different sizes: %d; bytes compared: %d' % (same, len(names), sized, nbytes))
print('in the files that differ: %d of %d 32-bit words differ; largest absolute difference as float %.3g, largest relative %.3g' % (ndiffw, nwords, worst_abs, worst_rel))
for e in big[:10]:
    print('  above 1e-3: %s max abs %.4g, %d of %d words differ' % e)
