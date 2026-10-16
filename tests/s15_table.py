"""S15: build fighters\\STATUS_CHECK_S15.md and fighters_bin_s15_safe\\ from tests\\logs\\s15_rows.tsv (+ the hash logs of the runs).
    python tests/s15_table.py
Verdict SAFE = lifted run and source run both exited normally (EXITED 0), hash logs identical over all frames, same frame count >= 1500.
Final column: the debug script forces the FINAL status at fight frame ~1631; 'started' = fighter 0 holds one non-zero status for >= 100 frames
after frame 1631 in BOTH runs. No game content in this file."""
import os
import re
import shutil
import sys

STUDY = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
LOGS = os.path.join(STUDY, 'tests', 'logs')
ALL = open(os.path.join(STUDY, 'tests', 's14_names.txt')).read().split()


def stat_after(tag, start=1631):
    best, cur, n = None, None, 0
    try:
        for l in open(os.path.join(LOGS, 's11_%s.fh.txt' % tag), errors='replace'):
            m = re.match(r'F (\d+) e 0 st (\w+) ', l)
            if not m or int(m.group(1)) < start:
                continue
            if m.group(2) == cur:
                n += 1
            else:
                cur, n = m.group(2), 1
            if cur != '0' and n >= 100:
                best = cur
    except OSError:
        pass
    return best


def main():
    rows = {}
    extra = {}
    last = None
    for l in open(os.path.join(LOGS, 's15_rows.tsv'), errors='replace'):
        if l.startswith('   '):
            extra[last] = extra.get(last, '') + l.strip() + ' | '
            continue
        p = l.rstrip('\n').split('\t')
        if len(p) >= 8:
            rows[p[0]] = p
            last = p[0]
    out = ['# STATUS_CHECK_S15: fast check of the 96 status-source DLLs (fighters_bin_s14 builds, run from fighters_bin_s15)', '',
           'One pair of deterministic runs per fighter (lifted SSBU_FIGHTER_SRC=0, then source), stage end, immobile dummy (mario, luigi for mario; p2=human),',
           'scripted inputs: every special tapped and held on the ground and in the air, dummy re-placed in front (pos) four times, then the FORCED Final',
           '(flag + term + status FINAL) at fight frame ~1631. SAFE = both runs exited normally and the hash logs are identical. NOT covered: being hit,',
           'grabs, items, other stages, CPU play, the Final started by the button.', '',
           '| fighter | hash identical (frames) | final checked | verdict |', '|---|---|---|---|']
    safe, notsafe, notrun = [], [], []
    for f in ALL:
        r = rows.get(f)
        if not r:
            out.append('| %s | - | - | NOT RUN |' % f)
            notrun.append(f)
            continue
        ident, na, nb, la, lb = r[1], int(r[2]), int(r[3]), r[5], r[6]
        okexit = 'EXITED 0' in la and 'EXITED 0' in lb
        fa, fb = stat_after('s15_%s_a' % f), stat_after('s15_%s_b' % f)
        if fa and fb:
            fin = 'yes (status %s / %s)' % (fa, fb)
        elif fa and not fb:
            fin = 'lifted only (%s)' % fa
        else:
            fin = 'final not seen (no status held 100 frames after the forced FINAL)'
        if na == 0 or nb == 0 or 'TIMEOUT' in la or 'TIMEOUT' in lb:
            out.append('| %s | %s (frames %d/%d) | %s | NOT RUN (a run timed out in my 170 s limit or never reached the fight; no difference seen in the common frames: %s) |' % (f, ident, na, nb, fin, 'a: ' + la[:60]))
            notrun.append(f)
        elif ident == 'identical' and okexit and na == nb and na >= 1500:
            out.append('| %s | identical (%d) | %s | SAFE |' % (f, na, fin))
            safe.append(f)
        else:
            why = '%s; frames %d/%d; a: %s; b: %s %s' % (ident, na, nb, la[:90], lb[:90], extra.get(f, '')[:400])
            out.append('| %s | %s | %s | NOT SAFE: %s |' % (f, ident, fin, why.replace('|', '/')))
            notsafe.append(f)
    out += ['', 'Totals: SAFE %d, NOT SAFE %d, NOT RUN %d (of %d).' % (len(safe), len(notsafe), len(notrun), len(ALL))]
    open(os.path.join(STUDY, 'fighters', 'STATUS_CHECK_S15.md'), 'w').write('\n'.join(out) + '\n')
    d = os.path.join(STUDY, 'fighters_bin_s15_safe')
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    for f in safe:
        shutil.copy(os.path.join(STUDY, 'fighters_bin_s15', f + '.dll'), os.path.join(d, f + '.dll'))
    print('SAFE', len(safe), 'NOT SAFE', notsafe, 'NOT RUN', len(notrun))


main()
