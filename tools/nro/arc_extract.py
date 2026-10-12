#!/usr/bin/env python3
"""data.arc reader for SSBU (layout taken from reference/smash-arc, src/filesystem.rs
and src/lookups.rs).  Read-only on the archive.

  python arc_extract.py info
  python arc_extract.py list <ext>                 # every file with that extension (hash, sizes)
  python arc_extract.py get <path-or-0xhash> <out> # extract one file (zstd-decompressed)
  python arc_extract.py nro <outdir>               # extract every .nro, named from its own module name

Paths are hashed with hash40 = crc32(lowercase path) | len << 32.
"""
import os, struct, sys, zlib, json

HERE = os.path.dirname(os.path.abspath(__file__))
ARC = os.environ.get('SSBU_ARC') or os.path.normpath(os.path.join(HERE, '..', '..', 'romfs', 'data.arc'))

def hash40(s):
    b = s.lower().encode() if isinstance(s, str) else s
    return (len(b) << 32) | (zlib.crc32(b) & 0xffffffff)

def h2i(q):
    """HashToIndex: u32 crc, u8 length, 24-bit index -> (hash40, index)."""
    return q & 0xffffffffff, q >> 40

class Arc:
    def __init__(self, path=ARC):
        import zstandard
        self.path = path
        self.f = open(path, 'rb')
        hdr = self.f.read(0x38)
        (magic, self.stream_off, self.file_off, self.shared_off,
         self.fs_off, self.search_off, _) = struct.unpack('<7Q', hdr)
        assert magic == 0xABCDEF9876543210, hex(magic)
        self.f.seek(self.fs_off)
        m, self.fs_decomp, self.fs_comp, self.fs_section = struct.unpack('<4I', self.f.read(16))
        assert m == 0x10, hex(m)
        comp = self.f.read(self.fs_comp)
        self.t = t = zstandard.ZstdDecompressor().decompress(comp, max_output_size=self.fs_decomp)
        assert len(t) == self.fs_decomp
        H = struct.unpack_from('<14I2BH7I', t, 0)
        (self.table_filesize, self.n_path, self.n_info_index, self.n_folder, self.n_folder_off1,
         self.n_hash_folder, self.n_info, self.n_sub_index, self.n_data, self.n_folder_off2,
         self.n_data2, _pad, _u1, _u2, self.reg1, self.reg2, _p2, self.version, self.extra_folder,
         self.extra_count, _unk0, _unk1, self.extra_count2, self.extra_sub_count) = H
        p = 0x100
        qd, sh, sfi, soe = struct.unpack_from('<4I', t, p); p += 16
        self.n_stream = sh
        p += qd * 12
        p += sh * 8          # stream_hash_to_entries
        p += sh * 12         # stream_entries
        p += sfi * 4
        p += soe * 16
        self.n_hash_group, self.n_bucket = struct.unpack_from('<2I', t, p); p += 8
        self.o_bucket = p; p += self.n_bucket * 8
        self.o_hash2path = p; p += self.n_hash_group * 8
        self.o_path = p; p += self.n_path * 32
        self.o_info_index = p; p += self.n_info_index * 8
        self.o_dirhash = p; p += self.n_folder * 8
        self.o_dirinfo = p; p += self.n_folder * 52
        self.n_folder_offsets = self.n_folder_off1 + self.n_folder_off2 + self.extra_folder
        self.o_folder_off = p; p += self.n_folder_offsets * 28
        self.o_child = p; p += self.n_hash_folder * 8
        self.n_infos = self.n_info + self.n_data2 + self.extra_count
        self.o_info = p; p += self.n_infos * 16
        self.n_i2d = self.n_sub_index + self.n_data2 + self.extra_count2
        self.o_i2d = p; p += self.n_i2d * 12
        self.n_datas = self.n_data + self.n_data2 + self.extra_sub_count
        self.o_data = p; p += self.n_datas * 16
        self.end = p
        self.zd = zstandard.ZstdDecompressor()

    # -- table accessors -------------------------------------------------
    def file_path(self, i):
        a, b, c, d = struct.unpack_from('<4Q', self.t, self.o_path + i * 32)
        return h2i(a), h2i(b), h2i(c), h2i(d)   # path, ext, parent, file_name

    def path_index_from_hash(self, h):
        start, count = struct.unpack_from('<2I', self.t, self.o_bucket + (h % self.n_bucket) * 8)
        lo, hi = 0, count
        while lo < hi:
            mid = (lo + hi) // 2
            hh, idx = h2i(struct.unpack_from('<Q', self.t, self.o_hash2path + (start + mid) * 8)[0])
            if hh == h: return idx
            if hh < h: lo = mid + 1
            else: hi = mid
        return None

    def file_record(self, path_index, region=0):
        (ph, pidx), _, _, _ = self.file_path(path_index)
        _dir_off, info_idx = struct.unpack_from('<2I', self.t, self.o_info_index + pidx * 8)
        fp_i, fii_i, i2d_i, flags = struct.unpack_from('<4I', self.t, self.o_info + info_idx * 16)
        regional = (flags >> 15) & 1; localized = (flags >> 16) & 1
        if regional or localized: i2d_i += region
        fo_i, fd_i, bits = struct.unpack_from('<3I', self.t, self.o_i2d + i2d_i * 12)
        folder_offset, = struct.unpack_from('<Q', self.t, self.o_folder_off + fo_i * 28)
        off_in_folder, comp, decomp, dflags = struct.unpack_from('<4I', self.t, self.o_data + fd_i * 16)
        return dict(hash=ph, info_index=info_idx, info_flags=flags, folder_offset_index=fo_i,
                    file_data_index=fd_i, load_type=bits >> 24,
                    offset=self.file_off + folder_offset + (off_in_folder << 2),
                    comp_size=comp, decomp_size=decomp, data_flags=dflags)

    def read(self, rec):
        self.f.seek(rec['offset'])
        raw = self.f.read(rec['comp_size'])
        fl = rec['data_flags']
        if fl & 1:
            if not fl & 2: raise ValueError('compressed but not zstd')
            out = self.zd.decompress(raw, max_output_size=rec['decomp_size'])
        else:
            out = raw
        if len(out) != rec['decomp_size']:
            raise ValueError('size mismatch %d != %d' % (len(out), rec['decomp_size']))
        return out

    def get(self, key, region=0):
        h = key if isinstance(key, int) else hash40(key)
        pi = self.path_index_from_hash(h)
        if pi is None: raise KeyError(hex(h))
        return self.read(self.file_record(pi, region))

    def list_ext(self, ext):
        eh = hash40(ext)
        out = []
        for i in range(self.n_path):
            (ph, _), (xh, _), (parent, _), (name, _) = self.file_path(i)
            if xh == eh:
                r = self.file_record(i); r['parent'] = parent; r['name'] = name; r['path_index'] = i
                out.append(r)
        return out

