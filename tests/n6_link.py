"""N5: link the test exe that has the fighter registry and the loose-file layer in it, WITHOUT editing build.py.

    python tests\\n5_link.py [exe name, default ssbu_n5.exe]

build.py's own link step on the patched game DLL of N3 (ssbu_game_n3.dll, obj_n3) with loose_host.c added. The
registry (fighter_sdk\\newmodule_host.c) is part of nnro.c; it does nothing without SSBU_CHARACTERS.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
os.environ.setdefault('RECOMP_DLL', 'ssbu_game_n3.dll')
os.environ.setdefault('RECOMP_OBJ', 'obj_n3')
os.environ['RECOMP_EXE'] = sys.argv[1] if len(sys.argv) > 1 else 'ssbu_n6.exe'      # N6: the only change to n5_link.py
sys.argv = [sys.argv[0], 'link']
sys.path.insert(0, STUDY)
os.chdir(STUDY)
import build  # noqa: E402

build.HOST_SOURCES.append('loose_host.c')
sys.exit(build.cmd_link())
