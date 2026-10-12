"""Relink the host objects of an exe with a linker map, so handler addresses can be named.
    python tools_audit/link_map.py [exe name whose obj_host folder to use, default ssbu_audit]
Output: <name>_map.exe and tools_audit/out/<name>.map (static functions included)."""
import os, subprocess, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.argv = [sys.argv[0], 'none'] + sys.argv[1:]
import build
name = sys.argv[2] if len(sys.argv) > 2 else 'ssbu_audit'
objdir = os.path.join(HERE, 'obj_host', name)
objs = [os.path.join(objdir, n[:-2] + '.obj') for n in build.HOST_SOURCES + ['gamedll.c']]
out = os.path.join(HERE, name + '_map.exe')
mapf = os.path.join(HERE, 'tools_audit', 'out', name + '.map')
r = subprocess.run([build.CLANG] + objs + [os.path.join(HERE, build.GAME_DLL[:-4] + '.lib')] + build.LIBS + ['-Xlinker', '/MAP:' + mapf, '-o', out], capture_output=True, text=True)
print((r.stdout + r.stderr)[-2000:])
print('map:', mapf, os.path.getsize(mapf) if os.path.exists(mapf) else 'MISSING')
