"""Run the local menu preview with copied saves and capture the renderer's frame.

    python tools/ui/menu_probe.py --tag four_tiles

The layout is read from build/characters_ui_test. Each run has its own saves,
log and executable; only the process started here is stopped. Requires the
existing competitive build, a local light ROMFS, and Pillow to export PNG.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time


REPO = Path(__file__).resolve().parents[2]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag', default='menu')
    ap.add_argument('--workspace', type=Path, default=REPO.parent)
    ap.add_argument('--build', type=Path, default=REPO / 'build')
    ap.add_argument('--save-template', type=Path)
    ap.add_argument('--loose', type=Path)
    ap.add_argument('--romfs', type=Path, help='complete ROMFS (the reduced archive can omit random title demos)')
    ap.add_argument('--exe', type=Path, help='host executable (defaults to the UI host when built)')
    ap.add_argument('--sequence', help='override the automatic input sequence')
    ap.add_argument('--movie-samples', type=int, default=1, help='skip intro after N decoded samples (0 = disable decoder)')
    ap.add_argument('--activate', action='store_true', help='open the selected tile after navigation')
    ap.add_argument('--sound', action='store_true', help='use the host audio device (preview defaults to a silent clock)')
    ap.add_argument('--trace-routes', action='store_true')
    ap.add_argument('--select', choices=['smash', 'other', 'online', 'spirits', 'settings', 'friends', 'ranked'], default='smash')
    ap.add_argument('--timeout', type=int, default=150)
    ap.add_argument('--game-seconds', type=int, help='time limit of the game itself (it then prints its end-of-run reports)')
    ap.add_argument('--env', action='append', default=[], help='extra NAME=VALUE for the game')
    ap.add_argument('--frame', type=int, default=1500)
    ap.add_argument('--visible', action='store_true')
    ap.add_argument('--inspect-seconds', type=int, default=0, help='keep the preview open after capture, with keyboard input')
    ap.add_argument('--play', action='store_true', help='keep playing until the window is closed, using copied saves')
    a = ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', a.tag):
        ap.error('tag must contain only letters, numbers, underscores or hyphens')
    from PIL import Image

    workspace, build = a.workspace.resolve(), a.build.resolve()
    template = (a.save_template or workspace / 'cov_save_snap').resolve()
    loose = (a.loose or build / 'characters_ui_test').resolve()
    state = json.loads((build / 'state.json').read_text())
    romfs = (a.romfs or Path(state['dump']['romfs'])).resolve()
    if not template.is_dir() or not romfs.is_dir():
        ap.error('save template or light ROMFS not found; set --workspace / --save-template')
    out = workspace / 'ui_work' / 'runs' / (a.tag + '_' + time.strftime('%Y%m%d_%H%M%S'))
    out.mkdir(parents=True, exist_ok=False)
    shutil.copytree(template, out / 'userdata')
    work = build / 'work'
    exe = work / ('ssbu_ui_probe_%d.exe' % os.getpid())
    host = a.exe or work / 'ssbu_ui_native.exe'
    if not host.is_file() and not a.exe:
        host = work / 'ssbu_native.exe'
    shutil.copy2(host, exe)
    sequence = '@movie @draws:36-44/30 30:Z'
    sequence += {'smash': '', 'other': ' 600:r', 'settings': ' 600:r',
                 'online': ' 600:r 90:d', 'ranked': ' 600:r 90:d',
                 'spirits': ' 600:d', 'friends': ' 600:d'}[a.select]
    if a.activate:
        sequence += ' 180:Z'
    sequence = a.sequence or sequence
    env = {k: v for k, v in os.environ.items() if not k.startswith(('RECOMP_', 'SSBU_'))}
    env.update({
        'SSBU_ROMFS': str(romfs), 'SSBU_USERDATA': str(out / 'userdata'),
        'SSBU_VK_CACHE': str(workspace / 'cache' / 'vk_light'),
        'SSBU_CHARACTERS': str(loose), 'SSBU_LOOSE_FILES': '1',
        'SSBU_COMPETITIVE': '1', 'SSBU_SKIP_MOVIES': str(a.movie_samples),
        'SSBU_MENU': '1', 'SSBU_COMPETITIVE_UI': '1',
        'SSBU_VK_PREP': '0',
        'SSBU_FIXED_SEED': '1', 'SSBU_PAIR_WARM': '0',
        'SSBU_SEQ': sequence, 'SSBU_SHOW': '1' if a.visible else '0',
        'SSBU_SHOT': str(a.frame), 'SSBU_SHOT_DIR': str(out),
        'SSBU_FONTS': str(build / 'sysdata' / 'fonts'),
        'SSBU_TZDIR': str(build / 'sysdata' / 'zoneinfo'),
    })
    if not a.movie_samples:
        env['SSBU_MOVIE'] = '0'
    if not a.sound:
        env['SSBU_AUDIO_MUTE'] = '1'
    env.update(e.split('=', 1) for e in a.env)
    if a.trace_routes:
        env['SSBU_UI_TRACE'] = '1'
    if a.inspect_seconds or a.play:
        env['SSBU_SEQ_KEYBOARD'] = '1'
    bmp = out / ('frame_%d.bmp' % a.frame)
    print('Preview: %s\nOutput: %s' % (a.select, out), flush=True)
    process = None
    try:
        with (out / 'game.log').open('wb') as log:
            process = subprocess.Popen(
                [str(exe), str(build / 'binaries' / state.get('game_version', '13.0.4') / 'main.elf'), '0' if a.play else str(a.game_seconds or a.timeout)],
                cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + a.timeout
            while not bmp.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.5)
            if not bmp.exists():
                raise RuntimeError('no capture; see ' + str(out / 'game.log'))
            # The renderer creates the file before its write has completed.
            while time.monotonic() < deadline:
                try:
                    with Image.open(bmp) as im:
                        im.load()
                        im.save(out / 'menu.png')
                    break
                except (OSError, ValueError):
                    time.sleep(0.25)
            else:
                raise RuntimeError('capture is incomplete')
            text = (out / 'game.log').read_text(errors='replace')
            if not any('[loose] served ui/layout/menu/main_menu/main_menu/layout.arc' in line for line in text.splitlines()):
                raise RuntimeError('menu override was not loaded; see game.log')
            print('Captured: %s' % (out / 'menu.png'), flush=True)
            if a.play:
                print('Preview open. Close the game window to finish.', flush=True)
                process.wait()
            elif a.inspect_seconds:
                print('Keyboard preview for %d seconds' % a.inspect_seconds, flush=True)
                try:
                    process.wait(timeout=a.inspect_seconds)
                except subprocess.TimeoutExpired:
                    pass
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=30)
        if process is None or process.poll() is not None:
            exe.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
