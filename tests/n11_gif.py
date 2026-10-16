"""N11: build a GIF from the per-frame pictures of a game run (SSBU_SHOT_BURST files burst_<n>_<presented frame>.bmp).

    python tests\\n11_gif.py <picture folder> <run log> <out.gif> <first fight frame> <last fight frame> <x,y,w,h | auto> [width, default 480] [step, default 2]

The fight frame of a picture = the presented frame in its file name minus an offset read from the run's log: the line
`shot: fight frame F saved at presented frame Q` (one SSBU_SHOT_FIGHT picture in the same run gives it).
Crop: a fixed rectangle of the 1920x1080 picture, or `auto` = the bounding box of everything that changes between
the pictures inside the stage's middle band (the fighter, when it is the only thing moving), padded, 4:3 at least.
Every <step>-th frame, 60 / step pictures per second, one shared palette. Prints the size; if the file is larger than
8 MB it is rebuilt smaller (width x 0.8) until it fits. With --keep the pictures stay; without it NOTHING is deleted
here either (the caller deletes the folder). --sheet <png> also writes four evenly spaced frames side by side.
No game content in this file."""
import os
import re
import sys

from PIL import Image, ImageChops


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    sheet = sys.argv[sys.argv.index('--sheet') + 1] if '--sheet' in sys.argv else None
    if sheet:
        args.remove(sheet)
    folder, log, out, f0, f1, crop = args[0], args[1], args[2], int(args[3]), int(args[4]), args[5]
    width = int(args[6]) if len(args) > 6 else 480
    step = int(args[7]) if len(args) > 7 else 2
    m = re.search(r'shot: fight frame (\d+) saved at presented frame (\d+)', open(log, errors='replace').read())
    assert m, 'no SSBU_SHOT_FIGHT line in the log'
    off = int(m.group(2)) - int(m.group(1))
    files = {}
    for fn in os.listdir(folder):
        k = re.match(r'burst_\d+_(\d+)\.bmp$', fn)
        if k:
            files[int(k.group(1)) - off] = os.path.join(folder, fn)
    frames = [f for f in range(f0, f1 + 1, step) if f in files]
    assert frames, 'no pictures in that range (have %s..%s)' % (min(files) if files else '-', max(files) if files else '-')
    if crop == 'auto':
        base = Image.open(files[frames[0]]).convert('L').resize((480, 270))
        acc = None
        for f in frames[1:]:
            d = ImageChops.difference(base, Image.open(files[f]).convert('L').resize((480, 270))).point(lambda v: 255 if v > 40 else 0)
            acc = d if acc is None else ImageChops.lighter(acc, d)
        box = acc.crop((0, 40, 480, 235)).getbbox() if acc else None
        if not box:
            box = (180, 60, 300, 150)
        x0, y0, x1, y1 = box[0] * 4, (box[1] + 40) * 4, box[2] * 4, (box[3] + 40) * 4
        w, h = x1 - x0 + 160, y1 - y0 + 160
        h = max(h, w * 3 // 4)
        w = max(w, h * 4 // 3)
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        x, y = max(0, min(1920 - w, cx - w // 2)), max(0, min(1080 - h, cy - h // 2))
        w, h = min(w, 1920), min(h, 1080)
    else:
        x, y, w, h = (int(v) for v in crop.split(','))
    print('%d pictures (fight frames %d..%d of %d..%d, step %d), crop %d,%d %dx%d' % (len(frames), frames[0], frames[-1], min(files), max(files), step, x, y, w, h))
    while True:
        size = (width, max(2, width * h // w))
        imgs = [Image.open(files[f]).convert('RGB').crop((x, y, x + w, y + h)).resize(size, Image.LANCZOS) for f in frames]
        pal = imgs[len(imgs) // 2].quantize(colors=128, method=Image.MEDIANCUT)
        q = [im.quantize(palette=pal, dither=Image.Dither.NONE) for im in imgs]
        q[0].save(out, save_all=True, append_images=q[1:], duration=int(1000 * step / 60), loop=0, optimize=False)
        mb = os.path.getsize(out) / 1e6
        print('%s: %dx%d, %d frames, %.1f MB' % (out, size[0], size[1], len(q), mb))
        if mb <= 8 or width < 200:
            break
        width = int(width * 0.8)
    if sheet:
        pick = [imgs[i * (len(imgs) - 1) // 3] for i in range(4)]
        s = Image.new('RGB', (size[0] * 4, size[1]))
        for i, im in enumerate(pick):
            s.paste(im, (size[0] * i, 0))
        s.save(sheet)
        print('sheet %s: fight frames %s' % (sheet, [frames[i * (len(frames) - 1) // 3] for i in range(4)]))


if __name__ == '__main__':
    main()
