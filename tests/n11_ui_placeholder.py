"""N11: GENERIC PLACEHOLDER PICTURES for a new fighter, so that no screen shows its donor's face
(plan\\phases\\N11_visible_fighter.md). No game content in this file; what it writes stays in the fighter's folder.

    python tests\\n11_ui_placeholder.py <characters folder> <name> [--force]

For every picture type 0..7 of the fighter's first colour it writes
    <characters>\\<name>\\ui\\replace\\chara\\chara_<t>\\chara_<t>_<name>_00.bntx
(the file the registry answers the picture-path question with; docs\\NEW_FIGHTER.md section 14.4), unless the file
exists already (the fighter's OWN picture: never overwritten without --force):
  - where the game has a picture of that type for its "random" entry (the question mark): a copy of it;
  - else: the donor's picture container of that type with ALL PIXEL DATA ZEROED (same size, format and layout, so the
    engine loads it like the donor's; it shows as an empty / dark picture, not as a face).
The donor is read from the folder's fighter.json. Only colour 00: the other colours are still asked for under the
donor's files (the registry falls back per file)."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(STUDY, 'ro_study'))


def blank(data):
    """zero the texture data block: from behind the data block's 16-byte header to the relocation table"""
    d = bytearray(data)
    at = d.find(b'BRTD')
    end = d.rfind(b'_RLT')
    if at < 0 or end < at + 16:
        return None
    for i in range(at + 16, end):
        d[i] = 0
    return bytes(d)


def main():
    chars, name = sys.argv[1], sys.argv[2]
    force = '--force' in sys.argv
    folder = os.path.join(chars, name)
    donor = json.load(open(os.path.join(folder, 'fighter.json')))['donor']
    import arc_extract as ax
    a = ax.Arc()

    def get(who, t):
        pi = a.path_index_from_hash(ax.hash40('ui/replace/chara/chara_%d/chara_%d_%s_00.bntx' % (t, t, who)))
        if pi is None:
            return None
        for region in range(15):
            try:
                return a.read(a.file_record(pi, region))
            except Exception:      # noqa: BLE001
                continue
        return None

    for t in range(8):
        dst = os.path.join(folder, 'ui', 'replace', 'chara', 'chara_%d' % t, 'chara_%d_%s_00.bntx' % (t, name))
        if os.path.exists(dst) and not force:
            print('type %d: %s exists (the fighter\'s own): kept' % (t, dst))
            continue
        d_donor = get(donor, t)
        data, what = get('random', t), 'the game\'s "random" picture (question mark)'
        if data is None or (d_donor is not None and len(data) > len(d_donor)):
            data, what = (blank(d_donor) if d_donor else None), 'the donor\'s container with the pixel data zeroed (an empty picture)'
        if data is None:
            print('type %d: no source picture: NOT written (the donor\'s picture stays)' % t)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, 'wb') as f:
            f.write(data)
        print('type %d: %d bytes (the donor\'s: %s) <- %s' % (t, len(data), len(d_donor) if d_donor else '-', what))


if __name__ == '__main__':
    main()
