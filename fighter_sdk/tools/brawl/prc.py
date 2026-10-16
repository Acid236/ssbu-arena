"""The native parameter file (.prc): reader and writer.

Layout (the community's public description, checked here by round trip on the game's files): "paracobn", u32 size
of the hash table, u32 size of the reference table, the hash table (40-bit name hashes as u64), the reference
table, then one parameter tree. A parameter is a type byte + value:
  1 bool (u8)  2 i8  3 u8  4 i16  5 u16  6 i32  7 u32  8 f32  9 hash (u32 index into the hash table)
  10 string (u32 offset into the reference table)  11 list (u32 count, count u32 offsets from the list's type
  byte, the elements)  12 struct (u32 field count, u32 offset into the reference table of its field table:
  {u32 hash index, u32 offset from the struct's type byte} per field, sorted by hash index; the fields follow).
Identical field tables are stored once (structs of the same shape share one).

Values in memory: ('bool', v) ... ('hash', u64) ('str', text) ('list', [params]) ('struct', [(u64 key, param)]),
fields in the order they lie in the file.

    python -I prc.py roundtrip <folder>     every .prc under the folder: read -> write, compared byte for byte
    python -I prc.py dump <file> [<ParamLabels.csv>]
"""
import os
import struct
import sys
import zlib

_SCALAR = {1: ('bool', '<B'), 2: ('i8', '<b'), 3: ('u8', '<B'), 4: ('i16', '<h'), 5: ('u16', '<H'), 6: ('i32', '<i'),
           7: ('u32', '<I'), 8: ('f32', '<f')}
_CODE = {v[0]: (k, v[1]) for k, v in _SCALAR.items()}


def hash40(s):
    b = s.encode('ascii')
    return len(b) << 32 | (zlib.crc32(b) & 0xFFFFFFFF)


