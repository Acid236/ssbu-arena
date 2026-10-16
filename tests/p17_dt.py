"""Round 17: compare the tagged draws (nvn_dt.h, SSBU_DRAWTAG=1) of the same fight frame in an OpenGL log and a Vulkan log.
    python tests/p17_dt.py <opengl log> <vulkan log> <fight frame> [box]
Per draw number: the command data and the hashes of guest memory must agree between the two back ends (addresses are
left out of the comparison: only sizes and hashes); in the Vulkan log the bytes BOUND (DTV line, ring copies only) must
have the hash of guest memory. With "box": the OpenGL draws that changed the SSBU_DRAWSHOT_BOX box are listed with their
DT line and the Vulkan DT / DTV lines of the same number. No game content."""
import re
import sys


def load(path, fight):
    dt, dtv, box = {}, {}, []
    last = None
    with open(path, errors='replace') as f:
        for line in f:
            if line.startswith('DT gl %d ' % fight) or line.startswith('DT vk %d ' % fight):
                p = line.split()
                last = int(p[3])
                dt[last] = line.strip()
            elif line.startswith('DTV %d ' % fight):
                dtv[int(line.split()[2])] = line.strip()
            elif line.startswith('  BOX: draw'):
                m = re.search(r'\(DT (-?\d+)\)', line)
                box.append((int(m.group(1)) if m else last, line.strip()))
    return dt, dtv, box


def norm(line):
    """Fields that must agree: everything but the back end name, guest addresses and program serials."""
    s = re.sub(r'^DT (gl|vk) ', 'DT ', line)
    s = re.sub(r'=[0-9a-f]+\+(\d+)', r'=+\1', s)           # address+size -> +size
    s = re.sub(r'(vs|fs)=#\d+:', r'\1=', s)
    return s


def fields(line):
    return dict((k, v) for k, v in (t.split('=', 1) for t in line.split() if '=' in t))


def main():
    fight = int(sys.argv[3])
    gl, _, box = load(sys.argv[1], fight)
    vk, vkv, _ = load(sys.argv[2], fight)
    print('fight frame %d: OpenGL %d draw commands, Vulkan %d' % (fight, len(gl), len(vk)))
    ndiff = nstale = 0
    for i in sorted(set(gl) | set(vk)):
        a, b = gl.get(i), vk.get(i)
        if a is None or b is None:
            print('draw %d: only in %s' % (i, 'Vulkan' if a is None else 'OpenGL'))
            ndiff += 1
            continue
        if norm(a) != norm(b):
            ndiff += 1
            fa, fb = fields(norm(a)), fields(norm(b))
            d = [k for k in sorted(set(fa) | set(fb)) if fa.get(k) != fb.get(k)]
            print('draw %d DIFFERS in: %s' % (i, ', '.join('%s (gl %s | vk %s)' % (k, fa.get(k), fb.get(k)) for k in d[:8])))
        v = vkv.get(i)
        if v:
            fb, fv = fields(b), fields(v)
            for k, val in fv.items():
                if not k.endswith('_bound') or not val.startswith('ring'):
                    continue
                src = 'ib' if k == 'ib_bound' else k[:-6]
                g = fb.get(src)
                if g and g.split(':')[-1] != val.split(':')[-1]:
                    nstale += 1
                    print('draw %d: Vulkan BOUND bytes of %s differ from guest memory at the draw (guest %s, bound %s)' % (i, src, g, val))
    print('%d draws differ between the back ends; %d bound ranges differ from guest memory in Vulkan' % (ndiff, nstale))
    if len(sys.argv) > 4:
        print('--- OpenGL draws that changed the box:')
        for i, line in box:
            print(line)
            if 'CHANGED' in line and i in gl:
                print('   gl : %s' % gl[i][:1500])
                print('   vk : %s' % vk.get(i, '(none)')[:1500])
                print('   vkv: %s' % vkv.get(i, '(none)')[:900])


main()
