"""Model converter: a costume archive of the Wii predecessor -> the native model files of one fighter folder.

    python -I convert_model.py roundtrip <folder with native model.* files>
        reads skeleton / mesh / model description / materials with this tool's own parser, writes them again and
        compares byte for byte (the proof that reader and writer agree with the game's own files)

    python -I convert_model.py convert <costume.pac> <out folder> --template-matl <a native .numatb>
            --opaque <label> --alpha <label> [--prefix zero] [--model 0] [--scale 1.0] [--all-meshes]
            [--col <material>=<texture>[@<uv channel>] ...] [--matte <texture>=<RRGGBB> ...]
        writes model.nusktb, model.numshb, model.numshexb, model.numdlb, model.numatb, model.nuhlpb and one
        .nutexb per texture into <out folder>. Materials are copies of two entries of the template file (a plain
        opaque one, one with alpha) pointed at the new textures.

The input is read only. Nothing is executed from it. This file contains no game content.
"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brawl import arc, brres, mdl0, nutexb, ssbh, tex0     # noqa: E402

# Native name the engine / a donor's files may ask for  <-  bone of the package's skeleton it is attached to.
# The package's own bone names are kept; each native name is an extra bone with an identity transform under the
# mapped bone, so it has the mapped bone's position and axes.
BONE_MAP = [
    ('Rot', 'HipN'), ('Hip', 'HipN'), ('Waist', 'WaistN'), ('Bust', 'BustN'), ('Neck', 'NeckN'), ('Head', 'HeadN'),
    ('Face', 'HeadN'), ('ClavicleC', 'BustN'),
    ('ClavicleL', 'LShoulderN'), ('ShoulderL', 'LShoulderJ'), ('ArmL', 'LArmJ'), ('HandL', 'LHandN'),
    ('HaveL', 'LHaveN'),
    ('ClavicleR', 'RShoulderN'), ('ShoulderR', 'RShoulderJ'), ('ArmR', 'RArmJ'), ('HandR', 'RHandN'),
    ('HaveR', 'RHaveN'),
    ('LegC', 'HipN'), ('LegL', 'LLegJ'), ('KneeL', 'LKneeJ'), ('FootL', 'LFootJ'), ('ToeL', 'LToeN'),
    ('LegR', 'RLegJ'), ('KneeR', 'RKneeJ'), ('FootR', 'RFootJ'), ('ToeR', 'RToeN'),
    ('Throw', 'ThrowN'),
    # weapon bones of a sword donor (only added when the package has the mapped bone)
    ('Sword1', 'SwordN'), ('Sword2', 'SwordBladeN'), ('Scabbard', 'SwordSheathedM'), ('Hilt', 'SwordSheathedM'),
]
ROOT = 'Trans'            # the native root; the package's root becomes its child

TEX_COL, TEX_NOR, TEX_PRM = 0x5C, 0x60, 0x62
TEX_COL2, TEX_EMI, TEX_DIFFUSE = 0x5D, 0x61, 0x6A      # second colour layer, emission, the eye-type shaders' colour
SAMPLER_COL = 0x6C
PARAM_RASTERIZER = 0x12


# ------------------------------------------------------------------ matrices (4x4 lists, column-vector convention)
def m4(m34):
    return [list(m34[0]), list(m34[1]), list(m34[2]), [0.0, 0.0, 0.0, 1.0]]


def m4_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def m4_inv_affine(m):
    a = [r[:3] for r in m[:3]]
    det = (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0]) +
           a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    if abs(det) < 1e-12:
        raise ValueError('singular bone matrix')
    inv = [[(a[(j + 1) % 3][(i + 1) % 3] * a[(j + 2) % 3][(i + 2) % 3] -
             a[(j + 1) % 3][(i + 2) % 3] * a[(j + 2) % 3][(i + 1) % 3]) / det for j in range(3)] for i in range(3)]
    t = [m[i][3] for i in range(3)]
    out = [inv[i] + [-sum(inv[i][k] * t[k] for k in range(3))] for i in range(3)]
    return out + [[0.0, 0.0, 0.0, 1.0]]


def native_bytes(m):
    """column-vector 4x4 -> the file's layout (basis vectors in rows 0..2, translation in row 3)."""
    return struct.pack('<16f', *[m[j][i] for i in range(4) for j in range(4)])


IDENT4 = [[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]]


# ------------------------------------------------------------------ skeleton
# ---- the skeleton in NATIVE names (the default since the game runs): a package bone with a clear native
# counterpart takes the native name; the package's root chain is merged into the native standard Trans -> Rot -> Hip.
RENAME = [
    ('Hip', 'HipN'), ('Waist', 'WaistN'), ('Bust', 'BustN'), ('Neck', 'NeckN'), ('Head', 'HeadN'),
    ('ClavicleL', 'LShoulderN'), ('ShoulderL', 'LShoulderJ'), ('ArmL', 'LArmJ'), ('HandL', 'LHandN'),
    ('HaveL', 'LHaveN'),
    ('ClavicleR', 'RShoulderN'), ('ShoulderR', 'RShoulderJ'), ('ArmR', 'RArmJ'), ('HandR', 'RHandN'),
    ('HaveR', 'RHaveN'),
    ('LegL', 'LLegJ'), ('KneeL', 'LKneeJ'), ('FootL', 'LFootJ'), ('ToeL', 'LToeN'),
    ('LegR', 'RLegJ'), ('KneeR', 'RKneeJ'), ('FootR', 'RFootJ'), ('ToeR', 'RToeN'),
    ('Throw', 'ThrowN'), ('Sword1', 'SwordN'), ('Sword2', 'SwordBladeN'), ('Scabbard', 'SwordSheathedM'),
]
MERGE = [('Trans', ['TopN', 'TransN']), ('Rot', ['XRotN', 'YRotN'])]      # parent -> child chains, composed
EXTRA = [('Face', 'Head'), ('ClavicleC', 'Bust'), ('LegC', 'Hip'), ('Hilt', 'Scabbard')]   # identity children


