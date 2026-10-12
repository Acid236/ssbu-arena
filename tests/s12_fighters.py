"""S12: per-fighter status sources, proven by deterministic matches.
    python tests/s12_fighters.py run <fighter> [<fighter> ...]     the driver for each fighter (a, b, c, d, e below)
    python tests/s12_fighters.py bisect <fighter>                   find the status functions that make the hash logs differ
    python tests/s12_fighters.py install <fighter> ...              copy the fighter's status DLL into fighters_bin\\ (only if its row says proven)
For fighter F (DLLs: S12_BUILT = fighters_bin_s12 holds the status builds, S12_BASE = fighters_bin = what is installed):
  a  deterministic match F (player 1, tests\\seq_s12_generic.txt) vs level-3 CPU Mario, stage end, SSBU_DEBUG_END=1800 fight frames,
     lifted only (SSBU_FIGHTER_SRC=0)
  b  the same with fighters_bin_s12x = installed common + ACMD DLLs, only F.dll replaced by F's status build
  c  diff of the two hash logs (tests\\s11_run.py diff)
  d  F vs F (CPU, level 3) lifted / source, hash compared; and the generic match once more with SSBU_FIGHTER_DIFF=1
     (real-call differential of F's functions: report parsed)
  e  one row appended to tests\\logs\\s12_rows.txt (also .json)
Every game is started through tests\\s11_run.py (fast mode, waits on tests\\QUIET_PLEASE, fresh copy of the save, SSBU_VK_PREP=0
here). The sweep over F's own status kinds is NOT part of this driver. No game content in this file."""
import json
import os
import re
import shutil
import subprocess
import sys
import time

STUDY = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
LOGS = os.path.join(STUDY, 'tests', 'logs')
BUILT = os.path.join(STUDY, 'fighters_bin_s12')
BASE = os.path.join(STUDY, 'fighters_bin')
X = os.path.join(STUDY, 'fighters_bin_s12x')
FRAMES = os.environ.get('S12_FRAMES', '1800')
SEQ = 'seq_s12_generic.txt'
COMMON = ['SSBU_DETERMINISTIC=1', 'SSBU_VK_PREP=0', 'SSBU_DEBUG_END=' + FRAMES]


def prepare_x(f, with_status=True):
    """fighters_bin_s12x = copy of the installed folder (once), with F.dll = the status build (or the installed one)"""
    if not os.path.isdir(X):
        os.makedirs(X)
    for nm in os.listdir(BASE):
        if nm.endswith('.dll') and '.run' not in nm:
            dst = os.path.join(X, nm)
            if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(os.path.join(BASE, nm)):
                shutil.copy(os.path.join(BASE, nm), dst)
    src = os.path.join(BUILT if with_status else BASE, f + '.dll')
    shutil.copy(src, os.path.join(X, f + '.dll'))


def game(tag, binname, match, extra=()):
    args = [sys.executable, os.path.join(STUDY, 'tests', 's11_run.py'), tag, binname, SEQ, '0', 'SSBU_DEBUG_MATCH=' + match] + COMMON + list(extra)
    r = subprocess.run(args, capture_output=True, text=True, cwd=STUDY)
    line = (r.stdout.strip().splitlines() or ['?'])[-1]
    return line


def diff(a, b):
    r = subprocess.run([sys.executable, os.path.join(STUDY, 'tests', 's11_run.py'), 'diff', a, b], capture_output=True, text=True, cwd=STUDY)
    return r.stdout.strip()


def frames_of(tag):
    try:
        with open(os.path.join(LOGS, 's11_%s.fh.txt' % tag), errors='replace') as fh:
            return sum(1 for l in fh if l.startswith('F ') and ' e 0 ' in l and l.rstrip().endswith('%)'))
    except OSError:
        return 0


def status_names(f):
    p = os.path.join(STUDY, 'fighters', 'work_s12', f, 'generated', 'status_bindings.inc')
    if not os.path.exists(p):
        return []
    return re.findall(r'L2C_BIND\(\w+,\s*(\w+),', open(p).read())


def parse_report(tag, f):
    """-> dict for module lua2cpp_<f> from the differential report, and the per-name lines of the status functions"""
    p = os.path.join(LOGS, 's11_%s.report.txt' % tag)
    out = {'scripts_as_source': 0, 'called': 0, 'calls': 0, 'equal': 0, 'differ': 0, 'never': 0, 'status_called': 0, 'status_equal': 0, 'status_differ': 0, 'status_never': 0}
    if not os.path.exists(p):
        return out
    names = set(status_names(f))
    cur = None
    for l in open(p, errors='replace'):
        m = re.match(r'module lua2cpp_(\w+): (\d+) scripts as source; called in this run: (\d+) scripts, (\d+) calls', l)
        if m:
            cur = m.group(1)
            if cur == f:
                out.update(scripts_as_source=int(m.group(2)), called=int(m.group(3)), calls=int(m.group(4)))
            continue
        if cur != f:
            continue
        m = re.match(r'\s+differential, by script: (\d+) equal on every compared call, (\d+) differing, (\d+) called but never compared', l)
        if m:
            out.update(equal=int(m.group(1)), differ=int(m.group(2)), never=int(m.group(3)))
        m = re.match(r'\s+(\w+)\s+calls\s+(\d+)\s+equal\s+(\d+)\s+equal-interrupted\s+(\d+)\s+differ\s+(\d+)', l)
        if m and m.group(1) in names:
            out['status_called'] += 1
            if int(m.group(5)):
                out['status_differ'] += 1
            elif int(m.group(3)) + int(m.group(4)) == 0:
                out['status_never'] += 1
            else:
                out['status_equal'] += 1
    return out


