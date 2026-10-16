"""Round "four players": side build of the lifted main code with the helpers of runtime.h / neon.h / fpexact.h INLINED.

    python tests/p15_build.py compile <jobs> [prof15 dump ...]     gen_eh_o2\\*.c -> obj_p15\\*.obj (hot files of the dumps first)
    python tests/p15_build.py link                                 obj_eh_o1 with every file of obj_p15 in its place -> ssbu_game_p15.dll (+ .lib)
    python tests/p15_build.py hot <n> <dump ...>                   the n hottest generated files of the dumps

Why: clang 9 at -O1 runs only the "always inline" inliner, so every `static inline` helper of the lifted code (rd64,
wr32, adds64, cond, v_f3v, f3s, ...) is a real CALL in obj_eh_o1 (llvm-nm shows them as functions of each object). Here
the same sources and the same -O1 flags are used with ONE more definition on the command line,
`-Dinline=__inline__ __attribute__((always_inline))`: the generated C and the headers are untouched, semantics are the
same (no floating-point flag changes: -ffp-contract=off, no fast-math, default x86-64 target).
Nothing of the default build is written: gen_eh_o2\\, obj_eh_o1\\ and ssbu_game_eh_o1.dll are only read.
P15_OPT=-O2 / P15_CFLAGS="..." / P15_OBJ=<dir> / P15_DLL=<name> change level, flags, folder, DLL name. No game content."""
import collections
import concurrent.futures
import os
import subprocess
import sys
import time

HERE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, HERE)
os.chdir(HERE)
OBJ = os.environ.get('P15_OBJ', 'obj_p15')
DLL = os.environ.get('P15_DLL', 'ssbu_game_p15.dll')
os.environ['RECOMP_GEN'], os.environ['RECOMP_OBJ'], os.environ['RECOMP_DLL'] = 'gen_eh_o2', OBJ, DLL
os.environ['RECOMP_OPT'] = os.environ.get('P15_OPT', '-O1')
import build_opt  # noqa: E402

build_opt.EXTRA = ['-ffp-contract=off', '-Dinline=__inline__ __attribute__((always_inline))'] + os.environ.get('P15_CFLAGS', '').split()
GEN, BASE_OBJ = os.path.join(HERE, 'gen_eh_o2'), os.path.join(HERE, 'obj_eh_o1')
OBJDIR = os.path.join(HERE, OBJ)
if os.environ.get('P15_GEN'):       # N10 (new-fighter agent): `compile` reads another generated folder (e.g. gen_n3) with the same flags; unset = unchanged
    GEN = os.path.join(HERE, os.environ['P15_GEN'])
BASE, BUCKET = 0x7100000000, 0xC000


