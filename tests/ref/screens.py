"""Image helpers and screen recognition for the reference comparison.

A screen is recognised by a coarse signature: the frame reduced to 32x18 RGB (animation, text details and small
moving sprites vanish at that size; layout and colours remain). signatures.json holds one signature per known screen,
taken from the golden reference captures (python tests/ref/screens.py learn). classify() returns the nearest one and
its distance (mean absolute difference per channel, 0..255); the same signatures recognise the screens of the port,
which is itself a first, coarse comparison."""
import json, os, struct, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SIG_FILE = os.path.join(HERE, 'signatures.json')
W, H = 1920, 1080


def load(path):
    """frame as uint8 array (1080, 1920, 3) RGB; BMP frames of the port and PNG screenshots of the emulator"""
    im = Image.open(path).convert('RGB')
    if im.size != (W, H):
        im = im.resize((W, H), Image.BILINEAR)
    return np.asarray(im)


def save(path, a):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    Image.fromarray(np.ascontiguousarray(a).astype(np.uint8)).save(path)


def thumb(a, w=32, h=18):
    """area-averaged reduction"""
    hh, ww = a.shape[0] // h * h, a.shape[1] // w * w
    return a[:hh, :ww].reshape(h, hh // h, w, ww // w, 3).mean(axis=(1, 3))


def dist(t1, t2):
    return float(np.abs(t1 - t2).mean())


def is_black(a, limit=6.0):
    return float(thumb(a).mean()) < limit


def load_signatures():
    if not os.path.isfile(SIG_FILE):
        return {}
    with open(SIG_FILE) as f:
        return {k: np.array(v, dtype=np.float64) for k, v in json.load(f).items()}


def classify(a, sigs=None):
    sigs = load_signatures() if sigs is None else sigs
    t = thumb(a)
    if float(t.mean()) < 6.0:
        return 'black', 0.0
    best, bd = 'unknown', 1e9
    for name, s in sigs.items():
        d = dist(t, s)
        if d < bd:
            best, bd = name, d
    return best, bd


def learn(golden_dir, names):
    sigs = {}
    for n in names:
        p = os.path.join(golden_dir, n + '.png')
        if os.path.isfile(p):
            sigs[n] = np.round(thumb(load(p)), 1).tolist()
    aux = os.path.join(golden_dir, 'aux')
    for f in sorted(os.listdir(aux)) if os.path.isdir(aux) else []:
        if f.endswith('.png'):
            sigs[f[:-4]] = np.round(thumb(load(os.path.join(aux, f))), 1).tolist()
    with open(SIG_FILE, 'w') as f:
        json.dump(sigs, f)
    return sorted(sigs)


if __name__ == '__main__':
    if sys.argv[1] == 'learn':
        import scenario
        print('signatures for', learn(os.path.join(HERE, 'golden'), scenario.SIGNATURE_SCREENS))
    else:
        for p in sys.argv[1:]:
            print(p, classify(load(p)))
