"""MDL0 model reader (versions 8 - 11): bones, vertex arrays, display lists decoded to triangle lists with per-vertex
bone weights, materials with their texture references, the draw list (mesh -> material).

Space conventions of the format: a vertex bound to ONE bone is stored in that bone's local space; a vertex with
several weights is stored in model space. decode() returns everything in model space (bind pose).
"""
import math
import struct

from .brres import cstr, read_group


# ---------------------------------------------------------------- small matrix helpers (3x4, row major, tuples)
def mat_from_srt(s, r_deg, t):
    """Scale, Euler rotation in degrees (X applied first, then Y, then Z), translation -> 3x4."""
    rx, ry, rz = (math.radians(a) for a in r_deg)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    m = (
        (cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz),
        (cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz),
        (-sy, sx * cy, cx * cy),
    )
    return tuple(tuple(m[i][j] * s[j] for j in range(3)) + (t[i],) for i in range(3))


def mat_mul(a, b):
    out = []
    for i in range(3):
        row = [a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j] for j in range(4)]
        row[3] += a[i][3]
        out.append(tuple(row))
    return tuple(out)


def mat_point(m, p):
    return tuple(m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + m[i][3] for i in range(3))


def mat_dir(m, p):
    return tuple(m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] for i in range(3))


IDENT = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0))


class Bone:
    __slots__ = ('name', 'index', 'node_id', 'flags', 'scale', 'rot', 'trans', 'parent', 'world', 'stored_world',
                 'box_min', 'box_max', 'offset')


class Material:
    __slots__ = ('name', 'index', 'textures', 'palettes', 'xlu', 'cull', 'tex_gens', 'light_chans', 'stages',
                 'ind_stages', 'shader_offset', 'wraps')


class Mesh:
    __slots__ = ('name', 'index', 'node_id', 'vcd_lo', 'vcd_hi', 'num_vertices', 'num_faces', 'vertex_id',
                 'normal_id', 'color_ids', 'uv_ids', 'prim_offset', 'prim_size', 'offset', 'material', 'draw_bone',
                 'xlu', 'positions', 'normals', 'colors', 'uvs', 'weights', 'triangles', 'prim_counts')


def _array_header(d, off, kind):
    """-> dict for a vertex / normal / colour / uv array."""
    ln, _mdl, data_off, str_off, index = struct.unpack_from('>IiiiI', d, off)
    a = {'offset': off, 'data': off + data_off, 'name': cstr(d, off + str_off) if str_off else '', 'index': index,
         'kind': kind}
    if kind == 'color':
        a['is_rgba'], a['format'], a['stride'], _p, a['count'] = struct.unpack_from('>IIBBH', d, off + 0x14)
    else:
        a['components'], a['type'], a['divisor'], a['stride'], a['count'] = struct.unpack_from('>IIBBH', d, off + 0x14)
    return a


_FMT = {0: ('B', 1), 1: ('b', 1), 2: ('H', 2), 3: ('h', 2), 4: ('f', 4)}


def _read_vectors(d, a, n):
    code, size = _FMT[a['type']]
    if a['kind'] == 'normal':
        # fixed-point normals have a fixed scale (the divisor field is not used for them)
        scale = {0: 1.0, 1: 1.0 / 64, 2: 1.0, 3: 1.0 / 16384, 4: 1.0}[a['type']]
    else:
        scale = 1.0 if a['type'] == 4 else 1.0 / (1 << a['divisor'])
    stride = a['stride'] or size * n
    out = []
    fmt = '>%d%s' % (n, code)
    base = a['data']
    for i in range(a['count']):
        v = struct.unpack_from(fmt, d, base + i * stride)
        out.append(tuple(x * scale for x in v) if scale != 1.0 else tuple(float(x) for x in v))
    return out


