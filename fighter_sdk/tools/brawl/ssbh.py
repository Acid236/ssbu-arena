"""Reader and writer of the native model files: skeleton (.nusktb), mesh (.numshb), model description (.numdlb),
materials (.numatb). Layouts as publicly documented by the community (the ssbh family: little endian, 64-bit
offsets relative to the offset field itself, arrays as offset + count), checked against files on this PC by a
read -> write round trip (see convert_model.py roundtrip).

The writer lays data out depth first: a structure's fixed part, then, field by field, what each offset points to.
"""
import struct

# ------------------------------------------------------------------ schema engine
_PRIM = {'u8': ('<B', 1), 'u16': ('<H', 2), 'i16': ('<h', 2), 'u32': ('<I', 4), 'i32': ('<i', 4), 'u64': ('<Q', 8),
         'i64': ('<q', 8), 'f32': ('<f', 4)}


def S(*fields):
    return ('struct', fields)


def A(elem, align=8):
    return ('array', elem, align)


def STR(align=4):
    return ('str', align)


def RAW(n):
    return ('raw', n)


BYTEBUF = ('bytebuf',)
PARAM = ('param',)


def size_of(t):
    if isinstance(t, str):
        return _PRIM[t][1]
    k = t[0]
    if k == 'struct':
        return sum(size_of(ft) for _n, ft in t[1])
    if k == 'raw':
        return t[1]
    if k == 'str':
        return 8
    if k in ('array', 'bytebuf', 'param'):
        return 16
    raise ValueError(k)


def _cstr(buf, p):
    e = buf.index(b'\0', p)
    return buf[p:e].decode('utf-8')


# sizes of material parameter blobs by data type (bytes actually used)
PARAM_SIZES = {1: 4, 2: 4, 5: 16, 0xB: 8, 0xE: 56, 0x10: 20, 0x11: 48, 0x12: 32}


def read(buf, pos, t):
    if isinstance(t, str):
        return struct.unpack_from(_PRIM[t][0], buf, pos)[0]
    k = t[0]
    if k == 'struct':
        out = {}
        for n, ft in t[1]:
            out[n] = read(buf, pos, ft)
            pos += size_of(ft)
        return out
    if k == 'raw':
        return bytes(buf[pos:pos + t[1]])
    if k == 'str':
        off = struct.unpack_from('<Q', buf, pos)[0]
        return None if off == 0 else _cstr(buf, pos + off)
    if k == 'array':
        off, cnt = struct.unpack_from('<QQ', buf, pos)
        if off == 0:
            return []
        es = size_of(t[1])
        if pos + off + cnt * es > len(buf):
            raise ValueError('array beyond the end of the file')
        return [read(buf, pos + off + i * es, t[1]) for i in range(cnt)]
    if k == 'bytebuf':
        off, cnt = struct.unpack_from('<QQ', buf, pos)
        if off == 0:
            return b''
        if pos + off + cnt > len(buf):
            raise ValueError('byte buffer beyond the end of the file')
        return bytes(buf[pos + off:pos + off + cnt])
    if k == 'param':
        off, dt = struct.unpack_from('<QQ', buf, pos)
        p = pos + off
        if dt == 0xB:
            return (dt, read(buf, p, STR(4)))
        if dt not in PARAM_SIZES:
            raise ValueError('unknown material parameter type %#x' % dt)
        return (dt, bytes(buf[p:p + PARAM_SIZES[dt]]))
    raise ValueError(k)


class Writer:
    def __init__(self):
        self.buf = bytearray()
        self.data_ptr = 0

    def put(self, pos, b):
        end = pos + len(b)
        if end > len(self.buf):
            self.buf.extend(b'\0' * (end - len(self.buf)))
        self.buf[pos:end] = b

    def alloc(self, size, align):
        p = (self.data_ptr + align - 1) // align * align
        self.data_ptr = p + size
        if self.data_ptr > len(self.buf):
            self.buf.extend(b'\0' * (self.data_ptr - len(self.buf)))
        return p


