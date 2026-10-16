"""N9: give a fighter folder picture files (portrait / icon textures) of its own, as a visible marker: the picture
files of ANOTHER fighter of the archive, written under the new fighter's name.

    python tests\\n9_ui.py <name> <donor> <source fighter> add [characters folder] [colours, default 1] [big]
    python tests\\n9_ui.py <name> <donor> <source fighter> remove [characters folder]

For every picture type N (0..15) and colour for which the archive has ui/replace/chara/chara_N/chara_N_<source>_<cc>.bntx
AND the donor has the same type and colour, the source's file is written to
<characters>\\<name>\\ui\\replace\\chara\\chara_N\\chara_N_<name>_<cc>.bntx. The runtime gives such a file a row of its own
(its donor file = the donor's picture of that type) and answers the picture-path question of the new roster row with it.
A source file LARGER than the donor's is skipped unless "big" is given (the buffer is sized by the donor's file).
The files are game content: they stay under the characters folder. No game content in this file."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(STUDY, 'ro_study'))


def main():
    name, donor, source, what = sys.argv[1:5]
    rest = sys.argv[5:]
    big = 'big' in rest
    rest = [r for r in rest if r != 'big']
    chars = rest[0] if rest else os.path.join(STUDY, '..', 'characters')
    colours = int(rest[1]) if len(rest) > 1 else 1
    root = os.path.join(chars, name, 'ui', 'replace', 'chara')
    if what == 'remove':
        n = 0
        for d, _, fs in os.walk(root):
            for fn in fs:
                if fn.endswith('_%s_%s.bntx' % (name, fn[-7:-5])):
                    os.remove(os.path.join(d, fn))
                    n += 1
        print('%d picture files removed under %s' % (n, root))
        return
    import arc_extract as ax
    a = ax.Arc()
    made = 0
    for ty in range(16):
        for cc in range(colours):
            src = 'ui/replace/chara/chara_%d/chara_%d_%s_%02d.bntx' % (ty, ty, source, cc)
            don = 'ui/replace/chara/chara_%d/chara_%d_%s_%02d.bntx' % (ty, ty, donor, cc)
            ps, pd = a.path_index_from_hash(ax.hash40(src)), a.path_index_from_hash(ax.hash40(don))
            if ps is None or pd is None:
                continue
            data = a.get(src)
            dsize = a.file_record(pd)['decomp_size']
            if len(data) > dsize and not big:
                print('type %d colour %d: the source file (%d bytes) is larger than the donor\'s (%d): skipped' % (ty, cc, len(data), dsize))
                continue
            dst = os.path.join(root, 'chara_%d' % ty, 'chara_%d_%s_%02d.bntx' % (ty, name, cc))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, 'wb') as f:
                f.write(data)
            made += 1
            print('type %d colour %d: %d bytes (the donor\'s file: %d) -> %s' % (ty, cc, len(data), dsize, os.path.relpath(dst, chars)))
    print('%d picture files written' % made)


if __name__ == '__main__':
    main()
