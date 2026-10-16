"""Coordinator: unattended fast check of a list of fighters from one bin folder (no agent in the loop).
    python tests/coord_fixcheck.py <names file> <bin folder> [parallel=4] [first=peach,daisy]
Pairs the fighters (two per match, both driven by status requests: S16_BOTH=1, key script seq_s16_idle.txt) and runs
tests\\s16_check.py for each pair, <parallel> matches at a time; a pair without a verdict for a fighter (lost menus,
time-out) is run once more. s16_check.py appends its rows to tests\\logs\\s16_rows.tsv under the group names fx<nn>;
this tool reads those rows back and writes tests\\logs\\coord_fixcheck_result.txt:
    <fighter> <SAFE | NOT SAFE ... | NOT RUN ...>
and, at the end, a line 'DONE' with the counts. The games wait by themselves while tests\\QUIET_PLEASE or
tests\\OWNER_PLAYING exists (s16_run.py). Nothing is copied anywhere. No game content in this file."""
import os
import subprocess
import sys
import time

STUDY = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
LOGS = os.path.join(STUDY, 'tests', 'logs')
ROWS = os.path.join(LOGS, 's16_rows.tsv')
RESULT = os.path.join(LOGS, 'coord_fixcheck_result.txt')


def verdicts(group):
    """newest verdict per fighter among the rows of one group"""
    out = {}
    try:
        for l in open(ROWS, errors='replace'):
            f = l.rstrip('\n').split('\t')
            if len(f) > 1 and ('group %s entry' % group) in l:
                out[f[0]] = f[1]
    except OSError:
        pass
    return out


def write_result(res, done=False):
    with open(RESULT, 'w') as out:
        for n in sorted(res):
            out.write('%s\t%s\n' % (n, res[n]))
        if done:
            safe = sum(1 for v in res.values() if v == 'SAFE')
            out.write('DONE\tSAFE %d of %d, %s\n' % (safe, len(res), time.strftime('%H:%M')))


def main():
    names = open(sys.argv[1]).read().split()
    bindir = sys.argv[2]
    opts = dict(a.split('=', 1) for a in sys.argv[3:] if '=' in a)
    par = int(opts.get('parallel', '4'))
    first = [n for n in opts.get('first', '').split(',') if n in names]
    names = first + [n for n in names if n not in first]
    pairs = [names[i:i + 2] for i in range(0, len(names), 2)]
    if len(pairs[-1]) == 1:                      # odd count: the last one fights the first again
        pairs[-1].append(names[0])
    env = dict(os.environ, S16_BOTH='1', S16_SEQ='seq_s16_idle.txt')
    stamp = time.strftime('%d%H%M')              # s16_check.py refuses a group name used before: unique per invocation
    todo = [('fx%s_%02d' % (stamp, i), p, 0) for i, p in enumerate(pairs)]
    running = []
    res = {}
    log = open(os.path.join(LOGS, 'coord_fixcheck.log'), 'a')
    log.write('start %s: %d fighters, %d matches, bin %s\n' % (time.strftime('%H:%M'), len(names), len(pairs), bindir))
    log.flush()
    while todo or running:
        while todo and len(running) < par:
            group, pair, tries = todo.pop(0)
            name = group if not tries else '%sr' % group
            p = subprocess.Popen([sys.executable, os.path.join(STUDY, 'tests', 's16_check.py'), name] + pair + ['bin=' + bindir],
                                 cwd=STUDY, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
            running.append((p, name, group, pair, tries))
        time.sleep(20)
        for item in list(running):
            p, name, group, pair, tries = item
            if p.poll() is None:
                continue
            running.remove(item)
            v = verdicts(name)
            missing = [n for n in pair if not (v.get(n, '').startswith('SAFE') or v.get(n, '').startswith('NOT SAFE'))]
            for n in pair:
                if n in v and not (res.get(n) == 'SAFE' and not v[n].startswith('NOT SAFE')):   # a run without a verdict never replaces a SAFE
                    res[n] = v[n]
            log.write('%s %s %s: %s\n' % (time.strftime('%H:%M'), name, ' '.join(pair), ' | '.join('%s=%s' % (n, v.get(n, 'no row')[:60]) for n in pair)))
            log.flush()
            if missing and not tries:
                todo.append((group, pair, 1))
            write_result(res)
    write_result(res, done=True)
    log.write('done %s\n' % time.strftime('%H:%M'))


main()