# the "names_min" variant (option --names-min of convert_model / convert_anim / params hurtboxes): only these
# native names are given; every limb and spine bone keeps the package's name, so no engine system that finds a
# bone by its native NAME (leg / arm IK, look-at, hurt-box parts) can take it. Trans and Rot come from MERGE.
NAMES_MIN_KEEP = {'Hip', 'Head', 'HaveL', 'HaveR', 'Throw'}
NAMES_MIN = False
NO_MID_JOINTS = False          # --no-mid-joints: LegC / ClavicleC stay leaves (the hierarchy before 13:37)
CANONICAL_ORDER = False        # the game's standard-bone sequence first (tried 23:27: worse in the game)


def set_names_min(on=True):
    global NAMES_MIN
    NAMES_MIN = on


def bone_plan(model):
    """-> list of (new name, [package bone names composed in order], parent's new name or None) for every bone
    of the native-named skeleton that comes from package bones, in package order."""
    names = {b.index: b.name for b in model.bones}
    by_name = {b.name: b for b in model.bones}
    ren = {pkg: nat for nat, pkg in RENAME if pkg in by_name and (not NAMES_MIN or nat in NAMES_MIN_KEEP)}
    chain_of, first = {}, {}
    for nat, chain in MERGE:
        if all(c in by_name for c in chain) and all(
                names.get(by_name[c].parent) == chain[i] for i, c in enumerate(chain[1:])):
            for c in chain:
                chain_of[c] = nat
            first[chain[0]] = (nat, chain)
    new_name = {}
    plan = []
    for b in model.bones:
        if b.name in chain_of:
            new_name[b.name] = chain_of[b.name]
            if b.name in first:
                nat, chain = first[b.name]
                plan.append((nat, chain, new_name.get(names.get(b.parent))))
            continue
        new_name[b.name] = ren.get(b.name, b.name)
        plan.append((new_name[b.name], [b.name], new_name.get(names.get(b.parent))))
    return plan, new_name


HALF_TURN_X = [[1.0, 0, 0, 0], [0, -1.0, 0, 0], [0, 0, -1.0, 0], [0, 0, 0, 1.0]]     # its own inverse


def reoriented(model):
    """The package mirrors its right side by giving the first bone of the right leg and of the right arm a half
    turn about X at rest. Every rotation of such a bone then sits next to w = 0, where q and -q change places
    from one animation file to the next - and the engine blends files without choosing the nearer of the two
    (seen in the game: the right leg swung out during blends). The local frame of these bones AND of all their
    descendants is therefore turned by that half turn: positions in the world, the mesh and the hierarchy stay
    exactly the same; only the numbers of the local transforms change (rest rotation near 0 instead of near 180).
    -> set of package bone names whose local frame is turned."""
    names = {b.index: b.name for b in model.bones}
    roots = set()
    for b in model.bones:
        rx = abs(b.rot[0]) % 360.0
        if abs(rx - 180.0) < 20.0 and abs(b.rot[1]) < 20.0 and abs(b.rot[2]) < 20.0:
            roots.add(b.index)
    out = set()
    for b in model.bones:                      # parents come first
        if b.index in roots or (b.parent >= 0 and names[b.parent] in out):
            out.add(b.name)
    return out


def reorient_local(m, bone_turned, parent_turned):
    """4x4 local matrix in the turned frames."""
    if parent_turned:
        m = m4_mul(HALF_TURN_X, m)
    if bone_turned:
        m = m4_mul(m, HALF_TURN_X)
    return m


