"""Extract the RomFS of a Switch title with an update applied.

    python romfs_extract.py <base.nsp|.nsz|.xci|.nca> <update.nsp|.nsz|.xci|.nca> <output_dir> [--list]

Reads the Program NCA of both packages straight from the NSP or XCI files, applies
the update's relocation table (BKTR) over the base RomFS and writes the
resulting files. Keys come from ~/.switch/prod.keys (or SSBU_PROD_KEYS, or an emulator's key folder); title keys from the
tickets inside the packages (a loose .nca: title.keys). .nsz is decompressed first (see decompress_nsz).
"""
import bisect
import os
import struct
import sys
import time

from Crypto.Cipher import AES

def _key_files(name):
    """Where a keys file may be, first match wins: SSBU_PROD_KEYS / SSBU_TITLE_KEYS (a file), ~/.switch, then the key folders of
    the emulators (yuzu family, Ryujinx). scripts/find_inputs.py reports the same places."""
    env = os.environ.get('SSBU_PROD_KEYS' if name == 'prod.keys' else 'SSBU_TITLE_KEYS')
    if env:
        yield env
    yield os.path.join(os.path.expanduser('~'), '.switch', name)
    ad = os.environ.get('APPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Roaming')
    for emu in ('eden', 'Eden', 'yuzu', 'suyu', 'sudachi', 'citron', 'torzu', 'sumi', 'lime'):
        yield os.path.join(ad, emu, 'keys', name)
    yield os.path.join(ad, 'Ryujinx', 'system', name)


def load_keys(name='prod.keys'):
    """-> (dict key name -> bytes, path of the file used or None). Lines that are not NAME=HEX are ignored."""
    for path in _key_files(name):
        if os.path.isfile(path):
            out = {}
            for line in open(path, errors='replace'):
                if '=' in line:
                    k, v = line.split('=', 1)
                    try:
                        out[k.strip().lower()] = bytes.fromhex(v.strip())
                    except ValueError:
                        pass
            return out, path
    return {}, None


KEYS, KEYS_PATH = load_keys('prod.keys')
TITLE_KEYS, _ = load_keys('title.keys')           # rights id (32 hex) -> encrypted title key, as in a ticket


def need_keys():
    if 'header_key' not in KEYS:
        raise SystemExit("prod.keys not found (looked in ~/.switch, the emulators' key folders, SSBU_PROD_KEYS): "
                         'dump it from your own console, see BUILDING.md')


