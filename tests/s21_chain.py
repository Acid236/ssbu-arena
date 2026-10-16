"""S21: decompile + build + offline gate of one work tree with a CHOSEN copy of the generator (so that a generator being
edited meanwhile does not mix into a running chain). Same steps as tests/s18_build.py then tests/s18_gate.py.

    SSBU_FIGHTERS_ROOT=<tree> SSBU_FIGHTER_BIN=<bin> S21_TOOLS=fighter_sdk/tools_s20frozen python tests/s21_chain.py <names file> [nodecompile]
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(STUDY, os.environ.get('S21_TOOLS', 'fighter_sdk/tools')))
import fighter_status as FS      # noqa: E402

print('tools:', FS.__file__, flush=True)


def wait_free():
    while any(os.path.exists(os.path.join(HERE, n)) for n in ('QUIET_PLEASE', 'OWNER_PLAYING')):
        time.sleep(20)


def build(names):
    FS.cmd_sdk()
    todo, failed_all = names, []
    for rounds in range(8):
        again, failed = FS.cmd_build(todo)
        failed_all += failed
        if not again:
            break
        print('round %d: refused by the compiler in: %s' % (rounds, ' '.join(again)), flush=True)
        FS.cmd_decompile(again, quiet=True)
        todo = again
    print('S21 BUILD DONE: failed modules: %s' % (' '.join(failed_all) or 'none'), flush=True)


def gate(todo):
    for rounds in range(6):
        wait_free()
        results, again = FS.cmd_test(todo)
        missing = [m for m in todo if m not in results]
        print('gate round %d: tested %d, no result for: %s; with refusals: %s' % (rounds, len(results), ' '.join(missing) or 'none', ' '.join(again) or 'none'), flush=True)
        if not again:
            break
        FS.cmd_decompile(again, quiet=True)
        for k in range(6):
            bad, failed = FS.cmd_build(again if k == 0 else bad)
            if not bad:
                break
            FS.cmd_decompile(bad, quiet=True)
        todo = again
    FS.cmd_table()
    print('S21 GATE DONE', flush=True)


def main():
    names = open(sys.argv[1]).read().split()
    if 'nodecompile' not in sys.argv[2:]:
        FS.cmd_decompile(names)
    build(names)
    if 'nogate' not in sys.argv[2:]:
        gate(names)


if __name__ == '__main__':
    main()
