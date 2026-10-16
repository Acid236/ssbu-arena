"""N11: several frames of a capture run side by side, one fixed crop (for looking at a pose closely).
    python tests\\n11_zoom.py <picture folder> <run log> <out.png> <fight frames, comma separated> <x0,y0,x1,y1>
Frames are named as in tests\\n11_gif.py (burst files + the log's SSBU_SHOT_FIGHT line). No game content here."""
import os
import re
import sys

from PIL import Image

d, logp, out = sys.argv[1], sys.argv[2], sys.argv[3]
frames = [int(x) for x in sys.argv[4].split(',')]
box = tuple(int(x) for x in sys.argv[5].split(','))
m = re.search(r'shot: fight frame (\d+) saved at presented frame (\d+)', open(logp, errors='replace').read())
off = int(m.group(2)) - int(m.group(1))
files = {int(re.match(r'burst_\d+_(\d+)', f).group(1)) - off: os.path.join(d, f) for f in os.listdir(d) if f.startswith('burst_')}
ims = [Image.open(files[f]).convert('RGB').crop(box) for f in frames]
w, h = ims[0].size
s = Image.new('RGB', (w * len(ims), h))
for i, im in enumerate(ims):
    s.paste(im, (w * i, 0))
s.save(out)
print(out, s.size)