class Prc:
    def __init__(self, data=None):
        self.hashes = []
        self._hint = {}          # id of a value / field tuple read from a file -> its index in the hash table
        self._keep = []          # keeps those tuples alive so the ids stay theirs
        self.root = ('struct', [])
        if data is not None:
            self._read(data)

    # ------------------------------------------------------------ read
    def _read(self, d):
        if d[:8] != b'paracobn':
            raise ValueError('not a parameter file')
        hsize, rsize = struct.unpack_from('<II', d, 8)
        self.hashes = list(struct.unpack_from('<%dQ' % (hsize // 8), d, 16))
        self._ref = 16 + hsize
        self._d = d
        start = self._ref + rsize
        self.root, end = self._param(start)
        if end != len(d):
            raise ValueError('data after the parameter tree (%d of %d)' % (end, len(d)))

    def _param(self, p):
        d = self._d
        t = d[p]
        if t in _SCALAR:
            name, fmt = _SCALAR[t]
            n = struct.calcsize(fmt)
            return (name, struct.unpack_from(fmt, d, p + 1)[0]), p + 1 + n
        if t == 9:
            i = struct.unpack_from('<I', d, p + 1)[0]
            v = ('hash', self.hashes[i])
            self._hint[id(v)] = i
            self._keep.append(v)
            return v, p + 5
        if t == 10:
            o = self._ref + struct.unpack_from('<I', d, p + 1)[0]
            e = d.index(b'\0', o)
            return ('str', d[o:e].decode('utf-8')), p + 5
        if t == 11:
            n = struct.unpack_from('<I', d, p + 1)[0]
            offs = struct.unpack_from('<%dI' % n, d, p + 5)
            out = []
            end = p + 5 + 4 * n
            for o in offs:
                v, end = self._param(p + o)
                out.append(v)
            return ('list', out), end
        if t == 12:
            n, ro = struct.unpack_from('<II', d, p + 1)
            ents = [struct.unpack_from('<II', d, self._ref + ro + i * 8) for i in range(n)]
            out = []
            end = p + 9
            for hi, o in sorted(ents, key=lambda e: e[1]):
                v, end = self._param(p + o)
                f = (self.hashes[hi], v)
                self._hint[id(f)] = hi
                out.append(f)
            return ('struct', out), end
        raise ValueError('unknown parameter type %d at %#x' % (t, p))

    # ------------------------------------------------------------ write
    def to_bytes(self):
        hashes = list(self.hashes)
        index = {}
        for i, h in enumerate(hashes):
            index.setdefault(h, i)
        hint = getattr(self, '_hint', {})

        def hidx(h, obj=None):
            # the game's hash tables hold some hashes twice; a value read from a file keeps the index it had
            i = hint.get(id(obj))
            if i is not None and i < len(hashes) and hashes[i] == h:
                return i
            if h not in index:
                index[h] = len(hashes)
                hashes.append(h)
            return index[h]
        # every hash must have its index before the field tables are written
        def collect(v):
            if v[0] == 'hash':
                hidx(v[1], v)
            elif v[0] == 'list':
                for e in v[1]:
                    collect(e)
            elif v[0] == 'struct':
                for f in v[1]:
                    hidx(f[0], f)
                    collect(f[1])
        collect(self.root)
        ref = bytearray()
        tables = {}
        strings = {}
        out = bytearray()

        def size(v):
            kind = v[0]
            if kind in _CODE:
                return 1 + struct.calcsize(_CODE[kind][1])
            if kind in ('hash', 'str'):
                return 5
            if kind == 'list':
                return 5 + 4 * len(v[1]) + sum(size(e) for e in v[1])
            return 9 + sum(size(e) for _k, e in v[1])

        def put(v):
            start = len(out)
            kind = v[0]
            if kind in _CODE:
                code, fmt = _CODE[kind]
                out.append(code)
                out.extend(struct.pack(fmt, v[1]))
            elif kind == 'hash':
                out.append(9)
                out.extend(struct.pack('<I', hidx(v[1], v)))
            elif kind == 'str':
                if v[1] not in strings:
                    strings[v[1]] = len(ref)
                    ref.extend(v[1].encode('utf-8') + b'\0')
                out.append(10)
                out.extend(struct.pack('<I', strings[v[1]]))
            elif kind == 'list':
                out.append(11)
                out.extend(struct.pack('<I', len(v[1])))
                table = len(out)
                out.extend(b'\0' * (4 * len(v[1])))
                for i, e in enumerate(v[1]):
                    struct.pack_into('<I', out, table + 4 * i, len(out) - start)
                    put(e)
            elif kind == 'struct':
                out.append(12)
                out.extend(struct.pack('<I', len(v[1])))
                slot = len(out)
                out.extend(b'\0\0\0\0')
                # the field table goes into the reference table WHEN THE STRUCT IS MET, before its children's
                # tables (their offsets follow from the children's sizes), unless an identical table exists
                ents, o = [], 9
                for f in v[1]:
                    ents.append((hidx(f[0], f), o))
                    o += size(f[1])
                blob = b''.join(struct.pack('<II', *x) for x in sorted(ents, key=lambda x: hashes[x[0]]))
                if blob not in tables:
                    tables[blob] = len(ref)
                    ref.extend(blob)
                struct.pack_into('<I', out, slot, tables[blob])
                for k, e in v[1]:
                    put(e)
            else:
                raise ValueError('unknown value kind %r' % (kind,))
        put(self.root)
        head = b'paracobn' + struct.pack('<II', len(hashes) * 8, len(ref))
        return head + struct.pack('<%dQ' % len(hashes), *hashes) + bytes(ref) + bytes(out)


# Where a struct's field table goes in the reference table. Found by experiment on the game's files (see
# roundtrip): the table is appended AFTER the struct's children are written, unless an identical one exists.
def _reserve_none(v, ref, tables):
    return None


def _place_after(blob, ref, tables, place):
    if blob in tables:
        return tables[blob]
    tables[blob] = len(ref)
    ref.extend(blob)
    return tables[blob]


PLACE = [_reserve_none, _place_after]


def load(path):
    with open(path, 'rb') as f:
        return Prc(f.read())


# ------------------------------------------------------------ helpers for editing
def field(struct_value, key):
    """key: name or u64 hash. -> the field's param (KeyError when absent)."""
    h = hash40(key) if isinstance(key, str) else key
    for k, v in struct_value[1]:
        if k == h:
            return v
    raise KeyError(key)


def set_field(struct_value, key, new):
    h = hash40(key) if isinstance(key, str) else key
    for i, (k, v) in enumerate(struct_value[1]):
        if k == h:
            struct_value[1][i] = (k, new)
            return
    raise KeyError(key)


def labels(csv_path):
    out = {}
    with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            a, _, b = line.strip().partition(',')
            if a.startswith('0x') and b:
                out[int(a, 16)] = b
    return out


def dump(v, lab, ind=0, key=None, out=None, limit=4000):
    out = [] if out is None else out
    if len(out) > limit:
        return out
    name = '' if key is None else (lab.get(key, '%#x' % key) if isinstance(key, int) else str(key)) + ': '
    pad = '  ' * ind
    if v[0] == 'struct':
        out.append('%s%sstruct (%d)' % (pad, name, len(v[1])))
        for k, e in v[1]:
            dump(e, lab, ind + 1, k, out, limit)
    elif v[0] == 'list':
        out.append('%s%slist (%d)' % (pad, name, len(v[1])))
        for i, e in enumerate(v[1]):
            dump(e, lab, ind + 1, '[%d]' % i, out, limit)
    elif v[0] == 'hash':
        out.append('%s%shash %s' % (pad, name, lab.get(v[1], '%#x' % v[1])))
    else:
        out.append('%s%s%s %r' % (pad, name, v[0], v[1]))
    return out


def roundtrip(folder):
    ok = n = 0
    for dp, _dn, fs in os.walk(folder):
        for f in sorted(fs):
            if not f.endswith('.prc'):
                continue
            p = os.path.join(dp, f)
            with open(p, 'rb') as fh:
                raw = fh.read()
            n += 1
            try:
                again = Prc(raw).to_bytes()
            except Exception as ex:           # report and go on
                print('%-70s %8d bytes  NOT READ: %s' % (os.path.relpath(p, folder), len(raw), ex))
                continue
            same = again == raw
            ok += same
            note = ''
            if not same:
                k = next((i for i in range(min(len(raw), len(again))) if raw[i] != again[i]), min(len(raw), len(again)))
                note = ' (first difference at %#x; sizes %d / %d)' % (k, len(raw), len(again))
            print('%-70s %8d bytes  read -> write: %s%s' % (os.path.relpath(p, folder), len(raw),
                                                            'byte-identical' if same else 'DIFFERENT', note))
    print('%d of %d parameter files byte-identical' % (ok, n))
    return ok == n


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'roundtrip':
        sys.exit(0 if roundtrip(sys.argv[2]) else 1)
    elif len(sys.argv) >= 3 and sys.argv[1] == 'dump':
        lab = labels(sys.argv[3]) if len(sys.argv) > 3 else {}
        print('\n'.join(dump(load(sys.argv[2]).root, lab)))
    else:
        print(__doc__)
