"""Prepare the native boot loader from Ultimate Frame Data's Kirby Inhale GIF.

The Kirby animation is retained, while its opaque debug volumes are redrawn
as the translucent wireframe spheres used on the Arena website. These are a
stylized loading illustration, not a frame-data visualization.
No network access is needed after the explicitly sourced GIF is downloaded.
"""
import argparse
import hashlib
import math
from pathlib import Path
from urllib.request import urlopen

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

REPO = Path(__file__).resolve().parents[2]
SOURCE_URL = 'https://ultimateframedata.com/hitboxes/kirby/KirbyInhale.gif'
SIZE = (384, 256)
FRAMES = 60
FPS = 30
COLS = 10
ACCENT = (101, 199, 255)  # arena-website/src/app/globals.css --accent
PALE = (198, 234, 255)    # arena-website/src/components/arena-art.tsx HitSphere


def kirby_body(frame):
    """Separate Kirby from the old blue/purple overlays before redrawing them.

    The source's debug spheres composite blue at .5 and purple at .75 per
    projected sphere. Undo those flat tints in the character area. The opening
    is repainted because the source's yellow search volume hides its colour.
    """
    rgb = np.array(frame.convert('RGB'), dtype='float32')
    yy, xx = np.mgrid[:rgb.shape[0], :rgb.shape[1]]
    for cx, cy, r in ((267, 263, 114), (337, 263, 114)):
        inside = (xx-cx)**2 + (yy-cy)**2 <= r*r
        rgb[inside] = (rgb[inside] - (96, 0, 96)) / .25
    for cx, cy, r in ((335, 251, 154), (456, 251, 168)):
        inside = (xx-cx)**2 + (yy-cy)**2 <= r*r
        rgb[inside] = rgb[inside]*2 - (0, 0, 252)
    rgb = np.clip(rgb, 0, 255)
    red, green, blue = rgb.transpose(2, 0, 1)
    keep = (red > 110) & (red > blue*.85) & (green > 65) & (blue > green*.8) & (xx < 277)
    mask = Image.fromarray((keep*255).astype('uint8'), 'L')
    closed = np.asarray(mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))) > 0
    # Repair the one-pixel raster seams from the old sphere edges, using only
    # neighbouring character pixels; do not pull their grey matte into Kirby.
    for _ in range(3):
        total = np.zeros_like(rgb)
        weights = np.zeros_like(red)
        for dy, dx in ((-1,0), (1,0), (0,-1), (0,1)):
            valid = np.roll(keep, (dy, dx), axis=(0,1))
            total += np.roll(rgb, (dy, dx), axis=(0,1)) * valid[..., None]
            weights += valid
        repair = closed & ~keep & (weights > 0)
        rgb[repair] = total[repair] / weights[repair, None]
        keep |= repair
    # Remove isolated compression specks outside the character component.
    mask = Image.fromarray((keep*255).astype('uint8'), 'L').copy()
    ImageDraw.floodfill(mask, (100, 200), 128)
    out = Image.fromarray(rgb.astype('uint8'), 'RGB').convert('RGBA')
    out.putalpha(Image.fromarray((np.asarray(mask) == 128).astype('uint8')*255, 'L'))
    d = ImageDraw.Draw(out)
    d.ellipse((217,183,294,337), fill=(9,14,21,255), outline=(249,187,214,255), width=5)
    return out


def hit_sphere(canvas, cx, cy, r, phase, pale=False, strength=1):
    """Match the website's HitSphere: light fill, rim and two curved meridians."""
    colour = PALE if pale else ACCENT
    sphere = Image.new('RGBA', canvas.size)
    d = ImageDraw.Draw(sphere)
    d.ellipse((cx-r,cy-r,cx+r,cy+r), fill=(*colour, round(15*strength)),
              outline=(*colour, round(215*strength)), width=4)
    for rx, ry, angle, alpha in ((r*.36,r,20+3*math.sin(phase),110),
                                 (r,r*.30,-15+3*math.cos(phase),90)):
        angle = math.radians(angle)
        points = []
        for step in range(129):
            t = step*2*math.pi/128
            x, y = rx*math.cos(t), ry*math.sin(t)
            points.append((cx+x*math.cos(angle)-y*math.sin(angle),
                           cy+x*math.sin(angle)+y*math.cos(angle)))
        d.line(points, fill=(*colour, round(alpha*strength)), width=3, joint='curve')
    d.ellipse((cx-2,cy-2,cx+2,cy+2), fill=(*colour, round(190*strength)))
    # A restrained halo, softer than the actual rim, just as on the site.
    glow = sphere.filter(ImageFilter.GaussianBlur(4))
    glow.putalpha(glow.getchannel('A').point(lambda a: round(a*.22)))
    canvas.alpha_composite(glow)
    canvas.alpha_composite(sphere)


