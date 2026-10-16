"""The native motion list (motion_list.bin of a fighter's motion folder): reader, writer, new rows.

Layout (established on a donor's file: it parses to the last byte and writes back byte-identical):
  u64 file kind hash, u64 id hash, u64 row count, then per row
    u64 key            the motion kind's name hash (snake case: "wait", "attack_12", "special_n_start")
    u64 game script    hash of the script name, "game_" + the animation's lower-case name ("game_attack12")
    u16 flags, u8 blend frames, u8 animation count n, u32 size of the tail (28)
    n x u64            animation file name hashes ("c00attack12.nuanmb")
    n bytes, padded to a multiple of 4
    tail: u64 expression script, u64 sound script, u64 effect script ("expression_attack12" ...),
          4 bytes: two transparency frames, the cancel frame, a no-interpolation flag
A hash is length << 32 | CRC-32 of the lower-case name.

    python -I motion_list.py roundtrip <motion_list.bin>
    python -I motion_list.py list <motion_list.bin> [<labels .txt>]
    python -I motion_list.py add <motion_list.bin in> <out> <NEW_MOTIONS.txt out> <main fighter .pac> <motion .pac>
        adds one row per package animation of OWN (below) and writes the list for the script writer
"""
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def hash40(s):
    b = s.lower().encode('ascii')
    return len(b) << 32 | (zlib.crc32(b) & 0xFFFFFFFF)


class Row:
    __slots__ = ('key', 'game', 'flags', 'blend', 'anims', 'anim_bytes', 'expression', 'sound', 'effect', 'extra')


