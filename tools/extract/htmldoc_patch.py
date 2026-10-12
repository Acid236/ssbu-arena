"""The game's offline HTML documents (HtmlDocument content): what the UPDATE's Manual NCA holds without the base game.

    python htmldoc_patch.py <update Manual .nca>                 summary + file list (which files are whole in the update)
    python htmldoc_patch.py <update Manual .nca> --extract <dir> write every file whose bytes are all in the update

The update NCA is a patch (BKTR) over the base game's Manual NCA: a relocation table says, for every range of the
virtual RomFS, whether the bytes come from the update or from the base. Ranges that come from the base cannot be read
without the base game's package.
"""
import bisect
import os
import struct
import sys

from Crypto.Cipher import AES

import nca_info as NI
import romfs_extract as RX


class NeedBase(Exception):
    pass


class Adapter:
    """Loose NCA with the read() signature PatchedRomfs uses."""
    def __init__(self, loose):
        self.l = loose
    def section(self, t):
        return next(s for s in self.l.sections if s['type'] == t)
    def read(self, sec, offset, size, ctr_val=None):
        if size <= 0: return b''
        absolute = sec['offset'] + offset
        aligned = absolute & ~0xF
        self.l.f.seek(aligned)
        data = self.l.f.read((absolute - aligned + size + 15) & ~0xF)
        upper = sec['ctr'] if ctr_val is None else sec['ctr'][:4] + struct.pack('>I', ctr_val)
        counter = int.from_bytes(upper + struct.pack('>Q', aligned >> 4), 'big')
        return AES.new(self.l.key, AES.MODE_CTR, nonce=b'', initial_value=counter).decrypt(data)[absolute - aligned:absolute - aligned + size]


class NoBase:
    def section(self, t): return {}
    def read(self, sec, offset, size, ctr_val=None): raise NeedBase()


def main():
    path = sys.argv[1]
    out = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == '--extract' else None
    l = NI.Loose(path)
    assert l.ok and l.key, 'header or title key missing'
    pr = RX.PatchedRomfs.__new__(RX.PatchedRomfs)
    pr.base, pr.update = NoBase(), Adapter(l)
    pr.bsec, pr.usec = {}, pr.update.section(0)
    fs = pr.usec['fs']
    pr.level6 = struct.unpack('<Q', fs[0x8 + 0x10 + 5 * 0x18:0x8 + 0x18 + 5 * 0x18])[0]
    r_off, r_size, r_magic = struct.unpack('<QQ4s', fs[0x100:0x114])
    s_off, s_size, s_magic = struct.unpack('<QQ4s', fs[0x120:0x134])
    assert r_magic == b'BKTR' and s_magic == b'BKTR'
    reloc = pr.update.read(pr.usec, r_off, r_size)
    subs = pr.update.read(pr.usec, s_off, s_size)
    pr.total = struct.unpack('<Q', reloc[8:16])[0]
    pr.rel = []
    for b in range(struct.unpack('<I', reloc[4:8])[0]):
        bucket = reloc[0x4000 * (b + 1):0x4000 * (b + 2)]
        for e in range(struct.unpack('<I', bucket[4:8])[0]):
            pr.rel.append(struct.unpack('<QQI', bucket[0x10 + e * 0x14:0x24 + e * 0x14]))
    pr.rel_keys = [r[0] for r in pr.rel]
    pr.sub = []
    for b in range(struct.unpack('<I', subs[4:8])[0]):
        bucket = subs[0x4000 * (b + 1):0x4000 * (b + 2)]
        for e in range(struct.unpack('<I', bucket[4:8])[0]):
            off, _, ctr = struct.unpack('<QII', bucket[0x10 + e * 0x10:0x20 + e * 0x10])
            pr.sub.append((off, ctr))
    pr.sub.append((r_off, None))
    pr.sub_keys = [s[0] for s in pr.sub]
    from_patch = sum((pr.rel_keys[i + 1] if i + 1 < len(pr.rel) else pr.total) - r[0] for i, r in enumerate(pr.rel) if r[2])
    print('%s: title %016x, virtual RomFS section %d bytes in %d ranges: %d bytes from the update, %d bytes from the base game'
          % (os.path.basename(path), l.title_id, pr.total, len(pr.rel), from_patch, pr.total - from_patch))

    def whole(off, size):
        while size > 0:
            i = bisect.bisect_right(pr.rel_keys, off) - 1
            end = pr.rel_keys[i + 1] if i + 1 < len(pr.rel) else pr.total
            if not pr.rel[i][2]: return False
            n = min(size, end - off); off += n; size -= n
        return True
    try:
        files = sorted(RX.walk(pr, pr.level6))
    except NeedBase:
        print('the directory tables of the RomFS are in the base game: no file list without it')
        return
    ok = [f for f in files if whole(f[1], f[2])]
    print('%d files, %d bytes; whole in the update: %d files, %d bytes' % (len(files), sum(f[2] for f in files), len(ok), sum(f[2] for f in ok)))
    okset = set(f[0] for f in ok)
    for name, off, size in files:
        if out is None: print('%s %10d  %s' % ('U' if name in okset else 'B', size, name))
        elif name in okset:
            dst = os.path.join(out, name.lstrip('/'))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, 'wb').write(pr.read(off, size))
    if out: print('written to', out)


if __name__ == '__main__':
    main()
