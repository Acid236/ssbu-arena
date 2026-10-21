"""Build and install the native Arena UI in the configured local build.

The launcher enables it in Competitive mode. Original game hosts, DLLs, archive
and saves are preserved; the override lives in characters/arena_menu.
"""
import argparse
from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--skip-build', action='store_true', help='use the already built UI host and launcher')
    a = ap.parse_args()
    def run(*args):
        subprocess.run(args, cwd=REPO, check=True)
    if not a.skip_build:
        run(sys.executable, 'tools/ui/build_runtime.py')
        run('dotnet', 'build', 'tools/launcher/arena', '-c', 'Release')
    host = REPO / 'build/work/ssbu_ui_native.exe'
    launcher = REPO / 'tools/launcher/arena/bin/Release/net48/SSBU Arena.exe'
    if not host.is_file() or not launcher.is_file():
        raise RuntimeError('Build the UI host and launcher first (omit --skip-build).')
    run(sys.executable, 'tools/ui/menu_design.py')
    run(sys.executable, 'tools/ui/prepare_menu.py', '--labels', 'tools/ui/menu_labels_en.json',
        '--out', 'build/characters_ui_staging/ui_menu')
    # Publish only after the layout, texture and script checks have all passed.
    source = REPO / 'build/characters_ui_staging/ui_menu'
    dest = REPO / 'build/characters/arena_menu'
    backup = REPO / 'build/ui_backups' / datetime.now().strftime('%Y%m%d_%H%M%S')
    if dest.exists():
        shutil.copytree(dest, backup / 'arena_menu')
    (dest / 'ui/layout/system/loading/loading/layout.arc').unlink(missing_ok=True)
    for file in source.rglob('*'):
        if file.is_file():
            target = dest / file.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + '.tmp')
            shutil.copy2(file, temporary)
            temporary.replace(target)
    installed_launcher = REPO / 'build/SSBU Arena.exe'
    if installed_launcher.exists() and installed_launcher.read_bytes() != launcher.read_bytes():
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copy2(installed_launcher, backup / 'SSBU Arena.exe')
    shutil.copy2(launcher, installed_launcher)
    print('Arena native menu installed:', dest)
    print('Start build/SSBU Arena.exe with Competitive enabled.')


if __name__ == '__main__':
    main()