class MotionList:
    def __init__(self, data):
        self.kind, self.ident, count = struct.unpack_from('<QQQ', data, 0)
        self.rows = []
        p = 24
        for _ in range(count):
            r = Row()
            r.key, r.game, r.flags, r.blend, n, size = struct.unpack_from('<QQHBBI', data, p)
            if size != 28:
                raise ValueError('a row with a tail of %d bytes (this tool knows 28)' % size)
            p += 24
            r.anims = list(struct.unpack_from('<%dQ' % n, data, p))
            p += 8 * n
            r.anim_bytes = bytes(data[p:p + n])
            if any(data[p + n:p + (n + 3) // 4 * 4]):
                raise ValueError('non-zero padding after the animation bytes')
            p += (n + 3) // 4 * 4
            r.expression, r.sound, r.effect = struct.unpack_from('<QQQ', data, p)
            r.extra = bytes(data[p + 24:p + 28])
            p += 28
            self.rows.append(r)
        if p != len(data):
            raise ValueError('%d bytes after the last row' % (len(data) - p))

    def to_bytes(self):
        out = bytearray(struct.pack('<QQQ', self.kind, self.ident, len(self.rows)))
        for r in self.rows:
            n = len(r.anims)
            out += struct.pack('<QQHBBI', r.key, r.game, r.flags, r.blend, n, 28)
            out += struct.pack('<%dQ' % n, *r.anims)
            out += r.anim_bytes.ljust((n + 3) // 4 * 4, b'\0')
            out += struct.pack('<QQQ', r.expression, r.sound, r.effect) + r.extra
        return bytes(out)

    def find(self, key_name):
        h = hash40(key_name)
        for r in self.rows:
            if r.key == h:
                return r
        return None


# ---- the package's animations that have no native motion of their name: THEIR OWN motion kinds.
# package animation: (motion kind key, file prefix, donor row whose flags / blend frames are copied)
OWN = {
    'Attack13': ('attack_13', 'c00', 'attack_12'),
    'AttackS4Start': ('attack_s4_start', 'c03', 'attack_s4_hold'),
    'AttackS4SCharged': ('attack_s4_s_charged', 'c03', 'attack_s4_s'),
    'AttackHi4Start': ('attack_hi4_start', 'c04', 'attack_hi4_hold'),
    'AttackHi4Charged': ('attack_hi4_charged', 'c04', 'attack_hi4'),
    'AttackLw4Start': ('attack_lw4_start', 'c04', 'attack_lw4_hold'),
    'AttackLw4Charged': ('attack_lw4_charged', 'c04', 'attack_lw4'),
    'SpecialN1': ('special_n1', 'd00', 'special_n_start'), 'SpecialN2': ('special_n2', 'd00', 'special_n_start'),
    'SpecialN3': ('special_n3', 'd00', 'special_n_start'), 'SpecialN4': ('special_n4', 'd00', 'special_n_start'),
    'SpecialNCancel': ('special_n_cancel', 'd00', 'special_n_start'),
    'SpecialAirN1': ('special_air_n1', 'd00', 'special_air_n_start'),
    'SpecialAirN2': ('special_air_n2', 'd00', 'special_air_n_start'),
    'SpecialAirN3': ('special_air_n3', 'd00', 'special_air_n_start'),
    'SpecialAirN4': ('special_air_n4', 'd00', 'special_air_n_start'),
    'SpecialAirNCancel': ('special_air_n_cancel', 'd00', 'special_air_n_start'),
    'SpecialSStart': ('special_s_start', 'd01', 'special_s1'), 'SpecialSLoop': ('special_s_loop', 'd01', 'special_n_loop'),
    'SpecialSEnd': ('special_s_end', 'd01', 'special_s1'), 'SpecialSAttack': ('special_s_attack', 'd01', 'special_s1'),
    'SpecialAirSStart': ('special_air_s_start', 'd01', 'special_s1'),
    'SpecialAirSEnd': ('special_air_s_end', 'd01', 'special_s1'),
    'SpecialAirSAttack': ('special_air_s_attack', 'd01', 'special_s1'),
    'SpecialLwAir': ('special_lw_air', 'd03', 'special_n_start'),
    'SpecialLwLanding': ('special_lw_landing', 'd03', 'special_n_start'),
    'Final': ('final', 'd04', 'final_start'), 'FinalAir': ('final_air', 'd04', 'final_start'),
    'FinalLoop': ('final_loop', 'd04', 'special_n_loop'),
    'Wait4': ('wait_4', 'a00', 'wait_2'),
    # template given by the donor row's ANIMATION file (its key is not a regular name)
    'CliffAttackSlow': ('cliff_attack_slow', 'g02', 'anim:g02cliffattack.nuanmb'),
    'CliffClimbSlow': ('cliff_climb_slow', 'g02', 'anim:g02cliffclimb.nuanmb'),
    'CliffEscapeSlow': ('cliff_escape_slow', 'g02', 'anim:g02cliffescape.nuanmb'),
    'CliffJumpSlow1': ('cliff_jump_slow1', 'g02', 'anim:g02cliffjump1.nuanmb'),
    'CliffJumpSlow2': ('cliff_jump_slow2', 'g02', 'anim:g02cliffjump2.nuanmb'),
}


def own_file(name):
    """-> (native file name, hashed file name on disk) of an OWN animation."""
    fn = '%s%s.nuanmb' % (OWN[name][1], name.lower())
    return fn, '0x%010x.nuanmb' % hash40(fn)


def add(args):
    from brawl import arc, brres, chr0, psa_listing as pl
    from brawl.moveset import open_psa
    src, out, listing, main_pac, motion_pac = args
    with open(src, 'rb') as f:
        ml = MotionList(f.read())
    psa = open_psa(main_pac)
    subs = {}
    for s in psa.subactions:
        subs.setdefault(s['name'], s)
    frames = {}
    for e in arc.load(motion_pac).entries:
        if e.kind() == 'BRRES':
            for nm, off in brres.Brres(e.data).chr():
                c = chr0.Chr0(e.data, off)
                frames[nm] = (c.frames, c.loop)
    lines = ['NEW MOTIONS of the ported fighter (rows added to its motion list; made by fighter_sdk\\tools\\brawl\\'
             'motion_list.py)',
             'A status starts one with the KEY (MotionModule::change_motion with hash40 of the key); the scripts the',
             'row names are game_<x>, expression_<x>, sound_<x>, effect_<x> with <x> = the animation\'s lower-case '
             'name.',
             'frames = animation length (last frame index = frames - 1); loop = the package animation\'s loop flag;',
             'cancel = the row\'s cancel frame = the package\'s "can be interrupted" frame + 1 (0 = none in the '
             'package\'s script); flags / blend copied from the donor row named last.',
             '',
             '%-22s %-24s %-28s %-24s %6s %4s %6s  %s' % ('key', 'package animation', 'animation file', 'game script',
                                                        'frames', 'loop', 'cancel', 'flags / blend from'),
             '']
    added = 0
    for name, (key, prefix, template) in OWN.items():
        if name not in frames:
            lines.append('%-22s %-24s NOT ADDED: the motion archive has no such animation' % (key, name))
            continue
        if template.startswith('anim:'):
            ah = hash40(template[5:])
            t = next((r for r in ml.rows if ah in r.anims), None)
        else:
            t = ml.find(template)
        if t is None:
            lines.append('%-22s %-24s NOT ADDED: the donor has no row %s' % (key, name, template))
            continue
        if ml.find(key) is not None:
            lines.append('%-22s %-24s NOT ADDED: the list already has this key' % (key, name))
            continue
        low = name.lower()
        fn, _hashed = own_file(name)
        cancel = 0
        if name in subs:
            for frame, _d, code, _p in pl.walk(psa, subs[name]['scripts']['main']):
                if code == 0x64000000:
                    cancel = min(255, int(round(frame)) + 1)
                    break
        r = Row()
        r.key, r.game = hash40(key), hash40('game_' + low)
        r.flags, r.blend = t.flags, t.blend
        r.anims, r.anim_bytes = [hash40(fn)], b'\0'
        r.expression, r.sound, r.effect = hash40('expression_' + low), hash40('sound_' + low), hash40('effect_' + low)
        r.extra = bytes([0, 0, cancel, 0])
        ml.rows.append(r)
        added += 1
        lines.append('%-22s %-24s %-28s %-24s %6d %4d %6d  %s (%#06x / %d)' % (
            key, name, fn, 'game_' + low, frames[name][0], frames[name][1], cancel, template, t.flags, t.blend))
    data = ml.to_bytes()
    with open(out, 'wb') as f:
        f.write(data)
    again = MotionList(data)
    lines.append('')
    lines.append('%d rows added; the list has %d rows now (%d bytes); read back: %d rows.' % (
        added, len(ml.rows), len(data), len(again.rows)))
    with open(listing, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines[-1:]))
    print('listing: ' + listing)


def sync(args):
    """Existing rows of motions that got a package animation: the cancel frame and the "moves the fighter by its
    root" flag (0x04) from the package's sub-action. Writes old -> new for every changed row."""
    from brawl import arc, brres, chr0, psa_listing as pl
    from brawl.convert_anim import COMBINE, native_names
    from brawl.moveset import open_psa
    src, out, report, main_pac, motion_pac, donor_dir = args
    with open(src, 'rb') as f:
        ml = MotionList(f.read())
    psa = open_psa(main_pac)
    subs = {}
    for s in psa.subactions:
        if s['name'] and (s['name'] not in subs or len(psa.script(s['scripts']['main'])) >
                          len(psa.script(subs[s['name']]['scripts']['main']))):
            subs[s['name']] = s
    frames = {}
    for e in arc.load(motion_pac).entries:
        if e.kind() == 'BRRES':
            for nm, off in brres.Brres(e.data).chr():
                frames[nm] = chr0.Chr0(e.data, off).frames
    have = {f.lower() for f in os.listdir(donor_dir)}
    by_anim = {}
    for r in ml.rows:
        for a in r.anims:
            by_anim.setdefault(a, []).append(r)
    lines = ['MOTION LIST ROWS OF EXISTING MOTION NAMES, CHANGED FROM THE PACKAGE (motion_list.py sync)',
             'cancel = the package\'s "can be interrupted" frame + 1 (+ the start-up frames for the combined smashes);',
             'moves = flag 0x04: the motion moves the fighter by its root bone\'s travel (the package has the same flag).',
             '',
             '%-26s %-22s %-14s %s' % ('native animation file', 'package animation', 'cancel', 'moves')]
    n_cancel = n_move = 0
    for name in sorted(frames):
        sub = subs.get(name)
        if sub is None:
            continue
        cancel = None
        for frame, _d, code, _p in pl.walk(psa, sub['scripts']['main']):
            if code == 0x64000000:
                cancel = int(round(frame)) + 1
                break
        offset = frames.get(COMBINE.get(name), 0) if name in COMBINE else 0
        moves = bool(sub['flags'] & 4)
        for fn, _hashed in native_names(name, have):
            for r in by_anim.get(hash40(fn), []):
                c_old, m_old = r.extra[2], bool(r.flags & 4)
                c_new = min(255, cancel + offset) if cancel is not None else c_old
                if c_new != c_old:
                    r.extra = r.extra[:2] + bytes([c_new]) + r.extra[3:]
                    n_cancel += 1
                if moves != m_old:
                    r.flags = (r.flags & ~4) | (4 if moves else 0)
                    n_move += 1
                if c_new != c_old or moves != m_old:
                    lines.append('%-26s %-22s %-14s %s' % (
                        fn, name, ('%d -> %d' % (c_old, c_new)) if c_new != c_old else '%d' % c_old,
                        ('%s -> %s' % (m_old, moves)) if moves != m_old else str(m_old)))
    lines.append('')
    lines.append('%d cancel frames and %d "moves" flags changed.' % (n_cancel, n_move))
    with open(out, 'wb') as f:
        f.write(ml.to_bytes())
    with open(report, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print(lines[-1] + ' report: ' + report)


def roundtrip(path):
    with open(path, 'rb') as f:
        raw = f.read()
    ml = MotionList(raw)
    same = ml.to_bytes() == raw
    one = sum(1 for r in ml.rows if len(r.anims) == 1)
    print('%s: %d bytes, %d rows (%d with one animation, %d with none, %d with more); read -> write: %s' % (
        os.path.basename(path), len(raw), len(ml.rows), one, sum(1 for r in ml.rows if not r.anims),
        sum(1 for r in ml.rows if len(r.anims) > 1), 'byte-identical' if same else 'DIFFERENT'))
    return same


def listing(path, labels_path=None):
    lab = {}
    if labels_path:
        with open(labels_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                s = line.strip()
                if s:
                    lab[hash40(s)] = s
    with open(path, 'rb') as f:
        ml = MotionList(f.read())
    for r in ml.rows:
        print('%-34s game %-34s flags %#06x blend %2d anims %s extra %s' % (
            lab.get(r.key, '%#x' % r.key), lab.get(r.game, '%#x' % r.game), r.flags, r.blend,
            ','.join(lab.get(a, '%#x' % a) for a in r.anims) or '-', r.extra.hex(' ')))


if __name__ == '__main__':
    a = sys.argv
    if len(a) == 3 and a[1] == 'roundtrip':
        sys.exit(0 if roundtrip(a[2]) else 1)
    elif len(a) >= 3 and a[1] == 'list':
        listing(a[2], a[3] if len(a) > 3 else None)
    elif len(a) == 7 and a[1] == 'add':
        add(a[2:])
    elif len(a) == 8 and a[1] == 'sync':
        sync(a[2:])
    else:
        print(__doc__)
