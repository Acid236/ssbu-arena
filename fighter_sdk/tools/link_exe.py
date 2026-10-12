"""Link this track's own exe without editing build.py (other agents are editing it):
    RECOMP_EXE=ssbu_s1.exe python fighter_sdk/tools/link_exe.py
Same as `python build.py link`, plus host sources that exist on disk and are referenced but not yet listed in
build.py's HOST_SOURCES (seen 2026-10-09: nvn_vk_draw.c, track V in progress)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, STUDY)
os.chdir(STUDY)
sys.argv = ['build.py', 'link']
import build  # noqa: E402

for extra in ('nvn_vk_draw.c',):
    if os.path.exists(os.path.join(STUDY, extra)) and extra not in build.HOST_SOURCES:
        build.HOST_SOURCES.append(extra)
        print('link_exe: adding %s' % extra)
if not os.path.exists(os.path.join(STUDY, 'nvn_vk_draw.c')) and 'rb_vk' in open(os.path.join(STUDY, 'nvn_gl.c'), errors='replace').read():
    build.HOST_SOURCES.append(os.path.join('fighter_sdk', 's1_rb_vk_stub.c'))       # see that file
    print('link_exe: nvn_vk_draw.c does not exist yet: linking the empty rb_vk of fighter_sdk/s1_rb_vk_stub.c')
    # nvn_vk.c of the moment may #include that missing file: keep this exe's last good object of it
    obj = os.path.join(STUDY, 'obj_host', os.path.splitext(os.environ.get('RECOMP_EXE', 'ssbu_native.exe'))[0], 'nvn_vk.obj')
    if os.path.exists(obj) and 'nvn_vk_draw.c' in open(os.path.join(STUDY, 'nvn_vk.c'), errors='replace').read():
        os.utime(obj, None)
        print('link_exe: nvn_vk.c includes the missing file: keeping the object compiled earlier')
sys.exit(build.cmd_link())
