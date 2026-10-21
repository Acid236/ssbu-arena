"""Build the isolated UI host, including the project's existing ImGui settings.

Uses the configured local toolchain and preserves the game DLL. The default
target is ssbu_ui_native.exe; --exe explicitly selects another host. Optional
dependencies are pinned by install.py.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--exe', default='ssbu_ui_native.exe', choices=['ssbu_ui_native.exe', 'ssbu_native.exe', 'ssbu_native_rb.exe'])
    ap.add_argument('--no-stage', action='store_true', help='reuse runtime sources staged by a previous invocation')
    a = ap.parse_args()
    state_path = REPO / 'build' / 'state.json'
    state = json.loads(state_path.read_text())
    imgui = Path(state['tools'].get('imgui', str(REPO / 'deps' / 'imgui')))
    if not (imgui / 'imgui.h').is_file():
        sys.path.insert(0, str(REPO / 'scripts'))
        import install
        imgui = Path(install.fetch('imgui'))
    if not a.no_stage:
        subprocess.run([sys.executable, 'scripts/setup.py', '--dump', str(Path(state['dump']['romfs']).parent),
                        '--only', 'stage', '--redo', 'stage', '--imgui', str(imgui)], cwd=REPO, check=True)
    env = os.environ.copy()
    env.update(RECOMP_EXE=a.exe, RECOMP_CLANG=state['tools']['clang'],
               RECOMP_LDN_ONLINE='1' if state.get('ldn_online') else '0', IMGUI_ROOT=str(imgui),
               SDL3_ROOT=state['tools']['sdl3'], VULKAN_HEADERS=state['tools']['vulkan'])
    # Retain the legacy rollback host's write tracking when that host is requested.
    env['RECOMP_R1'] = '1' if a.exe == 'ssbu_native_rb.exe' else '0'
    subprocess.run([sys.executable, str(REPO / 'build/work/build.py'), 'host'], cwd=REPO, env=env, check=True)


if __name__ == '__main__':
    main()