def make_frames(source):
    gif = Image.open(source)
    if gif.size != (687, 463) or gif.n_frames != 18:
        raise ValueError('UFD source changed: recheck the measured overlay positions before preparing the atlas.')
    poses = []
    for i in range(gif.n_frames):
        gif.seek(i)
        poses.append(kirby_body(gif.copy()))
    # One fixed crop and baseline for the entire cycle: no per-frame recentering.
    bounds = (50, 70, 640, 430)
    output = []
    for i in range(FRAMES):
        t = i / FPS
        phase = 2 * math.pi * t / (FRAMES / FPS)
        # Two full source cycles per loop. The boundary advances 17 -> 0.
        pose = poses[(i * len(poses) * 2 // FRAMES) % len(poses)].crop(bounds)
        sx = 1 + .012 * math.sin(phase)
        sy = 1 - .012 * math.sin(phase)
        scale_x, scale_y = 296 / pose.width * sx, 296 / pose.width * sy
        pose = pose.resize((round(pose.width*scale_x*3), round(pose.height*scale_y*3)), Image.Resampling.LANCZOS)
        canvas = Image.new('RGBA', (SIZE[0]*3, SIZE[1]*3))
        d = ImageDraw.Draw(canvas)
        # Soft floor anchor; Kirby moves only a few pixels, never around the screen.
        d.ellipse((39*3, 211*3, 177*3, 220*3), fill=(*ACCENT, 22))
        bob = round(2 * math.sin(phase))
        origin_x, origin_y = 31*3, (219+bob)*3 - pose.height
        canvas.alpha_composite(pose, (origin_x, origin_y))
        # The website's spheres replace the solid blue and purple debug disks.
        for j, (cx, cy, radius) in enumerate(((456,251,168), (335,251,154), (302,251,59))):
            pulse = 1 + .012*math.sin(phase - j*.6)
            hit_sphere(canvas, origin_x + (cx-bounds[0])*scale_x*3,
                       origin_y + (cy-bounds[1])*scale_y*3,
                       radius*scale_x*3*pulse, phase, pale=j==1, strength=.76 if j==1 else 1)
        mouth_x = origin_x + (255-bounds[0])*scale_x*3
        mouth_y = origin_y + (260-bounds[1])*scale_y*3
        d = ImageDraw.Draw(canvas)
        # Staggered motes converge on the mouth; fade at both ends of the path.
        for j in range(7):
            p = (t + j / 7) % 1
            travel = 1 - p
            x = mouth_x + 205*3 * travel ** .82
            lane = (-1 if j % 2 else 1) * (20 + (j % 3) * 15)
            y = mouth_y + lane*3 * travel ** 1.45
            a = round(210 * math.sin(math.pi * p) ** .7)
            length = (3 + 8 * travel)*3
            d.line((x, y, x + length, y + lane*.054), fill=(*ACCENT, a), width=3)
        output.append(canvas.resize(SIZE, Image.Resampling.LANCZOS))
    return output


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--download', action='store_true')
    ap.add_argument('--preview', type=Path)
    a = ap.parse_args()
    source = REPO / 'media/sources/KirbyInhale.gif'
    if a.download:
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(urlopen(SOURCE_URL, timeout=30).read())
    frames = make_frames(source)
    atlas = Image.new('RGBA', (SIZE[0] * COLS, SIZE[1] * (FRAMES // COLS)))
    for i, frame in enumerate(frames):
        atlas.alpha_composite(frame, ((i % COLS) * SIZE[0], (i // COLS) * SIZE[1]))
    atlas.save(REPO / 'media/loading_kirby.png', optimize=True)
    import json
    (REPO / 'media/loading_kirby.json').write_text(json.dumps({
        'source': SOURCE_URL, 'page': 'https://ultimateframedata.com/kirby',
        'credit': 'Ultimate Frame Data / MetalMusicMan; Smash Ultimate hitboxes: Zeckemyro',
        'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'frame_width': SIZE[0], 'frame_height': SIZE[1], 'columns': COLS,
        'frames': FRAMES, 'fps': FPS,
        'edits': 'Original opaque debug volumes separated from Kirby; Arena website wireframe spheres with translucent fills, curved meridians and soft rims; subtle bob, breathing and seamless cyan suction motes.',
        'style_reference': 'arena-website/src/components/arena-art.tsx HitSphere; illustrative geometry, not a frame-data visualization'
    }, indent=2) + '\n', encoding='utf-8')
    if a.preview:
        a.preview.parent.mkdir(parents=True, exist_ok=True)
        preview = []
        for frame in frames:
            bg = Image.new('RGB', SIZE, '#000000')
            bg.paste(frame, mask=frame.getchannel('A'))
            preview.append(bg)
        preview[0].save(a.preview, save_all=True, append_images=preview[1:], duration=[30, 30, 40] * 20, loop=0)
    print('Kirby Inhale: %d frames, %d FPS, %s' % (FRAMES, FPS, atlas.size))


if __name__ == '__main__':
    main()
