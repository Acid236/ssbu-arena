"""S21 guard: regenerate (decompile only) the fighters named in a file into a SCRATCH tree with a chosen generator copy.
    SSBU_FIGHTERS_ROOT=<scratch tree> S21_TOOLS=fighter_sdk/tools_s20frozen python tests/s21_regen.py <names file>"""
import os
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), os.environ.get('S21_TOOLS', 'fighter_sdk/tools')))
import fighter_status as FS      # noqa: E402
if __name__ == '__main__':
    assert os.environ.get('SSBU_FIGHTERS_ROOT', '').startswith('work_s21g'), 'scratch trees only'
    print('tools:', FS.__file__, flush=True)
    FS.cmd_decompile(open(sys.argv[1]).read().split(), quiet=True)
    print('S21 REGEN DONE', flush=True)
