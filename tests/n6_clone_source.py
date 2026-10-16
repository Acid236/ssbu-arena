"""N6: a new fighter's script sources INCLUDING the status sources, from a donor's generated sources of a work run.

    python tests\\n6_clone_source.py <donor> <new name> [source root, default work_s12] [work root, default work_n6]

Differs from tests\\n5_clone_source.py in two points:
  - the donor's sources are taken from fighters\\<source root>\\<donor> (the work run that has the status sources that
    build: acmd\\, status\\, generated\\ with status_bindings.inc and status_local.h), which is only READ;
  - the SDK folder the status sources need (fighters\\<source root>\\sdk_generated: lua_bind.h, lua_const.h, fs_syms.inc)
    is copied ONCE to fighters\\<work root>\\sdk_generated, so that a build does not depend on a folder another run is
    still writing.
Build (the three variables are what fighter_sdk\\tools\\fighter_status.py's own build step sets):

    set SSBU_FIGHTERS_ROOT=work_n6& set SSBU_FIGHTER_STATUS=1& set SSBU_FIGHTER_SDK=work_n6/sdk_generated& set SSBU_FIGHTER_BIN=fighters_bin_n6& python fighter_sdk\\tools\\build_fighter.py <new name>

The names inside the sources are NOT renamed (as N5): they are the donor's exported symbol names by which the DLL's
functions are bound to the donor's offsets. The copied sources are generated from the game: they stay in the work
folder. This tool contains none.
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)


def main():
    donor, new = sys.argv[1], sys.argv[2]
    sroot = sys.argv[3] if len(sys.argv) > 3 else 'work_s12'
    root = sys.argv[4] if len(sys.argv) > 4 else 'work_n6'
    src = os.path.join(STUDY, 'fighters', sroot, donor)
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
    sdk_src = os.path.join(STUDY, 'fighters', sroot, 'sdk_generated')
    sdk_dst = os.path.join(STUDY, 'fighters', root, 'sdk_generated')
    sdk = 'kept'
    if not os.path.isdir(sdk_dst):
        shutil.copytree(sdk_src, sdk_dst)
        sdk = 'copied'
    with open(os.path.join(dst, 'clone.json'), 'w') as f:
        json.dump({'name': new, 'donor': donor, 'source_root': sroot, 'files': count, 'module': 'lua2cpp_' + new, 'status_sources': True}, f, indent=1)
    print('%s: %d files copied from fighters\\%s\\%s to %s; SDK folder fighters\\%s\\sdk_generated %s' % (new, count, sroot, donor, dst, root, sdk))
    return 0


if __name__ == '__main__':
    sys.exit(main())
