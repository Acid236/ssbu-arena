"""S11: relink ssbu_s4.exe from its PINNED objects (obj_host\\ssbu_s4) with the debug fast mode in it.
Extends tests\\s10_relink.py: besides nnro.c (which #includes fighter_sdk\\hook_host.c and fighter_host.c) the sources
in S11_SOURCES are compiled from the CURRENT tree into the pinned folder: debug_mode.c (new object), display.c,
nnmovie_mf.c, boot.c (the debug agent's fast mode) and, if present, determinism.c. Every other object stays the
pinned one (Vulkan files, nnhid, nnsdk, ...). Same compiler flags and link line as build.py (imported, not edited).
The previous exe and the previous copies of every object that is replaced go to obj_host\\ssbu_s4_bak_s11 (first run
only). S11_SOURCES="a.c b.c" overrides the list; S10_LINK_EXE=<name> links under another name.
    python tests/s11_relink.py
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
SOURCES = os.environ.get('S11_SOURCES', 'nnro.c debug_mode.c display.c nnmovie_mf.c boot.c determinism.c').split()
SOURCES = [s for s in SOURCES if os.path.exists(os.path.join(STUDY, s))]
objdir = os.path.join(STUDY, 'obj_host', 'ssbu_s4')
bak = os.path.join(STUDY, 'obj_host', 'ssbu_s4_bak_s11')
if not os.path.exists(bak):
    os.makedirs(bak)
    shutil.copy2(os.path.join(STUDY, EXE), bak)
    for s in SOURCES:
        o = os.path.join(objdir, s[:-2] + '.obj')
        if os.path.exists(o):
            shutil.copy2(o, bak)
    print('kept the previous exe and the replaced objects in %s' % bak)
for s in SOURCES:
    obj = os.path.join(objdir, s[:-2] + '.obj')
    if s != 'nnro.c' and os.path.exists(obj) and os.path.getmtime(obj) >= os.path.getmtime(os.path.join(STUDY, s)) and os.path.exists(os.path.join(bak, 'stamp_' + s)):
        continue
    tmp = obj + '.new'
    r = subprocess.run([build.CLANG, '-c'] + build.HOST_FLAGS + [os.path.join(STUDY, s), '-o', tmp], capture_output=True, text=True)
    if r.returncode:
        print('%s FAILED\n' % s + (r.stdout + r.stderr)[-6000:])
        sys.exit(1)
    os.replace(tmp, obj)
    open(os.path.join(bak, 'stamp_' + s), 'w').close()
    print('compiled %s' % s)
objs = sorted(glob.glob(os.path.join(objdir, '*.obj')))
out = os.path.join(STUDY, os.environ.get('S10_LINK_EXE', EXE))
r = subprocess.run([build.CLANG] + objs + [os.path.join(STUDY, build.GAME_DLL[:-4] + '.lib'), os.path.join(build.SDL_DIR, 'SDL3.lib')] + build.LIBS + ['-o', out],
                   capture_output=True, text=True)
print((r.stdout + r.stderr)[-3000:])
if r.returncode == 0:
    print('linked %s from %d objects: %.1f MB' % (os.path.basename(out), len(objs), os.path.getsize(out) / 1048576.0))
sys.exit(r.returncode)
