"""S19: deterministic proof of the ITEM module as source, in the game. Unattended.

    python tests/s19_itemcheck.py <bin folder with item.dll> <name> [matches=3]

Per match two games at the same time (tests\\s16_run.py; each waits while QUIET_PLEASE / OWNER_PLAYING): A with the
installed DLLs (fighters_bin\\: item.dll there runs no script as source), B with SSBU_FIGHTER_BIN=<bin folder>, which holds
ONLY item.dll (every other module falls back to fighters_bin\\, the same file as in A). So the only difference between A
and B is the item module as source. Four CPU fighters, items on, stage end, SSBU_DETERMINISTIC=1, idle key script.
Verdict per match: all hash-log lines (every entry, all fields but the running hash) equal over the frames both games
have, or the first differing line. The item scripts B ran as source are taken from B's report (lua2cpp_item section).
Writes tests\\logs\\s19_itemcheck_<name>.txt. No game content in this file.
"""
import os
import re
import subprocess
import sys
import time

STUDY = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
LOGS = os.path.join(STUDY, 'tests', 'logs')
MATCHES = [('mario', 'link', 'kirby', 'samus'), ('fox', 'pikachu', 'donkey', 'yoshi'), ('ness', 'captain', 'luigi', 'purin'),
           ('marth', 'peach', 'zelda', 'koopa')]


def lines(tag):
    try:
        with open(os.path.join(LOGS, 's11_%s.fh.txt' % tag), errors='replace') as f:
            return [re.sub(r' H [0-9a-f]+ ', ' ', l.rstrip('\n')) for l in f if l.startswith('F ') and l.rstrip('\n').endswith('%)')]
    except OSError:
        return []


def item_scripts(tag):
    out, on = [], False
    try:
        for l in open(os.path.join(LOGS, 's11_%s.report.txt' % tag), errors='replace'):
            if l.startswith('module '):
                on = l.startswith('module lua2cpp_item:')
                if on:
                    out.append(l.strip())
                continue
            m = re.match(r'\s+(\S+)\s+calls\s+(\d+)', l)
            if on and m and int(m.group(2)):
                out.append('  %s %s calls' % (m.group(1), m.group(2)))
    except OSError:
        pass
    return out


def run(tag, bindir, quad):
    m = 'p1=%s,p2=%s,p3=%s,p4=%s,cpu=9,items=on,stage=end' % quad
    args = [sys.executable, os.path.join(STUDY, 'tests', 's16_run.py'), tag, bindir, 'seq_s16_idle.txt', 'SSBU_DEBUG_MATCH=' + m,
            'SSBU_DETERMINISTIC=1', 'SSBU_VK_PREP=0', 'SSBU_DEBUG_END=' + os.environ.get('S19_END', '3700'), 'SSBU_DLC_LIST=tests\\vk13_nodlc.txt']
    return subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=STUDY)


def main():
    bindir, name = sys.argv[1], sys.argv[2]
    opts = dict(a.split('=', 1) for a in sys.argv[3:] if '=' in a)
    n = int(opts.get('matches', '3'))
    out = open(os.path.join(LOGS, 's19_itemcheck_%s.txt' % name), 'w')
    out.write('# item module as source (%s) v installed (item lifted); %s\n' % (bindir, time.strftime('%Y-%m-%d %H:%M')))
    out.flush()
    for k, quad in enumerate(MATCHES[:n]):
        ta, tb = 's19_%s_%d_a' % (name, k), 's19_%s_%d_b' % (name, k)
        pa, pb = run(ta, 'fighters_bin', quad), run(tb, bindir, quad)
        ra, rb = pa.communicate()[0].strip().splitlines(), pb.communicate()[0].strip().splitlines()
        la, lb = lines(ta), lines(tb)
        common = min(len(la), len(lb))
        diff = next((i for i in range(common) if la[i] != lb[i]), None)
        if not common:
            verdict = 'NO VERDICT (no hash lines: %s / %s)' % (ra[-1:] , rb[-1:])
        elif diff is None:
            verdict = 'IDENTICAL over %d hash lines (A %d, B %d lines)' % (common, len(la), len(lb))
        else:
            verdict = 'DIFFERS at hash line %d of %d:\n    A %s\n    B %s' % (diff + 1, common, la[diff][:200], lb[diff][:200])
        out.write('match %d %s: %s\n  run A: %s\n  run B: %s\n' % (k, ','.join(quad), verdict, ra[-1:] , rb[-1:]))
        for l in item_scripts(tb):
            out.write('  %s\n' % l)
        out.flush()
    out.write('DONE %s\n' % time.strftime('%H:%M'))


if __name__ == '__main__':
    main()
