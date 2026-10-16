"""S16: merges the two checks into fighters\\STATUS_CHECK_S15.md and fighters_bin_s15_safe\\.
    python tests/s16_table.py
Base = the rows of the one-fighter check (the existing STATUS_CHECK_S15.md, written by tests\\s15_table.py; that tool is NOT run again: it would
copy the rebuilt demon / pickel into the safe folder), overridden by the newest row of tests\\logs\\s16_rows.tsv (four-fighter matches,
tests\\s16_check.py) for each fighter. A fighter whose newest s16 row is SAFE gets its DLL copied from fighters_bin_s15\\ into
fighters_bin_s15_safe\\ (the folder never receives anything else; fighters_bin\\ is not touched). Prints the totals and the install list
(SAFE DLLs of the safe folder that differ from fighters_bin\\). No game content in this file."""
import filecmp
import os
import re
import shutil

STUDY = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
ALL = open(os.path.join(STUDY, 'tests', 's14_names.txt')).read().split()
MD = os.path.join(STUDY, 'fighters', 'STATUS_CHECK_S15.md')


def main():
    base = {}
    for l in open(os.path.join(STUDY, 'fighters', 'STATUS_CHECK_S15_onefighter.md'), errors='replace'):
        m = re.match(r'\| (\w+) \| (.*) \| (.*) \| (SAFE|NOT SAFE.*|NOT RUN.*|RERUN.*) \|$', l.rstrip('\n'))
        if m:
            base[m.group(1)] = (m.group(2), m.group(3), m.group(4), 'one-fighter check')
    for l in open(os.path.join(STUDY, 'tests', 'logs', 's16_rows.tsv'), errors='replace') if os.path.exists(os.path.join(STUDY, 'tests', 'logs', 's16_rows.tsv')) else []:
        p = l.rstrip('\n').split('\t')
        if len(p) >= 9 and 'group fl' not in p[8] and 'group fx' not in p[8]:        # the float matches (other DLLs, other key script) are reported by hand, not in the table
            v = p[1]
            if (v.startswith('NOT RUN') or 'ended early / abnormally' in v) and p[0] in base and base[p[0]][2] == 'SAFE':
                continue                                # a run that never started does not undo a verdict from another match
            if v == 'SAFE' or v.startswith('NOT SAFE') or v.startswith('NOT RUN') or v.startswith('RERUN'):
                base[p[0]] = ('identical (%s/%s)' % (p[2], p[3]), p[4], v, p[8])
    ov = os.path.join(STUDY, 'tests', 's16_overrides.tsv')
    for l in open(ov, errors='replace') if os.path.exists(ov) else []:          # manual verdicts (a run whose row was never written)
        p = l.rstrip('\n').split('\t')
        if len(p) >= 3:
            base[p[0]] = ('see note', 'see note', p[1], p[2])
    out = ['# STATUS_CHECK_S15: fast check of the 96 status-source DLLs (run from fighters_bin_s15)', '',
           'Two methods. (1) One fighter per match: lifted run then source run, immobile dummy, scripted inputs, forced Final at fight frame ~1631.',
           '(2) Four fighters per match (tests\\s16_check.py): the same lifted / source pair for a whole match of 4 (p1 key script, p2..p4 driven by 21 status',
           'requests each, forced Final one entry after the other); a fighter is judged by its own hash-log lines. SAFE = those lines identical over all frames',
           'both runs have, both runs exited normally. NOT covered: being hit on purpose, grabs, items, other stages, the Final started by the button.', '',
           '| fighter | hash identical | final checked | verdict | method |', '|---|---|---|---|---|']
    safe, bad, notrun = [], [], []
    for f in ALL:
        r = base.get(f)
        if not r:
            out.append('| %s | - | - | NOT RUN | - |' % f)
            notrun.append(f)
            continue
        out.append('| %s | %s | %s | %s | %s |' % (f, r[0], r[1], r[2].replace('|', '/'), r[3]))
        (safe if r[2] == 'SAFE' else notrun if r[2].startswith(('NOT RUN', 'RERUN')) else bad).append(f)
        if r[2] == 'SAFE' and r[3] != 'one-fighter check':
            shutil.copy2(os.path.join(STUDY, 'fighters_bin_s15', f + '.dll'), os.path.join(STUDY, 'fighters_bin_s15_safe', f + '.dll'))
    out += ['', 'Totals: SAFE %d, NOT SAFE %d, NOT RUN %d (of %d).' % (len(safe), len(bad), len(notrun), len(ALL))]
    open(MD, 'w').write('\n'.join(out) + '\n')
    inst = [f for f in safe if os.path.exists(os.path.join(STUDY, 'fighters_bin_s15_safe', f + '.dll')) and
            not filecmp.cmp(os.path.join(STUDY, 'fighters_bin_s15_safe', f + '.dll'), os.path.join(STUDY, 'fighters_bin', f + '.dll'), shallow=False)]
    print('SAFE %d NOT SAFE %s NOT RUN %d' % (len(safe), bad, len(notrun)))
    print('to install (differ from fighters_bin): %s' % ' '.join(inst))


main()
