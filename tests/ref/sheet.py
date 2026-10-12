"""python tests/ref/sheet.py <out.png> <cols> <tile width> <image>...   -- contact sheet with the file name under each tile"""
import os, sys
from PIL import Image, ImageDraw


def sheet(out, cols, tw, files, labels=None):
    th = tw * 9 // 16
    rows = (len(files) + cols - 1) // cols
    s = Image.new('RGB', (cols * (tw + 4), rows * (th + 18)), (40, 40, 40))
    d = ImageDraw.Draw(s)
    for i, f in enumerate(files):
        im = Image.open(f).convert('RGB').resize((tw, th), Image.BILINEAR)
        x, y = (i % cols) * (tw + 4), (i // cols) * (th + 18)
        s.paste(im, (x, y))
        d.text((x + 2, y + th + 3), labels[i] if labels else os.path.basename(f), fill=(255, 255, 255))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    s.save(out)
    return out


if __name__ == '__main__':
    print(sheet(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4:]))
