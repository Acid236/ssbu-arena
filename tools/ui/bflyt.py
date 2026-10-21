"""Minimal reader of Nintendo LayoutLibrary files (SARC with BFLYT layouts), for planning a menu redesign.
    python bflyt.py <layout.arc> list                 the files in the archive
    python bflyt.py <layout.arc> tree <name.bflyt>    the pane tree: type, name, position, size, scale, alpha, parts / text
Reads only. Pane formats after the public BFLYT documentation (Switch Toolbox / LayoutKit). No game content here."""
import struct, sys


def sarc(d):
    assert d[:4] == b'SARC'
    doff = struct.unpack_from('<I', d, 0xC)[0]
    sfat = 0x14; n = struct.unpack_from('<H', d, sfat + 6)[0]
    names = sfat + 0xC + 16 * n + 8
    out = {}
    for i in range(n):
        h, attr, s, e = struct.unpack_from('<IIII', d, sfat + 0xC + 16 * i)
        no = (attr & 0xFFFF) * 4
        out[d[names + no:d.index(b'\0', names + no)].decode()] = d[doff + s:doff + e]
    return out


def cstr(b):
    return b.split(b'\0', 1)[0].decode('ascii', 'replace')


def tree(f):
    assert f[:4] == b'FLYT', f[:4]
    hs = struct.unpack_from('<H', f, 6)[0]
    nsec = struct.unpack_from('<H', f, 0x10)[0]
    o, depth, lines, mats, texs = hs, 0, [], [], []
    while o + 8 <= len(f):
        mag, size = f[o:o + 4].decode('ascii', 'replace'), struct.unpack_from('<I', f, o + 4)[0]
        b = f[o:o + size]
        if mag == 'txl1':
            n = struct.unpack_from('<H', b, 8)[0]
            offs = [struct.unpack_from('<I', b, 0xC + 4 * i)[0] for i in range(n)]
            texs = [cstr(b[0xC + x:]) for x in offs]
        elif mag == 'mat1':
            n = struct.unpack_from('<H', b, 8)[0]
            offs = [struct.unpack_from('<I', b, 0xC + 4 * i)[0] for i in range(n)]
            for x in offs:
                name = cstr(b[x:x + 28]); texmaps = b[x + 28 + 8 + 8:]       # (name 28, colours 8, flags 4 ...)
                flags = struct.unpack_from('<I', b, x + 28 + 8)[0]
                ntex = flags & 3
                ti = [struct.unpack_from('<H', b, x + 28 + 12 + 4 * k)[0] for k in range(ntex)]
                mats.append((name, [texs[t] if t < len(texs) else '?' for t in ti]))
        elif mag in ('pan1', 'pic1', 'txt1', 'wnd1', 'bnd1', 'prt1', 'scr1', 'ali1'):
            flags, origin, alpha = b[8], b[9], b[10]
            name = cstr(b[0xC:0xC + 24])
            tx, ty, tz, rx, ry, rz, sx, sy, w, h = struct.unpack_from('<10f', b, 0x2C)
            extra = ''
            if mag == 'pic1':
                mi = struct.unpack_from('<H', b, 0x54 + 16)[0]
                extra = ' mat %s' % (mats[mi][0] + ' ' + ','.join(mats[mi][1]) if mi < len(mats) else mi)
            elif mag == 'prt1':
                n = struct.unpack_from('<I', b, 0x54)[0]
                pname = cstr(b[0x60 + 0x28 * n:])
                extra = ' part %s' % pname
            elif mag == 'txt1':
                ml, sl, mi, fi = struct.unpack_from('<HHHH', b, 0x54)
                to = struct.unpack_from('<I', b, 0x64)[0]
                txt = b[to:to + sl].decode('utf-16-le', 'replace').rstrip('\0') if sl else ''
                extra = ' text %r' % txt[:40]
            vis = '' if flags & 1 else ' (hidden)'
            lines.append('%s%s %-28s pos %7.1f %7.1f  size %6.1f %6.1f  scale %.2f %.2f  alpha %3d%s%s' % (
                '  ' * depth, mag[:3], name, tx, ty, w, h, sx, sy, alpha, vis, extra))
        elif mag == 'pas1':
            depth += 1
        elif mag == 'pae1':
            depth -= 1
        elif mag == 'grs1':
            depth += 1
        elif mag == 'gre1':
            depth -= 1
        if size < 8 or o + size > len(f):
            raise ValueError('invalid BFLYT section size at %#x' % o)
        o += size
    return lines, texs


if __name__ == '__main__':
    files = sarc(open(sys.argv[1], 'rb').read())
    if sys.argv[2] == 'list':
        for n in sorted(files): print(n, len(files[n]))
    else:
        lines, texs = tree(files['blyt/' + sys.argv[3]])
        print('textures:', ', '.join(texs))
        print('\n'.join(lines))
