"""Test of tools/lifter/build_opt.py's Linux / macOS compile scheduling, with a fake compiler (no clang, no game files):

    python tests/build_opt_sched_test.py [linux | macos | windows]      (default: all three)

Checks: the compilers' reservations never exceed the shared RAM (MEM_BUDGET) and are all given back; on Linux a file over
its reservation is compiled again with twice as much (up to the budget); on Linux / macOS a ladder retry that would leave
the same functions unoptimised as the attempt that just failed is skipped; on Windows (no RECOMP_TARGET) nothing of that
happens: no reservations, every ladder step as before.
"""
import concurrent.futures
import os
import subprocess
import sys
import tempfile
import threading
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
LIFTER = os.path.join(HERE, '..', 'tools', 'lifter')
GB = 1 << 30
# file -> (statements of each function, GB it really needs, seconds at -O1; None: always over the time limit unless at least
# `ok_from` functions are unoptimised)
SPEC = dict({'small%02d' % i: ([500, 300], 0.4, 0.02, 0) for i in range(24)},
            huge=([215493, 2846, 198], 12.0, None, 99),     # like c_00a3.c: over every limit
            same=([77061, 1186], 3.0, None, 99),            # like c_03d9.c: steps 1 and 2 = step 0
            mid=([30000, 6000], 2.5, 0.02, 0),              # needs more than its first reservation
            lad=([16581, 2101, 1717], 1.0, None, 2))        # like c_03fc.c: fits once two functions are unoptimised


def child(target):
    if target != 'windows':
        os.environ['RECOMP_TARGET'] = target
    sys.modules['build'] = types.ModuleType('build')         # build.py / build_nro.py are not needed by compile_file
    sys.modules['build_nro'] = types.ModuleType('build_nro')
    sys.path.insert(0, LIFTER)
    import build_opt as B
    if target != 'windows':
        B.ram_bytes = lambda: 14 * GB                        # a 16 GB machine as Linux reports it (a Steam Deck)
    B.limit_memory(8)
    lock = threading.Lock()
    calls, peak = [], [0]

    def fake_run_limited(cmd, limit, mem=0):
        name = os.path.basename(cmd[-3])[:-2]
        funcs, need, secs, ok_from = SPEC[name]
        hdr = cmd[cmd.index('-include') + 1] if '-include' in cmd else None
        n_off = sum(1 for l in open(hdr) if l.startswith('void ')) if hdr else 0
        with lock:
            calls.append((name, n_off, mem))
            peak[0] = max(peak[0], B._mem_used)
            assert B._mem_used <= max(B.MEM_BUDGET, 0), 'reservations over the budget'
        if B.MEM_LIMIT and need * GB > (mem or B.MEM_LIMIT):
            return None, B.OOM, 0.005
        if secs is None and n_off < ok_from:
            return None, '', 0.005
        time.sleep(secs or 0.005)
        open(cmd[-1], 'w').close()
        return 0, '', secs or 0.005

    class Done:
        returncode, stdout, stderr = 0, '', ''

    def fake_run(cmd, **kw):
        with lock:
            calls.append((os.path.basename(cmd[-3])[:-2], 'O0', None))
        return Done()

    B.run_limited = fake_run_limited
    B.subprocess = types.SimpleNamespace(run=fake_run)
    d = tempfile.mkdtemp()
    for n, (funcs, _, _, _) in SPEC.items():
        with open(os.path.join(d, n + '.c'), 'w') as f:
            for i, k in enumerate(funcs):
                f.write('void f%d(Ctx *c) {\n' % i + 'x;\n' * k + '}\n')
    order = sorted(SPEC, key=lambda n: -os.path.getsize(os.path.join(d, n + '.c')))
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        res = dict(pool.map(lambda n: (n, B.compile_file(os.path.join(d, n + '.c'), os.path.join(d, n + '.obj'), [])), order))
    import shutil
    shutil.rmtree(d, ignore_errors=True)
    steps = {n: [c[1] for c in calls if c[0] == n] for n in ('huge', 'same', 'mid', 'lad')}
    mems = {n: [c[2] for c in calls if c[0] == n] for n in ('huge', 'same', 'mid')}
    bad = []
    if any(r[0] for r in res.values()):
        bad.append('a compile failed: %r' % {n: r for n, r in res.items() if r[0]})
    if B._mem_used:
        bad.append('reservations not given back: %d' % B._mem_used)
    if target == 'windows':
        if B.MEM_BUDGET or any(c[2] for c in calls):
            bad.append('reservations on Windows')
        if steps['same'] != [1, 1, 1, 'O0']:
            bad.append('Windows ladder changed: %r' % steps['same'])
    else:
        budget = 10 * GB
        if B.MEM_BUDGET != budget:
            bad.append('budget %r, expected 10 GB' % B.MEM_BUDGET)
        if target == 'linux':
            # same: 2.9 GB reservation over its 3 GB need -> 5.9 GB, then the time limit; the identical steps 1 and 2 skipped
            if steps['same'] != [1, 1, 'O0'] or mems['same'][1] <= mems['same'][0]:
                bad.append('same: %r %r' % (steps['same'], mems['same']))
            if mems['mid'] != [1.5 * GB, 3 * GB]:
                bad.append('mid reservations %r' % mems['mid'])
            if B.MEM_FLOOR[0] != (1536 << 20) * 5 // 4:            # mid ran out at the floor: raised by a quarter, once
                bad.append('floor %r' % B.MEM_FLOOR[0])
            if mems['huge'][-2] != budget:
                bad.append('huge did not reach the budget: %r' % mems['huge'])
        else:
            if steps['same'] != [1, 'O0']:
                bad.append('same: %r' % steps['same'])
        if steps['lad'] != [0, 1, 3]:
            bad.append('lad: %r' % steps['lad'])
        if peak[0] > budget:
            bad.append('peak %d over the budget' % peak[0])
    print('%-7s %s   ladder %s   peak reserved %.1f GB' % (target, 'ok' if not bad else 'FAILED: ' + '; '.join(bad), steps, peak[0] / GB))
    return 1 if bad else 0


if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == '--child':
        sys.exit(child(sys.argv[2]))
    targets = sys.argv[1:] or ['linux', 'macos', 'windows']
    rc = 0
    for t in targets:                       # one process each: build_opt reads RECOMP_TARGET at import
        rc |= subprocess.call([sys.executable, os.path.abspath(__file__), '--child', t])
    sys.exit(rc)
