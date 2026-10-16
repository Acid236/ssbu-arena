"""Coordinator: link an exe from a STABLE object set plus a few files compiled from the current tree.
    python tests/coord_relink.py <base exe name, e.g. ssbu_vk12h.exe> <new exe name> <source.c> [<source.c> ...]
The base's objects (obj_host\\<base>) are copied to obj_host\\<new>; only the named sources are recompiled into the
copy; the rest stays as it was when the base was linked (other agents' half-done edits are not picked up).
Same flags and link line as build.py (imported, not edited), including its debug_link_flags: the .pdb and the linker map
the freeze watchdog reads (objects of the base that were built before -g have no debug information in the .pdb).
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

base, new, sources = sys.argv[1], sys.argv[2], sys.argv[3:]
assert new.lower() not in ('ssbu_native.exe', 'ssbu_user.exe'), 'link under a test name, then copy'
src_dir = os.path.join(STUDY, 'obj_host', os.path.splitext(base)[0])
dst_dir = os.path.join(STUDY, 'obj_host', os.path.splitext(new)[0])
if os.path.isdir(dst_dir):
    shutil.rmtree(dst_dir)
shutil.copytree(src_dir, dst_dir)
for s in sources:
    obj = os.path.join(dst_dir, os.path.basename(s)[:-2] + '.obj')
    r = subprocess.run([build.CLANG, '-c'] + build.HOST_FLAGS + [os.path.join(STUDY, s), '-o', obj], capture_output=True, text=True)
    if r.returncode:
        print('%s FAILED\n' % s + (r.stdout + r.stderr)[-4000:])
        sys.exit(1)
    print('compiled %s' % s)
objs = sorted(glob.glob(os.path.join(dst_dir, '*.obj')))
out = os.path.join(STUDY, new)
mapf = out[:-4] + '.map'
r = subprocess.run([build.CLANG] + objs + [os.path.join(STUDY, build.GAME_DLL[:-4] + '.lib'), os.path.join(build.SDL_DIR, 'SDL3.lib')] + build.LIBS + build.debug_link_flags(out) + ['-o', out],
                   capture_output=True, text=True, errors='replace')
print((r.stdout + r.stderr)[-1500:])
if r.returncode == 0 and os.path.exists(out):
    print('linked %s from %d objects (%d from the base %s): %.1f MB; map %d bytes'
          % (new, len(objs), len(objs) - len(sources), base, os.path.getsize(out) / 1048576.0, os.path.getsize(mapf) if os.path.exists(mapf) else 0))
sys.exit(r.returncode)
