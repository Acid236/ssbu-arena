"""Native animation tracks (the data inside a .nuanmb, container layout in ssbh.py): transform tracks.

Constant track (flags 0x201): one 44-byte value {scale 3 f32, rotation quaternion x y z w, translation 3 f32,
u32 scale-compensation flag}.
Packed track (flags 0x401): 16-byte header {u16 4, u16 flags, u16 offset of the default value, u16 bits per frame,
u32 offset of the bit stream, u32 frame count}; nine 16-byte ranges {f32 min, f32 max, u64 bit count} for scale
xyz, rotation xyz, translation xyz; the 44-byte default value; then per frame, least significant bit first: every
component of an enabled part with its range's bit count (0 = not stored; value = min + (max - min) * n /
(2^bits - 1)), in the order scale, rotation x y z, translation, and - when rotation is enabled - one bit: w is
negative. w = sqrt(1 - x^2 - y^2 - z^2).
Header flags: bits 0-1 scale kind (1 = three stored components, 2 = constant: nothing stored, 3 = one stored
value for all axes), bit 2 rotation enabled, bit 3 translation enabled.

decode() exists to check this description against the game's own files; encode() writes the same layout.
"""
import math
import struct

F_CONST, F_PACKED = 0x201, 0x401


def _bits(buf, pos, n):
    v = 0
    for i in range(n):
        if buf[(pos + i) >> 3] >> ((pos + i) & 7) & 1:
            v |= 1 << i
    return v


