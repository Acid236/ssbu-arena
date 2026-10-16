"""N7 proof B (picture): fill a fighter folder's body-model folder with the files of ANOTHER costume folder of the archive.
    python tests\\n7_model_swap.py <fighter> <donor> <source model folder of the archive> [list]
    python tests\\n7_model_swap.py <fighter> restore
e.g. python tests\\n7_model_swap.py n3test mario fighter/mario/model/body/c01
Every file of the donor's fighter/<donor>/model/body/c00 folder that has a file of the same name in the source folder
is written to characters\\<fighter>\\fighter\\<fighter>\\model\\body\\c00\\ (as 0x<name hash>.bin when its name is not
known as text) and entered in the folder's clone_files.json with the donor file's hash and the new path hash, so that
the loose-file layer serves it under the fighter's own name. A source file LARGER than the donor's is skipped unless
"big" is given (the buffer is sized by the donor's file). `restore` removes what was added.
The path hashes are computed without the names (crc32 is linear in the beginning of the text). The files written are
game content: they stay under characters\\ . No game content in this file."""
import json
import os
import shutil
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(STUDY, 'ro_study'))
import arc_extract as ax  # noqa: E402

CHARS = os.path.join(STUDY, '..', 'characters')
BACK = os.path.join(STUDY, 'work_n7', 'swap_backup')


def shift(x, nbytes):
    for _ in range(nbytes * 8):
        x = (x >> 1) ^ (0xedb88320 if x & 1 else 0)
    return x


def rename40(h, p, p2):
    ln = (h >> 32) & 0xff
    x = (zlib.crc32(p.encode()) ^ zlib.crc32(p2.encode())) & 0xffffffff
    return (((ln - len(p) + len(p2)) & 0xff) << 32) | ((h & 0xffffffff) ^ shift(x, ln - len(p)))


def main():
    name = sys.argv[1]
    folder = os.path.join(CHARS, name)
    cj = os.path.join(folder, 'clone_files.json')
    note = os.path.join(BACK, name + '_model.json')
    if sys.argv[2] == 'restore':
        if not os.path.exists(note):
            print('nothing to restore')
            return
        j = json.load(open(note))
        for p in j['added']:
            if os.path.exists(p):
                os.remove(p)
        for p, b in j['replaced'].items():
            shutil.copyfile(b, p)
        shutil.copyfile(j['clone_backup'], cj)
        os.remove(note)
        print('restored: %d files removed, %d put back' % (len(j['added']), len(j['replaced'])))
        return
    donor, src = sys.argv[2], sys.argv[3].rstrip('/')
    opts = sys.argv[4:]
    assert not os.path.exists(note), 'a model swap is in place: restore first'
    a = ax.Arc()
    dfolder = 'fighter/%s/model/body/c00' % donor
    nfolder = 'fighter/%s/model/body/c00' % name
    want = ax.hash40(dfolder + '/')
    clone = json.load(open(cj))
    by_donor = {int(f['donor_hash'], 16): f for f in clone['files']}
    os.makedirs(BACK, exist_ok=True)
    out_dir = os.path.join(folder, *nfolder.split('/'))
    os.makedirs(out_dir, exist_ok=True)
    added, replaced, rows, skipped, same = [], {}, 0, 0, 0
    for i in range(a.n_path):
        (ph, _), (xh, _), (parent, _), (nh, _) = a.file_path(i)
        if parent != want:
            continue
        sh = rename40(ph, dfolder, src)                   # the file of the same name in the source folder
        si = a.path_index_from_hash(sh)
        if si is None:
            continue
        drec = a.file_record(i)
        srec = a.file_record(si)
        try:
            data = a.read(srec)
        except Exception as e:                            # noqa: BLE001
            print('  %x: cannot read the source file (%s)' % (sh, e))
            continue
        ddata = a.read(drec)
        if data == ddata:
            same += 1
            continue
        if len(data) > drec['decomp_size'] and 'big' not in opts:
            skipped += 1
            continue
        rows += 1
        if 'list' in opts:
            print('  name %x: donor %d bytes -> source %d bytes' % (nh, drec['decomp_size'], len(data)))
            continue
        if ph in by_donor:                                # the folder has the file already (by its own name)
            p = os.path.join(folder, *by_donor[ph]['path'].split('/'))
            b = os.path.join(BACK, name + '_model_' + os.path.basename(p))
            shutil.copyfile(p, b)
            replaced[p] = b
        else:
            fn = '0x%010x.bin' % nh
            p = os.path.join(out_dir, fn)
            clone['files'].append({'path': nfolder + '/' + fn, 'donor_hash': '0x%x' % ph, 'new_hash': '0x%x' % rename40(ph, 'fighter/' + donor, 'fighter/' + name),
                                   'name_hash': '0x%x' % nh, 'size': len(data)})
            added.append(p)
        open(p, 'wb').write(data)
    print('%s <- %s: %d files differ and fit (%d identical, %d larger than the donor\'s skipped)' % (nfolder, src, rows, same, skipped))
    if 'list' in opts:
        return
    cb = os.path.join(BACK, name + '_clone_files.json')
    shutil.copyfile(cj, cb)
    json.dump(clone, open(cj, 'w'), indent=1)
    json.dump({'added': added, 'replaced': replaced, 'clone_backup': cb}, open(note, 'w'))
    print('written: %d new files, %d replaced; clone_files.json extended (backup %s)' % (len(added), len(replaced), cb))


if __name__ == '__main__':
    main()
