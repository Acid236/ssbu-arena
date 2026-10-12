"""python tests/bmp2png.py <scale divisor> <out dir> <frame.bmp>...   -- 24-bit BMP frames to reduced PNGs (no dependencies but numpy)
   python tests/bmp2png.py sheet <divisor> <out.png> <cols> <frame.bmp>...  -- contact sheet, left to right, top to bottom"""
import struct, sys, zlib, os
import numpy as np

def load(path):
    d = open(path, 'rb').read()
    off, = struct.unpack_from('<I', d, 10)
    w, h = struct.unpack_from('<ii', d, 18)
    row = (w * 3 + 3) & ~3
    a = np.frombuffer(d, np.uint8, row * abs(h), off).reshape(abs(h), row)[:, :w * 3].reshape(abs(h), w, 3)
    if h > 0: a = a[::-1]
    return a[:, :, ::-1]

def shrink(a, k):
    h, w = a.shape[0] // k * k, a.shape[1] // k * k
    return a[:h, :w].reshape(h // k, k, w // k, k, 3).mean(axis=(1, 3)).astype(np.uint8)

def save(path, a):
    h, w = a.shape[:2]
    raw = np.concatenate([np.zeros((h, 1), np.uint8), a.reshape(h, w * 3)], axis=1).tobytes()
    def chunk(t, b): return struct.pack('>I', len(b)) + t + b + struct.pack('>I', zlib.crc32(t + b) & 0xffffffff)
    open(path, 'wb').write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))

if sys.argv[1] == 'sheet':
    k, out, cols, files = int(sys.argv[2]), sys.argv[3], int(sys.argv[4]), sys.argv[5:]
    imgs = [shrink(load(f), k) for f in files]
    h, w = imgs[0].shape[:2]
    rows = (len(imgs) + cols - 1) // cols
    sheet = np.zeros((rows * (h + 4), cols * (w + 4), 3), np.uint8) + 60
    for i, im in enumerate(imgs):
        y, x = (i // cols) * (h + 4), (i % cols) * (w + 4)
        sheet[y:y + h, x:x + w] = im
    save(out, sheet)
    print(out, 'tiles', w, 'x', h, [os.path.basename(f) for f in files])
else:
    k, out = int(sys.argv[1]), sys.argv[2]
    os.makedirs(out, exist_ok=True)
    for f in sys.argv[3:]:
        save(os.path.join(out, os.path.splitext(os.path.basename(f))[0] + '.png'), shrink(load(f), k))
