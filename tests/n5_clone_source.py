"""N5: make a new fighter's script sources from a donor's generated sources (plan\\phases\\N5_own_module.md).

    python tests\\n5_clone_source.py <donor> <new name> [work root, default work_n5]

Copies fighters\\<donor>\\{acmd,status,generated} to fighters\\<work root>\\<new name>\\ (the donor's folder is only
read) and writes clone.json there (donor, new name, file count). Then build with

    set SSBU_FIGHTERS_ROOT=<work root>& set SSBU_FIGHTER_BIN=fighters_bin_n5& python fighter_sdk\\tools\\build_fighter.py <new name>

What is renamed: the folder and therefore the DLL (= the name of the script module the game asks for:
lua2cpp_<new name>, answered by fighter_sdk\\newmodule_host.c). What is NOT renamed, on purpose: the names inside
the sources. They are the donor's agent names (the game's factories compare the hash of "<donor>" and
"<donor>_<article>") and the donor's exported symbol names, by which the new module's functions are bound to the
donor's addresses; a fighter that is not a copy brings its own (docs\\NEW_FIGHTER.md).
The copied sources are generated from the game: they stay in the work folder. This tool contains none.
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)


def main():
    donor, new = sys.argv[1], sys.argv[2]
    root = sys.argv[3] if len(sys.argv) > 3 else 'work_n5'
    src = os.path.join(STUDY, 'fighters', donor)
    dst = os.path.join(STUDY, 'fighters', root, new)
    if not os.path.isdir(src):
        print('no sources for the donor: %s' % src)
        return 1
    if os.path.exists(dst):
        print('%s exists already: not overwritten (delete it to clone again)' % dst)
        return 1
    count = 0
    for sub in ('acmd', 'status', 'generated'):
        s = os.path.join(src, sub)
        if not os.path.isdir(s):
            continue
        shutil.copytree(s, os.path.join(dst, sub))
        count += sum(len(f) for _, _, f in os.walk(s))
    with open(os.path.join(dst, 'clone.json'), 'w') as f:
        json.dump({'name': new, 'donor': donor, 'files': count, 'module': 'lua2cpp_' + new}, f, indent=1)
    print('%s: %d files copied from fighters\\%s to %s' % (new, count, donor, dst))
    return 0


if __name__ == '__main__':
    sys.exit(main())
