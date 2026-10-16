"""S13: back-to-back batch over fighters, using tests\\s12_fighters.py.
    python tests/s13_batch.py <fighter> [<fighter> ...]
Per fighter F (one game at a time; every game waits on tests\\QUIET_PLEASE inside s11_run.py / s10_sweep.py):
  1. s12_fighters.py run F       generic deterministic match vs level-3 CPU Mario + F vs F (lifted vs source hash) + differential match
  2. on a hash difference or a differing function of the differential match: bisect (hash) / exclude, rebuild, run again (max 2 rounds)
  3. s12_fighters.py sweep F     the fighter's own status sweep, BEFORE any install
  4. on a differing function: exclude it, rebuild, run + sweep again (max 2 rounds)
  5. install only when the last run row and the last sweep row are clean. Result line -> tests\\logs\\s13_results.txt
Rebuild = fighter_status.py cycle F with SSBU_FIGHTERS_ROOT=work_s12 SSBU_FIGHTER_BIN=fighters_bin_s12 (decompile, build, offline test).
Exclude = an entry in fighters\\work_s12\\tools_out\\status\\F_exclude.json (the function stays the game's own lifted code)."""
import json
import os
import subprocess
import sys
import time

STUDY = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
LOGS = os.path.join(STUDY, 'tests', 'logs')
S12 = os.path.join(STUDY, 'tests', 's12_fighters.py')
EXC = os.path.join(STUDY, 'fighters', 'work_s12', 'tools_out', 'status')


def say(msg):
    line = '%s %s' % (time.strftime('%H:%M:%S'), msg)
    print(line, flush=True)
    with open(os.path.join(LOGS, 's13_batch.log'), 'a') as f:
        f.write(line + '\n')


def s12(*args):
    r = subprocess.run([sys.executable, S12] + list(args), capture_output=True, text=True, cwd=STUDY, env=dict(os.environ, S11_SECS='200'))
    return r.stdout + r.stderr


def last_row(path, f):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    rows = [r for r in rows if r.get('fighter') == f]
    return rows[-1] if rows else None


def exclude(f, items):
    p = os.path.join(EXC, f + '_exclude.json')
    cur = json.load(open(p)) if os.path.exists(p) else {}
    for k, why in items.items():
        cur[k] = why
    with open(p, 'w') as out:
        json.dump(cur, out, indent=1, sort_keys=True)


def rebuild(f):
    env = dict(os.environ, SSBU_FIGHTERS_ROOT='work_s12', SSBU_FIGHTER_BIN='fighters_bin_s12')
    r = subprocess.run([sys.executable, os.path.join(STUDY, 'fighter_sdk', 'tools', 'fighter_status.py'), 'cycle', f], capture_output=True, text=True, cwd=STUDY, env=env)
    with open(os.path.join(LOGS, 's13_cycle_%s.log' % f), 'a') as out:
        out.write(r.stdout + r.stderr)
    lines = [l for l in r.stdout.splitlines() if l.startswith('test: %s' % f)]
    return lines[-1] if lines else 'no test line'


def row_clean(row):
    return bool(row and row.get('hash_generic') and row.get('hash_ff') and row.get('differ', 1) == 0 and row.get('status_differ', 1) == 0 and row.get('traps', 1) == 0)


def one(f):
    res = {'fighter': f, 'start': time.strftime('%H:%M:%S'), 'excluded_here': {}, 'rounds': 0}
    rows = os.path.join(LOGS, 's12_rows.txt')
    sweeps = os.path.join(LOGS, 's12_sweeps.txt')
    for rnd in range(3):
        res['rounds'] = rnd + 1
        say('%s: run (round %d)' % (f, rnd + 1))
        s12('run', f)
        row = last_row(rows, f)
        for retry in range(2):           # a game that never reached the fight (menu sequence lost: 'hash lines 0', TIMEOUT) is not a difference: run again
            if row and any(('hash lines 0 ' in row.get(k, '') or 'TIMEOUT' in row.get(k, '')) for k in ('a', 'b', 'a2', 'b2', 'd')):
                say('%s: a game did not reach the fight (%s); run again' % (f, [row.get(k, '')[:60] for k in ('a', 'b', 'a2', 'b2', 'd') if 'hash lines 0 ' in row.get(k, '') or 'TIMEOUT' in row.get(k, '')]))
                res.setdefault('reruns', []).append([row.get(k, '')[:80] for k in ('a', 'b', 'a2', 'b2', 'd') if 'hash lines 0 ' in row.get(k, '') or 'TIMEOUT' in row.get(k, '')])
                s12('run', f)
                row = last_row(rows, f)
        res['row'] = row
        if not row:
            res['verdict'] = 'NO ROW'
            return res
        if not (row.get('hash_generic') and row.get('hash_ff')):
            say('%s: hash difference or too short: %s' % (f, row.get('c', '')[:200]))
            if rnd == 2:
                res['verdict'] = 'HASH DIFFERENCE (not resolved)'
                return res
            s12('bisect', f)
            bp = os.path.join(LOGS, 's12_bisect_%s.txt' % f)
            cul = json.load(open(bp)).get('culprits', []) if os.path.exists(bp) else []
            if not cul:
                res['verdict'] = 'HASH DIFFERENCE (bisect found no function)'
                return res
            items = {c: 'S13: hash difference in a deterministic match (bisect); left lifted' for c in cul}
            exclude(f, items)
            res['excluded_here'].update(items)
            say('%s: excluded by bisect %s; rebuild: %s' % (f, cul, rebuild(f)))
            continue
        if row.get('differ', 1) != 0 or row.get('status_differ', 1) != 0:
            say('%s: differential match shows differing functions' % f)
            res['verdict'] = 'DIFFERENTIAL DIFFERS (see report)'
            return res
        say('%s: sweep' % f)
        s12('sweep', f)
        sw = last_row(sweeps, f)
        res['sweep'] = sw
        if sw and sw.get('differing'):
            if rnd == 2:
                res['verdict'] = 'SWEEP DIFFERS (not resolved)'
                return res
            items = {}
            for d in sw['differing']:
                k, _, why = d.partition(': ')
                items[k] = 'S13: sweep: ' + why[:140]
            exclude(f, items)
            res['excluded_here'].update(items)
            say('%s: excluded by sweep %s; rebuild: %s' % (f, list(items), rebuild(f)))
            continue
        if not sw or sw.get('runs', 0) == 0:
            res['verdict'] = 'NO SWEEP RESULT'
            return res
        if row_clean(row) and not sw.get('differing'):
            out = s12('install', f)
            res['verdict'] = 'installed' if 'installed' in out and 'NOT' not in out else 'NOT installed: ' + out.strip()[-120:]
        else:
            res['verdict'] = 'NOT installed (row not clean)'
        return res
    res['verdict'] = 'ROUNDS EXHAUSTED'
    return res


def main():
    for f in sys.argv[1:]:
        try:
            r = one(f)
        except Exception as e:                      # one fighter failing must not stop the batch
            r = {'fighter': f, 'verdict': 'DRIVER ERROR %r' % (e,)}
        r['end'] = time.strftime('%H:%M:%S')
        with open(os.path.join(LOGS, 's13_results.txt'), 'a') as out:
            out.write(json.dumps(r) + '\n')
        say('%s: %s' % (f, r.get('verdict')))


main()
