"""S11 part 3a: the status kinds that trapped in the S10 sweep, forced again with the ORIGINAL alone (SSBU_FIGHTER_SRC=0)
and, with `src`, with the installed source. One game per kind (fast mode, SSBU_DEBUG_MATCH chooses the fighter).
    python tests/s11_traps.py orig|src [kind ...]
Prints one line per kind: TRAP (with the trap line) or no trap. No game content in this file."""
import os
import subprocess
import sys

STUDY = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
KINDS = [(13, 'mario', 0, None), (164, 'mario', 0, None), (164, 'mario', 0, 'ITEM_KIND_BEAMSWORD'), (172, 'mario', 0, None), (173, 'mario', 0, None), (196, 'mario', 0, None), (289, 'captain', 1, None)]
mode = sys.argv[1]
want = [int(a, 0) for a in sys.argv[2:]]
for kind, fighter, final, item in KINDS:
    if want and kind not in want:
        continue
    tag = 'trap_%s_%d%s' % (mode, kind, '_item' if item else '')
    script = os.path.join(STUDY, 'tests', 'logs', 's11_%s.debug.txt' % tag)
    with open(script, 'w') as f:
        f.write('at 700 pos 0 0 0.1\n')
        if item:
            f.write('at 700 item 0 %s\n' % item)
        if final:
            f.write('at 700 final 0\n')
        f.write('at 701 status 0 %d\nat 760 status 0 0\nat 790 pos 0 0 0.1\n' % kind)
    env = dict(os.environ, S11_DEBUG_END='790', S11_SECS='200')
    args = [sys.executable, os.path.join(STUDY, 'tests', 's11_run.py'), tag, '-', 'seq_det_play.txt', '0', 'SSBU_DETERMINISTIC=1',
            'SSBU_DEBUG_MATCH=p1=%s,p2=donkey,stage=end' % fighter, 'SSBU_FIGHTER_DEBUG=' + script]
    if mode == 'orig':
        args.append('SSBU_FIGHTER_SRC=0')
    r = subprocess.run(args, capture_output=True, text=True)
    line = (r.stdout.strip().splitlines() or ['?'])[-1]
    log = open(os.path.join(STUDY, 'tests', 'logs', 's11_%s.log' % tag), errors='replace').read()
    kinds = sorted(set(l.split('kind')[1].split(':')[0].strip() for l in log.splitlines() if l.startswith('[health] t=')))
    st = [l for l in log.splitlines() if l.startswith('[debug] frame 760')]
    print('%s kind %d %s%s: %s | fighter kinds %s | at 760: %s' % (mode, kind, fighter, ' +item' if item else '', line[:230], ' '.join(kinds), st[0][-40:] if st else '-'), flush=True)
