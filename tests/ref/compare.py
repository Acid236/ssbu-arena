"""Compare the port's checkpoint frames with the reference (golden) ones.

    python tests/ref/compare.py [--port <dir>] [--golden <dir>] [--out <dir>]

Per checkpoint (both frames 1920x1080, no letterboxing on either side):
  * whole-frame numbers: mean absolute difference, block SSIM on luminance, colour histogram intersection, mean colour
    of each side (a colour cast shows as a shift of the mean), amount of fine detail (edges: text, outlines);
  * animated areas are found, not guessed: each side provides a second frame of the same screen about a second later
    (<name>_b.png); blocks that change between the two on either side are left out of the difference search;
  * difference boxes: connected groups of 24x24 blocks whose mean absolute difference exceeds BLOCK_LIMIT; each box is
    a listed difference with a pair of crops (reference | port) and a first guess of its kind (missing / extra
    detail, colour, different content);
  * a sheet: reference | port | heat map of the block differences (animated blocks hatched grey).
The battle is not frame-identical (different timing, a CPU opponent): its checkpoints are PAIRS chosen as the
closest two frames inside the same window of the countdown / the first seconds (see pick_battle).
Writes <out>/report.md, report.json, sheets/<name>.png, crops/<name>_<k>.png. Exit code 0 always: the report is the result."""
import json, os, sys
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refcfg, scenario, screens

B = 24                      # block size
BLOCK_LIMIT = 16.0          # mean absolute difference (0..255) of a block that counts as different
ANIM_LIMIT = 7.0            # a block that changes this much between the two frames of one side is "animated"
MAX_BOXES = 10
RESULT_TAIL = 40


def gray(a):
    return a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114


