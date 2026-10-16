"""S18: the offline gate (fighter_status.py's 3-pass synthetic differential) on a work tree, with the refusal loop:
test -> functions that differ or stop go to the exclude file -> regenerate those fighters -> build -> test again.

    SSBU_FIGHTERS_ROOT=work_s18 SSBU_FIGHTER_BIN=fighters_bin_s18 S2_JOBS=4 SSBU_BUILD_JOBS=3 python tests/s18_gate.py <names file>

Waits while tests\\QUIET_PLEASE or tests\\OWNER_PLAYING exists before each round (fighter_status waits for the first
only). One exe at a time (fighter_status.cmd_test runs the modules one after the other).
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'fighter_sdk', 'tools'))
import fighter_status as FS      # noqa: E402


def wait_free():
    while any(os.path.exists(os.path.join(HERE, n)) for n in ('QUIET_PLEASE', 'OWNER_PLAYING')):
        time.sleep(20)


def main():
    todo = open(sys.argv[1]).read().split()
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
    print('S18 GATE DONE', flush=True)


if __name__ == '__main__':
    main()
