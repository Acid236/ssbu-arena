"""data.arcp.extra: every language / region version of the region-dependent files that a light archive (data.arcp) holds
in only some versions. The light archive keeps what the coverage runs read, and those ran with one system language: on
a PC with another language the game reads another version of the same files (ui messages, ...), finds zeros and stays
on a black screen. runtime/arcpack.c reads data.arcp.extra next to data.arcp where data.arcp has nothing.

    python tools/competitive/pack_regions.py [--arc <data.arc>] [--arcp <data.arcp>] [--out <data.arcp.extra>] [--dry]

A small file to copy next to a light archive already installed (no need to copy data.arcp again). No game content in
this file; the output is your own game data and stays on your PC.
"""
import argparse
import bisect
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'nro'))


def load_arcp(path):
    with open(path, 'rb') as f:
        hd = f.read(24)
        assert hd[:8] == b'SSBUARCP', 'not a light archive'
        size, n = struct.unpack_from('<QQ', hd, 8)
        tab = f.read(24 * n)
    r = sorted(struct.unpack_from('<QQ', tab, 24 * i) for i in range(n))
    return size, r


def main():
    root = os.path.normpath(os.path.join(HERE, '..', '..'))
    ap = argparse.ArgumentParser()
    ap.add_argument('--arc'); ap.add_argument('--arcp'); ap.add_argument('--out'); ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()
    arc = a.arc or os.path.join(json.load(open(os.path.join(root, 'build', 'state.json')))['dump']['romfs'], 'data.arc')
    arcp = a.arcp or os.path.join(os.path.dirname(os.path.dirname(arc)), 'romfs_light', 'data.arcp')
    out = a.out or arcp + '.extra'
    os.environ['SSBU_ARC'] = arc
    import arc_extract as ax
    A = ax.Arc(arc); t = A.t
    size, kept = load_arcp(arcp)
    assert size == os.path.getsize(arc), 'data.arcp was not made from this data.arc'
    starts = [k[0] for k in kept]

    def is_kept(o, n):
        i = bisect.bisect_right(starts, o) - 1
        return i >= 0 and kept[i][0] <= o and o + n <= kept[i][0] + kept[i][1]

    want, files, versions = [], 0, 0
    for k in range(A.n_info):
        fp_i, fii_i, i2d_i, flags = struct.unpack_from('<4I', t, A.o_info + k * 16)
        if not (flags >> 15) & 3:
            continue                                         # not a region-dependent file
        vs = []
        for reg in range(15):
            if i2d_i + reg >= A.n_i2d:
                break
            fo_i, fd_i, bits = struct.unpack_from('<3I', t, A.o_i2d + (i2d_i + reg) * 12)
            if fo_i >= A.n_folder_offsets or fd_i >= A.n_datas:
                continue
            off, = struct.unpack_from('<Q', t, A.o_folder_off + fo_i * 28)
            doff, csz, dsz, dfl = struct.unpack_from('<4I', t, A.o_data + fd_i * 16)
            if csz:
                vs.append((A.file_off + off + doff * 4, csz))
        if not any(is_kept(o, n) for o, n in vs):
            continue                                         # the light archive has no version of it: not needed
        add = [(o, n) for o, n in vs if not is_kept(o, n)]
        if add:
            files += 1; versions += len(add); want += add
    want.sort()
    merged = []
    for o, n in want:
        if merged and o <= merged[-1][0] + merged[-1][1] + 4096:      # the padding between files too (a whole-file read spans it)
            e = max(merged[-1][0] + merged[-1][1], o + n); merged[-1] = (merged[-1][0], e - merged[-1][0])
        else:
            merged.append((o, n))
    total = sum(n for _, n in merged)
    print('%d region-dependent files with a version in data.arcp: %d other versions, %d ranges, %.1f MB -> %s' % (files, versions, len(merged), total / 1048576.0, out))
    if a.dry:
        return
    hdr = 24 + 24 * len(merged)
    at = hdr
    table = []
    for o, n in merged:
        table.append((o, n, at)); at += n
    with open(arc, 'rb') as src, open(out + '.tmp', 'wb') as dst:
        dst.write(b'SSBUARCP' + struct.pack('<QQ', size, len(merged)))
        for o, n, p in table:
            dst.write(struct.pack('<QQQ', o, n, p))
        for o, n, p in table:
            src.seek(o); dst.write(src.read(n))
    os.replace(out + '.tmp', out)
    print('done: %s (%.1f MB)' % (out, os.path.getsize(out) / 1048576.0))


if __name__ == '__main__':
    main()
