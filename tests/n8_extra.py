"""N8: put test files into a fighter's folder that the donor's load group cannot supply under the fighter's name
(plan\\phases\\N8_first_frame.md, "files without a donor file"). Local only: the files are game content and stay
under characters\\.

    python tests\\n8_extra.py <name> <donor> add
        - model.nusktb and model.xmb of the donor's first costume (files the donor's group SHARES with other
          directories): the folder now brings them, the runtime makes them files of the fighter's own through the
          group's template;
        - fighter/<name>/model/body/c00/n8_extra.nutexb: a file the donor never had (a copy of a texture of the
          donor's second costume under a new name).
    python tests\\n8_extra.py <name> <donor> remove
Prints size and a checksum of each file (the run's log line "served NEW PATH ..." names the same sizes).
No game content in this file."""
import os
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(STUDY, 'ro_study'))
CHARS = os.path.join(STUDY, '..', 'characters')


def main():
    name, donor, what = sys.argv[1], sys.argv[2], sys.argv[3]
    d = os.path.join(CHARS, name, 'fighter', name, 'model', 'body', 'c00')
    items = [('model.nusktb', 'fighter/%s/model/body/c00/model.nusktb' % donor),
             ('model.xmb', 'fighter/%s/model/body/c00/model.xmb' % donor),
             ('n8_extra.nutexb', None)]
    if what == 'remove':
        for fn, _ in items:
            p = os.path.join(d, fn)
            if os.path.exists(p):
                os.remove(p)
                print('removed', p)
        return
    import arc_extract as ax
    a = ax.Arc()
    for fn, src in items:
        p = os.path.join(d, fn)
        assert not os.path.exists(p), 'already there: %s' % p
        if src is None:
            # any texture of the donor's second costume folder that the first costume does not have under that content
            cands = [x for x in sorted(os.listdir(d)) if x.endswith('.nutexb')]
            if cands:
                data = open(os.path.join(d, cands[0]), 'rb').read()
                src = 'a copy of %s of the folder' % cands[0]
            else:       # N9: the folder has no texture of its own (the unedited test folder): the bytes of the skeleton file
                data = a.get(items[0][1])
                src = 'the bytes of %s (the engine never parses this file: only its row and its load are tested)' % items[0][1]
        else:
            data = a.get(src)
        open(p, 'wb').write(data)
        print('%s: %d bytes, crc %08x  <- %s' % (p, len(data), zlib.crc32(data), src))


if __name__ == '__main__':
    main()
