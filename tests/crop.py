"""python tests/crop.py <frame.bmp> <out.png> <x> <y> <w> <h> [zoom]   -- a region of a saved frame, enlarged (nearest), to look at details"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np

def main():
    src, out, x, y, w, h = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:7])
    zoom = int(sys.argv[7]) if len(sys.argv) > 7 else 2
    argv, sys.argv = sys.argv, ['bmp2png', '1', os.path.dirname(out) or '.']      # bmp2png runs its command line on import
    import bmp2png
    sys.argv = argv
    a = bmp2png.load(src)[y:y + h, x:x + w]
    a = np.repeat(np.repeat(a, zoom, axis=0), zoom, axis=1)
    bmp2png.save(out, np.ascontiguousarray(a))
    print(out, a.shape)

main()
