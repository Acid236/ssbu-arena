"""Parameter files of a ported fighter, written from the package's moveset file with prc.py.

    python -I params.py hurtboxes <main fighter .pac> <costume .pac> <donor vl.prc> <out vl.prc>
        the package's hurt-box list in place of the donor's `hit_data` list (same fields, the donor's first entry
        as the shape of an entry)
    python -I params.py ik-none <donor ik.prc> <out .prc>
        the same file with every bone name replaced by a name no skeleton has (the limb IK finds nothing)
    python -I params.py no-lists <donor .prc> <out .prc>
        the same file with every list emptied (a swing / cloth file without bones, shapes and connections)
    python -I params.py row <main fighter .pac> <general fighter_param.prc> <donor fighter kind label>
            <ParamLabels.csv> <out .txt> <out .json>
        the package's attribute values under the native parameter names, beside the donor's row

Nothing of the package is executed. This file contains no game content.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brawl import prc, psa_listing as pl, ssbh              # noqa: E402
from brawl.convert_anim import load_model                   # noqa: E402
from brawl.convert_model import bone_plan                   # noqa: E402
from brawl.moveset import open_psa                          # noqa: E402

NONE_BONE = 'b1_no_such_bone'

# native parameter <- (package attribute name of psa_listing.ATTRIBUTES, conversion, note)
ROW = [
    ('walk_speed_max', 'walk maximum velocity', None, 'same unit; the walk animation\'s rate follows it'),
    ('walk_accel_mul', 'walk acceleration', None, 'meaning assumed the same'),
    ('walk_accel_add', 'walk initial velocity', None, 'meaning assumed the same'),
    ('ground_brake', 'ground friction', None, 'same unit'),
    ('dash_speed', 'dash initial velocity', None, 'same unit'),
    ('run_accel_mul', 'dash / run acceleration A', None, 'meaning assumed the same'),
    ('run_accel_add', 'dash / run acceleration B', None, 'meaning assumed the same'),
    ('run_speed_max', 'run terminal velocity', None, 'same unit'),
    ('jump_squat_frame', 'jump start-up frames', 'int', 'frames'),
    ('jump_speed_x', 'jump horizontal initial velocity', None, 'same unit'),
    ('jump_speed_x_mul', 'ground-to-air momentum multiplier', None, 'meaning assumed the same'),
    ('jump_speed_x_max', 'jump horizontal maximum velocity', None, 'same unit'),
    ('jump_y', 'jump vertical initial velocity', 'height', 'HEIGHT from the package\'s velocity: v^2 / 2g + v / 2'),
    ('mini_jump_y', 'short hop vertical initial velocity', 'height', 'height, as above'),
    ('jump_aerial_y', 'air jump multiplier', 'aerial', 'height of (multiplier x jump velocity)'),
    ('jump_count_max', 'jump count', 'int', 'same'),
    ('air_accel_y', 'gravity', None, 'same unit'),
    ('air_speed_y_stable', 'terminal fall velocity', None, 'same unit'),
    ('air_brake_y', 'air friction y', None, 'meaning assumed the same'),
    ('air_accel_x_mul', 'air mobility A', None, 'meaning assumed the same'),
    ('air_accel_x_add', 'air mobility B', None, 'meaning assumed the same'),
    ('air_speed_x_stable', 'air x terminal velocity', None, 'same unit'),
    ('air_brake_x', 'air friction x', None, 'same unit'),
    ('dive_speed_y', 'fast-fall terminal velocity', None, 'same unit'),
    ('weight', 'weight', None, 'same scale'),
    ('scale', 'size', None, 'same'),
    ('landing_frame_light', 'light landing lag (frames)?', None, 'alignment in the package\'s block judged by values'),
    ('landing_frame', 'normal landing lag (frames)?', None, 'as above'),
    ('landing_attack_air_frame_n', 'neutral air landing lag?', None, 'as above'),
    ('landing_attack_air_frame_f', 'forward air landing lag?', None, 'as above'),
    ('landing_attack_air_frame_b', 'back air landing lag?', None, 'as above'),
    ('landing_attack_air_frame_hi', 'up air landing lag?', None, 'as above'),
    ('landing_attack_air_frame_lw', 'down air landing lag?', None, 'as above'),
]


def native_bone(model, index):
    plan, new_name = bone_plan(model)
    for b in model.bones:
        if b.index == index:
            return new_name[b.name]
    raise KeyError(index)


def hurtboxes(args):
    psa, model = open_psa(args[0]), load_model(args[1])
    p = prc.load(args[2])
    data = prc.field(p.root, 'hit_data')
    shape = data[1][0]
    keys = [f[0] for f in shape[1]]
    part_of = {'Head': 'collision_part_head'}
    from brawl.convert_model import reoriented
    turned = reoriented(model)
    pkg_name = {b.index: b.name for b in model.bones}
    out = []
    for h in pl.hurtboxes(psa):
        bone = native_bone(model, h['bone'])
        low = bone.lower()
        if low.startswith(('leg', 'knee', 'foot', 'toe')):
            part = 'collision_part_body_legs'
        elif low.startswith(('arm', 'hand')):
            part = 'collision_part_etc'            # as the donor's entries for the fore-arms
        else:
            part = part_of.get(bone, 'collision_part_body')
        o1 = h['offset']
        o2 = tuple(a + b for a, b in zip(h['offset'], h['stretch']))
        if pkg_name[h['bone']] in turned:          # the bone's local frame is turned half about X (convert_model)
            o1 = (o1[0], -o1[1], -o1[2])
            o2 = (o2[0], -o2[1], -o2[2])
        vals = {
            'part': ('hash', prc.hash40(part)), 'size': ('f32', h['radius']),
            'status': ('hash', prc.hash40('hit_status_normal')),
            'height': ('hash', prc.hash40(('hit_height_low', 'hit_height_center', 'hit_height_high')[min(h['zone'], 2)])),
            'node_id': ('hash', prc.hash40(low)),
            'offset1_x': ('f32', o1[0]), 'offset1_y': ('f32', o1[1]), 'offset1_z': ('f32', o1[2]),
            'offset2_x': ('f32', o2[0]), 'offset2_y': ('f32', o2[1]), 'offset2_z': ('f32', o2[2]),
            'check_type': ('hash', prc.hash40('collision_shape_type_capsule')),
        }
        by_hash = {prc.hash40(k): v for k, v in vals.items()}
        if set(by_hash) != set(keys):
            raise SystemExit('the donor\'s hurt-box entry has other fields than this tool writes')
        out.append(('struct', [(k, by_hash[k]) for k in keys]))
        print('  hurt box on %-10s part %-24s height %d  radius %.2f  (%.2f %.2f %.2f) - (%.2f %.2f %.2f)' % (
            low, part, h['zone'], h['radius'], *o1, *o2))
    prc.set_field(p.root, 'hit_data', ('list', out))
    with open(args[3], 'wb') as f:
        f.write(p.to_bytes())
    again = prc.load(args[3])
    print('%d hurt boxes written to %s (%d bytes; the donor\'s list had %d); read back: %d entries' % (
        len(out), args[3], os.path.getsize(args[3]), len(data[1]), len(prc.field(again.root, 'hit_data')[1])))


def _map(v, fn):
    if v[0] == 'struct':
        return ('struct', [(f[0], _map(f[1], fn)) for f in v[1]])
    if v[0] == 'list':
        return fn(('list', [_map(e, fn) for e in v[1]]))
    return fn(v)


def ik_none(args):
    p = prc.load(args[0])
    n = [0]
    names = {prc.hash40(k) for k in ('bonename', 'end_bonename', 'start_bonename', 'middle_bonename')}

    def walk(v):
        if v[0] == 'struct':
            new = []
            for f in v[1]:
                if f[0] in names and f[1][0] == 'hash':
                    new.append((f[0], ('hash', prc.hash40(NONE_BONE))))
                    n[0] += 1
                else:
                    new.append((f[0], walk(f[1])))
            return ('struct', new)
        if v[0] == 'list':
            return ('list', [walk(e) for e in v[1]])
        return v
    p.root = walk(p.root)
    with open(args[1], 'wb') as f:
        f.write(p.to_bytes())
    prc.load(args[1])
    print('%d bone names replaced by "%s" in %s (%d bytes)' % (n[0], NONE_BONE, args[1], os.path.getsize(args[1])))


def no_lists(args):
    p = prc.load(args[0])
    n = [0, 0]

    def fn(v):
        if v[0] == 'list' and v[1]:
            n[0] += 1
            n[1] += len(v[1])
            return ('list', [])
        return v
    p.root = _map(p.root, fn)
    with open(args[1], 'wb') as f:
        f.write(p.to_bytes())
    prc.load(args[1])
    print('%d lists emptied (%d entries in the outer ones) in %s (%d bytes, the donor\'s %d)' % (
        n[0], n[1], args[1], os.path.getsize(args[1]), os.path.getsize(args[0])))


def row(args):
    psa = open_psa(args[0])
    p = prc.load(args[1])
    lab = prc.labels(args[3])
    att = {name: val for _o, name, val, _n, _t in pl.attributes(psa)}
    table = p.root[1][0][1]
    donor = None
    for r in table[1]:
        for f in r[1]:
            if lab.get(f[0]) == 'fighter_kind' and lab.get(f[1][1]) == args[2]:
                donor = {lab.get(g[0], '%#x' % g[0]): g[1] for g in r[1]}
    if donor is None:
        raise SystemExit('no row of %s' % args[2])
    g = att['gravity']
    lines = ['native parameter               package value   donor value   from the package attribute; note', '']
    setv = {}
    for native, src, conv, note in ROW:
        v = att[src]
        if conv == 'height':
            v = v * v / (2 * g) + v / 2
        elif conv == 'aerial':
            v0 = v * att['jump vertical initial velocity']
            v = v0 * v0 / (2 * g) + v0 / 2
        elif conv == 'int':
            v = int(round(v))
        d = donor.get(native)
        dv = d[1] if d else None
        setv[native] = round(v, 4) if isinstance(v, float) else v
        lines.append('%-30s %13s %13s   %s; %s' % (native, ('%.4f' % v) if isinstance(v, float) else v,
                                                  ('%.4f' % dv) if isinstance(dv, float) else dv, src, note))
    with open(args[4], 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    with open(args[5], 'w', encoding='utf-8') as f:
        json.dump({'copy_of': args[2].replace('fighter_kind_', ''), 'set': setv}, f, indent=2)
    print('%d parameters written to %s and %s' % (len(setv), args[4], args[5]))


MIRROR_PLANES = {0: 'kyz', 1: 'kxz', 2: 'kxy'}


def mirror(args):
    """mirror <skeleton .nusktb> <a game fighter's mirror table 0x0834377552.prc> <out .prc>

    The table that tells the engine how to mirror each bone when the fighter turns (pairs swap left and right).
    Its planes depend on each bone's LOCAL AXES, so the game's standard values (identical in every fighter, made
    for the standard skeleton's axes) are wrong for bones with the package's axes. Rule, checked on the game's own
    skeleton + table (39 of 41 entries reproduced; the 2 others are the special Have entries, kept):
    - a single (centre) bone: rotation plane = the plane normal to the bone's own local axis nearest to world x;
      translation plane = the same for its parent (world for the root);
    - a left / right pair: D = L^T M R (M = mirror of world x); the plane is normal to the one local axis that
      D negates; translation plane from the two parents the same way.
    The standard lists keep their entries (the engine's names); every entry naming a bone of THIS skeleton gets
    planes from this skeleton; entries of bones it lacks keep the standard values. Bones of this skeleton the
    standard lists do not name go into the fighter-specific lists single_bones / pair_bones (layout as the game's
    fighters that have them)."""
    skel_path, base_path, out = args
    s = ssbh.load(skel_path)[2]
    names = [b['name'] for b in s['bone_entries']]
    parent = [b['parent'] for b in s['bone_entries']]
    idx = {prc.hash40(n.lower()): i for i, n in enumerate(names)}

    def rot3(i):
        if i < 0 or i >= len(names):
            return [[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]]
        m = ssbh.mat4_rows(s['world'][i])
        return [m[k][:3] for k in range(3)]

    def single(i):
        m = rot3(i)
        return MIRROR_PLANES[max(range(3), key=lambda k: abs(m[k][0]))]

    def pair(i, j):
        a, b = rot3(i), rot3(j)
        d = [sum(a[k][c] * (-b[k][c] if c == 0 else b[k][c]) for c in range(3)) for k in range(3)]
        neg = [k for k in range(3) if d[k] < 0]
        return MIRROR_PLANES[neg[0]] if len(neg) == 1 else ('knone' if not neg else None)

    H = prc.hash40
    p = prc.load(base_path)
    covered = set()
    changed = 0
    for key, lst in p.root[1]:
        if lst[0] != 'list' or key == H('pair_bones') or key == H('single_bones'):
            continue
        for e in lst[1]:
            f = dict(e[1])
            if H('lhs_name') in f:
                li, ri = idx.get(f[H('lhs_name')][1]), idx.get(f[H('rhs_name')][1])
                if li is None or ri is None:
                    continue
                covered |= {li, ri}
                if f[H('rot')][1] == H('knone') or f[H('trans')][1] == H('knone'):
                    continue                                    # the special Have entries: kept
                r, t = pair(li, ri), pair(parent[li], parent[ri])
            elif H('name') in f:
                i = idx.get(f[H('name')][1])
                if i is None:
                    continue
                covered.add(i)
                r = 'knone' if f[H('rot')][1] == H('knone') else single(i)
                t = single(parent[i] if 0 <= parent[i] < len(names) else -1)
            else:
                continue
            new = []
            for k, v in e[1]:
                if k == H('rot') and r:
                    changed += v[1] != H(r)
                    v = ('hash', H(r))
                elif k == H('trans') and t:
                    changed += v[1] != H(t)
                    v = ('hash', H(t))
                new.append((k, v))
            e[1][:] = new
    # the bones the standard lists do not name
    rest = [i for i in range(len(names)) if i not in covered]
    pairs, singles = [], []
    used = set()
    for i in rest:
        n = names[i]
        mate = None
        for a, b in (('L', 'R'), ('l', 'r')):
            if n.startswith(a) and (b + n[1:]) in names:
                mate = names.index(b + n[1:])
            elif n.endswith(a) and (n[:-1] + b) in names:
                mate = names.index(n[:-1] + b)
        if mate is not None and mate in rest and i not in used:
            used |= {i, mate}
            pairs.append(('struct', [(H('rot'), ('hash', H(pair(i, mate) or 'knone'))),
                                     (H('trans'), ('hash', H(pair(parent[i], parent[mate]) or 'knone'))),
                                     (H('scale'), ('bool', 1)),
                                     (H('lhs_name'), ('hash', H(n.lower()))),
                                     (H('rhs_name'), ('hash', H(names[mate].lower())))]))
    for i in rest:
        if i in used or names[i] in ('Trans',):
            continue
        singles.append(('struct', [(H('rot'), ('hash', H(single(i)))), (H('name'), ('hash', H(names[i].lower()))),
                                   (H('trans'), ('hash', H(single(parent[i] if 0 <= parent[i] < len(names) else -1))))]))
    root = [(k, v) for k, v in p.root[1] if k not in (H('pair_bones'), H('single_bones'))]
    root.append((H('pair_bones'), ('list', pairs)))
    root.append((H('single_bones'), ('list', singles)))
    p.root = ('struct', root)
    for h in [H(x) for x in ('kyz', 'kxz', 'kxy', 'knone', 'pair_bones', 'single_bones', 'rot', 'trans', 'scale',
                             'lhs_name', 'rhs_name', 'name')] + [H(n.lower()) for n in names]:
        if h not in p.hashes:
            p.hashes.append(h)
    with open(out, 'wb') as f:
        f.write(p.to_bytes())
    again = prc.load(out)
    print('mirror table: %d standard planes changed for this skeleton; %d pairs and %d single bones added; '
          'read back: %d top-level lists' % (changed, len(pairs), len(singles), len(again.root[1])))


def ik_axes(args):
    """ik <our skeleton> <a game fighter's ik.prc> <a standard skeleton .nusktb> <out .prc>

    The game's ik file with its bone names kept (the engine's standard limb names, which this skeleton has) and
    every pole vector re-expressed in THIS skeleton's local axes: the file's pole is a direction in the start
    bone's local frame of the standard skeleton; world = R_std(start) * pole; ours = R_ours(start)^T * world.
    A chain whose bone this skeleton lacks is pointed at no bone (as ik-none)."""
    ours_path, base_path, std_path, out = args
    H = prc.hash40

    def frames(path):
        s = ssbh.load(path)[2]
        res = {}
        for b, w in zip(s['bone_entries'], s['world']):
            m = ssbh.mat4_rows(w)
            res[H(b['name'].lower())] = [m[k][:3] for k in range(3)]       # row k = local axis k in world
        return res
    ours, std = frames(ours_path), frames(std_path)
    p = prc.load(base_path)
    changed = []

    def fix(struct):
        f = dict(struct[1])
        start = f.get(H('start_bonename'))
        pole = f.get(H('pole_vector'))
        if start is None or pole is None:
            look = [k for k in (H('bonename'), H('end_bonename')) if k in f]
            if look and not all(f[k][1] in ours for k in look):          # a look-at chain on a missing bone
                return ('struct', [(k, ('hash', H(NONE_BONE)) if k in look else v) for k, v in struct[1]])
            return struct
        sh = start[1]
        names = [f[k][1] for k in (H('start_bonename'), H('middle_bonename'), H('end_bonename')) if k in f]
        if not all(n in ours for n in names) or sh not in std:
            return ('struct', [(k, ('hash', H(NONE_BONE)) if k in (H('start_bonename'), H('middle_bonename'),
                                                                   H('end_bonename')) else v) for k, v in struct[1]])
        pv = dict(pole[1])
        vec = [pv[H(a)][1] for a in 'xyz']
        rs, ro = std[sh], ours[sh]
        world = [sum(rs[k][c] * vec[k] for k in range(3)) for c in range(3)]
        new = [sum(ro[k][c] * world[c] for c in range(3)) for k in range(3)]
        new = [round(x, 4) for x in new]
        changed.append((sh, vec, new))
        np_ = ('struct', [(k, (v[0], new['xyz'.index(a)])) for (k, v) in pole[1]
                          for a in 'xyz' if k == H(a)])
        return ('struct', [(k, np_ if k == H('pole_vector') else v) for k, v in struct[1]])
    p.root = ('struct', [(k, fix(v) if v[0] == 'struct' else v) for k, v in p.root[1]])
    if H(NONE_BONE) not in p.hashes:
        p.hashes.append(H(NONE_BONE))
    with open(out, 'wb') as f:
        f.write(p.to_bytes())
    prc.load(out)
    for sh, a, b in changed:
        print('  chain from %#x: pole %s -> %s' % (sh, tuple(round(x, 3) for x in a), tuple(b)))
    print('%d pole vectors re-expressed; written %s' % (len(changed), out))


if __name__ == '__main__':
    cmds = {'hurtboxes': (hurtboxes, 4), 'ik-none': (ik_none, 2), 'no-lists': (no_lists, 2), 'row': (row, 6), 'mirror': (mirror, 3),
            'ik': (ik_axes, 4)}
    if '--names-min' in sys.argv:            # bone names of the convert_model --names-min skeleton
        from brawl.convert_model import set_names_min
        set_names_min(True)
        sys.argv.remove('--names-min')
    if len(sys.argv) >= 2 and sys.argv[1] in cmds and len(sys.argv) == 2 + cmds[sys.argv[1]][1]:
        cmds[sys.argv[1]][0](sys.argv[2:])
    else:
        print(__doc__)