def build_skeleton(model, scale):
    """-> (list of (name, parent, local4), {package bone index -> skeleton index}, mapping rows)."""
    plan, new_name = bone_plan(model)
    by_name = {b.name: b for b in model.bones}
    names = {b.index: b.name for b in model.bones}
    turned = reoriented(model)
    bones, pos = [], {}
    for name, chain, parent in plan:
        loc = IDENT4
        for c in chain:
            b = by_name[c]
            loc = m4_mul(loc, m4(mdl0.mat_from_srt(b.scale, b.rot, tuple(x * scale for x in b.trans))))
        if len(chain) == 1:
            b = by_name[chain[0]]
            loc = reorient_local(loc, b.name in turned, b.parent >= 0 and names[b.parent] in turned)
        pos[name] = len(bones)
        bones.append((name, pos[parent] if parent is not None else -1, loc))
    rows = [(name, ' + '.join(chain), 'renamed' if len(chain) == 1 else 'merged chain')
            for name, chain, _p in plan if [name] != chain]
    for extra, parent in EXTRA:
        if parent in pos and extra not in pos:
            pos[extra] = len(bones)
            bones.append((extra, pos[parent], IDENT4))
            rows.append((extra, '(under %s)' % parent, 'added, identity'))
    # the donor's form: LegC is the joint between Hip and both legs, ClavicleC between Bust and both clavicles
    # (identity at rest, so every posed vertex stays where it was; no motion file has tracks for them)
    for mid, kids in (('LegC', ('LegL', 'LegR')), ('ClavicleC', ('ClavicleL', 'ClavicleR'))):
        if mid in pos and not NO_MID_JOINTS:
            for k in kids:
                if k in pos and bones[pos[k]][1] == bones[pos[mid]][1]:
                    n_, _p, l_ = bones[pos[k]]
                    bones[pos[k]] = (n_, pos[mid], l_)
                    rows.append((k, '(under %s)' % mid, 'reparented'))
    # the native order: Trans (0), Rot (1), Hip (2) first, as every native skeleton has them (the package puts a
    # visibility bone between its root and its rotation node, which made Rot index 2); then depth first, children
    # in their old order (a parent always before its children)
    # every game fighter's skeleton (marth, roy, mario, link, rockman, cloud read from the game) starts with its
    # standard body bones in one canonical sequence, before any extra bone; ours interleaved package bones.
    # The canonical order was tried at 23:27 and made the game freeze MORE bones (00:30 dump), so it is off by
    # default (CANONICAL_ORDER); the default is the 21:30 order: Trans, Rot, Hip first, then depth first.
    canon = ('Trans', 'Rot', 'Hip', 'Waist', 'Bust', 'Neck', 'Head', 'Face', 'ClavicleC', 'ClavicleL',
             'ShoulderL', 'ArmL', 'HandL', 'HaveL', 'ClavicleR', 'ShoulderR', 'ArmR', 'HandR', 'HaveR',
             'Sword1', 'Sword2', 'Scabbard', 'Hilt', 'LegC', 'LegL', 'KneeL', 'FootL', 'ToeL', 'LegR',
             'KneeR', 'FootR', 'ToeR', 'Throw') if CANONICAL_ORDER else ('Trans', 'Rot', 'Hip')
    head = [n for n in canon if n in pos]
    kids_of = {}
    for i, (_n, p, _l) in enumerate(bones):
        kids_of.setdefault(p, []).append(i)
    order = [pos[n] for n in head]
    seen = set(order)

    def visit(i):
        if i not in seen:
            seen.add(i)
            order.append(i)
        for c in kids_of.get(i, []):
            if c not in seen or c in [pos[n] for n in head]:
                visit(c)
    for r in kids_of.get(-1, []):
        visit(r)
    new_index = {old: new for new, old in enumerate(order)}
    bones = [(bones[o][0], new_index[bones[o][1]] if bones[o][1] >= 0 else -1, bones[o][2]) for o in order]
    for i, (_n, p, _l) in enumerate(bones):
        if p >= i:
            raise ValueError('reordered skeleton: a parent after its child')
    pos = {n: new_index[i] for n, i in pos.items()}
    index = {b.index: pos[new_name[b.name]] for b in model.bones}
    return bones, index, rows


def build_skeleton_extra(model, scale):
    """The first deliveries' skeleton: package names kept, native names as extra identity bones."""
    bones = [(ROOT, -1, IDENT4)]
    index = {}
    for b in model.bones:
        loc = m4(mdl0.mat_from_srt(b.scale, b.rot, tuple(x * scale for x in b.trans)))
        index[b.index] = len(bones)
        bones.append((b.name, index[b.parent] if b.parent >= 0 else 0, loc))
    by_name = {b.name: index[b.index] for b in model.bones}
    names = {n for n, _p, _l in bones}
    rows = []
    for native, pkg in BONE_MAP:
        if pkg not in by_name:
            rows.append((native, pkg, 'NOT ADDED: the package has no such bone'))
            continue
        if native in names:
            rows.append((native, pkg, 'the package already has a bone of this name'))
            continue
        names.add(native)
        bones.append((native, by_name[pkg], IDENT4))
        rows.append((native, pkg, 'added'))
    return bones, index, rows


def skeleton_value(bones):
    world = []
    for name, parent, loc in bones:
        world.append(loc if parent < 0 else m4_mul(world[parent], loc))
    return {
        'bone_entries': [{'name': n, 'index': i, 'parent': p, 'flags': 1} for i, (n, p, _l) in enumerate(bones)],
        'world': [native_bytes(w) for w in world],
        'inv_world': [native_bytes(m4_inv_affine(w)) for w in world],
        'local': [native_bytes(l) for _n, _p, l in bones],
        'inv_local': [native_bytes(m4_inv_affine(l)) for _n, _p, l in bones],
    }, world


# ------------------------------------------------------------------ meshes
def bounding(points):
    xs, ys, zs = zip(*points)
    mn = (min(xs), min(ys), min(zs))
    mx = (max(xs), max(ys), max(zs))
    c = tuple((a + b) / 2 for a, b in zip(mn, mx))
    r = max(math.sqrt(sum((p[i] - c[i]) ** 2 for i in range(3))) for p in points)
    half = tuple((b - a) / 2 for a, b in zip(mn, mx))
    return struct.pack('<25f', c[0], c[1], c[2], r, *mn, *mx, *c, 1, 0, 0, 0, 1, 0, 0, 0, 1, *half), mn, mx


def orient(mesh):
    """Counter-clockwise front faces: compare the geometric normal with the vertex normals, flip on majority."""
    agree = dis = 0
    P, N = mesh.positions, mesh.normals
    for a, b, c in mesh.triangles:
        e1 = [P[b][i] - P[a][i] for i in range(3)]
        e2 = [P[c][i] - P[a][i] for i in range(3)]
        g = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
        s = sum(g[i] * (N[a][i] + N[b][i] + N[c][i]) for i in range(3))
        if s > 0:
            agree += 1
        elif s < 0:
            dis += 1
    if dis > agree:
        mesh.triangles = [(a, c, b) for a, b, c in mesh.triangles]
        agree, dis = dis, agree
    return agree, dis


