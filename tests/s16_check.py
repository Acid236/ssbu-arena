"""S16: fast check of four fighters at once.
    python tests/s16_check.py <name> <f1> <f2> <f3> <f4> [nofinal=<entries>] [bin=<folder>]
One lifted run (SSBU_FIGHTER_SRC=0) and one source run of the same match, started at the same time (two games at once, own save copies):
SSBU_DEBUG_MATCH=p1=f1,p2=f2,p2=human,p3=f3,p4=f4,stage=end, SSBU_DETERMINISTIC=1, SSBU_FIGHTER_DEBUG=tests\\s16_dbg_<name>.txt (made by s16_gen_dbg.py:
positions, 21 status requests per entry 1..3, the forced FINAL one entry after the other), key script tests\\seq_s15_check.txt for entry 0.
A fighter's verdict compares ITS OWN hash-log lines (all fields but the running hash H) over the frames both runs have; a difference of another
entry that never reaches this one does not count against it. Rows -> tests\\logs\\s16_rows.tsv (one per fighter; 'group <name> entry k'). Fewer than 4 names
= a match with that many (2 or 3 players). No game content in this file."""
import os
import re
import subprocess
import sys
import time

STUDY = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
LOGS = os.path.join(STUDY, 'tests', 'logs')
DLC = {'jack', 'brave', 'buddy', 'dolly', 'master', 'tantan', 'pickel', 'edge', 'eflame', 'elight', 'demon', 'trail', 'packun'}
FINAL_AT = [1625, 2170, 2710, 3250]
END = os.environ.get('S16_END', '3700')


def start(tag, names, src, dbg, bindir):
    args = [sys.executable, os.path.join(STUDY, 'tests', 's16_run.py'), tag, bindir, os.environ.get('S16_SEQ', 'seq_s15_check.txt')]
    m = 'p1=%s,p2=%s,p2=human' % (names[0], names[1])
    for i in range(2, len(names)):
        m += ',p%d=%s' % (i + 1, names[i])
    args += ['SSBU_DEBUG_MATCH=' + m + ',stage=end', 'SSBU_DETERMINISTIC=1', 'SSBU_VK_PREP=0', 'SSBU_DEBUG_END=' + END, 'SSBU_FIGHTER_DEBUG=' + dbg]
    if not any(n in DLC for n in names):
        args.append('SSBU_DLC_LIST=tests\\vk13_nodlc.txt')
    if not src:
        args.append('SSBU_FIGHTER_SRC=0')
    return subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=STUDY, env=dict(os.environ))


def entry_lines(tag, k):
    out = []
    try:
        for l in open(os.path.join(LOGS, 's11_%s.fh.txt' % tag), errors='replace'):
            if l.startswith('F ') and l.rstrip().endswith('%)') and (' e %d ' % k) in l[:20]:
                out.append(re.sub(r' H [0-9a-f]+ ', ' ', l.rstrip()))
    except OSError:
        pass
    return out


def held(lines, start_frame):
    best, cur, n = None, None, 0
    for l in lines:
        m = re.match(r'F (\d+) e \d+ st (\w+) ', l)
        if not m or int(m.group(1)) < start_frame:
            continue
        if m.group(2) == cur:
            n += 1
        else:
            cur, n = m.group(2), 1
        if cur != '0' and n >= 100:
            best = cur
    return best


def main():
    name = sys.argv[1]
    names = [a for a in sys.argv[2:] if '=' not in a]
    opts = dict(a.split('=', 1) for a in sys.argv[2:] if '=' in a)
    bindir = opts.get('bin', 'fighters_bin_s15')
    try:                                                # two chains of groups may run at the same time: a group is taken once
        os.close(os.open(os.path.join(LOGS, 's16_lock_%s' % name), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        print('group %s already taken' % name)
        return
    dbg = 'tests\\s16_dbg_%s.txt' % name
    gen = [sys.executable, os.path.join(STUDY, 'tests', 's16_gen_dbg.py'), os.path.join(STUDY, dbg)]
    if 'nofinal' in opts:
        gen.append('nofinal=' + opts['nofinal'])
    if 'float' in opts:
        gen.append('float=' + opts['float'])
    subprocess.run(gen, cwd=STUDY, check=True)
    t0 = time.time()
    ta, tb = 's16_%s_a' % name, 's16_%s_b' % name
    pa, pb = start(ta, names, False, dbg, bindir), start(tb, names, True, dbg, bindir)
    la = (pa.communicate()[0].strip().splitlines() or ['?'])[-1]
    lb = (pb.communicate()[0].strip().splitlines() or ['?'])[-1]
    secs = time.time() - t0
    nofinal = set(int(x) for x in opts.get('nofinal', '').split(',') if x)
    with open(os.path.join(LOGS, 's16_rows.tsv'), 'a') as out:
        for k, f in enumerate(names):
            A, B = entry_lines(ta, k), entry_lines(tb, k)
            n = min(len(A), len(B))
            first = next((i for i in range(n) if A[i] != B[i]), -1)
            exited = 'EXITED 0' in la and 'EXITED 0' in lb
            fin = 'final not checked (nofinal)' if k in nofinal else None
            if fin is None:
                fa, fb = held(A, FINAL_AT[k] + 6), held(B, FINAL_AT[k] + 6)
                fin = 'yes (status %s / %s)' % (fa, fb) if fa and fb else ('lifted only (%s)' % fa if fa else 'final not seen')
            if not A or not B:
                v = 'NOT RUN: a run never reached the fight (a: %s; b: %s)' % (la[:70], lb[:70])
            elif first >= 0:
                v = 'NOT SAFE: first difference at entry line %d (%s) lifted `%s` source `%s`' % (first + 1, A[first].split()[1], A[first][:110], B[first][:110])
            elif 'TRAP' in la and 'TRAP' in lb and len(A) == len(B):
                v = 'RERUN: both runs trapped at the same frame (%s): the forced Final is not forceable here' % A[-1].split()[1]
            elif n < 3000 or not exited:
                v = 'NOT SAFE: hash identical for %d frames but the runs ended early / abnormally (a: %s; b: %s)' % (n, la[:70], lb[:70])
            else:
                v = 'SAFE'
            row = '\t'.join([f, v, str(len(A)), str(len(B)), fin, la[:120], lb[:120], '%.0f' % secs, 'group %s entry %d (%s)' % (name, k, ' '.join(names))])
            out.write(row + '\n')
            print(row[:300], flush=True)


if __name__ == '__main__':
    main()
