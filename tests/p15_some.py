"""Round "four players": compile a FEW generated files with tests/p15_build.py's flags and a long time limit.
    P15_OBJ=<dir> P15_OPT=-O2 python tests/p15_some.py <seconds limit> c_04cb.c c_04cc.c ...
No game content."""
import concurrent.futures
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
limit = sys.argv[1]
os.environ['RECOMP_TIME_LIMIT'] = limit
import p15_build as b  # noqa: E402

os.makedirs(b.OBJDIR, exist_ok=True)
names = sys.argv[2:]
t = time.time()
with concurrent.futures.ThreadPoolExecutor(max(1, len(names))) as pool:
    for r in pool.map(b.compile_one, names):
        print(r[0], 'exit', r[1], '%.0fs' % r[3], r[4], flush=True)
        if r[4] != 'up to date':
            with open(os.path.join(b.OBJDIR, '_p15_log.txt'), 'a') as log:
                log.write('%s exit %s %.0fs %s (p15_some.py, limit %s s)\n' % (r[0], r[1], r[3], r[4], limit))
print('%.0fs' % (time.time() - t))