def tangents(P, N, UV, tris):
    n = len(P)
    tan = [[0.0, 0.0, 0.0] for _ in range(n)]
    bit = [[0.0, 0.0, 0.0] for _ in range(n)]
    for a, b, c in tris:
        e1 = [P[b][i] - P[a][i] for i in range(3)]
        e2 = [P[c][i] - P[a][i] for i in range(3)]
        du1, dv1 = UV[b][0] - UV[a][0], UV[b][1] - UV[a][1]
        du2, dv2 = UV[c][0] - UV[a][0], UV[c][1] - UV[a][1]
        d = du1 * dv2 - du2 * dv1
        if abs(d) < 1e-12:
            continue
        r = 1.0 / d
        t = [(e1[i] * dv2 - e2[i] * dv1) * r for i in range(3)]
        s = [(e2[i] * du1 - e1[i] * du2) * r for i in range(3)]
        for v in (a, b, c):
            for i in range(3):
                tan[v][i] += t[i]
                bit[v][i] += s[i]
    out = []
    for v in range(n):
        nn, t = N[v], tan[v]
        d = sum(nn[i] * t[i] for i in range(3))
        t = [t[i] - nn[i] * d for i in range(3)]
        ln = math.sqrt(sum(x * x for x in t))
        if ln < 1e-9:
            # any vector perpendicular to the normal
            ax = (1.0, 0.0, 0.0) if abs(nn[0]) < 0.9 else (0.0, 1.0, 0.0)
            t = [ax[1] * nn[2] - ax[2] * nn[1], ax[2] * nn[0] - ax[0] * nn[2], ax[0] * nn[1] - ax[1] * nn[0]]
            ln = math.sqrt(sum(x * x for x in t))
        t = [x / ln for x in t]
        cr = (nn[1] * t[2] - nn[2] * t[1], nn[2] * t[0] - nn[0] * t[2], nn[0] * t[1] - nn[1] * t[0])
        w = -1.0 if sum(cr[i] * bit[v][i] for i in range(3)) < 0 else 1.0
        out.append((t[0], t[1], t[2], w))
    return out


def attr(usage, dtype, buf, off, name, aname):
    return {'usage': usage, 'data_type': dtype, 'buffer_index': buf, 'buffer_offset': off, 'subindex': 0,
            'name': name, 'attribute_names': [{'name': aname}]}


ATTRS = [attr(0, 0, 0, 0, 'Position0', 'Position0'), attr(1, 5, 0, 12, 'Normal0', 'Normal0'),
         attr(3, 5, 0, 20, 'map1', 'Tangent0'), attr(4, 8, 1, 0, 'map1', 'map1')]


def mesh_object_name(mesh, vis_bone):
    if vis_bone is not None and vis_bone.index != 0:
        return mesh.name + '_VIS_O_OBJShape'
    return mesh.name + 'Shape'         # every mesh object of the game's files ends in "Shape"; the short name
    #                                    (mesh-extension file, visibility node) is the name without that suffix


def switched_meshes(model):
    """-> {mesh name: index of its visibility bone} for the meshes the package switches."""
    return {m.name: m.draw_bone for m in model.meshes if m.draw_bone > 0}


def limit_weights(inf, n=4):
    acc = {}
    for b, w in inf:
        acc[b] = acc.get(b, 0.0) + w
    lst = sorted(acc.items(), key=lambda x: -x[1])[:n]
    lst = [(b, w) for b, w in lst if w > 0] or lst[:1]
    s = sum(w for _b, w in lst)
    return [(b, w / s) for b, w in lst] if s > 0 else [(lst[0][0], 1.0)]


def meshex_bytes(groups, entries):
    """groups: list of (full name, name, sphere); entries: list of group index (one per mesh object)."""
    def padded(s):
        b = s.encode('ascii') + b'\0'
        return b + b'\0' * (-len(b) % 4)
    all_off, grp_off = 0x40, 0x70
    str_off = grp_off + len(groups) * 32
    strs = b''
    grp = b''
    for full, name, sph in groups:
        a = str_off + len(strs)
        strs += padded(full)
        b = str_off + len(strs)
        strs += padded(name)
        grp += struct.pack('<4fQQ', *sph, a, b)
    ent_off = str_off + len(strs)
    ent_off += -ent_off % 16
    ents = b''.join(struct.pack('<I3f', g, 0.0, 1.0, 0.0) for g in entries)
    flg_off = ent_off + len(ents)
    flags = struct.pack('<%dH' % len(entries), *([3] * len(entries)))
    total = flg_off + len(flags)
    total += -total % 16
    cx = [sum(g[2][i] for g in groups) / len(groups) for i in range(3)]
    rad = max(math.sqrt(sum((g[2][i] - cx[i]) ** 2 for i in range(3))) + g[2][3] for g in groups)
    head = struct.pack('<QIIQQQQQ', total, len(entries), len(groups), all_off, grp_off, ent_off, flg_off, 0)
    head = head.ljust(0x40, b'\0')
    alld = struct.pack('<4fQQ', cx[0], cx[1], cx[2], rad, 0x60, 0) + b'All\0'.ljust(16, b'\0')
    out = head + alld + grp + strs
    out = out.ljust(ent_off, b'\0') + ents + flags
    return out.ljust(total, b'\0')