def _read_colors(d, a):
    out = []
    base, stride, f = a['data'], a['stride'], a['format']
    for i in range(a['count']):
        o = base + i * stride
        if f == 0:
            v = struct.unpack_from('>H', d, o)[0]
            r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
            c = (r * 255 // 31, g * 255 // 63, b * 255 // 31, 255)
        elif f in (1, 2):
            c = (d[o], d[o + 1], d[o + 2], 255)
        elif f == 3:
            v = struct.unpack_from('>H', d, o)[0]
            c = tuple(((v >> s) & 15) * 17 for s in (12, 8, 4, 0))
        elif f == 4:
            v = d[o] << 16 | d[o + 1] << 8 | d[o + 2]
            c = tuple(((v >> s) & 63) * 255 // 63 for s in (18, 12, 6, 0))
        else:
            c = (d[o], d[o + 1], d[o + 2], d[o + 3])
        out.append(c)
    return out


class Mdl0:
    def __init__(self, data, off=0):
        d = self.data = data
        self.off = off
        if d[off:off + 4] != b'MDL0':
            raise ValueError('not a model')
        self.size, self.version = struct.unpack_from('>II', d, off + 4)
        if self.version in (8, 9):
            names = ['defs', 'bones', 'verts', 'normals', 'colors', 'uvs', 'materials', 'shaders', 'objects',
                     'texrefs', 'pltrefs']
        elif self.version in (10, 11):
            names = ['defs', 'bones', 'verts', 'normals', 'colors', 'uvs', 'furvec', 'furlayer', 'materials',
                     'shaders', 'objects', 'texrefs', 'pltrefs']
        else:
            raise ValueError('unsupported model version %d' % self.version)
        offs = struct.unpack_from('>%di' % len(names), d, off + 0x10)
        p = off + 0x10 + 4 * len(names)
        if self.version == 11:
            p += 4                      # user data offset
        str_off = struct.unpack_from('>i', d, p)[0]
        self.name = cstr(d, off + str_off) if str_off else ''
        props = p + 4
        (_hl, _mo, self.scaling_rule, self.tex_mtx_mode, self.num_vertices, self.num_triangles, _path,
         self.num_nodes, _a, _b, _c, _e, node_tab) = struct.unpack_from('>IiIIIIIIBBBBI', d, props)
        self.box_min = struct.unpack_from('>3f', d, props + 0x28)
        self.box_max = struct.unpack_from('>3f', d, props + 0x34)
        n = struct.unpack_from('>I', d, props + node_tab)[0]
        self.node_table = list(struct.unpack_from('>%di' % n, d, props + node_tab + 4))   # matrix id -> bone index / -1
        self.groups = {nm: (read_group(d, off + o) if o else []) for nm, o in zip(names, offs)}
        self._read_defs()
        self._read_bones()
        self._read_materials()
        self.arrays = {}
        for kind, grp in (('vertex', 'verts'), ('normal', 'normals'), ('color', 'colors'), ('uv', 'uvs')):
            self.arrays[kind] = [_array_header(d, o, kind) for _n, o in self.groups[grp]]
        self._read_objects()

    # ------------------------------------------------------------ definitions (byte code)
    def _read_defs(self):
        d = self.data
        self.weight_nodes = {}        # matrix id -> [(matrix id of a bone, weight)]
        self.draws = []               # (material index, object index, bone index, priority, xlu)
        self.node_tree = []           # (bone index, parent matrix id)
        for name, o in self.groups['defs']:
            p = o
            while True:
                c = d[p]
                if c == 1:
                    break
                if c == 0:
                    p += 1
                elif c == 2:
                    self.node_tree.append(struct.unpack_from('>HH', d, p + 1))
                    p += 5
                elif c == 3:
                    mid, cnt = struct.unpack_from('>HB', d, p + 1)
                    lst = []
                    for k in range(cnt):
                        lst.append(struct.unpack_from('>Hf', d, p + 4 + k * 6))
                    self.weight_nodes[mid] = lst
                    p += 4 + cnt * 6
                elif c == 4:
                    m, ob, b, pr = struct.unpack_from('>HHHB', d, p + 1)
                    self.draws.append((m, ob, b, pr, name == 'DrawXlu'))
                    p += 8
                elif c in (5, 6):
                    p += 5
                else:
                    raise ValueError('unknown definition command %#x in %s' % (c, name))

    # ------------------------------------------------------------ bones
    def _read_bones(self):
        d = self.data
        self.bones = []
        by_off = {}
        raw = []
        for name, o in self.groups['bones']:
            b = Bone()
            (_hl, _mo, so, b.index, b.node_id, b.flags) = struct.unpack_from('>IiiiiI', d, o)
            b.name = cstr(d, o + so) if so else name
            b.scale = struct.unpack_from('>3f', d, o + 0x20)
            b.rot = struct.unpack_from('>3f', d, o + 0x2C)
            b.trans = struct.unpack_from('>3f', d, o + 0x38)
            b.box_min = struct.unpack_from('>3f', d, o + 0x44)
            b.box_max = struct.unpack_from('>3f', d, o + 0x50)
            par = struct.unpack_from('>i', d, o + 0x5C)[0]
            m = struct.unpack_from('>12f', d, o + 0x70)
            b.stored_world = (m[0:4], m[4:8], m[8:12])
            b.offset = o
            by_off[o] = b
            raw.append((b, o + par if par else None))
            self.bones.append(b)
        self.bones.sort(key=lambda x: x.index)
        for b, po in raw:
            b.parent = by_off[po].index if po is not None else -1
        for b in self.bones:              # index order: parents first (checked by the caller's sanity pass)
            local = mat_from_srt(b.scale, b.rot, b.trans)
            b.world = local if b.parent < 0 else mat_mul(self.bones[b.parent].world, local)

    # ------------------------------------------------------------ materials
    def _read_materials(self):
        d = self.data
        self.materials = []
        for name, o in self.groups['materials']:
            m = Material()
            _ln, _mo, so, m.index, flags = struct.unpack_from('>IiiII', d, o)
            m.name = cstr(d, o + so) if so else name
            m.xlu = bool(flags & 0x80000000)
            m.tex_gens, m.light_chans, m.stages, m.ind_stages = struct.unpack_from('>4B', d, o + 0x14)
            m.cull = struct.unpack_from('>I', d, o + 0x18)[0]
            m.shader_offset, ntex, ref = struct.unpack_from('>iIi', d, o + 0x28)
            m.shader_offset += o
            m.textures, m.palettes, m.wraps = [], [], []
            for k in range(ntex):
                r = o + ref + k * 0x34
                ts, ps = struct.unpack_from('>ii', d, r)
                m.textures.append(cstr(d, r + ts) if ts else '')
                m.palettes.append(cstr(d, r + ps) if ps else '')
                m.wraps.append(struct.unpack_from('>II', d, r + 0x18))
            self.materials.append(m)
        self.materials.sort(key=lambda x: x.index)

    # ------------------------------------------------------------ objects
    def _read_objects(self):
        d = self.data
        self.meshes = []
        ext = self.version >= 10
        for name, o in self.groups['objects']:
            m = Mesh()
            m.offset = o
            (_ln, _mo, m.node_id, m.vcd_lo, m.vcd_hi, _xf, _ds, _df, _do, _pb, m.prim_size, prim_off, _af, _fl, so,
             m.index, m.num_vertices, m.num_faces, m.vertex_id, m.normal_id) = struct.unpack_from(
                '>IiiIIIIIIIIIIIiIIIhh', d, o)
            m.prim_offset = o + 0x24 + prim_off
            m.color_ids = struct.unpack_from('>2h', d, o + 0x4C)
            m.uv_ids = struct.unpack_from('>8h', d, o + 0x50)
            m.name = cstr(d, o + so) if so else name
            m.material = -1
            m.draw_bone = -1
            m.xlu = False
            self.meshes.append(m)
        self.meshes.sort(key=lambda x: x.index)
        for mat, ob, bone, _pr, xlu in self.draws:
            if ob < len(self.meshes):
                me = self.meshes[ob]
                me.material, me.draw_bone, me.xlu = mat, bone, xlu

    def _array(self, kind, idx):
        for a in self.arrays[kind]:
            if a['index'] == idx:
                return a
        raise ValueError('%s array %d missing' % (kind, idx))

    def influences(self, matrix_id):
        """matrix id -> list of (bone index, weight)."""
        if matrix_id in self.weight_nodes:
            out = []
            for mid, w in self.weight_nodes[matrix_id]:
                b = self.node_table[mid]
                if b < 0:
                    raise ValueError('weighted matrix refers to a non-bone matrix')
                out.append((b, w))
            return out
        b = self.node_table[matrix_id]
        if b < 0:
            raise ValueError('matrix id %d is neither a bone nor a weight list' % matrix_id)
        return [(b, 1.0)]

    def decode(self, mesh):
        """Fills mesh.positions / normals / colors / uvs (lists per unique vertex), weights and triangles
        (index triples). Positions and normals in model space."""
        d = self.data
        lo, hi = mesh.vcd_lo, mesh.vcd_hi
        has_pn = lo & 1
        tex_mtx = [(lo >> (1 + i)) & 1 for i in range(8)]
        fpos, fnrm = (lo >> 9) & 3, (lo >> 11) & 3
        fcol = [(lo >> 13) & 3, (lo >> 15) & 3]
        fuv = [(hi >> (2 * i)) & 3 for i in range(8)]
        for f in [fpos, fnrm] + fcol + fuv:
            if f == 1:
                raise ValueError('direct vertex data in a display list is not supported')
        apos = self._array('vertex', mesh.vertex_id)
        P = _read_vectors(d, apos, 3 if apos['components'] else 2)
        N = None
        if fnrm:
            an = self._array('normal', mesh.normal_id)
            N = _read_vectors(d, an, 9 if an['components'] == 1 else 3)
            if an['components'] == 2:
                raise ValueError('normal / binormal / tangent with three indices is not supported')
        C = [None, None]
        for i in range(2):
            if fcol[i]:
                C[i] = _read_colors(d, self._array('color', mesh.color_ids[i]))
        U = [None] * 8
        for i in range(8):
            if fuv[i]:
                U[i] = _read_vectors(d, self._array('uv', mesh.uv_ids[i]), 2)

        def rd(p, f):
            if f == 2:
                return d[p], p + 1
            return (d[p] << 8 | d[p + 1]), p + 2

        slots = {}
        verts = {}
        order = []
        tris = []
        counts = {}
        p, end = mesh.prim_offset, mesh.prim_offset + mesh.prim_size
        single = mesh.node_id if mesh.node_id >= 0 else None
        if single is None and not has_pn:
            raise ValueError('weighted mesh without matrix indices')
        while p < end:
            c = d[p]
            if c == 0:
                p += 1
                continue
            if c in (0x20, 0x28, 0x30, 0x38):
                mid, v = struct.unpack_from('>HH', d, p + 1)
                if c == 0x20:
                    slots[(v & 0xFFF) // 12] = mid
                p += 5
                continue
            prim = c & 0xF8
            if prim not in (0x80, 0x90, 0x98, 0xA0, 0xA8, 0xB0, 0xB8):
                raise ValueError('unknown display list command %#x at %#x' % (c, p - mesh.prim_offset))
            cnt = struct.unpack_from('>H', d, p + 1)[0]
            p += 3
            counts[prim] = counts.get(prim, 0) + 1
            idx = []
            for _ in range(cnt):
                mid = single
                if has_pn:
                    mid = slots[d[p] // 3]
                    p += 1
                for i in range(8):
                    p += tex_mtx[i]
                ip, p = rd(p, fpos)
                inr = -1
                if fnrm:
                    inr, p = rd(p, fnrm)
                ic = [-1, -1]
                for i in range(2):
                    if fcol[i]:
                        ic[i], p = rd(p, fcol[i])
                iu = [-1] * 8
                for i in range(8):
                    if fuv[i]:
                        iu[i], p = rd(p, fuv[i])
                key = (mid, ip, inr, ic[0], ic[1]) + tuple(iu)
                vi = verts.get(key)
                if vi is None:
                    vi = verts[key] = len(order)
                    order.append(key)
                idx.append(vi)
            if prim == 0x90:
                for k in range(0, cnt - 2, 3):
                    tris.append((idx[k], idx[k + 1], idx[k + 2]))
            elif prim == 0x98:
                for k in range(cnt - 2):
                    t = (idx[k], idx[k + 1], idx[k + 2]) if k % 2 == 0 else (idx[k + 1], idx[k], idx[k + 2])
                    tris.append(t)
            elif prim == 0xA0:
                for k in range(1, cnt - 1):
                    tris.append((idx[0], idx[k], idx[k + 1]))
            elif prim == 0x80:
                for k in range(0, cnt - 3, 4):
                    tris.append((idx[k], idx[k + 1], idx[k + 2]))
                    tris.append((idx[k], idx[k + 2], idx[k + 3]))
        mesh.prim_counts = counts
        mesh.positions, mesh.normals, mesh.weights = [], [], []
        mesh.colors = [[] if C[i] is not None else None for i in range(2)]
        mesh.uvs = [[] if U[i] is not None else None for i in range(8)]
        inf_cache = {}
        for key in order:
            mid, ip, inr = key[0], key[1], key[2]
            inf = inf_cache.get(mid)
            if inf is None:
                inf = inf_cache[mid] = self.influences(mid)
            pos = P[ip]
            if len(pos) == 2:
                pos = (pos[0], pos[1], 0.0)
            nrm = N[inr][:3] if N is not None else (0.0, 1.0, 0.0)
            if len(inf) == 1:
                w = self.bones[inf[0][0]].world
                pos = mat_point(w, pos)
                nrm = mat_dir(w, nrm)
            ln = math.sqrt(nrm[0] ** 2 + nrm[1] ** 2 + nrm[2] ** 2)
            nrm = (nrm[0] / ln, nrm[1] / ln, nrm[2] / ln) if ln > 1e-12 else (0.0, 1.0, 0.0)
            mesh.positions.append(pos)
            mesh.normals.append(nrm)
            mesh.weights.append(inf)
            for i in range(2):
                if C[i] is not None:
                    mesh.colors[i].append(C[i][key[3 + i]])
            for i in range(8):
                if U[i] is not None:
                    mesh.uvs[i].append(U[i][key[5 + i]])
        # winding: the format's front face is clockwise; flip to counter-clockwise
        mesh.triangles = [(a, c, b) for a, b, c in tris if a != b and b != c and a != c]
        return mesh
