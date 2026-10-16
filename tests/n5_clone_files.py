"""N5: clone a donor's archive files under a new fighter's name (plan\\phases\\N5_own_module.md, task 2).
The seed of "create a fighter from a donor".

    python tests\\n5_clone_files.py <log of a run with the registry> <new name> [characters folder, default ..\\characters] [--dry]

Input: the lines `[registry] path asked: <path with the new name> ... -> the donor's: <donor path>: found | NOT a file ...`
that fighter_sdk\\newmodule_host.c writes for every path the engine builds with the new fighter's name.
Output, under <characters>\\<new name>\\<archive path with the NEW name>:
  - a path that is a FILE of the archive: the donor's file, extracted (ro_study\\arc_extract.py), under the new path;
  - a path that is a FOLDER: every archive file whose parent folder is the donor's folder. The archive stores no
    names, only hashes (hash40 = crc32 | length << 32) of the path, the folder and the file name; the file is written
    as 0x<file name hash>.<extension> (extension from a list of hashed candidates, else .bin). Its NEW path hash is
    computed without the name: crc32 is linear, so crc32(new folder + "/" + name) follows from crc32(new folder + "/"),
    crc32(name) and len(name) (crc32_combine). The identity is checked on the donor's own path hash for every file.
  - clone_files.json: every cloned file with its donor path hash, its new path hash and its size.
The extracted files are GAME CONTENT: they stay under the characters folder on this PC. This tool contains none.
What it does not do: serve them (stage 2 of the loose-file layer needs rows for the new path hashes; the json is
the list of rows to add).
"""
import json
import os
import re
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(STUDY, 'ro_study'))

EXTS = ('prc bin nuanmb numdlb numshb nusktb numatb nutexb nuhlpb numshexb nus3audio nus3bank tonelabel sqb eff xmb '
        'lc stprm stdat nro arc bntx bfotf bfttf nufxlb shpc shpcanim nusrcmdlb adjb h264 webm msbt csb fnv sli spt '
        'svt lvd nuanimb fresbin').split()


def hash40(s):
    b = s.lower().encode()
    return (len(b) << 32) | (zlib.crc32(b) & 0xffffffff)


def _gf2_times(mat, vec):
    s, i = 0, 0
    while vec:
        if vec & 1:
            s ^= mat[i]
        vec >>= 1
        i += 1
    return s


def _gf2_square(mat):
    return [_gf2_times(mat, mat[n]) for n in range(32)]


def crc32_combine(crc1, crc2, len2):
    """crc32(A + B) from crc32(A), crc32(B), len(B) (the method of zlib's crc32_combine)."""
    if len2 <= 0:
        return crc1
    odd = [0xedb88320] + [1 << n for n in range(31)]
    even = _gf2_square(odd)
    odd = _gf2_square(even)
    while True:
        even = _gf2_square(odd)
        if len2 & 1:
            crc1 = _gf2_times(even, crc1)
        len2 >>= 1
        if not len2:
            break
        odd = _gf2_square(even)
        if len2 & 1:
            crc1 = _gf2_times(odd, crc1)
        len2 >>= 1
        if not len2:
            break
    return crc1 ^ crc2


def child_hash(folder, name_hash):
    """hash40 of folder + "/" + name, from the folder STRING and the name's hash40."""
    pre = (folder + '/').lower().encode()
    crc = crc32_combine(zlib.crc32(pre) & 0xffffffff, name_hash & 0xffffffff, name_hash >> 32)
    return ((len(pre) + (name_hash >> 32)) << 32) | crc


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    dry = '--dry' in sys.argv
    log, new = args[0], args[1]
    chars = args[2] if len(args) > 2 else os.path.join(STUDY, '..', 'characters')
    pat = re.compile(r"\[registry\] path asked: (\S+) \(hash \w+, by \w+\) -> not in the archive -> the donor's: (\S+): (found|NOT)")
    asked = {}
    with open(log, 'r', errors='replace') as f:
        for line in f:
            m = pat.search(line)
            if m and re.search(r'(?<![a-z0-9])%s(?![a-z0-9])' % re.escape(new), m.group(1), re.I):
                asked[m.group(1)] = (m.group(2), m.group(3) == 'found')
    if not asked:
        print('no path with the name %s in %s' % (new, log))
        return 1
    import arc_extract
    arc = arc_extract.Arc()
    ext_names = {hash40(e): e for e in EXTS}
    folders = {p: d for p, (d, is_file) in asked.items() if not is_file}
    by_parent = {}
    if folders:
        want = {hash40(d): p for p, d in folders.items()}
        want.update({hash40(d + '/'): p for p, d in folders.items()})
        for i in range(arc.n_path):
            (ph, _), (xh, _), (parent, _), (name, _) = arc.file_path(i)
            if parent in want:
                by_parent.setdefault(want[parent], []).append((i, ph, xh, name))
    out_root = os.path.join(chars, new)
    rows, n_files, n_bytes, n_bad, missing = [], 0, 0, 0, []
    for p in sorted(asked):
        donor, is_file = asked[p]
        if is_file:
            data = None
            for region in range(0, 15):                 # a regional file has one data row per region: the first that reads
                try:
                    data = arc.get(donor, region)
                    break
                except Exception:
                    continue
            if data is None:
                missing.append(p)
                print('file    %-64s NOT extracted (no region of %s could be read)' % (p, donor))
                continue
            dst = os.path.join(out_root, p.replace('/', os.sep))
            if not dry:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, 'wb') as f:
                    f.write(data)
            rows.append({'path': p, 'donor': donor, 'donor_hash': '0x%x' % hash40(donor), 'new_hash': '0x%x' % hash40(p), 'size': len(data)})
            n_files += 1
            n_bytes += len(data)
            print('file    %-64s %8d bytes  <- %s' % (p, len(data), donor))
            continue
        kids = by_parent.get(p, [])
        if not kids:
            missing.append(p)
            print('folder  %-64s no archive file has %s as its parent folder (a load group, a stream folder, or missing)' % (p, donor))
            continue
        size = 0
        for (i, ph, xh, name) in kids:
            if child_hash(donor, name) != ph:
                n_bad += 1
                continue
            data = arc.read(arc.file_record(i))
            fn = '0x%010x.%s' % (name, ext_names.get(xh, 'bin'))
            dst = os.path.join(out_root, p.replace('/', os.sep), fn)
            if not dry:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, 'wb') as f:
                    f.write(data)
            rows.append({'path': p + '/' + fn, 'donor_hash': '0x%x' % ph, 'new_hash': '0x%x' % child_hash(p, name), 'name_hash': '0x%x' % name, 'size': len(data)})
            n_files += 1
            size += len(data)
        n_bytes += size
        print('folder  %-64s %4d files, %9d bytes  <- %s (names unknown: written as 0x<name hash>.<ext>)' % (p, len(kids), size, donor))
    if not dry:
        os.makedirs(out_root, exist_ok=True)
        with open(os.path.join(out_root, 'clone_files.json'), 'w') as f:
            json.dump({'name': new, 'files': rows, 'not_cloned': missing}, f, indent=1)
    print('%s: %d paths asked (%d files, %d folders); %d files cloned, %d bytes; %d folder paths without files; '
          '%d files skipped because the computed path hash did not match the archive\'s%s'
          % (new, len(asked), sum(1 for v in asked.values() if v[1]), len(folders), n_files, n_bytes, len(missing), n_bad, ' (dry run: nothing written)' if dry else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