def empty_helper_bones():
    return (b'HBSS' + struct.pack('<Q', 0x40) + b'\0\0\0\0' + b'BPLH' + struct.pack('<HH', 1, 1) + b'\0' * 64)


# ------------------------------------------------------------------ the conversion
def convert(args):
    pac, out = args[0], args[1]
    opts = {'--prefix': 'zero', '--model': '0', '--scale': '1.0', '--template-matl': None, '--opaque': None,
            '--alpha': None, '--blend': None, '--emission': None, '--eye': None, '--emission-match': 'Emission',
            '--blend-match': ''}
    eye_mats = {}
    col_over = {}
    matte = {}
    all_meshes = True
    extra_bones = False
    i = 2
    while i < len(args):
        a = args[i]
        if a == '--all-meshes':
            i += 1
        elif a == '--visible-only':          # leave out the meshes whose visibility bone is hidden by default
            all_meshes = False
            i += 1
        elif a == '--extra-bones':           # the first deliveries' skeleton (package names + extra native names)
            extra_bones = True
            i += 1
        elif a == '--names-min':             # only Trans, Rot, Hip, Head, HaveL / R, Throw get native names
            set_names_min(True)
            i += 1
        elif a == '--no-mid-joints':
            global NO_MID_JOINTS
            NO_MID_JOINTS = True
            i += 1
        elif a == '--col':
            k, v = args[i + 1].split('=', 1)
            col_over[k] = v
            i += 2
        elif a == '--matte':
            k, v = args[i + 1].split('=', 1)
            matte[k] = (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))
            i += 2
        elif a == '--eye-mat':               # <material>=<base texture>@<uv>,<layer texture>@<uv>
            k, v = args[i + 1].split('=', 1)
            eye_mats[k] = [(x.split('@')[0], int(x.split('@')[1])) for x in v.split(',')]
            i += 2
        elif a in opts:
            opts[a] = args[i + 1]
            i += 2
        else:
            raise SystemExit('unknown option ' + a)
    if not (opts['--template-matl'] and opts['--opaque'] and opts['--alpha']):
        raise SystemExit('--template-matl, --opaque and --alpha are required')
    prefix, scale = opts['--prefix'], float(opts['--scale'])
    os.makedirs(out, exist_ok=True)

    container = arc.load(pac)
    models, textures, palettes = [], {}, {}
    for e in container.entries:
        if e.kind() != 'BRRES':
            continue
        b = brres.Brres(e.data)
        for name, off in b.models():
            models.append((e.data, off))
        for name, off in b.palettes():
            palettes[name] = tex0.read_palette(e.data, off)[0]
        for name, off in b.textures():
            textures[name] = tex0.Tex0(e.data, off)
    model = mdl0.Mdl0(*models[int(opts['--model'])])
    print('model %s: %d bones, %d meshes, %d materials, %d textures in the archive' % (
        model.name, len(model.bones), len(model.meshes), len(model.materials), len(textures)))

    # ---- skeleton
    bones, bidx, rows = (build_skeleton_extra if extra_bones else build_skeleton)(model, scale)
    skel, world = skeleton_value(bones)
    bone_names = [n for n, _p, _l in bones]
    if len(set(bone_names)) != len(bone_names):
        raise SystemExit('duplicate bone names')
    print('skeleton: %d bones (the package has %d)' % (len(bones), len(model.bones)))
    for native, pkg, what in rows:
        print('  map  %-12s <- %-16s %s' % (native, pkg, what))

    # ---- meshes
    objects, rigging, modl_entries, groups, vb0, vb1, ib = [], [], [], [], bytearray(), bytearray(), bytearray()
    used_materials = {}
    all_points = []
    vstart = 0
    skipped = []
    for me in model.meshes:
        vis = model.bones[me.draw_bone] if me.draw_bone >= 0 else None
        if vis is not None and not (vis.flags & 0x100) and not all_meshes:
            skipped.append((me.name, vis.name))
            continue
        model.decode(me)
        if not me.triangles:
            skipped.append((me.name, 'no triangles'))
            continue
        mat = model.materials[me.material]
        tex = col_over.get(mat.name, mat.textures[0] if mat.textures else None)
        chan = mat.textures.index(tex) if tex in mat.textures else 0
        if tex and '@' in tex:                       # <texture>@<uv channel>
            tex, c = tex.split('@', 1)
            chan = int(c)
        kind, tex2, uv2 = None, None, None
        if mat.name in eye_mats and opts['--eye']:
            (tex, chan), (tex2, chan2) = eye_mats[mat.name]
            kind = 'eye'
            uv2 = me.uvs[chan2] if me.uvs[chan2] is not None else me.uvs[0]
        elif opts['--emission'] and opts['--emission-match'] in mat.name:
            kind = 'emission'
        uv = me.uvs[chan] if me.uvs[chan] is not None else me.uvs[0]
        if uv is None:
            uv = [(0.0, 0.0)] * len(me.positions)
        if kind == 'emission':
            uv2 = uv
        agree, dis = orient(me)
        P = [tuple(x * scale for x in p) for p in me.positions]
        N = me.normals
        T = tangents(P, N, uv, me.triangles)
        if len(P) > 65535:
            raise SystemExit('mesh %s has more than 65535 vertices' % me.name)
        box, mn, mx = bounding(P)
        all_points.append(mn)
        all_points.append(mx)
        for p, nn, t in zip(P, N, T):
            vb0 += struct.pack('<3f4e4e', p[0], p[1], p[2], nn[0], nn[1], nn[2], 1.0, *t)
        vb1_off = len(vb1)
        for k, u in enumerate(uv):
            vb1 += struct.pack('<2e', max(-60000.0, min(60000.0, u[0])), max(-60000.0, min(60000.0, u[1])))
            if uv2 is not None:              # second UV set ("uvSet") for the layered / eye-type shaders
                vb1 += struct.pack('<2e', max(-60000.0, min(60000.0, uv2[k][0])),
                                   max(-60000.0, min(60000.0, uv2[k][1])))
        ib_off = len(ib)
        for t in me.triangles:
            ib += struct.pack('<3H', *t)
        per_bone = {}
        max_inf = 1
        for vi, inf in enumerate(me.weights):
            lst = limit_weights([(bidx[b], w) for b, w in inf])
            max_inf = max(max_inf, len(lst))
            for b, w in lst:
                per_bone.setdefault(b, []).append((vi, w))
        # a mesh the package switches (its visibility bone is not the root) gets the native name form of a
        # switchable mesh: "<name>_VIS_O_OBJShape"; a motion file's Visibility group addresses it as "<name>"
        short = me.name
        name = mesh_object_name(me, vis)
        objects.append({
            'name': name, 'subindex': 0, 'parent_bone_name': '', 'vertex_count': len(P),
            'vertex_index_count': len(me.triangles) * 3, 'unk2': 3, 'vb0_offset': vstart * 28,
            'vb1_offset': vb1_off, 'vb2_offset': vstart * 32, 'vb3_offset': 0, 'stride0': 28,
            'stride1': 8 if uv2 is not None else 4,
            'stride2': 0, 'stride3': 0, 'index_buffer_offset': ib_off, 'unk8': 4, 'draw_element_type': 0,
            'use_vertex_skinning': 1, 'sort_bias': 0, 'depth_flags': 0, 'bounding': box,
            'attributes': [dict(a, attribute_names=[dict(x) for x in a['attribute_names']])
                           for a in ATTRS + ([attr(4, 8, 1, 4, 'uvSet', 'uvSet')] if uv2 is not None else [])]})
        rigging.append({'mesh_name': name, 'subindex': 0, 'flags': 0x100 | max_inf, 'buffers': [
            {'bone_name': bone_names[b], 'data': b''.join(struct.pack('<Hf', vi, w) for vi, w in per_bone[b])}
            for b in sorted(per_bone, key=lambda i: bone_names[i])]})     # by bone NAME, as in the game's files
        modl_entries.append({'mesh_name': name, 'subindex': 0, 'material_label': mat.name})
        used_materials[mat.name] = (mat, tex, tex2, kind)
        sph = struct.unpack_from('<4f', box, 0)
        groups.append((name, short, sph))
        vstart += len(P)
        print('  mesh %-22s material %-26s texture %-20s uv %d  %5d vertices %5d triangles, winding %d/%d, '
              'influences <= %d, %d bones' % (name, mat.name, tex, chan, len(P), len(me.triangles), agree, dis,
                                              max_inf, len(per_bone)))
    for name, why in skipped:
        print('  mesh %-22s NOT written (hidden by default: visibility bone %s)' % (name, why))
    box, mn, mx = bounding(all_points)
    print('model box: (%.2f %.2f %.2f) - (%.2f %.2f %.2f); height %.2f' % (mn + mx + (mx[1] - mn[1],)))
    # THE GAME'S FILES KEEP THE RIGGING GROUPS SORTED by (mesh name, sub-index) in byte order - not in the order of
    # the mesh objects - and the material entries sorted by label: the engine evidently looks both up by a sorted
    # search. Unsorted, some meshes get no skinning / no material and are silently not drawn (seen in the game:
    # which ones depends on the names).
    rigging.sort(key=lambda r: (r['mesh_name'].encode('utf-8'), r['subindex']))
    mesh = {'model_name': '', 'bounding': box, 'unk1': 0, 'objects': objects,
            'buffer_sizes': [len(vb0), len(vb1), 0, 0], 'polygon_index_size': len(ib),
            'vertex_buffers': [{'data': bytes(vb0)}, {'data': bytes(vb1)}, {'data': b''}, {'data': b''}],
            'index_buffer': bytes(ib), 'rigging': rigging, 'unknown_offset': 0, 'unknown_size': 0}

    # ---- textures
    tex_files = {}

    def texture(name):
        if name not in tex_files:
            t = textures[name]
            w, h, rgba = t.decode(palettes.get(name))
            if name in matte:                        # blend over a plain colour and make opaque
                r0, g0, b0 = matte[name]
                for o in range(0, len(rgba), 4):
                    al = rgba[o + 3]
                    rgba[o] = (rgba[o] * al + r0 * (255 - al)) // 255
                    rgba[o + 1] = (rgba[o + 1] * al + g0 * (255 - al)) // 255
                    rgba[o + 2] = (rgba[o + 2] * al + b0 * (255 - al)) // 255
                    rgba[o + 3] = 255
            low = name.lower().replace('.', '_')
            fn = '%s_col' % low if low.startswith(prefix) else '%s_%s_col' % (prefix, low)
            tex_files[name] = (fn, nutexb.build(fn, w, h, rgba, srgb=True), w, h, t.format_name,
                               min(rgba[3::4]) < 255)
        return tex_files[name]

    flat_nor = '%s_flat_nor' % prefix
    flat_prm = '%s_flat_prm' % prefix
    extra = {flat_nor: nutexb.build(flat_nor, 16, 16, bytes((128, 128, 255, 255)) * 256, srgb=False),
             flat_prm: nutexb.build(flat_prm, 16, 16, bytes((0, 153, 255, 41)) * 256, srgb=False)}

    # ---- materials
    _m, _v, template = ssbh.load(opts['--template-matl'])
    by_label = {e['label']: e for e in template['entries']}
    for key in ('--opaque', '--alpha', '--blend', '--emission', '--eye'):
        if opts[key] is not None and opts[key] not in by_label:
            raise SystemExit('the template material file has no entry %r' % opts[key])
    entries = []
    for label, (mat, tex, tex2, kind) in used_materials.items():
        fn, _data, _w, _h, _f, has_alpha = texture(tex) if tex in textures else (None, None, 0, 0, '', False)
        fn2 = texture(tex2)[0] if tex2 in textures else None
        # which native entry is copied: eye (two layers) / emission / blended (translucent with texture alpha) /
        # alpha-tested (texture alpha, not translucent) / plain
        if kind == 'eye':
            src = by_label[opts['--eye']]
        elif kind == 'emission':
            src = by_label[opts['--emission']]
        elif has_alpha and mat.xlu and opts['--blend'] and opts['--blend-match'] in mat.name:
            src = by_label[opts['--blend']]
        elif has_alpha:
            src = by_label[opts['--alpha']]
        else:
            src = by_label[opts['--opaque']]
        attrs = []
        wrap_note = ''
        for a in src['attributes']:
            dt, val = a['param']
            if dt == 0xB and a['param_id'] in (TEX_COL, TEX_DIFFUSE, TEX_EMI) and fn:
                val = fn
            elif dt == 0xB and a['param_id'] == TEX_COL2 and fn2:
                val = fn2
            elif dt == 0xB and a['param_id'] == TEX_NOR:
                val = flat_nor
            elif dt == 0xB and a['param_id'] == TEX_PRM:
                val = flat_prm
            elif dt == 0xE and a['param_id'] == SAMPLER_COL and tex in mat.textures:
                # wrap modes of the source: 0 clamp, 1 repeat, 2 mirror -> native 1, 0, 2
                wu, wv = mat.wraps[mat.textures.index(tex)]
                conv = {0: 1, 1: 0, 2: 2}
                val = struct.pack('<II', conv.get(wu, 0), conv.get(wv, 0)) + val[8:]
                wrap_note = ', wrap %d/%d' % (wu, wv)
            elif dt == PARAM_RASTERIZER and mat.cull == 0:
                val = val[:4] + struct.pack('<I', 2) + val[8:]         # draw both sides
            attrs.append({'param_id': a['param_id'], 'param': (dt, val)})
        entries.append({'label': label, 'attributes': attrs, 'shader_label': src['shader_label']})
        print('  material %-28s <- template %-16s col %s%s%s%s' % (
            label, src['label'], fn, ' + layer %s' % fn2 if fn2 else '', ', both sides' if mat.cull == 0 else '',
            wrap_note))
    entries.sort(key=lambda e: e['label'].encode('utf-8'))          # sorted by label, as in the game's files
    matl = {'entries': entries}
    modl = {'model_name': 'model', 'skeleton_file': 'model.nusktb', 'material_files': [{'name': 'model.numatb'}],
            'animation_file': None, 'mesh_file': 'model.numshb', 'entries': modl_entries}

    files = {'model.nusktb': ssbh.build(b'LEKS', skel), 'model.numshb': ssbh.build(b'HSEM', mesh),
             'model.numdlb': ssbh.build(b'LDOM', modl), 'model.numatb': ssbh.build(b'LTAM', matl),
             'model.numshexb': meshex_bytes(groups, list(range(len(groups)))),
             'model.nuhlpb': empty_helper_bones()}
    for name, (fn, data, w, h, f, al) in tex_files.items():
        files[fn + '.nutexb'] = data
        print('  texture %-24s %4dx%-4d %-7s alpha %-5s -> %s.nutexb' % (name, w, h, f, al, fn))
    for fn, data in extra.items():
        files[fn + '.nutexb'] = data
    for fn, data in files.items():
        with open(os.path.join(out, fn), 'wb') as f:
            f.write(data)
    print('%d files written to %s' % (len(files), out))
    verify(out)


