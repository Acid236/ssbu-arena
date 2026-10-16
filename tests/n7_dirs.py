"""N7: print the directory ("load group") rows of the archive for given directory paths (read-only, offline).
    python tests\\n7_dirs.py fighter/<name>/c00 [more paths ...]
Per directory: its row, its directory-offset row(s), the file-info range, and how the files of the range are spread
over directory-offset rows (the info-to-data row of each file names one). No game content is written anywhere."""
import collections
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'ro_study'))
import arc_extract as ax  # noqa: E402


def main():
    a = ax.Arc()
    t = a.t
    dirhash = [struct.unpack_from('<Q', t, a.o_dirhash + 8 * i)[0] for i in range(a.n_folder)]
    lut = {q & 0xffffffffff: q >> 40 for q in dirhash}
    print('folders %d, folder offsets %d + %d + %d, child hashes %d, file infos %d + %d + %d'
          % (a.n_folder, a.n_folder_off1, a.n_folder_off2, a.extra_folder, a.n_hash_folder, a.n_info, a.n_data2, a.extra_count))

    def diroff(i):
        return struct.unpack_from('<QIIIII', t, a.o_folder_off + 28 * i)

    def show(path, depth=0):
        h = ax.hash40(path) if not path.startswith('0x') else int(path, 16)
        ind = '  ' * depth
        if h not in lut:
            print('%s%s (%x): NOT a directory row' % (ind, path, h))
            return
        di = lut[h]
        (pq, name, parent, ex, exl, fstart, fcount, cstart, ccount, flags) = struct.unpack_from('<QQQIIIIIII', t, a.o_dirinfo + 52 * di)
        print('%s%s (%x): dir row %d: offset index %d, name %x, parent %x, extra %x/%x, file infos %d..+%d, children %d..+%d, flags %08x'
              % (ind, path, h, di, pq >> 40, name & 0xffffffffff, parent & 0xffffffffff, ex, exl, fstart, fcount, cstart, ccount, flags))
        oi = pq >> 40
        seen = 0
        while oi != 0xffffff and oi < a.n_folder_offsets and seen < 3:
            off, dsz, sz, fs, fc, di2 = diroff(oi)
            print('%s  directory offset %d: offset %x, decomp %d, size %d, file start %d, count %d, directory index %x' % (ind, oi, off, dsz, sz, fs, fc, di2))
            if not (flags & 0x04000000) or (flags & 0x10000000):
                break
            oi = di2
            seen += 1
        spread = collections.Counter()
        own = 0
        for k in range(fcount):
            fp_i, fii_i, i2d_i, fl = struct.unpack_from('<4I', t, a.o_info + 16 * (fstart + k))
            fo_i, fd_i, bits = struct.unpack_from('<3I', t, a.o_i2d + 12 * i2d_i)
            spread[(fo_i, fl & 0xfff00000, bits >> 24)] += 1
            # is this file info the one its path's indice row points to?
            (ph, pidx), _, _, _ = a.file_path(fp_i)
            _d, info_idx = struct.unpack_from('<2I', t, a.o_info_index + pidx * 8)
            if (info_idx & 0xffffff) == fstart + k:
                own += 1
        print('%s  files by (directory offset, info flags top bits, load type): %s; %d of %d are the file info their indice row names'
              % (ind, dict(spread), own, fcount))
        for k in range(min(ccount, 12)):
            q = struct.unpack_from('<Q', t, a.o_child + 8 * (cstart + k))[0]
            show('0x%x' % (q & 0xffffffffff), depth + 1)

    for p in sys.argv[1:]:
        show(p)


if __name__ == '__main__':
    main()
