"""N10: test inputs for "files the donor never had" and "a model of another shape" (plan\\phases\\N10_custom_model.md).
Everything written is game content and stays in the characters folder given (a work folder, never public\\).

    python tests\\n10_model.py extra <characters folder> <name> <donor>
        into <characters>\\<name>\\fighter\\<name>\\model\\body\\c00\\ :
        - model.nusktb : the donor's skeleton file (a file the donor's group SHARES) + 16 zero bytes appended (the one
          harmless edit: the container's offsets are relative, nothing points behind its end);
        - n10_extra.nutexb : a file with a name the donor never had (a copy of the first texture the donor's material
          file names; when none is found, the skeleton's bytes).
    python tests\\n10_model.py swap <characters folder> <name> <other fighter> [cNN]
        replaces the WHOLE folder fighter\\<name>\\model\\body\\c00 by every file of fighter/<other>/model/body/<cNN, default c00>
        of the archive, under the same file names (the names are found by hashing: the fixed model file names + every
        text the model's own files contain + ".nutexb"). The old folder is moved to <characters>\\<name>\\_model_before.
    python tests\\n10_model.py unswap <characters folder> <name>
Prints every file with size and crc32 (the run's log names the same numbers). No game content in this file."""
import os
import re
import shutil
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(STUDY, 'ro_study'))

FIXED = ['model.numdlb', 'model.numshb', 'model.numatb', 'model.nusktb', 'model.nuhlpb', 'model.xmb', 'model.adjb',
         'model.numshexb', 'model.nusrcmdlb', 'model.nuanmb', 'light.nuanmb', 'default.nuhlpb', 'dark_model.numatb', 'light_model.numatb', 'metamon_model.numatb']
EXTS = ['nutexb', 'numdlb', 'numshb', 'numatb', 'nusktb', 'nuhlpb', 'xmb', 'adjb', 'numshexb', 'nusrcmdlb', 'nuanmb', 'bin', 'prc', 'eff', 'lc']


def texts(data):
    return set(m.group().decode() for m in re.finditer(rb'[A-Za-z0-9_\-\.]{3,80}', data))


def folder_files(a, folder):
    import arc_extract as ax
    want = ax.hash40(folder + '/')
    out = []
    for i in range(a.n_path):
        (ph, _), (xh, _), (parent, _), (nh, _) = a.file_path(i)
        if parent == want:
            out.append((i, ph, xh, nh))
    return out


def main():
    what, chars, name = sys.argv[1], sys.argv[2], sys.argv[3]
    d = os.path.join(chars, name, 'fighter', name, 'model', 'body', 'c00')
    before = os.path.join(chars, name, '_model_before')
    if what == 'unswap':
        assert os.path.isdir(before), 'no swap in place'
        shutil.rmtree(d)
        shutil.move(before, d)
        print('restored', d)
        return
    import arc_extract as ax
    a = ax.Arc()
    if what == 'extra':
        donor = sys.argv[4]
        os.makedirs(d, exist_ok=True)
        skel = a.get('fighter/%s/model/body/c00/model.nusktb' % donor)
        out = [('model.nusktb', skel + b'\0' * 16, 'the donor\'s skeleton (%d bytes, crc %08x) + 16 zero bytes' % (len(skel), zlib.crc32(skel)))]
        tex, src = skel, 'the skeleton\'s bytes (no texture name found)'
        try:
            mat = a.get('fighter/%s/model/body/c00/model.numatb' % donor)
            for t in sorted(texts(mat)):
                try:
                    tex = a.get('fighter/%s/model/body/c00/%s.nutexb' % (donor, t))
                    src = 'a copy of the donor\'s texture number %d of its material file' % (sorted(texts(mat)).index(t))
                    break
                except Exception:      # noqa: BLE001
                    continue
        except Exception:              # noqa: BLE001
            pass
        out.append(('n10_extra.nutexb', tex, src))
        for fn, data, src in out:
            p = os.path.join(d, fn)
            open(p, 'wb').write(data)
            print('%s: %d bytes, crc32 %08x  <- %s' % (p, len(data), zlib.crc32(data), src))
        return
    assert what == 'swap'
    other = sys.argv[4]
    cc = sys.argv[5] if len(sys.argv) > 5 else 'c00'
    src_folder = 'fighter/%s/model/body/%s' % (other, cc)
    files = folder_files(a, src_folder)
    assert files, 'no files under ' + src_folder
    blobs = {}
    for i, ph, xh, nh in files:
        try:
            blobs[ph] = a.read(a.file_record(i))
        except Exception as e:         # noqa: BLE001
            print('  cannot read %x (%s)' % (ph, e))
    cands = set(FIXED)
    for data in blobs.values():
        if len(data) < 4000000 and data[:4] == b'HBSS':
            for t in texts(data):
                cands.add(t + '.nutexb')
                cands.add(t)
    by_hash = {ax.hash40(c): c for c in cands}
    ext_by_hash = {ax.hash40(e): e for e in EXTS}
    assert not os.path.exists(before), 'a swap is in place: unswap first'
    if os.path.isdir(d):
        shutil.move(d, before)
    else:
        os.makedirs(before)
    os.makedirs(d)
    named = unnamed = total = 0
    for i, ph, xh, nh in sorted(files, key=lambda x: x[3]):
        if ph not in blobs:
            continue
        fn = by_hash.get(nh)
        data = blobs[ph]
        if fn is None:
            unnamed += 1
            print('  NOT WRITTEN: name hash %x (extension %s), %d bytes: its name was not found as text' % (nh, ext_by_hash.get(xh, '%x' % xh), len(data)))
            continue
        named += 1
        total += len(data)
        open(os.path.join(d, fn.lower()), 'wb').write(data)
        print('  %-44s %9d bytes  crc32 %08x' % (fn.lower(), len(data), zlib.crc32(data)))
    print('%s <- %s: %d files written (%d bytes), %d not written; the folder before is in %s' % (d, src_folder, named, total, unnamed, before))


if __name__ == '__main__':
    main()