# ------------------------------------------------------------------ checks on what was written
def verify(folder):
    """Re-reads the written files with this tool's parser and checks every cross reference."""
    _m, _v, skel = ssbh.load(os.path.join(folder, 'model.nusktb'))
    _m, _v, mesh = ssbh.load(os.path.join(folder, 'model.numshb'))
    _m, _v, modl = ssbh.load(os.path.join(folder, 'model.numdlb'))
    _m, _v, matl = ssbh.load(os.path.join(folder, 'model.numatb'))
    bones = [b['name'] for b in skel['bone_entries']]
    problems = []
    for i, b in enumerate(skel['bone_entries']):
        if b['index'] != i or not (-1 <= b['parent'] < i):
            problems.append('bone %s: index / parent order' % b['name'])
    for key in ('world', 'inv_world', 'local', 'inv_local'):
        for mtx in skel[key]:
            if not all(math.isfinite(x) for x in struct.unpack('<16f', mtx)):
                problems.append('non-finite bone matrix')
    for w, iw in zip(skel['world'], skel['inv_world']):
        a, b = ssbh.mat4_rows(w), ssbh.mat4_rows(iw)
        prod = [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
        if max(abs(prod[i][j] - (1.0 if i == j else 0.0)) for i in range(4) for j in range(4)) > 1e-3:
            problems.append('world x inverse is not the identity')
    vb0, vb1 = mesh['vertex_buffers'][0]['data'], mesh['vertex_buffers'][1]['data']
    ib = mesh['index_buffer']
    tv = tt = 0
    rig = {(r['mesh_name'], r['subindex']): r for r in mesh['rigging']}
    for o in mesh['objects']:
        n = o['vertex_count']
        tv += n
        tt += o['vertex_index_count'] // 3
        if o['vb0_offset'] + n * o['stride0'] > len(vb0) or o['vb1_offset'] + n * o['stride1'] > len(vb1):
            problems.append('%s: vertex data beyond the buffer' % o['name'])
            continue
        idx = struct.unpack_from('<%dH' % o['vertex_index_count'], ib, o['index_buffer_offset'])
        if max(idx) >= n:
            problems.append('%s: vertex index out of range' % o['name'])
        for k in range(n):
            v = struct.unpack_from('<3f4e4e', vb0, o['vb0_offset'] + k * 28)
            if not all(math.isfinite(x) for x in v):
                problems.append('%s: non-finite vertex' % o['name'])
                break
        r = rig.get((o['name'], o['subindex']))
        if r is None:
            problems.append('%s: no rigging group' % o['name'])
            continue
        sums = [0.0] * n
        cnt = [0] * n
        for b in r['buffers']:
            if b['bone_name'] not in bones:
                problems.append('%s: weights for a bone the skeleton lacks: %s' % (o['name'], b['bone_name']))
            for k in range(len(b['data']) // 6):
                vi, w = struct.unpack_from('<Hf', b['data'], k * 6)
                if vi >= n:
                    problems.append('%s: weight for vertex %d of %d' % (o['name'], vi, n))
                    break
                sums[vi] += w
                cnt[vi] += 1
        if any(abs(s - 1.0) > 1e-3 for s in sums):
            problems.append('%s: weights do not sum to 1 on %d vertices' % (
                o['name'], sum(1 for s in sums if abs(s - 1.0) > 1e-3)))
        if max(cnt) > 4 or max(cnt) > (r['flags'] & 0xFF):
            problems.append('%s: more influences than declared' % o['name'])
    order = [(r['mesh_name'].encode(), r['subindex']) for r in mesh['rigging']]
    if order != sorted(order):
        problems.append('rigging groups are not sorted by (mesh name, sub-index)')
    for r in mesh['rigging']:
        bn = [b['bone_name'].encode() for b in r['buffers']]
        if bn != sorted(bn):
            problems.append('%s: bone buffers are not sorted by bone name' % r['mesh_name'])
    lab_order = [e['label'].encode() for e in matl['entries']]
    if lab_order != sorted(lab_order):
        problems.append('material entries are not sorted by label')
    labels = {e['label'] for e in matl['entries']}
    objs = {(o['name'], o['subindex']) for o in mesh['objects']}
    for e in modl['entries']:
        if e['material_label'] not in labels:
            problems.append('model description names a material the material file lacks: ' + e['material_label'])
        if (e['mesh_name'], e['subindex']) not in objs:
            problems.append('model description names a mesh the mesh file lacks: ' + e['mesh_name'])
    ntex = 0
    for e in matl['entries']:
        for a in e['attributes']:
            dt, val = a['param']
            if dt == 0xB and not val.startswith(('#', '/')):
                p = os.path.join(folder, val + '.nutexb')
                if not os.path.exists(p):
                    problems.append('material %s names a texture that is not in the folder: %s' % (e['label'], val))
                else:
                    with open(p, 'rb') as f:
                        ft = nutexb.read_footer(f.read())
                    if ft['name'] != val or ft['data_size'] + nutexb.FOOTER != os.path.getsize(p):
                        problems.append('texture %s: footer does not match the file' % val)
                    ntex += 1
    print('check of the written files: %d bones, %d meshes, %d vertices, %d triangles, %d materials, '
          '%d texture references' % (len(bones), len(mesh['objects']), tv, tt, len(labels), ntex))
    for p in problems:
        print('  PROBLEM: ' + p)
    print('  result: %s' % ('OK' if not problems else '%d problem(s)' % len(problems)))
    return not problems


def roundtrip(folder):
    ok = True
    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(('.nusktb', '.numshb', '.numdlb', '.numatb')):
            continue
        with open(os.path.join(folder, fn), 'rb') as f:
            raw = f.read()
        magic, _ver, value = ssbh.parse(raw)
        again = ssbh.build(magic, value)
        if again == raw:
            res = 'byte-identical'
        else:
            res = 'field-identical' if ssbh.parse(again)[2] == value else 'DIFFERENT'
            ok = ok and res != 'DIFFERENT'
        print('%-24s %8d bytes  read -> write: %s' % (fn, len(raw), res))
    return ok


if __name__ == '__main__':
    if len(sys.argv) >= 3 and sys.argv[1] == 'roundtrip':
        sys.exit(0 if roundtrip(sys.argv[2]) else 1)
    if len(sys.argv) >= 4 and sys.argv[1] == 'convert':
        convert(sys.argv[2:])
    elif len(sys.argv) >= 3 and sys.argv[1] == 'verify':
        sys.exit(0 if verify(sys.argv[2]) else 1)
    else:
        print(__doc__)
