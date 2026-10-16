"""Mean absolute difference inside boxes between a shot and the reference of the same fight frame.
    python boxdiff.py <ref.bmp> <shot.bmp> x0,y0,x1,y1 [x0,y0,x1,y1 ...]"""
import sys
import numpy as np
from PIL import Image

a = Image.open(sys.argv[1]).convert('RGB')
b = Image.open(sys.argv[2]).convert('RGB')
if b.size != a.size:
    b = b.resize(a.size, Image.BILINEAR)
A = np.asarray(a).astype(np.int16)
B = np.asarray(b).astype(np.int16)
d = np.abs(A - B).max(axis=2)
print('whole: %.2f %% of pixels over 12' % (100.0 * (d > 12).mean()))
for box in sys.argv[3:]:
    x0, y0, x1, y1 = [int(v) for v in box.split(',')]
    print('box %s: mean difference %.1f, %.1f %% of pixels over 12' % (box, d[y0:y1, x0:x1].mean(), 100.0 * (d[y0:y1, x0:x1] > 12).mean()))
