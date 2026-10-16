"""CHR0 bone animation reader (versions 4 and 5): keyframe tracks -> per-frame scale / rotation / translation.

Per bone entry: name, a code word, then for scale, rotation, translation (when present) either one value (all axes
equal) or three; each value is a constant float or an offset to a track. Track encodings: interpolated with 4-, 6-
or 12-byte keys (frame, value, tangent; Hermite), or one value per frame as u8 / u16 (step, base) or float.
Rotations are Euler angles in degrees (X applied first, then Y, then Z), as in the model's bones.
"""
import struct

from .brres import cstr, read_group


def _hermite(keys, f):
    """keys: sorted list of (frame, value, tangent)."""
    if f <= keys[0][0]:
        return keys[0][1]
    if f >= keys[-1][0]:
        return keys[-1][1]
    lo, hi = 0, len(keys) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if keys[mid][0] <= f:
            lo = mid
        else:
            hi = mid
    f0, p0, m0 = keys[lo]
    f1, p1, m1 = keys[hi]
    span = f1 - f0
    if span <= 0:
        return p1
    t = (f - f0) / span
    t2, t3 = t * t, t * t * t
    return ((2 * t3 - 3 * t2 + 1) * p0 + (t3 - 2 * t2 + t) * span * m0 + (-2 * t3 + 3 * t2) * p1 +
            (t3 - t2) * span * m1)


class Track:
    """One animated component. sample(frame) -> float."""

    def __init__(self, kind, keys=None, values=None, const=None):
        self.kind, self.keys, self.values, self.const = kind, keys, values, const

    def sample(self, f):
        if self.const is not None:
            return self.const
        if self.values is not None:
            i = int(f)
            if i >= len(self.values) - 1:
                return self.values[-1]
            fr = f - i
            return self.values[i] * (1 - fr) + self.values[i + 1] * fr
        return _hermite(self.keys, f)


def _read_track(d, off, fmt, frames):
    if fmt == 1:        # 4-byte keys
        n, _u, _fs, step, base = struct.unpack_from('>HHfff', d, off)
        keys = []
        for i in range(n):
            v = struct.unpack_from('>I', d, off + 16 + i * 4)[0]
            tan = v & 0xFFF
            if tan & 0x800:
                tan -= 0x1000
            keys.append((float(v >> 24), base + step * ((v >> 12) & 0xFFF), tan / 32.0))
        return Track('I4', keys=keys)
    if fmt == 2:        # 6-byte keys
        n, _u, _fs, step, base = struct.unpack_from('>HHfff', d, off)
        keys = []
        for i in range(n):
            fr, st, tan = struct.unpack_from('>HHh', d, off + 16 + i * 6)
            keys.append((fr / 32.0, base + step * st, tan / 256.0))
        return Track('I6', keys=keys)
    if fmt == 3:        # 12-byte keys
        n, _u, _fs = struct.unpack_from('>HHf', d, off)
        keys = [struct.unpack_from('>fff', d, off + 8 + i * 12) for i in range(n)]
        return Track('I12', keys=keys)
    if fmt == 4:        # one byte per frame
        step, base = struct.unpack_from('>ff', d, off)
        return Track('L1', values=[base + step * v for v in struct.unpack_from('>%dB' % frames, d, off + 8)])
    if fmt == 5:        # one u16 per frame
        step, base = struct.unpack_from('>ff', d, off)
        return Track('L2', values=[base + step * v for v in struct.unpack_from('>%dH' % frames, d, off + 8)])
    if fmt == 6:        # one float per frame
        return Track('L4', values=list(struct.unpack_from('>%df' % frames, d, off)))
    raise ValueError('unknown track format %d' % fmt)


class BoneAnim:
    __slots__ = ('name', 'code', 'scale', 'rot', 'trans')

    def sample(self, f):
        """-> (scale xyz, rotation xyz in degrees, translation xyz); None for a part the entry does not hold."""
        return tuple(None if p is None else tuple(t.sample(f) for t in p) for p in (self.scale, self.rot, self.trans))


class Chr0:
    def __init__(self, data, off):
        d = data
        if d[off:off + 4] != b'CHR0':
            raise ValueError('not a bone animation')
        self.size, self.version, _bres, data_off = struct.unpack_from('>IIii', d, off + 4)
        p = off + 0x14
        if self.version == 5:
            p += 4
        elif self.version != 4:
            raise ValueError('unsupported animation version %d' % self.version)
        str_off, _path, self.frames, count, self.loop, self.scaling_rule = struct.unpack_from('>iiHHII', d, p)
        self.name = cstr(d, off + str_off) if str_off else ''
        # the header's count is the number of key positions: frame indices run 0 .. frames - 1
        self.entries = []
        for name, eo in read_group(d, off + data_off):
            e = BoneAnim()
            so, code = struct.unpack_from('>iI', d, eo)
            e.name = cstr(d, eo + so) if so else name
            e.code = code
            q = eo + 8
            parts = []
            for has_bit, iso_bit, fix_shift, fmt_shift, fmt_mask, default in (
                    (22, 4, 13, 25, 3, 1.0), (23, 5, 16, 27, 7, 0.0), (24, 6, 19, 30, 3, 0.0)):
                if not (code >> has_bit) & 1:
                    parts.append(None)
                    continue
                fmt = (code >> fmt_shift) & fmt_mask
                iso = (code >> iso_bit) & 1
                comps = []
                for axis in range(1 if iso else 3):
                    if (code >> (fix_shift + axis)) & 1:
                        comps.append(Track('const', const=struct.unpack_from('>f', d, q)[0]))
                    else:
                        to = struct.unpack_from('>I', d, q)[0]
                        comps.append(_read_track(d, eo + to, fmt, self.frames))
                    q += 4
                if iso:
                    comps = comps * 3
                parts.append(comps)
            e.scale, e.rot, e.trans = parts
            self.entries.append(e)

    def track_kinds(self):
        out = {}
        for e in self.entries:
            for p in (e.scale, e.rot, e.trans):
                for t in p or ():
                    out[t.kind] = out.get(t.kind, 0) + 1
        return out