def run_fighter(f):
    t0 = time.time()
    names = status_names(f)
    row = {'fighter': f, 'bound_status': len(names)}
    m1 = 'p1=%s,p2=mario,stage=end,cpu=3' % f
    prepare_x(f)
    xb = os.path.relpath(X, STUDY)
    row['a'] = game('%s_a' % f, '-', m1, ['SSBU_FIGHTER_SRC=0'])
    row['b'] = game('%s_b' % f, xb, m1)
    row['c'] = diff('%s_a' % f, '%s_b' % f)
    row['frames_generic'] = frames_of('%s_a' % f)
    same1 = 'IDENTICAL' in row['c'] and frames_of('%s_b' % f) >= 1500
    row['hash_generic'] = same1
    row['same_note'] = '' if same1 else 'not identical or too short'
    if same1:
        m2 = 'p1=%s,p2=%s,stage=end,cpu=3' % (f, f)
        row['a2'] = game('%s_a2' % f, '-', m2, ['SSBU_FIGHTER_SRC=0'])
        row['b2'] = game('%s_b2' % f, xb, m2)
        row['c2'] = diff('%s_a2' % f, '%s_b2' % f)
        row['frames_ff'] = frames_of('%s_a2' % f)
        row['hash_ff'] = 'IDENTICAL' in row['c2'] and frames_of('%s_b2' % f) >= 1500
        row['d'] = game('%s_d' % f, xb, m1, ['SSBU_FIGHTER_DIFF=1'])
        row.update(parse_report('%s_d' % f, f))
    row['secs'] = int(time.time() - t0)
    row['traps'] = sum(1 for k in ('a', 'b', 'a2', 'b2', 'd') if 'TRAP' in row.get(k, '') or 'GUEST TRAP' in row.get(k, ''))
    with open(os.path.join(LOGS, 's12_rows.txt'), 'a') as out:
        out.write(json.dumps(row) + '\n')
    print(json.dumps(row, indent=1))
    return row


def first_frame(c):
    m = re.search(r'at line (\d+) of', c)
    return int(m.group(1)) if m else 10 ** 9


def bisect(f):
    """greedy: find status functions to force lifted until the hash log of the source run equals the lifted one"""
    names = status_names(f)
    prepare_x(f)
    xb = os.path.relpath(X, STUDY)
    m1 = 'p1=%s,p2=mario,stage=end,cpu=3' % f
    lifted = []
    if not os.path.exists(os.path.join(LOGS, 's11_%s_a.fh.txt' % f)):
        game('%s_a' % f, '-', m1, ['SSBU_FIGHTER_SRC=0'])
    n = 0

    def probe(subset):
        nonlocal n
        n += 1
        tag = '%s_bis%d' % (f, n)
        game(tag, xb, m1, ['SSBU_FIGHTER_LIFTED=' + ','.join(subset)] if subset else [])
        c = diff('%s_a' % f, tag)
        return first_frame(c), c
    base, c = probe(lifted)
    culprits = []
    while base < 10 ** 9 and len(culprits) < 8:
        rest = [x for x in names if x not in lifted]
        lo, hi = 0, len(rest)
        while lo < hi:
            mid = (lo + hi) // 2
            fr, _ = probe(lifted + rest[:mid + 1])
            if fr > base:
                hi = mid
            else:
                lo = mid + 1
        if lo >= len(rest):
            print('no single function moves the first difference; stopping')
            break
        culprits.append(rest[lo])
        lifted.append(rest[lo])
        base, c = probe(lifted)
        print('culprit %s; first difference now at line %s' % (rest[lo], base if base < 10 ** 9 else 'none'))
    with open(os.path.join(LOGS, 's12_bisect_%s.txt' % f), 'w') as out:
        out.write(json.dumps({'fighter': f, 'culprits': culprits, 'final': c}) + '\n')
    print(culprits)


