"""N11: recolour a fighter folder's OWN texture files in place, so that a new fighter is visibly not its donor
(plan\\phases\\N11_visible_fighter.md). No game content in this file; what it rewrites stays in the work folder.

    python tests\\n11_tint.py <model folder> <rb|gb|rg> [name filter, default _col]

Every <name>.nutexb in the folder whose name contains the filter and whose pixel format is the 16-byte-block format
with mode bits (format byte 0xe0..0xe5 in the texture footer) gets two colour channels exchanged: block by block, the
two channels' end-point bit fields are swapped (and the block's channel-rotation field where it names one of the two).
Nothing is decoded or re-encoded, so the picture keeps its exact detail; the block order in the file (whatever it is)
does not matter because every block is handled by itself. Other formats: reported, not touched.
Prints per file: blocks changed per mode, crc32 before / after.
"""
import os
import sys
import zlib

# per mode: (first colour bit, bits per channel field, rotation bit offset or -1)
MODES = {0: (5, 24, -1), 1: (8, 24, -1), 2: (9, 30, -1), 3: (10, 28, -1), 4: (8, 10, 5), 5: (8, 14, 6), 6: (7, 14, -1), 7: (14, 20, -1)}
PAIR = {'rb': (0, 2), 'gb': (1, 2), 'rg': (0, 1)}


def swap_block(v, a, b):
    low = v & 0xff
    if low == 0:
        return v, -1
    mode = (low & -low).bit_length() - 1
    start, width, rot_at = MODES[mode]
    mask = (1 << width) - 1
    fa = (v >> (start + a * width)) & mask
    fb = (v >> (start + b * width)) & mask
    v &= ~((mask << (start + a * width)) | (mask << (start + b * width)))
    v |= (fb << (start + a * width)) | (fa << (start + b * width))
    if rot_at >= 0:
        rot = (v >> rot_at) & 3              # 1 / 2 / 3: the alpha field holds channel 0 / 1 / 2
        if rot == a + 1 or rot == b + 1:
            new = (b + 1) if rot == a + 1 else (a + 1)
            v = (v & ~(3 << rot_at)) | (new << rot_at)
    return v, mode


def main():
    folder, pair = sys.argv[1], PAIR[sys.argv[2]]
    filt = sys.argv[3] if len(sys.argv) > 3 else '_col'
    done = 0
    for fn in sorted(os.listdir(folder)):
        if not fn.endswith('.nutexb') or filt not in fn:
            continue
        p = os.path.join(folder, fn)
        data = bytearray(open(p, 'rb').read())
        foot = len(data) - 0xb0
        if foot <= 0 or data[foot + 0x40:foot + 0x44] != b' XNT':
            print('%s: no texture footer where expected: not touched' % fn)
            continue
        fmt = data[foot + 0x90]
        if fmt & 0xf0 != 0xe0:
            print('%s: pixel format 0x%02x is not the block format this tool handles: not touched' % (fn, fmt))
            continue
        before = zlib.crc32(data)
        count = [0] * 8
        for o in range(0, foot - 15, 16):
            v = int.from_bytes(data[o:o + 16], 'little')
            nv, mode = swap_block(v, pair[0], pair[1])
            if mode >= 0:
                count[mode] += 1
                if nv != v:
                    data[o:o + 16] = nv.to_bytes(16, 'little')
        open(p, 'wb').write(data)
        done += 1
        print('%s: format 0x%02x, %d bytes, blocks per mode %s, crc32 %08x -> %08x' % (fn, fmt, len(data), count, before, zlib.crc32(data)))
    print('%d texture file(s) rewritten in %s (channels %s exchanged)' % (done, folder, sys.argv[2]))


if __name__ == '__main__':
    main()
