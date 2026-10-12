"""Track V session 5: read the stage records of cache\\vk\\stage and report sampler declarations per unit.
    python tests/vk5_strec.py [cache dir]      (default ..\\cache\\vk)
Prints: records read, records whose fragment stage declares two sampler kinds on one unit (and which kinds), and
the count of records with a 3D sampler."""
import glob, os, struct, sys, collections

DIM = ['1D', '2D', '3D', 'CUBE', '1DA', '2DA', 'CUBEA']      # enum DIM_* of nvn_vk_draw.c
root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'cache', 'vk')
n = two = with3d = 0
kinds = collections.Counter()
ex = []
for path in glob.glob(os.path.join(root, 'stage', '*.st')):
    b = open(path, 'rb').read()
    if len(b) < 88:
        continue
    magic, stage, code_len = struct.unpack_from('<Iii', b, 0)
    uses_alpha, nsmp = struct.unpack_from('<ii', b, 80)
    n += 1
    per = collections.defaultdict(list)
    for i in range(min(nsmp, 64)):
        unit, dim, shadow, _, binding = struct.unpack_from('<BBBBH', b, 88 + 6 * i)
        per[unit].append((DIM[dim] if dim < 7 else '?%d' % dim, shadow, binding))
    if any(d == '3D' for v in per.values() for d, _, _ in v):
        with3d += 1
    for unit, v in per.items():
        if len(v) > 1:
            two += 1
            kinds[(stage, unit, tuple(sorted(d for d, _, _ in v)))] += 1
            if len(ex) < 5:
                ex.append((os.path.basename(path), unit, v))
print('records %d, with a 3D sampler %d, (record, unit) pairs with two sampler kinds %d' % (n, with3d, two))
for k, c in kinds.most_common(20):
    print('  stage %d unit %d kinds %s: %d records' % (k[0], k[1], k[2], c))
for e in ex:
    print('  e.g.', e)
