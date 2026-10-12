"""The scripted path both sides walk, and its checkpoints.

One list of abstract steps drives the port (as an SSBU_SEQ sequence, see nnhid.c) and the reference emulator
(ref_capture.py, through the DSU pad). A step never waits for a time: the port waits for the screen's draw count,
the emulator side for the screen's image signature (screens.py).

  ('until', screen, key)        press key again and again until the screen is up (the opening movie ignores A at first)
  ('press', key)                one press (8 frames)
  ('stick', dir, frames)        left stick fully u/d/l/r for that many frames
  ('reach', screen)             wait until that screen is shown; on the emulator side, screens in PASS (tutorial pages,
                                notices) are answered with A on the way
  ('check', name, polls)        checkpoint: wait `polls` frames so the screen has settled, then capture
  ('burst', name, seconds)      capture continuously (battle start: not frame-identical, frames are paired afterwards)

Keys: a b x y l r zl zr plus minus (pad buttons)."""

STEPS = [
    ('until', 'title', 'a'),
    ('check', 'title', 90),
    ('press', 'a'), ('reach', 'main_menu'), ('check', 'main_menu', 150),
    ('press', 'a'), ('reach', 'smash_menu'), ('check', 'smash_menu', 150),
    ('press', 'a'), ('reach', 'rules'), ('check', 'rules', 120),
    ('press', 'a'), ('reach', 'stage_select'), ('check', 'stage_select', 120),
    # the hand starts on the first tile, "Casuale" (random stage); tiles 2 and 3 are the random Battlefield / Omega
    # forms; the fourth is Battlefield ("Campo di battaglia"). About 18.5 pixels per frame, a tile is 115 wide.
    ('stick', 'r', 21), ('check', 'stage_select_bf', 90),
    ('press', 'a'), ('reach', 'char_select'), ('check', 'char_select', 150),
    # hand up to the first portrait row, left onto Mario, A = pick
    ('stick', 'u', 30), ('stick', 'l', 18), ('press', 'a'), ('check', 'char_select_p1', 120),
    # With P1 chosen the "ready" banner is up; the hand is carried onto it (right, down) and A starts the match.
    # The CPU's fighter stays the game's own pick ("Casuale"): carrying its token to a portrait was tried and dropped
    # (the hand's start position after the pick is not where the portraits suggest; T1_reference.md, "Limits").
    ('stick', 'r', 57), ('stick', 'd', 11), ('check', 'char_ready', 60),
    ('press', 'a'),
    ('burst', 'battle', 75),
]

CHECKPOINTS = [s[1] for s in STEPS if s[0] == 'check'] + ['versus', 'battle_start', 'battle_idle', 'results']
# screens with a signature (golden/<name>.png); the tutorial pages and notices live in golden/aux
SIGNATURE_SCREENS = ['title', 'main_menu', 'smash_menu', 'rules', 'stage_select', 'char_select']
PASS_SCREENS = ['tutorial']          # answered with A when met on the way to a screen (emulator side)

# ---- port side: draw calls per frame of each screen (plan/phases/P1_battle.md "Numbers")
PORT_DRAWS = {'main_menu': '700-800/40', 'smash_menu': '700-800/40', 'rules': '370-400/40', 'stage_select': '270-295/40',
              'char_select': '175-205/60'}
PORT_KEY = {'a': 'Z', 'b': 'X', 'x': 'C', 'y': 'V', 'l': 'Q', 'r': 'E', 'zl': 'A', 'zr': 'S', 'plus': '!', 'minus': '-'}


def port_sequence():
    """-> (SSBU_SEQ text, {checkpoint name: index of the first key step after it}, index of the burst's first step)"""
    tok, checks, burst = [], {}, None
    pending = []
    def key_token(t):
        for name in pending:
            checks[name] = len(tok)
        pending.clear()
        tok.append(t)
    for s in STEPS:
        if s[0] == 'until':
            tok += ['@movie', '@draws:22-26/30']
            tok.append('@until:36-44/30:%s/200' % PORT_KEY[s[2]])
        elif s[0] == 'press':
            key_token('2:%s' % PORT_KEY[s[1]])
        elif s[0] == 'stick':
            key_token('12:%s/%d' % (s[1], s[2]))
        elif s[0] == 'reach':
            tok.append('@draws:' + PORT_DRAWS[s[1]])
        elif s[0] == 'check':
            tok.append('%d' % s[2])
            pending.append(s[1])
        elif s[0] == 'burst':
            burst = len(tok) - 1
    return ' '.join(tok), checks, burst


# ---- emulator side: runs of press / stick steps that contain a stick move are played as a TAS script (one command per
# displayed frame, so a hold lasts exactly as many game frames as on the port, however slow the machine is)
TAS_KEY = {'a': 'KEY_A', 'b': 'KEY_B', 'x': 'KEY_X', 'y': 'KEY_Y', 'l': 'KEY_L', 'r': 'KEY_R', 'zl': 'KEY_ZL', 'zr': 'KEY_ZR',
           'plus': 'KEY_PLUS', 'minus': 'KEY_MINUS'}
TAS_TAIL = 90                # idle frames at the end of every script (time to write the next script file)


def input_groups():
    """-> {index of the first step: [steps]} for every maximal run of press / stick steps"""
    groups, i = {}, 0
    while i < len(STEPS):
        if STEPS[i][0] in ('press', 'stick'):
            j = i
            while j < len(STEPS) and STEPS[j][0] in ('press', 'stick'):
                j += 1
            groups[i] = STEPS[i:j]
            i = j
        else:
            i += 1
    return groups


def tas_script(steps):
    """the same frame layout as port_sequence(): press = 2 idle + 8 held, stick = 12 idle + n held"""
    lines, f = [], 0
    for s in steps:
        if s[0] == 'press':
            f += 2
            lines += ['%d %s 0;0 0;0' % (f + k, TAS_KEY[s[1]]) for k in range(8)]
            f += 9
        else:
            x, y = {'u': (0, 32767), 'd': (0, -32767), 'l': (-32767, 0), 'r': (32767, 0)}[s[1]]
            f += 12
            lines += ['%d NONE %d;%d 0;0' % (f + k, x, y) for k in range(s[2])]
            f += s[2] + 1
    lines.append('%d NONE 0;0 0;0' % (f + TAS_TAIL))
    return '\n'.join(lines) + '\n', f + TAS_TAIL + 1


if __name__ == '__main__':
    seq, checks, burst = port_sequence()
    print(seq)
    print(checks, 'burst after step', burst)
