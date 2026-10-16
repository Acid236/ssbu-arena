"""Track V session 12: link a test exe from the current tree AND write its linker map (<exe name>.map), which the freeze
watchdog (nvn_vk_wd.c) reads to name host functions in its report.
    python tests/s12_link.py ssbu_vk12.exe
build.py is imported, not edited: same flags and link line, including its debug_link_flags (.pdb and .map). nvn_vk.obj is
deleted first (kept from before build.py followed the nvn_vk*.c files itself). A PermissionError on SDL3.dll (a game is running) is ignored.
No game content in this file."""
import os
import subprocess
import sys

STUDY = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
exe = sys.argv[1]
assert exe.lower() not in ('ssbu_native.exe', 'ssbu_user.exe'), 'never the owner\'s exes'
os.environ['RECOMP_EXE'] = exe
sys.path.insert(0, STUDY)
os.chdir(STUDY)
import build  # noqa: E402

objdir = os.path.join(STUDY, 'obj_host', os.path.splitext(exe)[0])
try:
    os.remove(os.path.join(objdir, 'nvn_vk.obj'))
except OSError:
    pass
try:
    rc = build.cmd_link()
except PermissionError as e:
    print('ignored: %s' % e)
    rc = 0
if rc:
    sys.exit(rc)
objs = [os.path.join(objdir, n[:-2] + '.obj') for n in build.HOST_SOURCES + ['gamedll.c']]
out = os.path.join(STUDY, exe)
mapf = out[:-4] + '.map'
r = subprocess.run([build.CLANG] + objs + [os.path.join(STUDY, build.GAME_DLL[:-4] + '.lib'), os.path.join(build.SDL_DIR, 'SDL3.lib')] + build.LIBS + build.debug_link_flags(out) + ['-o', out],
                   capture_output=True, text=True, errors='replace')
print((r.stdout + r.stderr)[-2000:])
print('map: %s (%d bytes)' % (mapf, os.path.getsize(mapf) if os.path.exists(mapf) else 0))
sys.exit(r.returncode)
