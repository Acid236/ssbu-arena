"""Convert the port's input files to the yuzu-family TAS script format.

    python tests/ref/seq2tas.py <input.rec | sequence.txt> <out dir>

TAS format (suyu src/input_common/drivers/tas_input.h/.cpp): a text file `script0-<player>.txt` in the emulator's `tas`
folder, one line per frame: `<frame> <buttons> <lx>;<ly> <rx>;<ry>`, buttons = KEY_A;KEY_B;... or NONE, sticks
-32767..32767. A frame without a line is "nothing pressed", so a held input is written on every frame it lasts.
One command is consumed per frame the emulator displays (bootmanager.cpp, OnFrameDisplayed -> Tas::UpdateThread).

A TAS script has no conditions, and loading times differ between the port and the emulator, so ONE script for a whole
path does not line up. The conversion therefore cuts at every wait-for-a-screen:
  * recording (`a <anchor> <polls> <buttons> <lx> <ly>`): one script per anchor, frame = polls since the anchor;
  * SSBU_SEQ text: one script per run of timed steps between two `@...` waits.
Each segment goes to <out>/seg_<k>/script0-1.txt and manifest.txt says which screen change must be seen before
starting it. ref_capture.py does not use these files (it drives the pad through the DSU server, which can wait for
screens); they are for frame-exact playback of one segment with the emulator's TAS hotkeys (Ctrl+F6 load, Ctrl+F5
start: both can be bound to controller buttons in qt-config.ini, `Shortcuts\\Main%20Window\\TAS%20Start\\Stop\\Controller_KeySeq`)."""
import os, re, sys

BITS = ['KEY_A', 'KEY_B', 'KEY_X', 'KEY_Y', 'KEY_LSTICK', 'KEY_RSTICK', 'KEY_L', 'KEY_R', 'KEY_ZL', 'KEY_ZR', 'KEY_PLUS', 'KEY_MINUS',
        'KEY_DLEFT', 'KEY_DUP', 'KEY_DRIGHT', 'KEY_DDOWN']                      # bit order of nn::hid NpadButton = nnhid.c
SEQ_KEY = {'Z': 0, 'X': 1, 'C': 2, 'V': 3, 'Q': 6, 'E': 7, 'A': 8, 'S': 9, '!': 10, '-': 11, 'J': 12, 'I': 13, 'L': 14, 'K': 15}
SEQ_STICK = {'u': (0, 32767), 'd': (0, -32767), 'l': (-32767, 0), 'r': (32767, 0)}


def line(frame, buttons, lx, ly):
    names = ';'.join(BITS[i] for i in range(16) if buttons >> i & 1) or 'NONE'
    return '%d %s %d;%d 0;0' % (frame, names, lx, ly)


def from_rec(path):
    """-> [(condition text, [(frame, buttons, lx, ly) changes])]"""
    segs = {}
    for l in open(path):
        m = re.match(r'a (-?\d+) (-?\d+) ([0-9a-fA-F]+) (-?\d+) (-?\d+)', l)
        if m:
            segs.setdefault(int(m.group(1)), []).append((int(m.group(2)), int(m.group(3), 16) & 0xffff, int(m.group(4)), int(m.group(5))))
    return [('anchor %d reached (screen change number %d since the opening movie was created; classes in nnhid.c)' % (a, a), ch) for a, ch in sorted(segs.items())]


def from_seq(path):
    text = ' '.join(l for l in open(path).read().splitlines() if not l.startswith('#'))
    segs, cond, changes, t = [], 'start of the run', [], 0
    for tok in text.split():
        if tok.startswith('@'):
            if changes:
                segs.append((cond, changes))
            if tok.startswith('@until:'):
                rng, keys = tok[7:].split(':')
                segs.append(('repeat every %s frames until %s draws per frame' % (keys.split('/')[1], rng),
                             [(0, sum(1 << SEQ_KEY[k] for k in keys.split('/')[0] if k in SEQ_KEY), 0, 0), (8, 0, 0, 0)]))
                cond = 'after the repeated press reached its screen'
            else:
                cond = 'wait: ' + tok
            changes, t = [], 0
            continue
        m = re.match(r'(\d+)(?::([^/]+)(?:/(\d+))?)?$', tok)
        t += int(m.group(1))
        if m.group(2):
            hold = int(m.group(3) or 8)
            b = sum(1 << SEQ_KEY[k] for k in m.group(2) if k in SEQ_KEY)
            lx = sum(SEQ_STICK[k][0] for k in m.group(2) if k in SEQ_STICK)
            ly = sum(SEQ_STICK[k][1] for k in m.group(2) if k in SEQ_STICK)
            changes += [(t, b, lx, ly), (t + hold, 0, 0, 0)]
            t += hold + 1
    if changes:
        segs.append((cond, changes))
    return segs


def write(segs, out):
    os.makedirs(out, exist_ok=True)
    man = []
    for k, (cond, changes) in enumerate(segs):
        d = os.path.join(out, 'seg_%02d' % k)
        os.makedirs(d, exist_ok=True)
        base = min(c[0] for c in changes)
        lines, state = [], None
        for i, (f, b, lx, ly) in enumerate(changes):
            end = changes[i + 1][0] if i + 1 < len(changes) else f + 1
            if b or lx or ly:
                lines += [line(fr - base, b, lx, ly) for fr in range(f, end)]
        lines.append(line(changes[-1][0] - base + 1, 0, 0, 0))
        with open(os.path.join(d, 'script0-1.txt'), 'w', newline='\n') as fh:
            fh.write('\n'.join(lines) + '\n')
        man.append('seg_%02d: start %d frames after: %s  (%d frames)' % (k, base, cond, changes[-1][0] - base + 2))
    with open(os.path.join(out, 'manifest.txt'), 'w') as fh:
        fh.write('\n'.join(man) + '\n')
    return man


if __name__ == '__main__':
    src, out = sys.argv[1], sys.argv[2]
    print('\n'.join(write(from_rec(src) if src.endswith('.rec') else from_seq(src), out)))