def write(w, pos, t, v):
    if isinstance(t, str):
        w.put(pos, struct.pack(_PRIM[t][0], v))
        return
    k = t[0]
    if k == 'struct':
        for n, ft in t[1]:
            write(w, pos, ft, v[n])
            pos += size_of(ft)
    elif k == 'raw':
        if len(v) != t[1]:
            raise ValueError('raw field size')
        w.put(pos, v)
    elif k == 'str':
        if v is None:
            w.put(pos, struct.pack('<Q', 0))
            return
        b = v.encode('utf-8') + b'\0'
        if len(b) == 1:
            b = b'\0' * 4          # an empty string occupies four bytes
        p = w.alloc(len(b), t[1])
        w.put(pos, struct.pack('<Q', p - pos))
        w.put(p, b)
    elif k == 'array':
        if not v:
            w.alloc(0, t[2])       # an empty array still aligns the data position (seen in the game's files)
            w.put(pos, struct.pack('<QQ', 0, 0))
            return
        es = size_of(t[1])
        p = w.alloc(es * len(v), t[2])
        w.put(pos, struct.pack('<QQ', p - pos, len(v)))
        for i, e in enumerate(v):
            write(w, p + i * es, t[1], e)
    elif k == 'bytebuf':
        if not v:
            w.put(pos, struct.pack('<QQ', 0, 0))
            return
        p = w.alloc(len(v), 8)
        w.put(pos, struct.pack('<QQ', p - pos, len(v)))
        w.put(p, v)
    elif k == 'param':
        dt, val = v
        if dt == 0xB:
            p = w.alloc(8, 8)
            w.put(pos, struct.pack('<QQ', p - pos, dt))
            write(w, p, STR(4), val)
        else:
            p = w.alloc(len(val), 8)
            w.put(pos, struct.pack('<QQ', p - pos, dt))
            w.put(p, val)
    else:
        raise ValueError(k)


# ------------------------------------------------------------------ the four formats
BOUNDING = RAW(100)        # sphere (centre, radius), box (min, max), oriented box (centre, 3x3, size)

SKEL = S(('bone_entries', A(S(('name', STR(4)), ('index', 'u16'), ('parent', 'i16'), ('flags', 'u32')))),
         ('world', A(RAW(64))), ('inv_world', A(RAW(64))), ('local', A(RAW(64))), ('inv_local', A(RAW(64))))

MODL = S(('model_name', STR(4)), ('skeleton_file', STR(4)), ('material_files', A(S(('name', STR(4))))),
         ('animation_file', STR(4)), ('mesh_file', STR(4)),
         ('entries', A(S(('mesh_name', STR(4)), ('subindex', 'u64'), ('material_label', STR(4))))))

MATL = S(('entries', A(S(('label', STR(4)),
                         ('attributes', A(S(('param_id', 'u64'), ('param', PARAM)))),
                         ('shader_label', STR(4))))))

MESH_ATTR = S(('usage', 'u32'), ('data_type', 'u32'), ('buffer_index', 'u32'), ('buffer_offset', 'u32'),
              ('subindex', 'u64'), ('name', STR(4)), ('attribute_names', A(S(('name', STR(4))))))

MESH_OBJECT = S(('name', STR(4)), ('subindex', 'u64'), ('parent_bone_name', STR(4)), ('vertex_count', 'u32'),
                ('vertex_index_count', 'u32'), ('unk2', 'u32'), ('vb0_offset', 'u32'), ('vb1_offset', 'u32'),
                ('vb2_offset', 'u32'), ('vb3_offset', 'u32'), ('stride0', 'u32'), ('stride1', 'u32'),
                ('stride2', 'u32'), ('stride3', 'u32'), ('index_buffer_offset', 'u32'), ('unk8', 'u32'),
                ('draw_element_type', 'u32'), ('use_vertex_skinning', 'u32'), ('sort_bias', 'i32'),
                ('depth_flags', 'u32'), ('bounding', BOUNDING), ('attributes', A(MESH_ATTR)))

RIGGING = S(('mesh_name', STR(4)), ('subindex', 'u64'), ('flags', 'u64'),
            ('buffers', A(S(('bone_name', STR(4)), ('data', BYTEBUF)))))

