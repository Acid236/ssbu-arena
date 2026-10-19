"""Turn a compressed package (.nsz, NCZ entries) back into a plain .nsp, so the other tools here can read it.

    python nsz_to_nsp.py <package.nsz> <out.nsp>

An .nsz is a PFS0 (as an .nsp) whose .ncz entries are NCAs with their body compressed: the first 0x4000 bytes are the
NCA header as it is, then 'NCZSECTN' (the sections: offset, size, crypto type, key, counter), then either one zstd
stream or 'NCZBLOCK' (blocks of 2^exp bytes, each zstd or stored), holding the DECRYPTED body from 0x4000 on.
Rebuilding the NCA = decompress + encrypt each section again (AES-128-CTR for crypto types 3 and 4: counter = the
section's upper 8 bytes + (offset >> 4) big-endian). No keys are needed: the section keys travel in the NCZ header.
Other entries (tickets, certificates, .cnmt) are copied. Needs pip install zstandard pycryptodome. Contains no keys.
"""
import os
import struct
import sys

import zstandard
from Crypto.Cipher import AES
from Crypto.Util import Counter

CHUNK = 16 << 20


def pfs0(f):
    """-> (entries [(name, abs offset, size)], header size)"""
    f.seek(0)
    magic, count, strsize, _ = struct.unpack('<4sIII', f.read(16))
    assert magic == b'PFS0', 'not a PFS0 package'
    ents = [struct.unpack('<QQII', f.read(24)) for _ in range(count)]
    strings = f.read(strsize)
    base = 16 + 24 * count + strsize
    return [(strings[n:strings.index(b'\0', n)].decode(), base + o, s) for o, s, n, _ in ents], base


class Sections:
    def __init__(self, secs):
        self.secs = secs                       # [(offset, size, crypto, key, ctr)]

    def encrypt(self, off, data):
        """data = the decrypted bytes of the NCA at off (>= 0x4000): encrypted in place where a section says so."""
        out = bytearray(data)
        for s_off, s_size, crypto, key, ctr in self.secs:
            lo, hi = max(off, s_off), min(off + len(data), s_off + s_size)
            if lo >= hi or crypto not in (3, 4):
                continue
            a = lo & ~0xF                          # CTR works in 16-byte steps
            pad = lo - a
            c = Counter.new(64, prefix=ctr[:8], initial_value=a >> 4)
            enc = AES.new(key, AES.MODE_CTR, counter=c).encrypt(bytes(pad) + bytes(out[lo - off:hi - off]))
            out[lo - off:hi - off] = enc[pad:]
        return bytes(out)


def ncz_to_nca(src, start, size, dst):
    """Write the NCA of the NCZ at src[start:start+size] to dst; returns its size."""
    src.seek(start)
    head = src.read(0x4000)
    dst.write(head)
    magic, n = struct.unpack('<8sQ', src.read(16))
    assert magic == b'NCZSECTN', 'no NCZSECTN after the header'
    secs = []
    for _ in range(n):
        o, s, crypto, _pad = struct.unpack('<QQQQ', src.read(32))
        key, ctr = src.read(16), src.read(16)
        secs.append((o, s, crypto, key, ctr))
    S = Sections(secs)
    pos = src.tell()
    blk = src.read(8)
    off = 0x4000
    dec = zstandard.ZstdDecompressor()
    if blk == b'NCZBLOCK':
        ver, typ, _u, exp, nblk, total = struct.unpack('<BBBBIQ', src.read(16))
        sizes = struct.unpack('<%dI' % nblk, src.read(4 * nblk))
        bsize = 1 << exp
        for i, cs in enumerate(sizes):
            raw = src.read(cs)
            want = min(bsize, 0x4000 + total - off) if i == nblk - 1 else bsize
            data = raw if cs >= want else dec.decompress(raw, max_output_size=want)
            dst.write(S.encrypt(off, data))
            off += len(data)
    else:
        src.seek(pos)
        remain = start + size - pos

        class Bounded:                         # the zstd stream ends where the entry ends
            def read(self, n):
                nonlocal remain
                n = min(n, remain)
                remain -= n
                return src.read(n) if n > 0 else b''
        reader = dec.stream_reader(Bounded())
        while True:
            data = reader.read(CHUNK)
            if not data:
                break
            dst.write(S.encrypt(off, data))
            off += len(data)
    return off


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    src_path, out_path = sys.argv[1:]
    with open(src_path, 'rb') as src:
        ents, _ = pfs0(src)
        tmp = out_path + '.body'
        out_ents = []
        with open(tmp, 'wb') as body:
            for name, off, size in ents:
                at = body.tell()
                if name.endswith('.ncz'):
                    n = ncz_to_nca(src, off, size, body)
                    name = name[:-4] + '.nca'
                else:
                    src.seek(off)
                    left = size
                    while left:
                        b = src.read(min(CHUNK, left))
                        body.write(b)
                        left -= len(b)
                    n = size
                out_ents.append((name, at, n))
                print('  %-48s %12d' % (name, n))
    strings = b''.join(n.encode() + b'\0' for n, _, _ in out_ents)
    strings += b'\0' * ((-(16 + 24 * len(out_ents) + len(strings))) % 0x20)
    name_off, table = 0, b''
    for n, at, size in out_ents:
        table += struct.pack('<QQII', at, size, name_off, 0)
        name_off += len(n) + 1
    with open(out_path, 'wb') as out, open(tmp, 'rb') as body:
        out.write(struct.pack('<4sIII', b'PFS0', len(out_ents), len(strings), 0) + table + strings)
        while True:
            b = body.read(CHUNK)
            if not b:
                break
            out.write(b)
    os.remove(tmp)
    print('written %s' % out_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
