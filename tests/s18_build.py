"""S18: SDK + build of a work tree WITHOUT the offline test (no exe is started): fighter_status.py's own steps
sdk -> build -> (functions the compiler refuses go to the exclude file) -> decompile those fighters -> build, until clean.

    SSBU_FIGHTERS_ROOT=work_s18 SSBU_FIGHTER_BIN=fighters_bin_s18 S2_JOBS=4 SSBU_BUILD_JOBS=3 python tests/s18_build.py [names file]

S2_JOBS=4 builds 2 fighters at a time, SSBU_BUILD_JOBS=3 compiles each: 6 compiler processes at most.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'fighter_sdk', 'tools'))
import fighter_status as FS      # noqa: E402


def main():
    names = open(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 's14_names.txt')).read().split()
    FS.cmd_sdk()
    todo = names
    failed_all = []
    for rounds in range(8):
        again, failed = FS.cmd_build(todo)
        failed_all += failed
        if not again:
            break
        print('round %d: refused by the compiler in: %s' % (rounds, ' '.join(again)), flush=True)
        FS.cmd_decompile(again, quiet=True)
        todo = again
    print('S18 BUILD DONE: failed modules: %s' % (' '.join(failed_all) or 'none'), flush=True)


if __name__ == '__main__':
    main()