def decode(data, flags, frame_count):
    """-> (list of (scale, quaternion xyzw, translation), info dict)."""
    if flags == F_CONST:
        v = struct.unpack_from('<10f', data, 0)
        return [(v[0:3], v[3:7], v[7:10])], {'kind': 'const'}
    if flags != F_PACKED:
        raise ValueError('track storage %#x not handled' % flags)
    unk, fl, def_off, bpe, bit_off, frames = struct.unpack_from('<HHHHII', data, 0)
    rng = [struct.unpack_from('<ffQ', data, 16 + i * 16) for i in range(9)]
    d = struct.unpack_from('<10f', data, def_off)
    scale_kind, has_rot, has_trans = fl & 3, (fl >> 2) & 1, (fl >> 3) & 1
    # WHICH COMPONENTS ARE IN THE BIT STREAM (corrected 22:30 after the game runs): a component of an ENABLED
    # part is stored with exactly its range's bit count - 0 bits = not stored - whether or not min equals max.
    # Scale is enabled for kinds 1 and 3 only (kind 2 = constant scale, its ranges are not read; kind 3 = one
    # value for all three axes); rotation by bit 2, translation by bit 3. The first version of this file skipped
    # a component when min == max and wrote 16 as its bit count: the game then read 16 bits that were not there.
    use = []
    if scale_kind == 1:
        use += [0, 1, 2]
    elif scale_kind == 3:
        use += [0]
    if has_rot:
        use += [3, 4, 5]
    if has_trans:
        use += [6, 7, 8]
    use = [i for i in use if rng[i][2] > 0]
    width = sum(rng[i][2] for i in use) + (1 if has_rot else 0)
    info = {'kind': 'packed', 'flags': fl, 'bits_per_frame': bpe, 'computed_bits': width, 'frames': frames,
            'expected_size': bit_off + (frames * bpe + 7) // 8, 'unk': unk, 'ranges': rng}
    out = []
    if width != bpe:
        return out, info
    pos = bit_off * 8
    for _f in range(frames):
        vals = [d[0], d[1], d[2], d[3], d[4], d[5], d[7], d[8], d[9]]
        for i in use:
            mn, mx, n = rng[i]
            raw = _bits(data, pos, n)
            pos += n
            vals[i] = mn + (mx - mn) * raw / ((1 << n) - 1)
        if scale_kind == 3:
            vals[1] = vals[2] = vals[0]
        w = d[6]
        if has_rot:
            neg = _bits(data, pos, 1)
            pos += 1
            w = math.sqrt(max(0.0, 1.0 - vals[3] ** 2 - vals[4] ** 2 - vals[5] ** 2))
            if neg:
                w = -w
        out.append((tuple(vals[0:3]), (vals[3], vals[4], vals[5], w), tuple(vals[6:9])))
    return out, info


def const_bytes(scale, quat, trans):
    return struct.pack('<10fI', *scale, *quat, *trans, 0)


def encode(frames, bits=16):
    """frames: list of (scale xyz, quaternion xyzw, translation xyz). -> (flags, frame count, bytes)."""
    first = frames[0]
    if all(_close(f, first) for f in frames):
        return F_CONST, 1, const_bytes(*first)
    comps = [[f[0][0] for f in frames], [f[0][1] for f in frames], [f[0][2] for f in frames],
             [f[1][0] for f in frames], [f[1][1] for f in frames], [f[1][2] for f in frames],
             [f[2][0] for f in frames], [f[2][1] for f in frames], [f[2][2] for f in frames]]
    # The game's own files, surveyed: a part (scale / rotation / translation) is enabled in the header flags only
    # when it varies; inside an enabled part a constant component has bit count 0 and a varying one n bits; a
    # part that is not enabled keeps bit count 16 in its ranges (never read). Scale that varies uses kind 1
    # (three components); constant scale uses kind 2. The sign bit of w exists only when rotation is enabled.
    span = []
    for c in comps:
        mn, mx = struct.unpack('<ff', struct.pack('<ff', min(c), max(c)))
        if mx - mn < 1e-7:
            mx = mn
        span.append((mn, mx))
    part_varies = [any(span[i][0] != span[i][1] for i in range(p * 3, p * 3 + 3)) for p in range(3)]
    # stored scale occurs in the game's files only together with an enabled rotation: keep to that
    enabled = [part_varies[0], part_varies[1] or part_varies[0], part_varies[2]]
    rng = []
    for i, (mn, mx) in enumerate(span):
        if not enabled[i // 3]:
            rng.append((mn, mx, 16))
        else:
            rng.append((mn, mx, bits if mn != mx else 0))
    has_rot = enabled[1]
    flag_word = (1 if enabled[0] else 2) | (4 if has_rot else 0) | (8 if enabled[2] else 0)
    stored = [i for i in range(9) if enabled[i // 3] and rng[i][2] > 0]
    width = sum(rng[i][2] for i in stored) + (1 if has_rot else 0)
    head_len = 16 + 9 * 16
    bit_off = head_len + 44
    total_bits = width * len(frames)
    stream = bytearray((total_bits + 7) // 8)
    pos = 0

    def put(v, n):
        nonlocal pos
        for i in range(n):
            if v >> i & 1:
                stream[(pos + i) >> 3] |= 1 << ((pos + i) & 7)
        pos += n

    top = (1 << bits) - 1
    for k in range(len(frames)):
        for i in stored:
            mn, mx, n = rng[i]
            put(max(0, min(top, int(round((comps[i][k] - mn) / (mx - mn) * top)))), n)
        if has_rot:
            put(1 if frames[k][1][3] < 0 else 0, 1)
    out = struct.pack('<HHHHII', 4, flag_word, head_len, width, bit_off, len(frames))
    for mn, mx, n in rng:
        out += struct.pack('<ffQ', mn, mx, n)
    out += const_bytes(*first)
    return F_PACKED, len(frames), out + bytes(stream)


def _close(a, b, eps=1e-6):
    return all(abs(x - y) < eps for pa, pb in zip(a, b) for x, y in zip(pa, pb))


def quat_from_euler_deg(r):
    """Euler degrees, X applied first, then Y, then Z -> quaternion (x, y, z, w)."""
    hx, hy, hz = (math.radians(a) / 2 for a in r)
    cx, sx, cy, sy, cz, sz = math.cos(hx), math.sin(hx), math.cos(hy), math.sin(hy), math.cos(hz), math.sin(hz)
    return (sx * cy * cz - cx * sy * sz, cx * sy * cz + sx * cy * sz, cx * cy * sz - sx * sy * cz,
            cx * cy * cz + sx * sy * sz)
