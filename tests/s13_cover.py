"""S13: coverage matches and the normal-speed check (every game through tests\\s11_run.py / s10_sweep.py, one at a time).
    python tests/s13_cover.py hit <fighter>        deterministic match F (scripted: shield, attacks, specials, final-smash flag) vs a level-9 CPU of a grab-heavy
                                                   fighter: lifted alone (a) and the status build with the real-call differential (b); hash diff; coverage union
    python tests/s13_cover.py orig <fighter>       the fighter's own-status sweep with the ORIGINAL ALONE (SSBU_FIGHTER_SRC=0): which forced kinds trap
    python tests/s13_cover.py normal <A> <B> ...   one normal-speed stock-1 match A vs B to its end (SSBU_DEBUG_MATCH is the only variable), garbage-motion scan
Rows: tests\\logs\\s13_cover.txt, s13_orig.txt, s13_normal.txt (json lines)."""
import json
import os
import re
import subprocess
import sys

STUDY = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.join(STUDY, 'tests'))
LOGS = os.path.join(STUDY, 'tests', 'logs')
X = os.path.join(STUDY, 'fighters_bin_s12x')
BASE = os.path.join(STUDY, 'fighters_bin')
DBG = os.path.join(STUDY, 'tests', 's13_final_dbg.txt')


def run_game(tag, binname, seq, match, extra=(), frames='2300', secs='200'):
    env = dict(os.environ, S11_SECS=secs, S11_RESULTS_MOD=match.split(',')[0].split('=')[1])
    args = [sys.executable, os.path.join(STUDY, 'tests', 's11_run.py'), tag, binname, seq, '0', 'SSBU_DEBUG_MATCH=' + match, 'SSBU_DETERMINISTIC=1',
            'SSBU_VK_PREP=0', 'SSBU_DEBUG_END=' + frames] + list(extra)
    for attempt in range(2):         # a game that never reaches the fight (menu sequence lost, 'hash lines 0') is run once more
        r = subprocess.run(args, capture_output=True, text=True, cwd=STUDY, env=env)
        line = (r.stdout.strip().splitlines() or ['?'])[-1]
        if 'hash lines 0 ' not in line and 'TIMEOUT' not in line:
            break
        line += ' [RERUN]'
    return line


def status_names(f):
    p = os.path.join(STUDY, 'fighters', 'work_s12', f, 'generated', 'status_bindings.inc')
    return re.findall(r'L2C_BIND\(\w+,\s*(\w+),', open(p).read()) if os.path.exists(p) else []


def prepare_x(f):
    """as s12_fighters.prepare_x: fighters_bin_s12x = the installed folder with F.dll = the status build (fighters_bin_s12)"""
    import shutil
    if not os.path.isdir(X):
        os.makedirs(X)
    for nm in os.listdir(BASE):
        if nm.endswith('.dll') and '.run' not in nm:
            dst = os.path.join(X, nm)
            if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(os.path.join(BASE, nm)):
                shutil.copy(os.path.join(BASE, nm), dst)
    shutil.copy(os.path.join(STUDY, 'fighters_bin_s12', f + '.dll'), os.path.join(X, f + '.dll'))


def union(f, reps, out):
    reps = [r for r in reps if os.path.exists(r)]
    subprocess.run([sys.executable, os.path.join(STUDY, 'tests', 's10_sweep.py'), 'union', 'lua2cpp_' + f] + reps + ['--out=' + out], capture_output=True, text=True, cwd=STUDY)
    names = set(status_names(f))
    res = {'bound': len(names), 'called': 0, 'equal': 0, 'differ': 0, 'called_never_compared': 0, 'never_called': 0, 'differing': []}
    seen = set()
    if os.path.exists(out):
        for l in open(out):
            k, calls, eq, df, first = (l.rstrip('\n').split('\t') + ['', '', '', '', ''])[:5]
            if k not in names:
                continue
            seen.add(k)
            if int(calls) > 0:
                res['called'] += 1
            if int(df):
                res['differ'] += 1
                res['differing'].append(k + ': ' + first[:150])
            elif int(eq):
                res['equal'] += 1
            elif int(calls) > 0:
                res['called_never_compared'] += 1
    res['never_called'] = len(names) - res['called']
    return res


def statuses_seen(tag):
    s = set()
    try:
        for l in open(os.path.join(LOGS, 's11_%s.fh.txt' % tag), errors='replace'):
            m = re.match(r'F \d+ e 0 st ([0-9a-f]+) ', l)
            if m:
                s.add(int(m.group(1), 16))
    except OSError:
        pass
    return s


