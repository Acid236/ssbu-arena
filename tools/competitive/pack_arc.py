"""The light archive: data.arcp with only the parts of data.arc that the competitive mode reads (runtime/arcpack.c).

    python tools/competitive/pack_arc.py <SSBU_ARC_LOG file> [...] [--arc <data.arc>] [--out <data.arcp>]

Kept, in whole units of the archive (a unit is read whole or not at all, so a later run that reads another file of a
unit still finds it):
  - every unit a logged read touched: a directory stretch of the file section (its zstd frames, one per file), or one
    stream entry (music, movies); reads outside any unit (header, tables) are kept as read, rounded to 4 KB;
  - the header and everything from the file system tables to the end;
  - every fighter's costume folders fighter/<name>/c00..c07 (models, textures, motions of all 8 costumes), and the
    costume-dependent UI portraits and voice / sound banks found by name (chara_<n>_<name>_<cc>, vc_/se_<name>_c<cc>),
    so every costume works although the coverage runs used the first one;
  - with --keep-movies, every stream entry the opening and menus may play is not added: movies come only from the logs.
Everything else (other stages, World of Light, Spirits, items, assist trophies, bosses, their music and effects) is not
copied. A read of something missing is zero-filled and logged by the runtime ("arcpack: MISSING ..."): add that run's
log and pack again. No game content in this file; the output is your own game data and stays on your PC.
"""
import argparse
import bisect
import json
import os
import re
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'nro'))

FIGHTERS = '''mario donkey link samus samusd yoshi kirby fox pikachu luigi ness captain purin peach daisy koopa popo nana sheik
zelda mariod pichu falco marth lucina younglink ganon mewtwo roy chrom gamewatch metaknight pit pitb szerosuit wario snake
ike pzenigame pfushigisou plizardon ptrainer diddy lucas sonic dedede pikmin lucario robot toonlink wolf murabito rockman
wiifit rosetta littlemac gekkouga palutena pacman reflet shulk koopajr duckhunt ryu ken cloud kamui bayonetta inkling ridley
simon richter krool shizue gaogaen packun jack brave buddy dolly master tantan pickel edge eflame elight element demon
trail miifighter miiswordsman miigunner'''.split()


def h40(s):
    b = s.lower().encode()
    return (len(b) << 32) | (zlib.crc32(b) & 0xffffffff)


