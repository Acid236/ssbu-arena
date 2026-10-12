"""Content type and file list of loose NCA files (e.g. the ones a reference emulator installed).

    python nca_info.py <file.nca> ...            header: content type, title id, sections
    python nca_info.py --list <file.nca>         also the file names and sizes of a RomFS section
    python nca_info.py --extract <dir> <file.nca> [name prefix]   write the files of the RomFS section

Keys: ~/.switch/prod.keys (header key, key area keys, title KEKs) and ~/.switch/title.keys (rights id = title key).
Only plain sections are read (no patch / BKTR section).
"""
import os
import struct
import sys

from Crypto.Cipher import AES

import romfs_extract as RX

TYPES = {0: 'Program', 1: 'Meta', 2: 'Control', 3: 'Manual (HtmlDocument / LegalInformation)', 4: 'Data', 5: 'PublicData'}
KEYS = RX.KEYS
TITLE = {}
p = os.path.expanduser('~/.switch/title.keys')
if os.path.exists(p):
    for line in open(p, errors='replace'):
        if '=' in line:
            k, v = line.split('=', 1)
            try: TITLE[bytes.fromhex(k.strip())] = bytes.fromhex(v.strip())
            except ValueError: pass


class Loose:
    def __init__(self, path):
        self.f = open(path, 'rb')
        self.size = os.path.getsize(path)
        h = RX.xts_decrypt(KEYS['header_key'], self.f.read(0xC00), 0)
        self.ok = h[0x200:0x204] == b'NCA3'
        self.header = h
        if not self.ok: return
        self.ctype = h[0x205]
        self.title_id, = struct.unpack('<Q', h[0x210:0x218])
        gen = max(max(h[0x206], h[0x220]) - 1, 0)
        rights = h[0x230:0x240]
        self.key = None
        if any(rights):
            enc = TITLE.get(rights)
            if enc and ('titlekek_%02x' % gen) in KEYS: self.key = AES.new(KEYS['titlekek_%02x' % gen], AES.MODE_ECB).decrypt(enc)
            self.keysrc = 'title key ' + ('found' if enc else 'NOT in title.keys')
        else:
            kak = ['key_area_key_application_%02x', 'key_area_key_ocean_%02x', 'key_area_key_system_%02x'][h[0x207] if h[0x207] < 3 else 0] % gen
            if kak in KEYS: self.key = AES.new(KEYS[kak], AES.MODE_ECB).decrypt(h[0x300:0x340])[0x20:0x30]
            self.keysrc = 'key area'
        self.sections = []
        for i in range(4):
            start, end = struct.unpack('<II', h[0x240 + i * 16:0x248 + i * 16])
            if end:
                fs = h[0x400 + i * 0x200:0x600 + i * 0x200]
                self.sections.append({'index': i, 'offset': start * 0x200, 'size': (end - start) * 0x200, 'fs': fs, 'type': fs[2], 'hash': fs[3], 'crypto': fs[4], 'ctr': fs[0x140:0x148][::-1]})

    def read(self, sec, offset, size):
        if size <= 0: return b''
        absolute = sec['offset'] + offset
        aligned = absolute & ~0xF
        self.f.seek(aligned)
        data = self.f.read((absolute - aligned + size + 15) & ~0xF)
        if sec['crypto'] == 1: plain = data
        else:
            counter = int.from_bytes(sec['ctr'] + struct.pack('>Q', aligned >> 4), 'big')
            plain = AES.new(self.key, AES.MODE_CTR, nonce=b'', initial_value=counter).decrypt(data)
        return plain[absolute - aligned:absolute - aligned + size]


def romfs_files(n, sec):
    """(path, offset in section, size) of every file of an IVFC RomFS section."""
    fs = sec['fs']
    lv_off, lv_size = struct.unpack('<QQ', fs[0x8 + 0x10 + 0x18 * 5:0x8 + 0x10 + 0x18 * 5 + 16])     # level 6 = the RomFS image
    hdr = n.read(sec, lv_off, 0x50)
    (hsz, dh_off, dh_sz, dm_off, dm_sz, fh_off, fh_sz, fm_off, fm_sz, data_off) = struct.unpack('<10Q', hdr)
    if hsz != 0x50: return None
    dm = n.read(sec, lv_off + dm_off, dm_sz)
    fm = n.read(sec, lv_off + fm_off, fm_sz)
    out = []

    def walk(doff, path):
        parent, sibling, child, ffile, hsh, nlen = struct.unpack_from('<6I', dm, doff)
        f = ffile
        while f != 0xffffffff:
            fparent, fsib, foff, fsize, fh, fn = struct.unpack_from('<IIQQII', fm, f)
            out.append((path + fm[f + 0x20:f + 0x20 + fn].decode('utf-8', 'replace'), lv_off + data_off + foff, fsize))
            f = fsib
        c = child
        while c != 0xffffffff:
            cp, cs, cc, cf, ch, cn = struct.unpack_from('<6I', dm, c)
            walk(c, path + dm[c + 0x18:c + 0x18 + cn].decode('utf-8', 'replace') + '/')
            c = cs
    walk(0, '/')
    return out


def main():
    args = sys.argv[1:]
    mode, outdir, prefix = 'info', None, ''
    if args and args[0] == '--list': mode, args = 'list', args[1:]
    elif args and args[0] == '--extract':
        mode, outdir, args = 'extract', args[1], args[2:]
        if len(args) > 1: prefix, args = args[1], args[:1]
    for path in args:
        n = Loose(path)
        if not n.ok:
            print('%s: not an NCA3 (header key wrong or other format)' % path); continue
        print('%s: %d bytes, type %d = %s, title id %016x, %s%s' % (os.path.basename(path), n.size, n.ctype, TYPES.get(n.ctype, '?'), n.title_id, n.keysrc, '' if n.key else ' (no key: sections not readable)'))
        for s in n.sections:
            print('  section %d: offset 0x%x size 0x%x fs type %d (%s) hash type %d crypto %d' % (s['index'], s['offset'], s['size'], s['type'], 'PFS0' if s['type'] == 1 else 'RomFS', s['hash'], s['crypto']))
            if mode == 'info' or s['type'] != 0 or not n.key or s['crypto'] not in (1, 3): continue
            files = romfs_files(n, s)
            if files is None: print('    RomFS header not recognised (wrong key or a patch section)'); continue
            total = sum(f[2] for f in files)
            print('    %d files, %d bytes' % (len(files), total))
            for name, off, size in sorted(files):
                if mode == 'list': print('    %10d  %s' % (size, name))
                elif name.startswith(prefix):
                    dst = os.path.join(outdir, name.lstrip('/'))
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with open(dst, 'wb') as o:
                        done = 0
                        while done < size:
                            k = min(1 << 22, size - done)
                            o.write(n.read(s, off + done, k)); done += k


if __name__ == '__main__':
    main()