def sweep(f):
    """status sweep over F's own kinds (+ the common SPECIAL_* kinds) on the ground and in the air, under the real-call differential,
    with F's status build (fighters_bin_s12x). -> row appended to tests\\logs\\s12_sweeps.txt"""
    prepare_x(f)
    env = dict(os.environ, S10_OWN=f, S10_SEQ='seq_s12_menu.txt')
    tag = 's12%s' % f
    for n in range(1, 41):
        p = os.path.join(LOGS, 's10_sw_%s_%d.report.txt' % (tag, n))
        if os.path.exists(p):
            os.remove(p)
    skipfile = os.path.join(STUDY, 'tests', 's10_skip_own_%s.txt' % f)
    if os.path.exists(skipfile):
        os.remove(skipfile)
    r = subprocess.run([sys.executable, os.path.join(STUDY, 'tests', 's10_sweep.py'), 'run', tag, 'own', os.path.relpath(X, STUDY),
                        'SSBU_DEBUG_MATCH=p1=%s,p2=mario,stage=end,cpu=3' % f, 'SSBU_VK_PREP=0', 'SSBU_SPEED=0', 'SSBU_SKIP_MOVIES=1', 'SSBU_AUDIO_MUTE=1'],
                       capture_output=True, text=True, cwd=STUDY, env=env)
    reps = [os.path.join(LOGS, 's10_sw_%s_%d.report.txt' % (tag, n)) for n in range(1, 41) if os.path.exists(os.path.join(LOGS, 's10_sw_%s_%d.report.txt' % (tag, n)))]
    tsv = os.path.join(LOGS, 's12_sweep_%s.tsv' % f)
    u = subprocess.run([sys.executable, os.path.join(STUDY, 'tests', 's10_sweep.py'), 'union', 'lua2cpp_' + f] + reps + ['--out=' + tsv], capture_output=True, text=True, cwd=STUDY, env=env)
    names = set(status_names(f))
    row = {'fighter': f, 'runs': len(reps), 'skip': open(skipfile).read().strip().splitlines() if os.path.exists(skipfile) else [], 'tail': r.stdout.strip().splitlines()[-2:],
           'status_called': 0, 'status_equal': 0, 'status_differ': 0, 'status_never': 0, 'differing': []}
    if os.path.exists(tsv):
        for l in open(tsv):
            k, calls, eq, df, first = (l.rstrip('\n').split('\t') + ['', '', '', '', ''])[:5]
            if k in names:
                row['status_called'] += 1
                if int(df):
                    row['status_differ'] += 1
                    row['differing'].append(k + ': ' + first[:150])
                elif int(eq):
                    row['status_equal'] += 1
                else:
                    row['status_never'] += 1
    with open(os.path.join(LOGS, 's12_sweeps.txt'), 'a') as out:
        out.write(json.dumps(row) + '\n')
    print(json.dumps(row, indent=1))
    return row


def install(f):
    """fighters_bin\\<f>.dll := the status build, only when the LAST row of the fighter says: both hash logs identical (>= 1500 frames),
    0 differing in the differential. Backup of the old DLL in fighters_bin_backup_<date>_s12. Row appended to fighters\\STATUS_PROVEN.md."""
    rows = [json.loads(l) for l in open(os.path.join(LOGS, 's12_rows.txt')) if l.strip()]
    row = [r for r in rows if r['fighter'] == f][-1]
    if not (row.get('hash_generic') and row.get('hash_ff') and row.get('differ', 1) == 0 and row.get('status_differ', 1) == 0 and row.get('traps', 1) == 0):
        print('%s: NOT installed (row does not say proven)' % f)
        return False
    bk = os.path.join(STUDY, 'fighters_bin_backup_%s_s12' % time.strftime('%Y%m%d'))
    os.makedirs(bk, exist_ok=True)
    if not os.path.exists(os.path.join(bk, f + '.dll')):
        shutil.copy(os.path.join(BASE, f + '.dll'), os.path.join(bk, f + '.dll'))
    shutil.copy(os.path.join(BUILT, f + '.dll'), os.path.join(BASE, f + '.dll'))
    xp = os.path.join(STUDY, 'fighters', 'work_s12', 'tools_out', 'status', f + '_exclude.json')
    excluded = len(json.load(open(xp))) if os.path.exists(xp) else 0
    never = row['bound_status'] - row['status_called'] + row['status_never']
    p = os.path.join(STUDY, 'fighters', 'STATUS_PROVEN.md')
    if not os.path.exists(p):
        with open(p, 'w') as out:
            out.write('# Per-fighter status sources installed in fighters_bin\\ (S1 section 17)\n\n| fighter | status functions as source | lifted by exclusion | never called / never compared | status functions compared and equal | frames compared (generic vs CPU Mario / F vs F) | date |\n|---|---|---|---|---|---|---|\n')
    with open(p, 'a') as out:
        out.write('| %s | %d | %d | %d | %d | %d / %d | %s |\n' % (f, row['bound_status'], excluded, never, row['status_equal'], row['frames_generic'], row['frames_ff'], time.strftime('%Y-%m-%d')))
    print('%s: installed' % f)
    return True


def main():
    cmd = sys.argv[1]
    if cmd == 'install':
        for f in sys.argv[2:]:
            install(f)
    if cmd == 'run':
        for f in sys.argv[2:]:
            run_fighter(f)
    elif cmd == 'sweep':
        for f in sys.argv[2:]:
            sweep(f)
    elif cmd == 'bisect':
        bisect(sys.argv[2])


main()
