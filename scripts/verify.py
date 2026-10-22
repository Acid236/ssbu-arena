#!/usr/bin/env python3
"""Check and repair an install: the files the game needs, against the list made when they were last built.

    python scripts/verify.py write  [--build DIR]           build\\files.sha256 from the files there now (install.py does it)
    python scripts/verify.py check  [--build DIR] [--quick]  each file: ok / missing / changed (--quick: sizes only)
    python scripts/verify.py repair [--build DIR] [--quick]  check, then remove the bad files and mark the setup steps that
                                                             make them again as not done (build\\state.json); then
                                                             scripts/install.py (the launcher's setup screen) remakes them

The list, build\\files.sha256, is one line per file: "<sha256> <size> <path>", the path relative to the build folder ("romfs:"
for the game archive, checked by size only: hashing 16 GB at every check would take minutes, and the dump step checks it).
Lines starting with "#" are comments. The launcher (tools/launcher/arena/FileCheck.cs) reads the same list and checks the
files itself (a portable copy has no Python); repairing needs this script and the setup.

What each group of files is remade by (setup.py steps, install.py's menu step):
    work\\ssbu_native.exe, ssbu_game_eh_o1.dll, SDL3.dll, ssbu_glslang.dll   compile + link (setup.py makes them again
                                                                            when they are gone; objects are kept)
    work\\nro_bin_eh_o2\\*.dll                                               nro (only the missing modules are compiled)
    work\\ (opus, FFmpeg, loading animation, icon, arena_fonts)             link (copied again)
    binaries\\, sysdata\\                                                    convert (from the dump)
    characters\\arena_menu\\                                                 install.py menu (always run)
    romfs:data.arc, characters\\competitive\\, the rollback pair             not remade here: reported (the setup's game files,
                                                                            tools/competitive/make_competitive.py, the release)
No game content in this file.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
LIST = 'files.sha256'

WORK_FILES = ('ssbu_native.exe', 'ssbu_game_eh_o1.dll', 'SDL3.dll', 'ssbu_glslang.dll', 'opus.dll', 'libopus-0.dll',
              'loading_kirby.png', 'arena.ico', 'ssbu_native_rb.exe', 'ssbu_game_r1.dll', 'ssbu_ui_native.exe')
TREES = ('work/nro_bin_eh_o2', 'work/nro_bin_eh_o2r1', 'work/arena_fonts', 'binaries', 'sysdata',
         'characters/arena_menu', 'characters/competitive')
LINK_MADE = ('ssbu_native.exe', 'ssbu_game_eh_o1.dll', 'SDL3.dll', 'ssbu_glslang.dll')


def say(s=''):
    print(s, flush=True)


def default_build():
    f = os.path.join(REPO, 'build_location.txt')
    try:
        line = open(f, encoding='utf-8').readline().strip().strip('"')
        if line:
            return os.path.abspath(os.path.expandvars(line))
    except OSError:
        pass
    return os.path.join(REPO, 'build')


def romfs(build):
    try:
        with open(os.path.join(build, 'state.json'), encoding='utf-8') as f:
            return json.load(f)['dump']['romfs']
    except (OSError, ValueError, KeyError):
        p = os.path.join(build, '..', 'dump', 'romfs')            # a portable copy
        return p if os.path.isdir(p) else None


def files_now(build):
    """the paths (relative, with /) of the files to list"""
    out = []
    work = os.path.join(build, 'work')
    for n in WORK_FILES:
        if os.path.isfile(os.path.join(work, n)):
            out.append('work/' + n)
    if os.path.isdir(work):
        out += ['work/' + n for n in sorted(os.listdir(work)) if re.match(r'(av|sw)\w*-\d+\.dll$', n, re.I)]
    for t in TREES:
        root = os.path.join(build, *t.split('/'))
        for d, dirs, fs in os.walk(root):
            dirs.sort()
            for f in sorted(fs):
                if t.startswith('work/nro_bin') and not f.lower().endswith('.dll'):
                    continue                                       # (import libraries, maps: not needed to play)
                out.append(os.path.relpath(os.path.join(d, f), build).replace(os.sep, '/'))
    return out


def path_of(build, rel):
    if rel.startswith('romfs:'):
        r = romfs(build)
        return os.path.join(r, rel[6:]) if r else None
    return os.path.join(build, *rel.split('/'))


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def write(build):
    lines = ['# SSBU Arena: the files of this install (scripts/verify.py). <sha256> <size> <path>']
    for rel in files_now(build):
        p = path_of(build, rel)
        lines.append('%s %d %s' % (sha256(p), os.path.getsize(p), rel))
    r = romfs(build)
    if r and os.path.isfile(os.path.join(r, 'data.arc')):
        lines.append('- %d romfs:data.arc' % os.path.getsize(os.path.join(r, 'data.arc')))
    with open(os.path.join(build, LIST), 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    say('%s: %d files' % (os.path.join(build, LIST), len(lines) - 1))


def read_list(build):
    out = []
    with open(os.path.join(build, LIST), encoding='utf-8') as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            h, size, rel = line.rstrip('\n').split(' ', 2)
            out.append((h, int(size), rel))
    return out


def check(build, quick):
    """[(path, 'missing' | 'changed')]"""
    bad = []
    for h, size, rel in read_list(build):
        p = path_of(build, rel)
        if not p or not os.path.isfile(p):
            bad.append((rel, 'missing'))
        elif os.path.getsize(p) != size or (not quick and h != '-' and sha256(p) != h):
            bad.append((rel, 'changed'))
    return bad


def remade_by(rel):
    """the setup step that makes this file again, or None (reported only)"""
    if rel.startswith('romfs:') or rel.startswith('characters/competitive/') or 'nro_bin_eh_o2r1/' in rel or \
            rel in ('work/ssbu_native_rb.exe', 'work/ssbu_game_r1.dll', 'work/ssbu_ui_native.exe'):
        return None
    if rel.startswith('work/nro_bin_eh_o2/'):
        return 'nro'
    if rel.startswith('work/'):
        return 'compile' if rel[5:] in LINK_MADE else 'link'
    if rel.startswith(('binaries/', 'sysdata/')):
        return 'convert'
    if rel.startswith('characters/arena_menu/'):
        return 'menu'
    return None


def repair(build, quick):
    bad = check(build, quick)
    if not bad:
        say('all files are fine: nothing to repair')
        return 0
    state_p = os.path.join(build, 'state.json')
    with open(state_p, encoding='utf-8') as f:
        state = json.load(f)
    done = state.setdefault('done', {})
    redo, left = set(), []
    for rel, why in bad:
        step = remade_by(rel)
        if not step:
            left.append((rel, why))
            continue
        p = path_of(build, rel)
        if os.path.exists(p):
            os.remove(p)
        if rel.startswith('sysdata/'):                     # convert copies the fonts only into a missing folder
            shutil.rmtree(os.path.join(build, *rel.split('/')[:2]), ignore_errors=True)
        redo.add(step)
        say('removed %s (%s): made again by %s' % (rel, why, step))
    for s in redo:
        done.pop(s, None)
        if s == 'compile':
            done.pop('link', None)
        if s in ('compile', 'nro', 'link', 'convert'):
            done.pop('check', None)
    with open(state_p + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=1)
    os.replace(state_p + '.tmp', state_p)
    for rel, why in left:
        say('NOT REPAIRED %s (%s): %s' % (rel, why, 'give the setup your game files again' if rel.startswith('romfs:') else
                                          'it comes with the release (the launcher updates it) or tools/competitive'))
    say('repair prepared: %d file(s) to remake (%s); %d left' % (len(bad) - len(left), ', '.join(sorted(redo)) or '-', len(left)))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('what', choices=('write', 'check', 'repair'))
    ap.add_argument('--build', default=None)
    ap.add_argument('--quick', action='store_true', help='sizes only, no hashes')
    a = ap.parse_args()
    build = os.path.abspath(a.build or default_build())
    if a.what == 'write':
        write(build)
        return 0
    if not os.path.isfile(os.path.join(build, LIST)):
        say('no %s in %s: run "verify.py write" after a finished install' % (LIST, build))
        return 2
    if a.what == 'check':
        bad = check(build, a.quick)
        for rel, why in bad:
            say('%s %s' % (why.upper(), rel))
        say('%d problem(s)' % len(bad))
        return 1 if bad else 0
    return repair(build, a.quick)


if __name__ == '__main__':
    sys.exit(main())
