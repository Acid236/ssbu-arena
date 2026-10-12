"""Find every call site in main of the nn::ro imports (BL/B to their PLT stubs) and of other
symbols given on the command line (substring match).  Read-only; uses ..\\recomp.py helpers.

  python find_ro_calls.py [substring ...]     default: nn2ro
"""
import os, sys, struct, bisect
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(os.path.join(HERE, '..'))
sys.path.insert(0, os.getcwd())
import recomp
import numpy as np

pats = sys.argv[1:] or ['2ro']
env = recomp.Env(); env.imports = set(); env.full = True
env.load_plt()
text = np.frombuffer(recomp.IMG, dtype='<u4', count=recomp.TEXT_SIZE // 4, offset=recomp.FILE_OFF)
# PLT stubs
m = ((text[:-3] & 0x9f00001f) == 0x90000010) & ((text[1:-2] & 0xffc003ff) == 0xf9400211) & (text[3:] == 0xd61f0220)
stubs = {}
for i in np.nonzero(m)[0]:
    a = recomp.BASE + int(i) * 4
    nm = env.plt_symbol(a)
    if nm and any(p in nm for p in pats): stubs[a] = nm
print('%d matching PLT stubs' % len(stubs))
starts = env.compute_starts()
isbl = np.nonzero(((text & 0xfc000000) == 0x94000000) | ((text & 0xfc000000) == 0x14000000))[0]
imm = (text[isbl] & 0x3ffffff).astype(np.int64); imm = np.where(imm & 0x2000000, imm - 0x4000000, imm)
tg = recomp.BASE + isbl.astype(np.int64) * 4 + imm * 4
for a, nm in sorted(stubs.items(), key=lambda kv: kv[1]):
    sites = [recomp.BASE + int(i) * 4 for i in isbl[tg == a]]
    print('%x %s' % (a, nm))
    for s in sites:
        f = starts[bisect.bisect_right(starts, s) - 1]
        print('     called at %x  (function f_%x)' % (s, f))
