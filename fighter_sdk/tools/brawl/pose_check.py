"""Pose check that uses ONLY what the written native files contain, beside the same frame posed from the source.

    python -I pose_check.py <native model folder> <native .nuanmb> <frame> <costume .pac> <motion .pac> <CHR0 name>
            <out .png>

Left half: the native mesh file skinned with the native skeleton file's inverse bind matrices and the native
animation file's tracks at that frame (a bone without a track keeps the skeleton file's local transform), rigging
groups found BY NAME as the engine must, meshes switched by the animation's Visibility group, back faces culled
(counter-clockwise = front). A mesh without a rigging group or a material entry is NOT drawn and is reported.
Right half: the source model's decoded vertices skinned with the source skeleton and the source animation.
Both are drawn flat-shaded, one colour per mesh, the same camera. A picture for a person to look at.
"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brawl import arc, brres, chr0, mdl0, nuanmb, ssbh, tex0     # noqa: E402
from brawl.convert_anim import load_model, read_bool_track       # noqa: E402

W, H = 560, 640


def short_name(mesh_object_name):
    for suffix in ('_VIS_O_OBJShape', '_O_OBJShape', 'Shape'):
        if mesh_object_name.endswith(suffix):
            return mesh_object_name[:-len(suffix)]
    return mesh_object_name


def q_to_m(q, t, s=(1.0, 1.0, 1.0)):
    x, y, z, w = q
    r = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    return [[r[i][0] * s[0], r[i][1] * s[1], r[i][2] * s[2], t[i]] for i in range(3)]


def mul(a, b):
    return [[a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j] + (a[i][3] if j == 3 else 0.0)
             for j in range(4)] for i in range(3)]


def from_file(b):          # 64 bytes, basis vectors in rows, translation in row 3 -> 3x4 column-vector matrix
    v = struct.unpack('<16f', b)
    return [[v[0 + i], v[4 + i], v[8 + i], v[12 + i]] for i in range(3)]


def point(m, p):
    return (m[0][0] * p[0] + m[0][1] * p[1] + m[0][2] * p[2] + m[0][3],
            m[1][0] * p[0] + m[1][1] * p[1] + m[1][2] * p[2] + m[1][3],
            m[2][0] * p[0] + m[2][1] * p[1] + m[2][2] * p[2] + m[2][3])


LAST_BONES = {}            # bone name -> world position of the last native pose
MARKS = (('Throw', (255, 255, 0)), ('Sword1', (0, 255, 255)), ('Trans', (255, 255, 255)))   # crosses on the sheet


def mark(img, x_off, pos, colour):
    ca, sa = math.cos(math.radians(35)), math.sin(math.radians(35))
    x = int(x_off + W / 2 + (pos[0] * ca + pos[2] * sa) * 24.0)
    y = int(H - 40 - pos[1] * 24.0)
    for d in range(-9, 10):
        for px, py in ((x + d, y), (x, y + d), (x + d, y + 1), (x + 1, y + d)):
            if x_off <= px < x_off + W and 0 <= py < H:
                o = (py * 2 * W + px) * 4
                img[o:o + 3] = bytes(colour)


KEEP_ROOT = [False]      # True: the root's travel is left in (what would be drawn if the engine did not
#                            take the root bone's travel out); False: the figure relative to the root bone


def native_pose(folder, anim_path, frame):
    _m, _v, skel = ssbh.load(os.path.join(folder, 'model.nusktb'))
    _m, _v, mesh = ssbh.load(os.path.join(folder, 'model.numshb'))
    _m, _v, modl = ssbh.load(os.path.join(folder, 'model.numdlb'))
    _m, _v, matl = ssbh.load(os.path.join(folder, 'model.numatb'))
    _m, _v, anim = ssbh.load(anim_path)
    tracks, vis = {}, {}
    for g in anim['groups']:
        for node in g['nodes']:
            t = node['tracks'][0]
            data = anim['buffer'][t['data_offset']:t['data_offset'] + t['data_size']]
            if g['type'] == 1:
                fr, _i = nuanmb.decode(data, t['flags'], t['frame_count'])
                if fr:               # a track this tool's description does not fit is left at the bind value
                    tracks[node['name']] = fr[min(frame, len(fr) - 1)]
            elif g['type'] == 2:
                vals = read_bool_track(data, t['flags'], t['frame_count'])
                vis[node['name']] = vals[min(frame, len(vals) - 1)]
    names = [b['name'] for b in skel['bone_entries']]
    world = [None] * len(names)

    def world_of(i):                 # a parent can come later in the file's bone list
        if world[i] is None:
            b = skel['bone_entries'][i]
            if b['name'] in tracks:
                s, q, t = tracks[b['name']]
                if b['parent'] < 0 and not KEEP_ROOT[0]:
                    t = (0.0, 0.0, 0.0)         # the root's travel is not part of the pose (as on the source side)
                loc = q_to_m(q, t, s)
            else:
                loc = from_file(skel['local'][i])
            world[i] = loc if b['parent'] < 0 else mul(world_of(b['parent']), loc)
        return world[i]
    for i in range(len(names)):
        world_of(i)
    LAST_BONES.clear()
    LAST_BONES.update({n: (world[i][0][3], world[i][1][3], world[i][2][3]) for i, n in enumerate(names)})
    skin = {n: mul(world[i], from_file(skel['inv_world'][i])) for i, n in enumerate(names)}
    rig = {(r['mesh_name'], r['subindex']): r for r in mesh['rigging']}
    rig_order = [(r['mesh_name'].encode(), r['subindex']) for r in mesh['rigging']]
    labels = [e['label'] for e in matl['entries']]
    mat_of = {(e['mesh_name'], e['subindex']): e['material_label'] for e in modl['entries']}
    sorted_ok = rig_order == sorted(rig_order) and [x.encode() for x in labels] == sorted(x.encode() for x in labels)
    vb0, ib = mesh['vertex_buffers'][0]['data'], mesh['index_buffer']
    out, notes = [], []
    if not sorted_ok:
        notes.append('rigging groups / material labels NOT SORTED: the engine would miss some')
    for oi, o in enumerate(mesh['objects']):
        key = (o['name'], o['subindex'])
        short = short_name(o['name'])
        if key not in rig or mat_of.get(key) not in labels:
            notes.append('%s: no rigging group or material: not drawn' % o['name'])
            continue
        if short in vis and not vis[short]:
            continue
        n = o['vertex_count']
        P = [struct.unpack_from('<3f', vb0, o['vb0_offset'] + k * 28) for k in range(n)]
        acc = [[0.0, 0.0, 0.0] for _ in range(n)]
        if o['parent_bone_name'] and not rig[key]['buffers']:
            # a mesh parented to one bone (the game's weapon / eye meshes): positions in model space at bind
            m = skin[o['parent_bone_name']]
            acc = [list(point(m, p)) for p in P]
        for b in rig[key]['buffers']:
            m = skin[b['bone_name']]
            for k in range(len(b['data']) // 6):
                vi, w = struct.unpack_from('<Hf', b['data'], k * 6)
                p = point(m, P[vi])
                acc[vi][0] += p[0] * w
                acc[vi][1] += p[1] * w
                acc[vi][2] += p[2] * w
        idx = struct.unpack_from('<%dH' % o['vertex_index_count'], ib, o['index_buffer_offset'])
        out.append((oi, acc, [idx[i:i + 3] for i in range(0, len(idx), 3)]))
    return out, notes


def source_pose(costume, motion, name, frame):
    model = load_model(costume)
    a = arc.load(motion)
    c = None
    for e in a.entries:
        if e.kind() == 'BRRES':
            for nm, off in brres.Brres(e.data).chr():
                if nm == name:
                    c = chr0.Chr0(e.data, off)
    ent = {en.name: en for en in c.entries}
    world = {}
    for b in model.bones:
        if b.name in ent:
            en = ent[b.name]
            s, r, t = en.sample(float(frame))
            s = s or (b.scale if en.code >> 7 & 1 else (1, 1, 1))
            r = r or (b.rot if en.code >> 8 & 1 else (0, 0, 0))
            t = t or (b.trans if en.code >> 9 & 1 else (0, 0, 0))
            if b.name == 'TransN':
                t = (0.0, 0.0, 0.0)             # root motion is not part of the pose
            loc = mdl0.mat_from_srt(s, r, t)
        else:
            loc = mdl0.mat_from_srt(b.scale, b.rot, b.trans)
        world[b.index] = loc if b.parent < 0 else mdl0.mat_mul(world[b.parent], loc)
    inv = {}
    for b in model.bones:
        w = [list(r) for r in b.world] + [[0, 0, 0, 1]]
        from brawl.convert_model import m4_inv_affine
        iw = m4_inv_affine(w)
        inv[b.index] = mdl0.mat_mul(world[b.index], tuple(tuple(r) for r in iw[:3]))
    out = []
    for me in model.meshes:
        model.decode(me)
        acc = []
        for p, infl in zip(me.positions, me.weights):
            x = y = z = 0.0
            for bi, w in infl:
                q = mdl0.mat_point(inv[bi], p)
                x += q[0] * w
                y += q[1] * w
                z += q[2] * w
            acc.append((x, y, z))
        out.append((me.index, acc, me.triangles, me.name, model.bones[me.draw_bone].name))
    return out


def draw(img, zb, x_off, meshes, cull):
    ca, sa = math.cos(math.radians(35)), math.sin(math.radians(35))
    sc = 24.0
    for item in meshes:
        oi, P, tris = item[0], item[1], item[2]
        col = ((oi * 67) % 180 + 60, (oi * 131) % 180 + 60, (oi * 29) % 180 + 60)
        S = []
        for p in P:
            x = p[0] * ca + p[2] * sa
            z = -p[0] * sa + p[2] * ca
            S.append((x_off + W / 2 + x * sc, H - 40 - p[1] * sc, z))
        for a, b, c in tris:
            (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = S[a], S[b], S[c]
            area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
            if abs(area) < 1e-9:
                continue
            if cull and area > 0:          # screen y is down: counter-clockwise in the world = negative here
                continue
            # flat shade from the screen-space normal
            nz = abs(area) / (math.sqrt(((y1 - y0) * (z2 - z0) - (z1 - z0) * (y2 - y0)) ** 2 +
                                        ((z1 - z0) * (x2 - x0) - (x1 - x0) * (z2 - z0)) ** 2 + area * area) + 1e-9)
            sh = 0.35 + 0.65 * nz
            for y in range(max(0, int(min(y0, y1, y2))), min(H - 1, int(max(y0, y1, y2)) + 1) + 1):
                for x in range(max(x_off, int(min(x0, x1, x2))), min(x_off + W - 1, int(max(x0, x1, x2)) + 1) + 1):
                    px, py = x + 0.5, y + 0.5
                    w0 = ((x1 - px) * (y2 - py) - (x2 - px) * (y1 - py)) / area
                    w1 = ((x2 - px) * (y0 - py) - (x0 - px) * (y2 - py)) / area
                    w2 = 1 - w0 - w1
                    if w0 < 0 or w1 < 0 or w2 < 0:
                        continue
                    z = w0 * z0 + w1 * z1 + w2 * z2
                    if z <= zb[y * 2 * W + x]:
                        continue
                    zb[y * 2 * W + x] = z
                    o = (y * 2 * W + x) * 4
                    img[o] = int(col[0] * sh)
                    img[o + 1] = int(col[1] * sh)
                    img[o + 2] = int(col[2] * sh)


def main(a):
    folder, anim_path, frame, costume, motion, name, out = a[0], a[1], int(a[2]), a[3], a[4], a[5], a[6]
    native, notes = native_pose(folder, anim_path, frame)
    source = source_pose(costume, motion, name, frame)
    # the source side: only the meshes the native side draws at this frame would be a circular check; instead the
    # source's meshes are all drawn except those whose visibility bone the native file hides by name
    shown = {m[0] for m in native}
    _mm, _v, mesh = ssbh.load(os.path.join(folder, 'model.numshb'))
    native_names = [short_name(o['name']) for o in mesh['objects']]
    src = []
    hidden_by_file = 0
    for m in source:
        if m[3] in native_names and native_names.index(m[3]) not in shown:
            hidden_by_file += 1
            continue
        src.append(m)
    img = bytearray(b'\x28\x28\x30\xff' * (2 * W * H))
    zb = [-1e9] * (2 * W * H)
    draw(img, zb, 0, native, True)
    draw(img, zb, W, src, True)
    for y in range(H):
        o = (y * 2 * W + W) * 4
        img[o:o + 3] = b'\xff\xff\xff'
    tex0.write_png(out, 2 * W, H, img)
    worst = 0.0
    by_index = {m[0]: m for m in native}
    for m in src:
        k = native_names.index(m[3]) if m[3] in native_names else None
        if k in by_index and len(by_index[k][1]) == len(m[1]):
            for p, q in zip(by_index[k][1], m[1]):
                worst = max(worst, abs(p[0] - q[0]), abs(p[1] - q[1]), abs(p[2] - q[2]))
    print('%s frame %d: native side %d meshes drawn (%d of the file not drawn at this frame), source side %d; '
          'largest distance between a native skinned vertex and the same source vertex: %.4f; %s' % (
              name, frame, len(native), len(mesh['objects']) - len(native), len(src), worst, out))
    for n in notes:
        print('   NOTE: ' + n)


def native_only(a):
    """pose_check.py native <model folder> <out .png> <anim>:<frame> [<anim>:<frame> ...]   (up to 2 per sheet row
    is not enforced: two poses are drawn side by side per call; more are written to <out>_<n>.png)"""
    folder, out = a[0], a[1]
    items = a[2:]
    for n in range(0, len(items), 2):
        img = bytearray(b'\x28\x28\x30\xff' * (2 * W * H))
        zb = [-1e9] * (2 * W * H)
        for k, it in enumerate(items[n:n + 2]):
            path, frame = it.rsplit(':', 1)
            KEEP_ROOT[0] = frame.endswith('+root')       # "<anim>:<frame>+root" = with the root's travel
            frame = frame.replace('+root', '')
            meshes, notes = native_pose(folder, path, int(frame))
            draw(img, zb, k * W, meshes, True)
            for bone, colour in MARKS:           # yellow = Throw (where a held opponent is put), cyan = Sword1,
                if bone in LAST_BONES:           # white = the root
                    mark(img, k * W, LAST_BONES[bone], colour)
            print('   bones: ' + ', '.join('%s (%.1f %.1f %.1f)' % ((b,) + tuple(LAST_BONES[b])) for b, _c in MARKS
                                           if b in LAST_BONES))
            ys = [p[1] for m in meshes for p in m[1]]
            xs = [p[0] for m in meshes for p in m[1]]
            zs = [p[2] for m in meshes for p in m[1]]
            print('%s frame %s: %d meshes drawn; posed box x %.1f..%.1f y %.1f..%.1f z %.1f..%.1f' % (
                os.path.basename(path), frame, len(meshes), min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)))
        name = out if n == 0 else out.replace('.png', '_%d.png' % (n // 2))
        tex0.write_png(name, 2 * W, H, img)
        print('   ' + name)


if __name__ == '__main__':
    if len(sys.argv) >= 5 and sys.argv[1] == 'native':
        native_only(sys.argv[2:])
    elif len(sys.argv) != 8:
        print(__doc__)
    else:
        main(sys.argv[1:])