def nro_module_name(d):
    """The module path the linker stored at the start of .rodata: u32 0, u32 len, chars."""
    if d[0x10:0x14] != b'NRO0': return None
    ro_off, = struct.unpack_from('<I', d, 0x28)
    z, n = struct.unpack_from('<2I', d, ro_off)
    if z == 0 and 0 < n < 0x200:
        s = d[ro_off + 8: ro_off + 8 + n].decode('ascii', 'replace')
        return s
    return None

def main():
    if len(sys.argv) < 2: print(__doc__); return
    cmd = sys.argv[1]
    arc = Arc()
    if cmd == 'info':
        print('arc', arc.path)
        print('stream/file/shared section offsets: %#x %#x %#x' % (arc.stream_off, arc.file_off, arc.shared_off))
        print('fs table at %#x: comp %#x decomp %#x (parsed up to %#x)' % (arc.fs_off, arc.fs_comp, arc.fs_decomp, arc.end))
        print('version %#x  file paths %d  file infos %d  file datas %d  dirs %d  folder offsets %d  streams %d' % (
            arc.version, arc.n_path, arc.n_infos, arc.n_datas, arc.n_folder, arc.n_folder_offsets, arc.n_stream))
    elif cmd == 'list':
        rs = arc.list_ext(sys.argv[2])
        for r in rs:
            print('%#012x parent %#012x name %#012x comp %9d decomp %9d flags %#x off %#x' % (
                r['hash'], r['parent'], r['name'], r['comp_size'], r['decomp_size'], r['data_flags'], r['offset']))
        print('%d files, %d bytes compressed, %d bytes decompressed' % (
            len(rs), sum(r['comp_size'] for r in rs), sum(r['decomp_size'] for r in rs)))
    elif cmd == 'get':
        key = sys.argv[2]
        key = int(key, 16) if key.startswith('0x') else key
        d = arc.get(key)
        open(sys.argv[3], 'wb').write(d)
        print('wrote', sys.argv[3], len(d))
    elif cmd == 'nro':
        outdir = sys.argv[2]
        os.makedirs(outdir, exist_ok=True)
        index = []
        seen = {}
        for r in arc.list_ext('nro'):
            d = arc.read(r)
            mod = nro_module_name(d) or ''
            base = os.path.splitext(mod.replace('\\', '/').split('/')[-1])[0] or ('%010x' % r['hash'])
            # verify the guessed archive path against the stored hashes
            guess = None
            for cand in ('prebuilt:/nro/release/%s.nro' % base,):
                if hash40(cand) == r['hash']: guess = cand
            name_ok = hash40(base + '.nro') == r['name']
            fn = base + '.nro'
            if fn in seen: fn = '%s_%010x.nro' % (base, r['hash'])
            seen[fn] = 1
            open(os.path.join(outdir, fn), 'wb').write(d)
            index.append(dict(file=fn, hash='%#012x' % r['hash'], parent='%#012x' % r['parent'],
                              module_name=mod, arc_path=guess, file_name_hash_ok=name_ok,
                              comp_size=r['comp_size'], size=r['decomp_size'], arc_offset=r['offset'],
                              file_data_index=r['file_data_index']))
        json.dump(index, open(os.path.join(outdir, 'index.json'), 'w'), indent=1)
        print('%d nro files, %d bytes; arc path verified for %d, file-name hash verified for %d' % (
            len(index), sum(i['size'] for i in index), sum(1 for i in index if i['arc_path']),
            sum(1 for i in index if i['file_name_hash_ok'])))
    else:
        print(__doc__)

if __name__ == '__main__':
    main()