def xts_decrypt(key, data, sector, sector_size=0x200):
    k1, k2 = AES.new(key[:16], AES.MODE_ECB), AES.new(key[16:], AES.MODE_ECB)
    out = bytearray()
    for s in range(len(data) // sector_size):
        tweak = int.from_bytes(k2.encrypt((sector + s).to_bytes(16, 'big')), 'little')
        for b in range(0, sector_size, 16):
            block = data[s * sector_size + b:s * sector_size + b + 16]
            t = tweak.to_bytes(16, 'little')
            out += bytes(x ^ y for x, y in zip(k1.decrypt(bytes(x ^ y for x, y in zip(block, t))), t))
            tweak <<= 1
            if tweak >> 128:
                tweak = (tweak & ((1 << 128) - 1)) ^ 0x87
    return bytes(out)


def not_a_package(path, head):
    """2026-10-21 (a tester's install: 'assert magic == PFS0'): what the file is instead of an .nsp, in words."""
    size = os.path.getsize(path) if os.path.exists(path) else 0
    kinds = ((b'PK\x03\x04', 'a ZIP archive'), (b'Rar!', 'a RAR archive'), (b'7z\xbc\xaf', 'a 7-Zip archive'), (b'\x1f\x8b', 'a GZIP archive'))
    what = next((k for m, k in kinds if head.startswith(m)), None)
    if what:
        why = 'it is %s renamed .nsp: extract it first and choose the .nsp / .xci inside' % what
    elif not head.strip(b'\x00'):
        why = 'it starts with zeros: the download is incomplete or the file is damaged; download it again'
    elif size < 64 << 20:
        why = 'it is only %.1f MB: not a game package (the base game is several GB); download it again' % (size / 1048576.0)
    else:
        why = 'it is not an NSP or XCI package (it starts with %s): download it again, or use another copy of the game' % head[:4].hex(' ')
    return '%s: this file cannot be read as the game: %s.' % (path, why)


class Nsp:
    def __init__(self, path):
        self.f = open(path, 'rb')
        head = self.f.read(16)
        if len(head) < 16 or head[:4] != b'PFS0':
            raise SystemExit(not_a_package(path, head))
        magic, count, strings_size, _ = struct.unpack('<4sIII', head)
        entries = [struct.unpack('<QQII', self.f.read(24)) for _ in range(count)]
        strings = self.f.read(strings_size)
        base = 16 + 24 * count + strings_size
        self.files = {}
        for off, size, name_off, _ in entries:
            name = strings[name_off:strings.index(b'\0', name_off)].decode()
            self.files[name] = (base + off, size)

    def read(self, name, offset, size):
        base, _ = self.files[name]
        self.f.seek(base + offset)
        return self.f.read(size)

    def program_nca(self):
        return max((n for n in self.files if n.endswith('.nca')), key=lambda n: self.files[n][1])

    def ticket(self):
        for n in self.files:
            if n.endswith('.tik'):
                return self.read(n, 0, self.files[n][1])
        return None


def hfs0_files(f, off):
    """Entries of the HFS0 partition at `off`: name -> (absolute offset, size). (PR #38, Acid236: .xci packages)"""
    f.seek(off)
    magic, count, strings_size, _ = struct.unpack('<4sIII', f.read(16))
    assert magic == b'HFS0', 'HFS0 partition not found at %#x' % off
    entries = [struct.unpack('<QQII8x32s', f.read(0x40)) for _ in range(count)]
    strings = f.read(strings_size)
    base = off + 16 + 0x40 * count + strings_size
    return {strings[n:strings.index(b'\0', n)].decode(): (base + o, s) for o, s, n, _, _ in entries}


class Xci(Nsp):
    """A cartridge image: header 'HEAD' at 0x100, the root HFS0 at the offset stored at 0x130; the game's NCAs are in its
    'secure' partition. Cartridge NCAs use the key area (no rights id), so no ticket is needed."""

    def __init__(self, path):
        self.f = open(path, 'rb')
        self.f.seek(0x100)
        assert self.f.read(4) == b'HEAD', '%s is not an XCI' % path
        self.f.seek(0x130)
        root = hfs0_files(self.f, struct.unpack('<Q', self.f.read(8))[0])
        assert 'secure' in root, 'the XCI has no secure partition'
        self.files = hfs0_files(self.f, root['secure'][0])

    def ticket(self):
        return None


class LooseNcaPackage(Nsp):
    """A single .nca file (the Program NCA of a title) used as a package of one entry. No ticket inside: a Program NCA that
    needs a title key takes it from title.keys."""

    def __init__(self, path):
        self.f = open(path, 'rb')
        self.files = {os.path.basename(path): (0, os.path.getsize(path))}

    def ticket(self):
        return None


def nsz_cache_dir():
    d = os.environ.get('SSBU_TMP') or os.path.join(os.environ.get('TEMP') or os.path.expanduser('~'), 'ssbu_nsz_cache')
    os.makedirs(d, exist_ok=True)
    return d


def decompress_nsz(path):
    r""".nsz -> a plain .nsp in the cache folder (SSBU_TMP, default %TEMP%\ssbu_nsz_cache), reused when it is already there.
    Needs: pip install zstandard pycryptodome. The .nsp is about as big as the original game file (the base is 13+ GB)."""
    st = os.stat(path)
    out = os.path.join(nsz_cache_dir(), '%s_%d_%d.nsp' % (os.path.splitext(os.path.basename(path))[0][:60].replace(' ', '_'),
                                                         st.st_size, int(st.st_mtime)))
    if os.path.isfile(out) and os.path.getsize(out) > 0:
        return out
    try:
        import nsz_to_nsp
    except ImportError as e:
        raise SystemExit('%s is compressed (.nsz): decompressing it needs  pip install zstandard pycryptodome  (%s)' % (path, e))
    print('decompressing %s -> %s (about the size of the original game file; SSBU_TMP changes the folder)' % (path, out))
    tmp = out + '.part'
    sys.argv, saved = ['nsz_to_nsp.py', path, tmp], sys.argv
    try:
        nsz_to_nsp.main()
    finally:
        sys.argv = saved
    os.replace(tmp, out)
    return out


def open_package(path):
    """A title package: .xci (cartridge image), .nsp, .nsz (decompressed to a cache .nsp first), or a loose .nca."""
    ext = os.path.splitext(path)[1].lower()
    if ext == '.xcz':
        raise SystemExit('%s: .xcz (compressed cartridge) is not supported; decompress it to .xci or use the .nsp/.nsz' % path)
    if ext == '.nsz':
        path = decompress_nsz(path)
    elif ext == '.nca':
        return LooseNcaPackage(path)
    with open(path, 'rb') as f:
        f.seek(0x100)
        is_xci = f.read(4) == b'HEAD'
    return Xci(path) if is_xci else Nsp(path)


class Nca:
    def __init__(self, nsp):
        need_keys()
        self.nsp, self.name = nsp, nsp.program_nca()
        if getattr(nsp, 'files', None) and 'program_nca' not in vars(nsp):
            # 2026-10-20: the largest NCA is not always the Program one (some dump tools add big delta fragments to an
            # update package): take the largest NCA whose header says content type 0 (Program)
            for n in sorted((n for n in nsp.files if n.endswith('.nca')), key=lambda n: -nsp.files[n][1]):
                hh = xts_decrypt(KEYS['header_key'], nsp.read(n, 0, 0xC00), 0)
                if hh[0x200:0x204] == b'NCA3' and hh[0x205] == 0:
                    self.name = n
                    break
        h = xts_decrypt(KEYS['header_key'], nsp.read(self.name, 0, 0xC00), 0)
        assert h[0x200:0x204] == b'NCA3'
        self.header = h
        gen = max(max(h[0x206], h[0x220]) - 1, 0)
        rights = h[0x230:0x240]
        if any(rights):
            tik = nsp.ticket()
            if tik and tik[0x2A0:0x2B0] == rights:
                tkey = tik[0x180:0x190]
            else:                                         # no ticket in the package (a loose .nca): title.keys
                tkey = TITLE_KEYS.get(rights.hex())
            assert tkey, 'ticket / title key for this NCA (rights id %s) not found' % rights.hex()
            self.key = AES.new(KEYS['titlekek_%02x' % gen], AES.MODE_ECB).decrypt(tkey)
        else:
            area = AES.new(KEYS['key_area_key_application_%02x' % gen], AES.MODE_ECB).decrypt(h[0x300:0x340])
            self.key = area[0x20:0x30]
        self.sections = []
        for i in range(4):
            start, end = struct.unpack('<II', h[0x240 + i * 16:0x248 + i * 16])
            if end:
                fs = h[0x400 + i * 0x200:0x600 + i * 0x200]
                self.sections.append({'index': i, 'offset': start * 0x200, 'size': (end - start) * 0x200,
                                      'fs': fs, 'type': fs[2], 'crypto': fs[4], 'ctr': fs[0x140:0x148][::-1]})

    def section(self, fs_type):
        return next(s for s in self.sections if s['type'] == fs_type)

    def read(self, sec, offset, size, ctr_val=None):
        """Decrypted read of `size` bytes at section-relative `offset`."""
        if size <= 0:
            return b''
        absolute = sec['offset'] + offset
        aligned = absolute & ~0xF
        data = self.nsp.read(self.name, aligned, ((absolute - aligned + size + 15) & ~0xF))
        upper = sec['ctr'] if ctr_val is None else sec['ctr'][:4] + struct.pack('>I', ctr_val)
        counter = int.from_bytes(upper + struct.pack('>Q', aligned >> 4), 'big')
        plain = AES.new(self.key, AES.MODE_CTR, nonce=b'', initial_value=counter).decrypt(data)
        return plain[absolute - aligned:absolute - aligned + size]


class PatchedRomfs:
    """Virtual RomFS section: update (BKTR) over base."""

    def __init__(self, base, update):
        self.base, self.update = base, update
        self.bsec = base.section(0)
        self.usec = update.section(0)
        if self.usec['crypto'] != 4:
            t = lambda n: struct.unpack('<Q', n.header[0x210:0x218])[0]
            raise SystemExit('the file given as the update is not an update of the game (its program NCA %s, title %016x, has '
                             'no patch RomFS): choose the update package (its name usually has [01006A800016E800] and a '
                             'version such as v1966080 = 13.0.4 or v2031616 = 13.0.5) as "Update" and the game itself '
                             '([01006A800016E000][v0]) as "Base game"' % (update.name, t(update)))
        fs = self.usec['fs']
        assert fs[0x8:0xC] == b'IVFC'
        self.level6 = struct.unpack('<Q', fs[0x8 + 0x10 + 5 * 0x18:0x8 + 0x18 + 5 * 0x18])[0]
        r_off, r_size, r_magic = struct.unpack('<QQ4s', fs[0x100:0x114])
        s_off, s_size, s_magic = struct.unpack('<QQ4s', fs[0x120:0x134])
        assert r_magic == b'BKTR' and s_magic == b'BKTR'
        reloc = update.read(self.usec, r_off, r_size)
        subs = update.read(self.usec, s_off, s_size)
        self.total = struct.unpack('<Q', reloc[8:16])[0]
        self.rel = []                                    # (virtual offset, physical offset, is_patch)
        for b in range(struct.unpack('<I', reloc[4:8])[0]):
            bucket = reloc[0x4000 * (b + 1):0x4000 * (b + 2)]
            for e in range(struct.unpack('<I', bucket[4:8])[0]):
                self.rel.append(struct.unpack('<QQI', bucket[0x10 + e * 0x14:0x24 + e * 0x14]))
        self.rel_keys = [r[0] for r in self.rel]
        self.sub = []                                    # (physical offset, counter value)
        for b in range(struct.unpack('<I', subs[4:8])[0]):
            bucket = subs[0x4000 * (b + 1):0x4000 * (b + 2)]
            for e in range(struct.unpack('<I', bucket[4:8])[0]):
                off, _, ctr = struct.unpack('<QII', bucket[0x10 + e * 0x10:0x20 + e * 0x10])
                self.sub.append((off, ctr))
        self.sub.append((r_off, None))                   # the tables themselves use the header counter
        self.sub_keys = [s[0] for s in self.sub]
        print('virtual RomFS section: %.2f GB, %d relocation entries, %d subsections'
              % (self.total / 2 ** 30, len(self.rel), len(self.sub)))

    def _read_patch(self, offset, size):
        out = []
        while size > 0:
            i = bisect.bisect_right(self.sub_keys, offset) - 1
            end = self.sub_keys[i + 1] if i + 1 < len(self.sub_keys) else offset + size
            n = min(size, end - offset)
            out.append(self.update.read(self.usec, offset, n, self.sub[i][1]))
            offset += n
            size -= n
        return b''.join(out)

    def read(self, offset, size):
        out = []
        while size > 0:
            i = bisect.bisect_right(self.rel_keys, offset) - 1
            virt, phys, patch = self.rel[i]
            end = self.rel_keys[i + 1] if i + 1 < len(self.rel) else self.total
            n = min(size, end - offset)
            if patch:
                out.append(self._read_patch(phys + offset - virt, n))
            else:
                out.append(self.base.read(self.bsec, phys + offset - virt, n))
            offset += n
            size -= n
        return b''.join(out)


def walk(romfs, base):
    """Yield (path, data offset, size) for every file of the RomFS image at `base`."""
    hdr = struct.unpack('<10Q', romfs.read(base, 0x50))
    assert hdr[0] == 0x50, 'RomFS header not found: wrong keys or wrong base/update pair'
    dir_off, dir_size, file_off, file_size, data_off = hdr[3], hdr[4], hdr[7], hdr[8], hdr[9]
    dirs = romfs.read(base + dir_off, dir_size)
    files = romfs.read(base + file_off, file_size)
    stack = [(0, '')]
    while stack:
        d, path = stack.pop()
        _, sibling, child, first_file, _, name_len = struct.unpack('<6I', dirs[d:d + 24])
        name = dirs[d + 24:d + 24 + name_len].decode('utf8')
        here = path + '/' + name if name else path
        if sibling != 0xFFFFFFFF:
            stack.append((sibling, path))
        if child != 0xFFFFFFFF:
            stack.append((child, here))
        f = first_file
        while f != 0xFFFFFFFF:
            _, next_file, off, size, _, name_len = struct.unpack('<IIQQII', files[f:f + 32])
            fname = files[f + 32:f + 32 + name_len].decode('utf8')
            yield here + '/' + fname, base + data_off + off, size
            f = next_file


def main():
    base_path, update_path, out_dir = sys.argv[1:4]
    extract(Nca(open_package(base_path)), Nca(open_package(update_path)), out_dir, '--list' in sys.argv)


def extract(base, update, out_dir, list_only=False):
    """Write the RomFS of `base` (Nca) with `update` (Nca) applied into out_dir (dump_folder.py uses it too)."""
    romfs = PatchedRomfs(base, update)
    entries = sorted(walk(romfs, romfs.level6))
    total = sum(e[2] for e in entries)
    print('%d files, %.2f GB' % (len(entries), total / 2 ** 30))
    for path, _, size in entries[:40]:
        print('  %14d  %s' % (size, path))
    if list_only:
        return
    t0 = time.time()
    done = 0
    for path, offset, size in entries:
        target = os.path.join(out_dir, *path.strip('/').split('/'))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'wb') as f:
            pos = 0
            while pos < size:
                n = min(64 << 20, size - pos)
                f.write(romfs.read(offset + pos, n))
                pos += n
                done += n
                print('\r%.1f%%  %.0f MB/s   ' % (100.0 * done / max(total, 1), done / 2 ** 20 / max(time.time() - t0, 0.01)),
                      end='', flush=True)
    print('\nextracted to %s in %.0f s' % (out_dir, time.time() - t0))


if __name__ == '__main__':
    main()