MESH = S(('model_name', STR(4)), ('bounding', BOUNDING), ('unk1', 'u32'), ('objects', A(MESH_OBJECT)),
         ('buffer_sizes', A('u32')), ('polygon_index_size', 'u64'), ('vertex_buffers', A(S(('data', BYTEBUF)))),
         ('index_buffer', BYTEBUF), ('rigging', A(RIGGING)), ('unknown_offset', 'u64'), ('unknown_size', 'u64'))

# animation (.nuanmb) 2.1: groups by kind (1 transform, 2 visibility, 4 material, 5 camera) -> nodes -> tracks; a
# track's data lies in the one buffer at data_offset. flags: low byte the value kind (1 transform, 2 texture
# transform, 3 float, 5 boolean, 9 vector), next byte the storage (1 one value per frame, 4 packed, 5 constant).
ANIM_TRACK = S(('name', STR(4)), ('flags', 'u32'), ('frame_count', 'u32'), ('transform_flags', 'u32'),
               ('data_offset', 'u32'), ('data_size', 'u64'))
ANIM = S(('final_frame_index', 'f32'), ('unk1', 'u16'), ('unk2', 'u16'), ('name', STR(4)),
         ('groups', A(S(('type', 'u64'), ('nodes', A(S(('name', STR(4)), ('tracks', A(ANIM_TRACK)))))))),
         ('buffer', BYTEBUF), ('unk_a', A(S(('kind', 'u64'), ('items', A(RAW(8)))))),
         ('unk_b', A(S(('kind', 'u64'), ('items', A(RAW(8)))))))

ANIM20 = S(*ANIM[1][:-2])          # version 2.0: the same without the two trailing arrays

FORMATS = {b'LEKS': ('skeleton', (1, 0), SKEL), b'LDOM': ('model description', (1, 7), MODL),
           b'LTAM': ('materials', (1, 6), MATL), b'HSEM': ('mesh', (1, 10), MESH),
           b'MINA': ('animation', (2, 1), ANIM)}
OTHER_VERSIONS = {(b'MINA', (2, 0)): ANIM20}


def parse(buf):
    """-> (magic, (major, minor), value)."""
    if buf[:4] != b'HBSS':
        raise ValueError('not a native model file')
    magic = bytes(buf[0x10:0x14])
    major, minor = struct.unpack_from('<HH', buf, 0x14)
    if magic not in FORMATS:
        raise ValueError('unsupported file type %r' % magic)
    _name, ver, schema = FORMATS[magic]
    if (major, minor) != ver:
        schema = OTHER_VERSIONS.get((magic, (major, minor)))
        if schema is None:
            raise ValueError('%s: version %d.%d, this tool knows %d.%d' % (_name, major, minor, ver[0], ver[1]))
    return magic, (major, minor), read(buf, 0x18, schema)


def build(magic, value, version=None, tail=b''):
    """version: None = the format's main version; tail: bytes after the last data (some of the game's files
    carry padding there)."""
    _name, ver, schema = FORMATS[magic]
    if version is not None and tuple(version) != ver:
        ver, schema = tuple(version), OTHER_VERSIONS[(magic, tuple(version))]
    w = Writer()
    w.put(0, b'HBSS' + struct.pack('<Q', 0x40) + b'\0\0\0\0' + magic + struct.pack('<HH', *ver))
    w.data_ptr = 0x18 + size_of(schema)
    w.put(w.data_ptr - 1, b'\0')
    write(w, 0x18, schema, value)
    return bytes(w.buf) + tail


def load(path):
    with open(path, 'rb') as f:
        return parse(f.read())


# ------------------------------------------------------------------ helpers for mesh buffers
def half(f):
    return struct.pack('<e', f)


def mat4_bytes(rows):
    """rows: 4 rows of 4 floats (row major, translation in the fourth row)."""
    return struct.pack('<16f', *[x for r in rows for x in r])


def mat4_rows(b):
    v = struct.unpack('<16f', b)
    return [list(v[i * 4:i * 4 + 4]) for i in range(4)]
