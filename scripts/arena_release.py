#!/usr/bin/env python3
"""Make an SSBU Arena release: what the launcher (tools/launcher/arena/Updater.cs) updates players to.

    python scripts/arena_release.py <version> [--publish] [--against build\\work] [--notes "text"] [make_release.py options]

A release is one commit of this repository plus its files on GitHub Releases (tag v<version>):
    SSBU-Arena.exe          the launcher, the only thing a player downloads
    ssbu-runtime-<c>.zip    the prebuilt runtime of the commit (scripts/make_release.py: our code only, audited)
    arena-release.json      {"version", "commit", "launcher": {"file", "sha256"}, "runtime": {"file", "sha256"}}
At every start the launcher reads arena-release.json of the latest release: a higher version replaces the launcher, another
commit runs scripts/install.py (the sources go to the release's commit, scripts/update.py follows the latest release; the
runtime comes from RUNTIME_RELEASE in scripts/install.py, SHA-256 checked; only what changed is rebuilt here).

Steps (the tree must be clean, on the commit to release):
 1. scripts/make_release.py builds and audits the runtime package of HEAD (dist\\).
 2. a release commit: scripts/install.py RUNTIME_RELEASE = (the package's URL on the release, its SHA-256) and the launcher's
    <Version> in ArenaLauncher.csproj. Neither file is part of the tree digest (setup.py STAGE_PLAN), so the package stays valid.
 3. the launcher built from that commit (dotnet build), dist\\SSBU-Arena.exe; dist\\arena-release.json.
 4. only with --publish: push to the arena remote's main, tag v<version>, `gh release create` with the three files.
Without --publish everything stays local (the release commit too): look, then run again with --publish (step 1-3 are redone).
No game content in this file.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GITHUB = 'Acid236/ssbu-arena'
DIST = os.path.join(REPO, 'dist')
PROJ = os.path.join(REPO, 'tools', 'launcher', 'arena')


def say(s=''):
    print(s, flush=True)


def run(argv, **kw):
    say('$ ' + ' '.join(argv))
    r = subprocess.run(argv, cwd=REPO, text=True, capture_output=True, errors='replace', **kw)
    if r.returncode:
        sys.exit('failed (exit %d):\n%s' % (r.returncode, (r.stdout + r.stderr)[-3000:]))
    return r.stdout


def git(*a):
    return run(['git'] + list(a)).strip()


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def arena_remote():
    for line in git('remote', '-v').splitlines():
        p = line.split()
        if len(p) >= 2 and re.search(r'github\.com[:/]+%s(\.git)?$' % re.escape(GITHUB), p[1], re.I):
            return p[0]
    sys.exit('no git remote points at github.com/%s' % GITHUB)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('version', help='x.y.z (higher than the last release: the launchers compare it)')
    ap.add_argument('--publish', action='store_true', help='push, tag and create the GitHub release')
    ap.add_argument('--notes', default='', help='release notes (players see them on the release page)')
    a, extra = ap.parse_known_args()
    if not re.fullmatch(r'\d+\.\d+\.\d+', a.version):
        sys.exit('version must look like 0.2.0')
    tag = 'v' + a.version
    if git('status', '--porcelain', '--untracked-files=no'):
        sys.exit('the tree has uncommitted changes: commit them first')
    if a.publish and not shutil.which('gh'):
        sys.exit('--publish needs the GitHub CLI (gh), signed in')
    if subprocess.run(['git', 'rev-parse', '-q', '--verify', 'refs/tags/' + tag], cwd=REPO, capture_output=True).returncode == 0:
        sys.exit('tag %s exists already' % tag)
    base = git('rev-parse', 'HEAD')

    # 1. the runtime package of this commit
    out = run([sys.executable, os.path.join('scripts', 'make_release.py'), '--out', DIST] + extra)
    say(out[-1500:])
    pkg = os.path.join(DIST, 'ssbu-runtime-%s.zip' % base[:10])         # make_release.py's name for it
    if not os.path.isfile(pkg):
        sys.exit('make_release.py did not write %s' % pkg)
    pkg_name, pkg_sha = os.path.basename(pkg), sha256(pkg)
    url = 'https://github.com/%s/releases/download/%s/%s' % (GITHUB, tag, pkg_name)

    # 2. the release commit
    ip = os.path.join(REPO, 'scripts', 'install.py')
    with open(ip, encoding='utf-8') as f:
        src = f.read()
    new, n = re.subn(r'^RUNTIME_RELEASE = \([^()]*\)', 'RUNTIME_RELEASE = (%r, %r)' % (url, pkg_sha), src, count=1, flags=re.M)
    if n != 1:
        sys.exit('RUNTIME_RELEASE not found in scripts/install.py')
    with open(ip, 'w', encoding='utf-8', newline='\n') as f:
        f.write(new)
    cp = os.path.join(PROJ, 'ArenaLauncher.csproj')
    with open(cp, encoding='utf-8') as f:
        c = f.read()
    c, n = re.subn(r'<Version>[^<]*</Version>', '<Version>%s</Version>' % a.version, c)
    if n != 1:
        sys.exit('<Version> not found in ArenaLauncher.csproj')
    with open(cp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(c)
    git('add', ip, cp)
    git('-c', 'user.name=%s' % (git('log', '-1', '--format=%an') or 'SSBU Arena'), '-c', 'user.email=%s' % git('log', '-1', '--format=%ae'),
        'commit', '-q', '-m', 'Release %s: prebuilt runtime %s' % (tag, base[:10]))
    commit = git('rev-parse', 'HEAD')

    # 3. the launcher and the release description
    run(['dotnet', 'build', PROJ, '-c', 'Release', '-v', 'q', '-nologo'])
    exe = os.path.join(DIST, 'SSBU-Arena.exe')
    shutil.copy2(os.path.join(PROJ, 'bin', 'Release', 'net48', 'SSBU Arena.exe'), exe)
    info = {'version': a.version, 'commit': commit, 'launcher': {'file': 'SSBU-Arena.exe', 'sha256': sha256(exe)},
            'runtime': {'file': pkg_name, 'sha256': pkg_sha, 'source_commit': base}}
    rel_json = os.path.join(DIST, 'arena-release.json')
    with open(rel_json, 'w', newline='\n') as f:
        json.dump(info, f, indent=1)
    say('')
    say('release %s: commit %s (runtime from %s)' % (tag, commit[:10], base[:10]))
    for p in (exe, pkg, rel_json):
        say('  %-24s %8.1f KB  %s' % (os.path.basename(p), os.path.getsize(p) / 1024.0, sha256(p)))

    # 4. publish
    if not a.publish:
        say('\nNot published (no --publish). The release commit stays here: `git reset --hard %s` drops it.' % base[:10])
        return 0
    remote = arena_remote()
    run(['git', 'push', remote, 'HEAD:main'])
    run(['git', 'tag', '-a', tag, '-m', 'SSBU Arena ' + a.version])
    run(['git', 'push', remote, tag])
    notes = a.notes or ('SSBU Arena %s. Download **SSBU-Arena.exe** only: it installs and updates everything else.' % a.version)
    run(['gh', 'release', 'create', tag, '--repo', GITHUB, '--title', 'SSBU Arena ' + a.version, '--notes', notes, exe, pkg, rel_json])
    say('published: https://github.com/%s/releases/tag/%s' % (GITHUB, tag))
    return 0


if __name__ == '__main__':
    sys.exit(main())