def hot_files(dumps):
    c = collections.Counter()
    for d in dumps:
        for line in open(d, errors='replace'):
            p = line.split()
            if len(p) >= 8 and p[1] == 'F' and p[3] == 'G':
                a = int(p[5], 16)
                if BASE <= a < 0x7200000000:
                    c['c_%04x.c' % ((a - BASE) // BUCKET)] += int(p[6])
    return c


def compile_one(name):
    src, obj = os.path.join(GEN, name), os.path.join(OBJDIR, name[:-2] + '.obj')
    if os.path.exists(obj) and os.path.getmtime(obj) >= os.path.getmtime(src):
        return name, 0, '', 0.0, 'up to date'
    tmp = os.path.join(OBJDIR, 'tmp_' + name[:-2] + '.obj')
    code, out, secs, note = build_opt.compile_file(src, tmp, ['-w', '-fno-strict-aliasing', '-I', HERE, '-I', GEN])
    if code == 0:
        os.replace(tmp, obj)
    return name, code, out, secs, note


def main():
    cmd = sys.argv[1]
    if cmd == 'hot':
        c = hot_files(sys.argv[3:])
        total = sum(c.values())
        acc = 0
        for name, n in c.most_common(int(sys.argv[2])):
            acc += n
            print('%s %d %.1f%% (cumulative %.1f%%)' % (name, n, 100.0 * n / total, 100.0 * acc / total))
        return 0
    if cmd == 'compile':
        jobs = int(sys.argv[2])
        os.makedirs(OBJDIR, exist_ok=True)
        hot = hot_files(sys.argv[3:])
        names = sorted(n for n in os.listdir(GEN) if n.startswith('c_') and n.endswith('.c'))
        if os.environ.get('P15_ONLY_HOT'):
            names = [n for n in names if n in hot][:10 ** 6]
            names = [n for n, _ in hot.most_common(int(os.environ['P15_ONLY_HOT'])) if n in set(names)]
        else:
            names.sort(key=lambda n: -hot.get(n, 0))
        t0 = time.time()
        done = failed = 0
        with open(os.path.join(OBJDIR, '_p15_log.txt'), 'a') as log:
            log.write('# %s %s %s jobs %d files %d\n' % (time.strftime('%H:%M:%S'), os.environ['RECOMP_OPT'], ' '.join(build_opt.EXTRA), jobs, len(names)))
            with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
                for name, code, out, secs, note in pool.map(compile_one, names):
                    done += 1
                    failed += bool(code)
                    if note != 'up to date':
                        log.write('%s exit %s %.0fs %s %s\n' % (name, code, secs, note, out.strip()[-300:] if code else ''))
                        log.flush()
                    if done % 100 == 0 or code:
                        print('%d of %d (%d failed) %.0fs %s' % (done, len(names), failed, time.time() - t0, name), flush=True)
        print('compile: %d files, %d failed, %.0fs' % (len(names), failed, time.time() - t0))
        return 1 if failed else 0
    if cmd == 'link':
        t2 = time.time()
        mine = set(n for n in os.listdir(OBJDIR) if n.endswith('.obj') and not n.startswith('tmp_'))
        # a file that fell back to -O0 whole (time limit) is SLOWER than the base's -O1 object: the base object is linked;
        # the last line of the log about a file decides (a later retry with a longer limit replaces the entry)
        last = {}
        logp = os.path.join(OBJDIR, '_p15_log.txt')
        if os.path.exists(logp):
            for line in open(logp):
                p = line.split()
                if p and p[0].startswith('c_'):
                    last[p[0][:-2] + '.obj'] = 'WHOLE FILE' in line
        skipped = sorted(n for n in mine if last.get(n))
        mine -= set(skipped)
        print('%d files of %s fell back to -O0 whole: the base objects are linked for them: %s' % (len(skipped), OBJ, ' '.join(skipped)))
        over_dir = os.environ.get('P15_OVERLAY')          # a second folder whose objects go before both (a few files at another level)
        over = set(n for n in os.listdir(over_dir) if n.endswith('.obj') and not n.startswith('tmp_')) if over_dir else set()
        objs = sorted(os.path.join(over_dir if n in over else OBJDIR if n in mine else BASE_OBJ, n) for n in os.listdir(BASE_OBJ) if n.endswith('.obj'))
        if over:
            print('%d objects from the overlay %s: %s' % (len(over), over_dir, ' '.join(sorted(over))))
        dll = os.path.join(HERE, DLL)
        rsp = dll + '.rsp'
        with open(rsp, 'w') as f:
            f.write('\n'.join('"%s"' % o.replace('\\', '/') for o in objs))
        shim = os.path.join(HERE, os.environ.get('RECOMP_SHIM', 'game_shim_eh.c'))
        r = subprocess.run([build_opt.build.CLANG, '-shared', '-O1', '-w', '-I', HERE, '-I', GEN, shim, '@' + rsp, '-o', dll], capture_output=True, text=True)
        print((r.stdout + r.stderr)[-3000:])
        print('link %s: exit %d, %d objects (%d of them from %s), %.0f MB, %.0fs' % (DLL, r.returncode, len(objs), len(mine), OBJ, os.path.getsize(dll) / 1048576.0 if os.path.exists(dll) else 0, time.time() - t2))
        return r.returncode
    return 2


if __name__ == '__main__':
    sys.exit(main())