def main():
    root = os.path.normpath(os.path.join(HERE, '..', '..'))
    ap = argparse.ArgumentParser()
    ap.add_argument('logs', nargs='+')
    ap.add_argument('--arc', default=None)
    ap.add_argument('--out', default=None)
    ap.add_argument('--dry', action='store_true', help='only print what would be kept')
    a = ap.parse_args()
    arc = a.arc
    if not arc:
        st = json.load(open(os.path.join(root, 'build', 'state.json')))
        arc = os.path.join(st['dump']['romfs'], 'data.arc')
    out = a.out or arc + 'p'
    os.environ['SSBU_ARC'] = arc
    import arc_extract as ax
    A = ax.Arc(arc)
    size = os.path.getsize(arc)
    t = A.t
    # ---- units
    units = []                                                         # (start, length)
    for gi in range(A.n_folder_offsets):
        off, dec, comp, fs, fc, red = struct.unpack_from('<QIIIII', t, A.o_folder_off + gi * 28)
        if comp: units.append((A.file_off + off, comp))
    qd, sh, sfi, soe = struct.unpack_from('<4I', t, 0x100)
    o_soe = 0x110 + qd * 12 + sh * 8 + sh * 12 + sfi * 4
    stream_entries = []
    for i in range(soe):
        ssize, soff = struct.unpack_from('<QQ', t, o_soe + i * 16)
        if ssize: units.append((soff, ssize))
        if ssize: stream_entries.append((soff, ssize))
    units.sort()
    starts = [u[0] for u in units]
    print('units: %d (directory stretches and stream entries); stream offsets %s the stream section' % (
        len(units), 'inside' if all(A.stream_off <= s < A.file_off for s, _ in units[:1]) else 'NOT inside'))
    keep = []
    def unit_at(pos):
        i = bisect.bisect_right(starts, pos) - 1
        if i >= 0 and units[i][0] <= pos < units[i][0] + units[i][1]: return i
        return None
    # ---- logged reads
    reads = 0
    used = set()
    for p in a.logs:
        for ln in open(p):
            parts = ln.split()
            if len(parts) != 2: continue
            try: off, n = int(parts[0], 16), int(parts[1], 16)
            except ValueError: continue
            reads += 1
            pos, end = off, off + n
            touched = False
            while pos < end:
                i = unit_at(pos)
                if i is None:
                    j = bisect.bisect_right(starts, pos)
                    nxt = units[j][0] if j < len(units) else end
                    stop = min(end, nxt)
                    keep.append((pos & ~0xfff, ((stop + 0xfff) & ~0xfff) - (pos & ~0xfff)))
                    pos = stop
                else:
                    used.add(i); pos = units[i][0] + units[i][1]
    print('logged reads: %d, units read: %d' % (reads, len(used)))
    # ---- costumes: fighter/<name>/cXX folders (and their children), portraits, voice and sound banks
    rows = {}
    for i in range(A.n_folder):
        ph, nm, par, _u, fs, fc, cs, cc = struct.unpack_from('<4Q4I', t, A.o_dirinfo + i * 52)
        rows[ph & 0xffffffffff] = (fs, fc, cs, cc, ph >> 40)
    def add_file_info(k):
        fp_i, fii_i, i2d_i, flags = struct.unpack_from('<4I', t, A.o_info + k * 16)
        for reg in range(15 if (flags >> 15) & 3 else 1):
            if i2d_i + reg >= A.n_i2d: break
            fo_i, fd_i, bits = struct.unpack_from('<3I', t, A.o_i2d + (i2d_i + reg) * 12)
            off, = struct.unpack_from('<Q', t, A.o_folder_off + fo_i * 28)
            j = unit_at(A.file_off + off)
            if j is not None: used.add(j)
    def add_dir(h, depth=0):
        r = rows.get(h)
        if not r or depth > 24: return 0
        fs, fc, cs, cc, gi = r
        for k in range(fs, fs + fc): add_file_info(k)
        for c in range(cs, cs + cc):
            ch, = struct.unpack_from('<Q', t, A.o_child + c * 8)
            add_dir(ch & 0xffffffffff, depth + 1)
        return 1
    before = len(used)
    parent = {}
    for i in range(A.n_folder):
        ph, nm, par, _u = struct.unpack_from('<4Q', t, A.o_dirinfo + i * 52)
        parent[ph & 0xffffffffff] = (par & 0xffffffffff, nm & 0xffffffffff)
    # every folder under fighter/ whole (costumes, shared parts such as fighter/element for Pyra / Mythra, fighter/common,
    # ptrainer_low ...), except the story's Mii enemies; effect/fighter/<name> and sound folders of the fighters are
    # found by the logged reads and the name rules below
    skip = {h40(x) for x in ('miienemyf', 'miienemyg', 'miienemys')}
    FH = h40('fighter')
    dirs = 0
    for i in range(A.n_folder):
        ph, nm, par = struct.unpack_from('<3Q', t, A.o_dirinfo + i * 52)
        if par & 0xffffffffff == FH and nm & 0xffffffffff not in skip: dirs += add_dir(ph & 0xffffffffff)
    for f in FIGHTERS: dirs += add_dir(h40('effect/fighter/%s' % f))
    # the whole UI (portraits of every size, result screens, icons, fonts and layouts): small next to what it protects
    # against (a results screen that waits for ever for a missing portrait)
    UIROOT = {h40('ui')}
    def under(h, roots, n=10):
        while h in parent and n:
            h = parent[h][0]; n -= 1
            if h in roots: return True
        return False
    files = 0
    for f in FIGHTERS:
        for c in range(8):
            cands = ['ui/replace/chara/chara_%d/chara_%d_%s_%02d.bntx' % (n, n, f, c) for n in (0, 1, 2, 3, 4, 5, 6, 7, 10, 11, 13)]
            cands += ['sound/bank/fighter_voice/vc_%s_c%02d.nus3audio' % (f, c), 'sound/bank/fighter_voice/vc_%s_c%02d.nus3bank' % (f, c),
                      'sound/bank/fighter/se_%s_c%02d.nus3audio' % (f, c), 'sound/bank/fighter/se_%s_c%02d.nus3bank' % (f, c)]
            for p in cands:
                pi = A.path_index_from_hash(h40(p))
                if pi is None: continue
                (ph, pidx), _, _, _ = A.file_path(pi)
                _d, info_idx = struct.unpack_from('<2I', t, A.o_info_index + pidx * 8)
                add_file_info(info_idx); files += 1
    # per-fighter UI folders (the VS / loading portraits: <ui root>/chara/chara_<n>/<fighter>, under ui/replace_patch and
    # its siblings): every folder named after a fighter whose grandparent is one of the ui chara roots
    fh = {h40(f) for f in FIGHTERS}
    def ancestors(h, n):
        out = []
        while h in parent and len(out) < n: h = parent[h][0]; out.append(h)
        return out
    UI = {h40('ui/replace'), h40('ui/replace_patch'), h40('ui')}
    uidirs = 0
    for h, (par, nm) in parent.items():
        if under(h, UI) or nm in fh and UI & set(ancestors(h, 6)):
            uidirs += add_dir(h)
    print('costumes: %d fighter folders, %d UI fighter folders, %d portrait / sound files -> %d more units' % (dirs, uidirs, files, len(used) - before))
    for i in used: keep.append(units[i])
    # every audio stream (NUS3: music, victory themes, which the game picks at random) is kept; videos (WebM) only as logged
    audio = []
    with open(arc, 'rb') as fa:
        for s_, n_ in stream_entries:
            fa.seek(s_)
            if fa.read(4) == b'NUS3': audio.append((s_, n_))
    keep += audio
    print('audio streams kept whole: %d (%.0f MB); videos only as logged' % (len(audio), sum(n for _, n in audio) / 2**20))
    keep.append((0, 0x1000))
    keep.append((A.fs_off, size - A.fs_off))
    # ---- merge and write (4 KB rounding can pass the end of the file: clip)
    keep = [(s, min(n, size - s)) for s, n in keep if s < size]
    keep.sort()
    merged = []
    for s, n in keep:
        if merged and s <= merged[-1][0] + merged[-1][1]:
            e = max(merged[-1][0] + merged[-1][1], s + n); merged[-1] = (merged[-1][0], e - merged[-1][0])
        else: merged.append((s, n))
    total = sum(n for _, n in merged)
    hdr = 24 + 24 * len(merged)
    at = (hdr + 0xfff) & ~0xfff
    table = []
    for s, n in merged: table.append((s, n, at)); at += n
    print('kept %d ranges, %.2f of %.2f GB (%.0f %%) -> %s' % (len(merged), total / 2**30, size / 2**30, 100.0 * total / size, out))
    if a.dry: return
    with open(arc, 'rb') as src, open(out + '.tmp', 'wb') as dst:
        dst.write(b'SSBUARCP' + struct.pack('<QQ', size, len(merged)))
        for s, n, p in table: dst.write(struct.pack('<QQQ', s, n, p))
        dst.write(b'\0' * (((hdr + 0xfff) & ~0xfff) - hdr))
        done = 0
        for s, n, p in table:
            src.seek(s); left = n
            while left:
                b = src.read(min(left, 64 << 20))
                if not b: raise SystemExit('data.arc ended early at %x' % (s + n - left))
                dst.write(b); left -= len(b)
            done += n
            print('\r  %5.1f %%' % (100.0 * done / total), end='', flush=True)
    os.replace(out + '.tmp', out)
    print('\ndone: %s (%.2f GB)' % (out, os.path.getsize(out) / 2**30))


if __name__ == '__main__':
    main()