def blocks(d, b=B):
    """mean over b x b blocks of a 2-D array"""
    h, w = d.shape[0] // b * b, d.shape[1] // b * b
    return d[:h, :w].reshape(h // b, b, w // b, b).mean(axis=(1, 3))


def block_diff(a, b):
    return blocks(np.abs(a.astype(np.float32) - b.astype(np.float32)).mean(axis=2))


def ssim(a, b):
    """block SSIM (8x8 windows) on luminance reduced 2x; 1 = identical structure"""
    ga, gb = blocks(gray(a.astype(np.float32)), 2), blocks(gray(b.astype(np.float32)), 2)
    def win(x):
        h, w = x.shape[0] // 8 * 8, x.shape[1] // 8 * 8
        return x[:h, :w].reshape(h // 8, 8, w // 8, 8).transpose(0, 2, 1, 3).reshape(h // 8, w // 8, 64)
    wa, wb = win(ga), win(gb)
    ma, mb = wa.mean(2), wb.mean(2)
    va, vb = wa.var(2), wb.var(2)
    cov = ((wa - ma[..., None]) * (wb - mb[..., None])).mean(2)
    c1, c2 = 6.5025, 58.5225
    s = ((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma * ma + mb * mb + c1) * (va + vb + c2))
    return float(s.mean()), s


def hist_intersection(a, b):
    tot = 0.0
    for c in range(3):
        ha = np.histogram(a[..., c], 32, (0, 256))[0] / a[..., c].size
        hb = np.histogram(b[..., c], 32, (0, 256))[0] / b[..., c].size
        tot += np.minimum(ha, hb).sum()
    return float(tot / 3)


def edges(a):
    g = gray(a.astype(np.float32))
    gx = np.abs(np.diff(g, axis=1))[:-1, :]
    gy = np.abs(np.diff(g, axis=0))[:, :-1]
    e = np.zeros(g.shape, np.float32)
    e[:-1, :-1] = ((gx + gy) > 48).astype(np.float32)
    return e


def components(mask):
    """8-connected groups of True cells -> list of lists of (y, x)"""
    seen = np.zeros(mask.shape, bool)
    out = []
    H, W = mask.shape
    for y0 in range(H):
        for x0 in range(W):
            if not mask[y0, x0] or seen[y0, x0]:
                continue
            stack, cells = [(y0, x0)], []
            seen[y0, x0] = True
            while stack:
                y, x = stack.pop()
                cells.append((y, x))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        yy, xx = y + dy, x + dx
                        if 0 <= yy < H and 0 <= xx < W and mask[yy, xx] and not seen[yy, xx]:
                            seen[yy, xx] = True
                            stack.append((yy, xx))
            out.append(cells)
    return out


def heat_image(bd, anim):
    """block differences as a colour image (black -> red -> yellow -> white), animated blocks grey"""
    v = np.clip(bd / 96.0, 0, 1)
    r = np.clip(v * 3, 0, 1); g = np.clip(v * 3 - 1, 0, 1); bl = np.clip(v * 3 - 2, 0, 1)
    img = (np.stack([r, g, bl], axis=2) * 255).astype(np.uint8)
    img[anim] = (70, 70, 90)
    return np.repeat(np.repeat(img, B, axis=0), B, axis=1)


def kind_of(ref_c, port_c):
    er, ep = float(edges(ref_c).mean()), float(edges(port_c).mean())
    cr, cp = ref_c.reshape(-1, 3).mean(0), port_c.reshape(-1, 3).mean(0)
    s = ssim(ref_c, port_c)[0] if min(ref_c.shape[:2]) >= 32 else 0.0
    dcol = float(np.abs(cr - cp).max())
    if er > 0.004 and ep < 0.5 * er:
        k = 'detail missing in the port (text / outlines / texture)'
    elif ep > 0.004 and er < 0.5 * ep:
        k = 'detail only in the port'
    elif s > 0.75 and dcol > 10:
        k = 'same shapes, different colour / brightness'
    elif s > 0.75:
        k = 'small difference (edges / position)'
    else:
        k = 'different content'
    return k, {'edge_ref': round(er, 4), 'edge_port': round(ep, 4), 'ssim': round(s, 3),
               'mean_ref': [int(round(x)) for x in cr], 'mean_port': [int(round(x)) for x in cp]}


def compare_pair(name, ref, port, ref_b, port_b, out, note=''):
    bd = block_diff(ref, port)
    anim = np.zeros(bd.shape, bool)
    if ref_b is not None:
        anim |= block_diff(ref, ref_b) > ANIM_LIMIT
    if port_b is not None:
        anim |= block_diff(port, port_b) > ANIM_LIMIT
    diff = (bd > BLOCK_LIMIT) & ~anim
    s_all, _ = ssim(ref, port)
    static = ~anim
    res = {'name': name, 'note': note,
           'mean_abs_diff': round(float(np.abs(ref.astype(np.float32) - port.astype(np.float32)).mean()), 2),
           'mean_abs_diff_static': round(float(bd[static].mean()) if static.any() else 0.0, 2),
           'ssim': round(s_all, 3), 'hist_intersection': round(hist_intersection(ref, port), 3),
           'mean_ref': [int(round(x)) for x in ref.reshape(-1, 3).mean(0)], 'mean_port': [int(round(x)) for x in port.reshape(-1, 3).mean(0)],
           'edge_ref': round(float(edges(ref).mean()), 4), 'edge_port': round(float(edges(port).mean()), 4),
           'animated_pct': round(100.0 * anim.mean(), 1), 'different_pct_of_static': round(100.0 * diff.sum() / max(1, static.sum()), 1),
           'boxes': []}
    comps = components(diff)
    comps.sort(key=lambda c: -sum(bd[y, x] for y, x in c))
    os.makedirs(os.path.join(out, 'crops'), exist_ok=True)
    sheet_boxes = []
    for k, cells in enumerate(comps[:MAX_BOXES]):
        ys, xs = [c[0] for c in cells], [c[1] for c in cells]
        x0, y0, x1, y1 = min(xs) * B, min(ys) * B, (max(xs) + 1) * B, (max(ys) + 1) * B
        px0, py0, px1, py1 = max(0, x0 - 12), max(0, y0 - 12), min(1920, x1 + 12), min(1080, y1 + 12)
        rc, pc = ref[py0:py1, px0:px1], port[py0:py1, px0:px1]
        kind, m = kind_of(ref[y0:y1, x0:x1], port[y0:y1, x0:x1])
        zoom = 3 if (px1 - px0) <= 300 else 2 if (px1 - px0) <= 620 else 1
        pair = np.concatenate([rc, np.full((rc.shape[0], 8, 3), 255, np.uint8), pc], axis=1)
        im = Image.fromarray(pair).resize((pair.shape[1] * zoom, pair.shape[0] * zoom), Image.NEAREST)
        crop_path = os.path.join(out, 'crops', '%s_%d.png' % (name, k + 1))
        im.save(crop_path)
        res['boxes'].append(dict(m, id=k + 1, x=x0, y=y0, w=x1 - x0, h=y1 - y0, blocks=len(cells),
                                 mean_diff=round(float(np.mean([bd[y, x] for y, x in cells])), 1), kind=kind,
                                 crop=os.path.relpath(crop_path, out).replace('\\', '/')))
        sheet_boxes.append((x0, y0, x1, y1, k + 1))
    res['more_boxes'] = max(0, len(comps) - MAX_BOXES)
    # sheet: reference | port | heat
    heat = np.zeros((1080, 1920, 3), np.uint8)
    hi = heat_image(bd, anim)
    heat[:hi.shape[0], :hi.shape[1]] = hi
    tiles = []
    for a, label in ((ref, 'reference (emulator)'), (port, 'port'), (heat, 'difference (grey = animated, left out)')):
        im = Image.fromarray(a).resize((960, 540), Image.BILINEAR)
        d = ImageDraw.Draw(im)
        for x0, y0, x1, y1, k in sheet_boxes:
            d.rectangle((x0 // 2, y0 // 2, x1 // 2 - 1, y1 // 2 - 1), outline=(0, 255, 0))
            d.text((x0 // 2 + 3, y0 // 2 + 2), str(k), fill=(0, 255, 0))
        d.rectangle((0, 0, 330, 14), fill=(0, 0, 0))
        d.text((3, 2), '%s: %s' % (name, label), fill=(255, 255, 255))
        tiles.append(np.asarray(im))
    os.makedirs(os.path.join(out, 'sheets'), exist_ok=True)
    sp = os.path.join(out, 'sheets', name + '.png')
    Image.fromarray(np.concatenate(tiles, axis=1)).save(sp)
    res['sheet'] = os.path.relpath(sp, out).replace('\\', '/')
    return res


# ---------------------------------------------------------------- battle: choose comparable pairs
def burst_frames(d):
    fs = sorted(f for f in os.listdir(d) if f.startswith('b_') and f.endswith('.png')) if os.path.isdir(d) else []
    out = []
    for f in fs:
        try:
            out.append((f, screens.thumb(screens.load(os.path.join(d, f)))))
        except Exception:
            pass
    return out


def phases(frames):
    """indices of the versus splash frames and of the first battle frame in a burst.
    Sequence after the start press: screen fades to black, loading, a logo flash, the versus splash (a still picture
    for seconds), black, then the battle. The splash is the longest run of nearly identical bright frames; the battle
    starts with the first non-black frame after the black frames that follow it."""
    n = len(frames)
    i, blacks = 0, 0
    while i < n and blacks < 3:                           # the loading: at least three black frames in a row
        blacks = blacks + 1 if frames[i][1].mean() < 12 else 0
        i += 1
    v0 = None
    while i + 1 < n:                                      # the first two bright frames that are the same picture
        if frames[i][1].mean() > 25 and frames[i + 1][1].mean() > 25 and screens.dist(frames[i][1], frames[i + 1][1]) < 9:
            v0 = i
            break
        i += 1
    if v0 is None:
        return None, None
    v1 = v0 + 1
    while v1 + 1 < n and screens.dist(frames[v1 + 1][1], frames[v1][1]) < 9:
        v1 += 1
    i = v1 + 1
    while i < n and screens.dist(frames[i][1], frames[v1][1]) < 25:
        i += 1
    while i < n and frames[i][1].mean() < 12:
        i += 1
    return (v0, v1), (i if i < n else None)


def pick_battle(ref_frames, port_frames, port_step, ref_phases=None):
    """-> {'versus': (ref index, port index), 'battle_start': ..., 'battle_idle': ...}; windows in seconds of game time
    after the first battle frame, converted with each side's seconds per burst frame"""
    out = {}
    rv, rb = ref_phases if ref_phases else phases(ref_frames)
    pv, pb = phases(port_frames)
    if rv and pv:
        out['versus'] = ((rv[0] + rv[1] + 1) // 2, (pv[0] + pv[1] + 1) // 2)
    if rb is None or pb is None:
        return out, (rv, rb, pv, pb)
    # The port's frames are counted in game frames (port_step seconds apart); the reference screenshots are not (their
    # spacing depends on how busy the machine was). So the window is set on the port side and the reference frame is
    # whichever battle frame of the golden burst is closest to a port frame of that window.
    used = rb
    for name, (t0, t1) in (('battle_start', (0.8, 3.4)), ('battle_idle', (4.4, 8.0))):
        ri = list(range(used, len(ref_frames)))
        pi = [i for i in range(pb, len(port_frames)) if t0 <= (i - pb) * port_step <= t1]
        best = None
        for i in ri:
            for j in pi:
                d = screens.dist(ref_frames[i][1], port_frames[j][1])
                if best is None or d < best[0]:
                    best = (d, i, j)
        if best:
            out[name] = (best[1], best[2])
            used = best[1] + 1
    # the end of the match: both bursts run to the results screen; the pair is the closest two frames among the last
    # RESULT_TAIL of each side (who won and when is up to the CPU opponent: comparable only if the outcome is the same)
    best = None
    for i in range(max(used, len(ref_frames) - RESULT_TAIL), len(ref_frames)):
        for j in range(max(pb, len(port_frames) - RESULT_TAIL), len(port_frames)):
            dd = screens.dist(ref_frames[i][1], port_frames[j][1])
            if best is None or dd < best[0]:
                best = (dd, i, j)
    if best:
        out['results'] = (best[1], best[2])
    return out, (rv, rb, pv, pb)


def main():
    a = sys.argv[1:]
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d
    port_dir = opt('--port', os.path.join(refcfg.WORK, 'port'))
    gold = opt('--golden', refcfg.GOLDEN)
    out = opt('--out', refcfg.OUT)
    os.makedirs(out, exist_ok=True)
    results, missing = [], []
    def load(d, n):
        p = os.path.join(d, n + '.png')
        return screens.load(p) if os.path.isfile(p) else None
    for name in [s[1] for s in scenario.STEPS if s[0] == 'check']:
        ref, port = load(gold, name), load(port_dir, name)
        if ref is None or port is None:
            missing.append('%s: %s' % (name, 'no reference frame' if ref is None else 'the port did not reach this checkpoint'))
            continue
        results.append(compare_pair(name, ref, port, load(gold, name + '_b'), load(port_dir, name + '_b'), out))
    # battle
    rdir, pdir = os.path.join(gold, 'burst'), os.path.join(port_dir, 'burst')
    rf, pf = burst_frames(rdir), burst_frames(pdir)
    if rf and pf:
        import port_capture
        pfile = os.path.join(rdir, 'phases.txt')            # written with the golden burst: its first n frames are the versus splash
        nv = int(open(pfile).read().strip()) if os.path.isfile(pfile) else 0
        pairs, ph = pick_battle(rf, pf, port_capture.SHOT_EVERY / 60.0, ((0, nv - 1), nv) if nv else None)
        print('battle phases (reference versus run, first battle frame, port versus run, first battle frame):', ph)
        for name in ('versus', 'battle_start', 'battle_idle', 'results'):
            if name not in pairs:
                missing.append('%s: no comparable pair found in the bursts' % name)
                continue
            i, j = pairs[name]
            ref, port = screens.load(os.path.join(rdir, rf[i][0])), screens.load(os.path.join(pdir, pf[j][0]))
            screens.save(os.path.join(out, 'pairs', name + '_ref.png'), ref)
            screens.save(os.path.join(out, 'pairs', name + '_port.png'), port)
            results.append(compare_pair(name, ref, port, None, None, out,
                                        note='closest pair of the window: reference %s, port %s; not frame-identical by nature' % (rf[i][0], pf[j][0])))
    else:
        missing.append('battle: %s' % ('no reference burst' if not rf else 'the port did not reach the battle'))
    with open(os.path.join(out, 'report.json'), 'w') as f:
        json.dump({'results': results, 'missing': missing}, f, indent=1)
    md = ['# Reference comparison report', '',
          'reference = golden captures of the emulator (`tests/ref/golden`), port = `%s`' % port_dir, '',
          '| checkpoint | mean abs diff (static) | SSIM | histogram | mean RGB ref | mean RGB port | edges ref / port | animated % | different % of static | boxes |',
          '|---|---:|---:|---:|---|---|---|---:|---:|---:|']
    for r in results:
        md.append('| %s | %.1f | %.3f | %.3f | %s | %s | %.4f / %.4f | %.1f | %.1f | %d%s |' % (
            r['name'], r['mean_abs_diff_static'], r['ssim'], r['hist_intersection'], r['mean_ref'], r['mean_port'], r['edge_ref'], r['edge_port'],
            r['animated_pct'], r['different_pct_of_static'], len(r['boxes']), '+%d' % r['more_boxes'] if r['more_boxes'] else ''))
    md += [''] + ['- NOT COMPARED: ' + m for m in missing] + ['']
    for r in results:
        md += ['## %s' % r['name'], '', 'sheet: `%s`%s' % (r['sheet'], ('  (' + r['note'] + ')') if r['note'] else ''), '']
        for b in r['boxes']:
            md.append('- box %d at (%d,%d) %dx%d, mean diff %.1f: %s; edges %.4f -> %.4f, mean RGB %s -> %s, SSIM %.2f; crop `%s`' % (
                b['id'], b['x'], b['y'], b['w'], b['h'], b['mean_diff'], b['kind'], b['edge_ref'], b['edge_port'], b['mean_ref'], b['mean_port'], b['ssim'], b['crop']))
        md.append('')
    with open(os.path.join(out, 'report.md'), 'w') as f:
        f.write('\n'.join(md) + '\n')
    print('\n'.join(md[:14 + len(results) + len(missing)]))
    print('report:', os.path.join(out, 'report.md'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
