"""S15: fast check of fighters_bin_s15 (status sources), one pair of runs per fighter.
    python tests/s15_check.py <fighter> [<fighter> ...]
Per fighter F: run A = lifted (SSBU_FIGHTER_SRC=0), run B = source, both SSBU_FIGHTER_BIN=fighters_bin_s15, tests\\seq_s15_check.txt,
SSBU_DEBUG_MATCH=p1=F,p2=<dummy>,p2=human,stage=end, SSBU_FIGHTER_DEBUG=tests\\s15_dbg.txt, SSBU_DETERMINISTIC=1, SSBU_DEBUG_END=S15_FRAMES.
The dummy is mario (luigi when F is mario). DLC fighters (S15_NODLC_SKIP list below) run without SSBU_DLC_LIST. Row -> tests\\logs\\s15_rows.tsv.
Runs go through tests\\s11_run.py (waits on tests\\QUIET_PLEASE, fresh save copy). No game content in this file."""
import os
import re
import subprocess
import sys
import time

STUDY = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
LOGS = os.path.join(STUDY, 'tests', 'logs')
FRAMES = os.environ.get('S15_FRAMES', '1950')
DLC = {'jack', 'brave', 'buddy', 'dolly', 'master', 'tantan', 'pickel', 'edge', 'eflame', 'elight', 'demon', 'trail', 'packun'}
SEQ = os.environ.get('S15_SEQ', 'seq_s15_check.txt')
DBG = os.environ.get('S15_DBG', 'tests\\s15_dbg.txt')


def game(tag, f, src, extra):
    dummy = 'luigi' if f == 'mario' else 'mario'
    args = [sys.executable, os.path.join(STUDY, 'tests', 's11_run.py'), tag, 'fighters_bin_s15', SEQ, '0',
            'SSBU_DEBUG_MATCH=p1=%s,p2=%s,p2=human,stage=end' % (f, dummy), 'SSBU_DETERMINISTIC=1', 'SSBU_VK_PREP=0',
            'SSBU_DEBUG_END=' + FRAMES, 'SSBU_FIGHTER_DEBUG=' + DBG]
    if f not in DLC:
        args.append('SSBU_DLC_LIST=tests\\vk13_nodlc.txt')
    if not src:
        args.append('SSBU_FIGHTER_SRC=0')
    args += extra
    env = dict(os.environ, S11_SECS=os.environ.get('S15_SECS', '170'))
    while os.path.exists(os.path.join(STUDY, 'tests', 'OWNER_PLAYING')):      # the owner is playing: no game may start
        time.sleep(5)
    r = subprocess.run(args, capture_output=True, text=True, cwd=STUDY, env=env)
    return (r.stdout.strip().splitlines() or ['?'])[-1]


def diff(a, b):
    r = subprocess.run([sys.executable, os.path.join(STUDY, 'tests', 's11_run.py'), 'diff', a, b], capture_output=True, text=True, cwd=STUDY)
    return r.stdout.strip()


def nlines(tag):
    try:
        with open(os.path.join(LOGS, 's11_%s.fh.txt' % tag), errors='replace') as fh:
            return sum(1 for l in fh if l.startswith('F ') and ' e 0 ' in l and l.rstrip().endswith('%)'))
    except OSError:
        return 0


def one(f, extra):
    t0 = time.time()
    ta, tb = 's15_%s_a' % f, 's15_%s_b' % f
    la = game(ta, f, False, extra)
    lb = game(tb, f, True, extra)
    d = diff(ta, tb)
    na, nb = nlines(ta), nlines(tb)
    ident = 'IDENTICAL' in d
    m = re.search(r'FIRST DIFFERENCE at line (\d+)', d)
    fin = 'final st37 seen a/b: %s/%s' % tuple('y' if any(' e 0 st 37 ' in l for l in open(os.path.join(LOGS, 's11_%s.fh.txt' % t), errors='replace')) else 'n' for t in (ta, tb))
    row = '\t'.join([f, 'identical' if ident else ('DIFF line ' + m.group(1) if m else 'NODATA'), str(na), str(nb), fin, la[:140], lb[:140], '%.0f' % (time.time() - t0)])
    print(row, flush=True)
    with open(os.path.join(LOGS, 's15_rows.tsv'), 'a') as out:
        out.write(row + '\n')
        if not ident:
            out.write('   ' + d.replace('\n', '\n   ')[:1500] + '\n')


if __name__ == '__main__':
    extra = [a for a in sys.argv[1:] if '=' in a]
    for f in [a for a in sys.argv[1:] if '=' not in a]:
        one(f, extra)
