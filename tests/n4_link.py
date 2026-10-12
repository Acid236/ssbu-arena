"""N4: link a test exe that has the loose-file layer in it (loose_host.c), WITHOUT editing build.py.

    python tests\\n4_link.py [exe name, default ssbu_n4x.exe]

Uses build.py's own link step with one more host source, on the patched game DLL of N3 (ssbu_game_n3.dll, obj_n3).
The layer in the exe is opt-in: SSBU_LOOSE_FILES=1.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
os.environ.setdefault('RECOMP_DLL', 'ssbu_game_n3.dll')
os.environ.setdefault('RECOMP_OBJ', 'obj_n3')
os.environ['RECOMP_EXE'] = sys.argv[1] if len(sys.argv) > 1 else 'ssbu_n4x.exe'
sys.argv = [sys.argv[0], 'link']
sys.path.insert(0, STUDY)
os.chdir(STUDY)
import build  # noqa: E402

build.HOST_SOURCES.append('loose_host.c')
sys.exit(build.cmd_link())
