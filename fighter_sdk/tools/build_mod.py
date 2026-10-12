"""Build a mod (a DLL that uses fighter_sdk/include/hook.h) into a mods folder.

    python fighter_sdk/tools/build_mod.py <mod.cpp> [<out folder, default mods>]

Run the game with SSBU_MODS=<folder>: every DLL of the folder is loaded before the game starts and its
mod_init(const HookApi *) is called. Nothing of the game is rebuilt.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.normpath(os.path.join(HERE, '..', '..'))
CLANG = r'C:\llvm-8.0.0\bin\clang.exe'


def main():
    src = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.join(STUDY, 'mods')
    os.makedirs(out, exist_ok=True)
    dll = os.path.join(out, os.path.splitext(os.path.basename(src))[0] + '.dll')
    r = subprocess.run([CLANG, '-x', 'c++', '-std=c++14', '-O1', '-shared', '-fno-exceptions', '-fno-rtti', '-Wall',
                        '-I', os.path.join(STUDY, 'fighter_sdk', 'include'), src, '-o', dll], capture_output=True, text=True)
    print((r.stdout + r.stderr).strip()[-3000:])
    if r.returncode:
        return 1
    for ext in ('.lib', '.exp'):
        if os.path.exists(dll[:-4] + ext):
            os.remove(dll[:-4] + ext)
    print('built %s (%d KB)' % (dll, os.path.getsize(dll) // 1024))
    return 0


if __name__ == '__main__':
    sys.exit(main())