def hit(f):
    prepare_x(f)
    xb = os.path.relpath(X, STUDY)
    opp = 'koopa' if f != 'koopa' else 'donkey'
    m = 'p1=%s,p2=%s,stage=end,cpu=9' % (f, opp)
    seq = 'seq_s13_hit.txt'
    dbg = 'SSBU_FIGHTER_DEBUG=' + DBG
    row = {'fighter': f, 'opponent': opp}
    row['a'] = run_game('%s_ha' % f, '-', seq, m, ['SSBU_FIGHTER_SRC=0', dbg])
    row['b'] = run_game('%s_hb' % f, xb, seq, m, ['SSBU_FIGHTER_DIFF=1', dbg])
    r = subprocess.run([sys.executable, os.path.join(STUDY, 'tests', 's11_run.py'), 'diff', '%s_ha' % f, '%s_hb' % f], capture_output=True, text=True, cwd=STUDY)
    row['hash'] = r.stdout.strip().splitlines()[0][:300] if r.stdout.strip() else '?'
    row['hash_identical'] = 'IDENTICAL' in row['hash']
    ma = re.search(r'lines (\d+)', row['hash'])
    st = statuses_seen('%s_ha' % f)
    row['status_kinds_seen_p1'] = len(st)
    reps = [os.path.join(LOGS, 's11_%s_d.report.txt' % f), os.path.join(LOGS, 's11_%s_hb.report.txt' % f)] + \
           [os.path.join(LOGS, 's10_sw_s12%s_%d.report.txt' % (f, n)) for n in range(1, 41)]
    row['cover_all'] = union(f, reps, os.path.join(LOGS, 's13_cover_%s.tsv' % f))
    row['cover_hit_only'] = union(f, [os.path.join(LOGS, 's11_%s_hb.report.txt' % f)], os.path.join(LOGS, 's13_cover_%s_hit.tsv' % f))
    log = open(os.path.join(LOGS, 's11_%s_ha.log' % f), errors='replace').read()
    row['final_flag_log'] = len(re.findall(r'is_flag\(FIGHTER_INSTANCE_WORK_ID_FLAG_FINAL\) = 1', log))
    row['hash_lines_a'] = sum(1 for _ in open(os.path.join(LOGS, 's11_%s_ha.fh.txt' % f), errors='replace')) if os.path.exists(os.path.join(LOGS, 's11_%s_ha.fh.txt' % f)) else 0
    with open(os.path.join(LOGS, 's13_cover.txt'), 'a') as out:
        out.write(json.dumps(row) + '\n')
    print(json.dumps(row, indent=1))


def orig(f):
    prepare_x(f)
    env = dict(os.environ, S10_OWN=f, S10_SEQ='seq_s12_menu.txt')
    tag = 's13o%s' % f
    for n in range(1, 41):
        p = os.path.join(LOGS, 's10_sw_%s_%d.report.txt' % (tag, n))
        if os.path.exists(p):
            os.remove(p)
    skipfile = os.path.join(STUDY, 'tests', 's10_skip_own_%s.txt' % f)
    old = open(skipfile).read() if os.path.exists(skipfile) else ''
    if os.path.exists(skipfile):
        os.remove(skipfile)
    r = subprocess.run([sys.executable, os.path.join(STUDY, 'tests', 's10_sweep.py'), 'run', tag, 'own', os.path.relpath(X, STUDY),
                        'SSBU_DEBUG_MATCH=p1=%s,p2=mario,stage=end,cpu=3' % f, 'SSBU_VK_PREP=0', 'SSBU_SPEED=0', 'SSBU_SKIP_MOVIES=1', 'SSBU_AUDIO_MUTE=1', 'SSBU_FIGHTER_SRC=0'],
                       capture_output=True, text=True, cwd=STUDY, env=env)
    new = open(skipfile).read().strip().splitlines() if os.path.exists(skipfile) else []
    if old and not os.path.exists(skipfile):
        pass
    row = {'fighter': f, 'original_alone_traps': new, 'tail': r.stdout.strip().splitlines()[-2:]}
    with open(skipfile, 'w') as out:                     # the skip file of the status build's sweep stays what it was
        out.write(old)
    with open(os.path.join(LOGS, 's13_orig.txt'), 'a') as out:
        out.write(json.dumps(row) + '\n')
    print(json.dumps(row, indent=1))


def normal(a, b, k):
    env = dict(os.environ, S11_SECS='480', S11_RESULTS_MOD=a)
    tag = 'n13_%d_%s_%s' % (k, a, b)
    args = [sys.executable, os.path.join(STUDY, 'tests', 's11_run.py'), tag, '-', 'seq_battle_play.txt', '0',
            'SSBU_DEBUG_MATCH=p1=%s,p2=%s,stage=end,cpu=9,stock=1' % (a, b), 'SSBU_SPEED=1', 'SSBU_SKIP_MOVIES=(unset)', 'SSBU_AUDIO_MUTE=(unset)', 'SSBU_FIXED_SEED=(unset)']
    r = subprocess.run(args, capture_output=True, text=True, cwd=STUDY, env=env)
    line = (r.stdout.strip().splitlines() or ['?'])[-1]
    log = open(os.path.join(LOGS, 's11_%s.log' % tag), errors='replace').read()
    row = {'tag': tag, 'a': a, 'b': b, 'runner': line, 'source_modules': re.findall(r'fighter source: (\w+)[^\n]{0,60}', log)[:6],
           'traps': len(re.findall(r'GUEST TRAP|HOST EXCEPTION', log)), 'health_lines': len(re.findall(r'\[health\]', log)),
           'garbage_motion': len(re.findall(r'\[health\][^\n]*motion [0-9a-f]{11,}', log))}
    with open(os.path.join(LOGS, 's13_normal.txt'), 'a') as out:
        out.write(json.dumps(row) + '\n')
    print(json.dumps(row, indent=1))


def main():
    cmd = sys.argv[1]
    if cmd == 'hit':
        for f in sys.argv[2:]:
            hit(f)
    elif cmd == 'orig':
        for f in sys.argv[2:]:
            orig(f)
    elif cmd == 'normal':
        names = sys.argv[2:]
        for k in range(0, len(names) - 1, 2):
            normal(names[k], names[k + 1], k // 2)


main()
