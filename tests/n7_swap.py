"""N7 proof B: replace ONE cloned file of a fighter folder by another archive file, or put the original back.
    python tests\\n7_swap.py <fighter> <folder below characters\\<fighter>, archive form> <file name> <archive path of the replacement>
    python tests\\n7_swap.py <fighter> restore
e.g. python tests\\n7_swap.py n3test fighter/n3test/motion/body/c00 a00wait1.nuanmb fighter/luigi/motion/body/c00/a00wait1.nuanmb
The fighter's file is found by its own name or as 0x<hash40 of the name>.<ext> (the clone tool's name for files whose
names the archive does not store). The original goes to recomp-study\\work_n7\\swap_backup\\ (local, never published).
Prints both sizes and, for animation files, the float at 0x18 of the header. No game content in this file."""
import json
import os
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(STUDY, 'ro_study'))
import arc_extract as ax  # noqa: E402

CHARS = os.path.join(STUDY, '..', 'characters')
BACK = os.path.join(STUDY, 'work_n7', 'swap_backup')


def main():
    name = sys.argv[1]
    note = os.path.join(BACK, name + '.json')
    if sys.argv[2] == 'restore':
        if not os.path.exists(note):
            print('nothing to restore')
            return
        j = json.load(open(note))
        shutil.copyfile(j['backup'], j['target'])
        os.remove(note)
        print('restored %s (%d bytes)' % (j['target'], os.path.getsize(j['target'])))
        return
    folder, fname, src = sys.argv[2], sys.argv[3], sys.argv[4]
    assert not os.path.exists(note), 'a swap is in place: restore first'
    d = os.path.join(CHARS, name, *folder.split('/'))
    ext = fname.rsplit('.', 1)[1]
    cands = [os.path.join(d, fname), os.path.join(d, '0x%010x.%s' % (ax.hash40(fname), ext))]
    target = next((c for c in cands if os.path.exists(c)), None)
    assert target, 'not in the folder: %s' % cands
    data = ax.Arc().get(src)
    os.makedirs(BACK, exist_ok=True)
    backup = os.path.join(BACK, name + '_' + os.path.basename(target))
    shutil.copyfile(target, backup)
    old = open(target, 'rb').read()
    open(target, 'wb').write(data)
    json.dump({'target': target, 'backup': backup, 'source': src}, open(note, 'w'))

    def f18(b):
        return struct.unpack_from('<f', b, 0x18)[0] if len(b) > 0x1c else 0.0
    print('%s: %d bytes (header float %.1f) -> the archive\'s %s: %d bytes (header float %.1f)' % (target, len(old), f18(old), src, len(data), f18(data)))


if __name__ == '__main__':
    main()
