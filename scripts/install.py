#!/usr/bin/env python3
"""One-click install: from your own game files to a playable build. Started by `Install SSBU.bat` (double click).

    python scripts/install.py [--no-gui] [--base <file>] [--update <file>] [--keys <prod.keys>] [--dump <folder>] [--jobs N]

What it does, in order (every step is skipped when its result is already there, so it can be started again after a stop):
 1. Python packages (requirements: numpy lz4 zstandard Pillow unicorn capstone pycryptodome) through pip.
 2. Your game files: a window asks for the base game (.nsp / .xci / .nsz), the 13.0.4 update (.nsp / .nsz) and your
    prod.keys, or for a dump folder you already have (exefs\\ and romfs\\). Packages are turned into build\\dump with
    tools/extract (nsz_to_nsp.py, dump_folder.py). Nothing is sent anywhere; nothing of the game goes into the repository.
 3. Tools: LLVM/clang 9, SDL3, Vulkan-Headers, glslang and libopus are looked for (deps\\, the usual folders); a missing
    one is downloaded from its official release URL into deps\\ and checked against the SHA-256 listed below before it is
    unpacked (an archive whose hash is not listed is refused). The MSVC Build Tools cannot be installed silently: if
    they are missing, the window gives the one command to install them (winget) and stops.
 4. scripts/setup.py --dump build\\dump: the long build (lift, compile, link), resumable.
 5. `Play SSBU.bat` at the top of the repository starts the game.
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPS = os.path.join(REPO, 'deps')
BUILD = os.path.join(REPO, 'build')
PKGS = ['numpy', 'lz4', 'zstandard', 'Pillow', 'unicorn', 'capstone', 'pycryptodome']
# name -> (url, sha256 or None, folder in deps, file that proves the folder is complete). A None hash refuses the download
# until the maintainer has checked the archive and written its hash here.
TOOLS = {   # checked 2026-10-19: SDL3 and glslang equal GitHub's own asset digests; LLVM's installer has a good signature of the
            # LLVM release key B6C8 F982 82B9 44E3 B0D5 C253 0FC3 042E 345A D05D (LLVM-9.0.0-win64.exe.sig)
    'sdl3': ('https://github.com/libsdl-org/SDL/releases/download/release-3.4.18/SDL3-devel-3.4.18-VC.zip',
             '78d84602ae616cfe26b33a73b7d3b9b6b56e8a6650e53d92c9c6ca938f747acd', 'SDL3', os.path.join('include', 'SDL3', 'SDL.h')),
    'vulkan-headers': ('https://github.com/KhronosGroup/Vulkan-Headers/archive/refs/tags/v1.4.329.zip',
                       '0f55079543cfbf023bda65f81bd2d5a1bab581f31e5c33cf9fd781bd754ebaba', 'Vulkan-Headers', os.path.join('include', 'vulkan', 'vulkan.h')),
    'glslang': ('https://github.com/KhronosGroup/glslang/releases/download/16.6.0/glslang-16.6.0-windows-x86_64-release.zip',
                '82bf434e69b9bb4829de7e2b4bc2c5e7a7861e53d66cf75e5cc70f5f694a8d9b', 'glslang',
                os.path.join('include', 'glslang', 'Include', 'glslang_c_interface.h')),
    'llvm': ('https://releases.llvm.org/9.0.0/LLVM-9.0.0-win64.exe',
             '71ed99a6720945d76b6772584735f2ed472f12719dff184a0b1a6a35047b8863', 'llvm', os.path.join('bin', 'clang.exe')),
}


def say(s):
    print(s, flush=True)


def ask_files(a):
    """Fill a.base / a.update / a.keys / a.dump from a small window (tkinter), unless given or --no-gui."""
    if a.dump or (a.base and a.update) or a.no_gui:
        return
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
    except ImportError:
        return
    root = tk.Tk(); root.withdraw()
    if messagebox.askyesno('SSBU native: your game files', 'Do you already have a dump FOLDER (with exefs and romfs inside)?\n\n'
                           'Yes = choose that folder.\nNo = choose your package files (.nsp / .xci / .nsz) and your prod.keys.'):
        a.dump = filedialog.askdirectory(title='The dump folder (exefs\\ and romfs\\ inside)') or None
    else:
        pk = [('Switch packages', '*.nsp *.xci *.nsz'), ('All files', '*.*')]
        a.base = filedialog.askopenfilename(title='The BASE game (v0): .nsp, .xci or .nsz', filetypes=pk) or None
        a.update = filedialog.askopenfilename(title='The UPDATE 13.0.4: .nsp or .nsz', filetypes=pk) or None
        if not os.path.exists(os.path.join(os.path.expanduser('~'), '.switch', 'prod.keys')):
            a.keys = filedialog.askopenfilename(title='Your prod.keys', filetypes=[('keys', '*.keys'), ('All files', '*.*')]) or None
    root.destroy()


def step_packages():
    missing = []
    for p in PKGS:
        mod = {'Pillow': 'PIL', 'pycryptodome': 'Crypto'}.get(p, p)
        try:
            __import__(mod)
        except ImportError:
            missing.append(p)
    if missing:
        say('1. Python packages: installing %s' % ' '.join(missing))
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--user'] + missing, check=True)
    else:
        say('1. Python packages: all there')


def step_dump(a):
    if a.dump:
        for sub in ('exefs', 'romfs'):
            if not os.path.isdir(os.path.join(a.dump, sub)):
                sys.exit('the dump folder %s has no %s\\ inside' % (a.dump, sub))
        need_fonts(a.dump)
        say('2. Game files: the dump folder %s' % a.dump)
        return a.dump
    dump = os.path.join(BUILD, 'dump')
    if os.path.isdir(os.path.join(dump, 'romfs')) and os.path.isdir(os.path.join(dump, 'exefs')):
        need_fonts(dump)
        say('2. Game files: build\\dump is already there')
        return dump
    if not (a.base and a.update):
        sys.exit('no game files chosen: start again and choose the base game and the update (or a dump folder)')
    if a.keys:
        kd = os.path.join(os.path.expanduser('~'), '.switch')
        os.makedirs(kd, exist_ok=True)
        shutil.copyfile(a.keys, os.path.join(kd, 'prod.keys'))
    ext = os.path.join(REPO, 'tools', 'extract')
    os.makedirs(BUILD, exist_ok=True)

    def plain(p, tag):
        if p.lower().endswith('.nsz'):
            out = os.path.join(BUILD, tag + '.nsp')
            if not os.path.exists(out):
                say('2. Game files: unpacking %s' % os.path.basename(p))
                subprocess.run([sys.executable, os.path.join(ext, 'nsz_to_nsp.py'), p, out], check=True)
            return out
        return p
    base, upd = plain(a.base, 'base'), plain(a.update, 'update')
    say('2. Game files: making build\\dump (about 17 GB, several minutes)')
    subprocess.run([sys.executable, os.path.join(ext, 'dump_folder.py'), base, upd, dump] + (['--firmware', a.firmware] if a.firmware else []), check=True)
    need_fonts(dump)
    return dump


def need_fonts(dump):
    """The runtime stops (code 7) without the system fonts, as a console always has them."""
    fonts = os.path.join(dump, 'sysdata', 'fonts')
    if not (os.path.isdir(fonts) and any(n.lower().endswith('.ttf') for n in os.listdir(fonts))):
        sys.exit('no system fonts in %s: the game needs them. Choose your firmware dump folder (Firmware) and start again, or put the fonts there with tools/extract/fw_fonts.py' % fonts)


# the two files of a yuzu-family source tree that tools/lifter/gen_sdktest.py reads (default Miis for the self-test), from a
# pinned commit of suyu (GPL-3.0); hashes of the files as GitHub serves them (LF line ends)
SUYU_BASE = 'https://raw.githubusercontent.com/suyu-emu/suyu-v0.0.4/c0dd2ff554327657f0c6318f29b740ac7e329ea0/'
SUYU_FILES = {'src/core/hle/service/mii/types/raw_data.cpp': '0f5b10dcde4038024fffd6079d75cd4bad8d72486efcf1ffa06e6c779803c486',
              'src/core/hle/service/mii/mii_types.h': 'cf2e0c990b881c238f5b7fd823f33fe2c0a8d0846cdbf012ec6f702b1647f3e1'}


def fetch_suyu():
    dst = os.path.join(DEPS, 'suyu')
    for rel, sha in SUYU_FILES.items():
        out = os.path.join(dst, *rel.split('/'))
        if os.path.exists(out):
            continue
        data = urllib.request.urlopen(SUYU_BASE + rel).read()
        if hashlib.sha256(data).hexdigest() != sha:
            sys.exit('suyu %s: the download does not match its SHA-256: refused' % rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, 'wb').write(data)
    return dst


def fetch(name):
    url, sha, folder, probe = TOOLS[name]
    dst = os.path.join(DEPS, folder)
    if os.path.exists(os.path.join(dst, probe)):
        return dst
    if not sha:
        sys.exit('%s is missing and its download is not verified yet (no SHA-256 listed in scripts/install.py): install it by hand '
                 '(BUILDING.md) or give its folder to setup.py' % name)
    os.makedirs(DEPS, exist_ok=True)
    arc = os.path.join(DEPS, os.path.basename(url))
    say('3. Tools: downloading %s' % url)
    urllib.request.urlretrieve(url, arc)
    h = hashlib.sha256(open(arc, 'rb').read()).hexdigest()
    if h != sha:
        os.remove(arc)
        sys.exit('%s: the download does not match its SHA-256 (got %s): refused' % (name, h))
    if arc.endswith('.zip'):
        tmp = dst + '.tmp'
        with zipfile.ZipFile(arc) as z:
            z.extractall(tmp)
        inner = [os.path.join(tmp, d) for d in os.listdir(tmp)]
        shutil.move(inner[0] if len(inner) == 1 and os.path.isdir(inner[0]) else tmp, dst)
        shutil.rmtree(tmp, ignore_errors=True)
    else:                                       # the LLVM installer: silent, into deps\llvm
        try:
            subprocess.run([arc, '/S', '/D=' + dst], check=True)
        except OSError as e:                    # 740: it asks for administrator rights; Windows shows its Yes/No prompt
            if getattr(e, 'winerror', None) != 740:
                raise
            say('3. Tools: the LLVM installer asks for administrator rights: answer Yes in the Windows prompt')
            ps = "Start-Process -FilePath '%s' -ArgumentList '/S','/D=%s' -Verb RunAs -Wait" % (arc.replace("'", "''"), dst.replace("'", "''"))
            subprocess.run(['powershell', '-NoProfile', '-Command', ps], check=True)
        if not os.path.exists(os.path.join(dst, 'bin', 'clang.exe')):
            sys.exit('LLVM was not installed into %s (was the Windows prompt answered No?): start the installer again' % dst)
    os.remove(arc)
    return dst


def step_tools(dump):
    vsw = os.path.join(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'), 'Microsoft Visual Studio', 'Installer', 'vswhere.exe')
    ok = os.path.exists(vsw) and subprocess.run([vsw, '-latest', '-products', '*', '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
                                                 '-property', 'installationPath'], capture_output=True, text=True).stdout.strip()
    if not ok:
        say('3. Tools: the MSVC Build Tools are missing.')
        sys.exit('3. Tools: the MSVC Build Tools are missing. Install them with this command (it asks for administrator rights), then '
                 'start the installer again:\n\n  winget install Microsoft.VisualStudio.2022.BuildTools --override "--quiet --wait '
                 '--add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"\n')
    if subprocess.run([sys.executable, os.path.join(REPO, 'scripts', 'setup.py'), '--only', 'deps', '--dump', dump], capture_output=True).returncode == 0:
        say('3. Tools: all found where setup.py looks')
        return []
    args = []
    for name, flag in (('llvm', '--llvm'), ('sdl3', '--sdl3'), ('vulkan-headers', '--vulkan-headers'), ('glslang', '--glslang')):
        args += [flag, fetch(name)]
    args += ['--suyu', fetch_suyu()]
    say('3. Tools: all there')
    return args


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--no-gui', action='store_true')
    ap.add_argument('--base'), ap.add_argument('--update'), ap.add_argument('--keys'), ap.add_argument('--dump'), ap.add_argument('--firmware')
    ap.add_argument('--jobs', type=int)
    ap.add_argument('--prepare-only', action='store_true', help='stop before the build (steps 1-3 only)')
    a = ap.parse_args()
    step_packages()
    ask_files(a)
    dump = step_dump(a)
    tool_args = step_tools(dump)
    if a.prepare_only:
        say('prepared: the build itself is not started (--prepare-only)')
        return 0
    say('4. Build: scripts/setup.py (30 minutes to a few hours the first time; it can be stopped and started again)')
    cmd = [sys.executable, os.path.join(REPO, 'scripts', 'setup.py'), '--dump', dump] + tool_args
    if a.jobs:
        cmd += ['--jobs', str(a.jobs)]
    r = subprocess.run(cmd)
    if r.returncode:
        sys.exit('the build stopped (code %d): see build\\logs, then start the installer again: it goes on from there' % r.returncode)
    say('5. Done: double-click "Play SSBU.bat"')
    return 0


if __name__ == '__main__':
    sys.exit(main())
