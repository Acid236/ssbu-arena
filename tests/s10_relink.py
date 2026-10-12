"""S10: relink ssbu_s4.exe from its PINNED objects (obj_host\\ssbu_s4), recompiling nnro.c only (it #includes
fighter_sdk\\hook_host.c and fighter_host.c). Same compiler flags and link line as build.py (imported, not edited);
build.py's own `link` is not used because it would rebuild the game DLL check and every object older than any
header. Keeps the previous exe and nnro.obj in obj_host\\ssbu_s4_bak_s10 (first run only).
    python tests/s10_relink.py            compile nnro.c + link
No game content in this file."""
import glob
import os
import shutil
import subprocess
import sys

STUDY = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, STUDY)
os.chdir(STUDY)
import build  # noqa: E402

EXE = 'ssbu_s4.exe'
objdir = os.path.join(STUDY, 'obj_host', 'ssbu_s4')
bak = os.path.join(STUDY, 'obj_host', 'ssbu_s4_bak_s10')
if not os.path.exists(bak):
    os.makedirs(bak)
    shutil.copy2(os.path.join(STUDY, EXE), bak)
    shutil.copy2(os.path.join(objdir, 'nnro.obj'), bak)
    print('kept the previous exe and nnro.obj in %s' % bak)
obj = os.path.join(objdir, 'nnro.obj')
tmp = obj + '.new'
r = subprocess.run([build.CLANG, '-c'] + build.HOST_FLAGS + [os.path.join(STUDY, 'nnro.c'), '-o', tmp], capture_output=True, text=True)
if r.returncode:
    print('nnro.c FAILED\n' + (r.stdout + r.stderr)[-6000:])
    sys.exit(1)
os.replace(tmp, obj)
objs = sorted(glob.glob(os.path.join(objdir, '*.obj')))
out = os.path.join(STUDY, os.environ.get('S10_LINK_EXE', EXE))      # another name while a game runs from ssbu_s4.exe (same objects)
r = subprocess.run([build.CLANG] + objs + [os.path.join(STUDY, build.GAME_DLL[:-4] + '.lib'), os.path.join(build.SDL_DIR, 'SDL3.lib')] + build.LIBS + ['-o', out],
                   capture_output=True, text=True)
print((r.stdout + r.stderr)[-3000:])
if r.returncode == 0:
    print('linked %s from %d objects: %.1f MB' % (EXE, len(objs), os.path.getsize(out) / 1048576.0))
sys.exit(r.returncode)
