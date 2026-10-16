"""N6 test driver (plan\\phases\\N6_own_files.md): tests\\n5_run.py with exe default ssbu_n6.exe (N5_EXE=... for another),
logs tests\\logs\\n6_<tag>.log / .hash.txt, save copy tests\\n6_userdata_<tag>, and a lock file tests\\n6_game.lock so that
several agents of one session never run two games at once. The text below is n5_run.py's.

    python tests\\n6_run.py <tag> [KEY=VALUE ...]

As tests\\n4_run.py, with: exe default ssbu_n5.exe (registry + loose-file layer in the exe, patched game DLL),
NO default for SSBU_MODS (with SSBU_CHARACTERS the registry loads its components from registry_bin itself),
SSBU_DETERMINISTIC=1 and SSBU_FIGHT_HASH=tests\\logs\\n5_<tag>.hash.txt always, sequence default seq_n4_det.txt,
and the save copy (tests\\n5_userdata_<tag>) is DELETED when the game has ended.
Waits while tests\\QUIET_PLEASE exists. Stops only its own process (by handle) at N5_SECS (default 240).
Log: tests\\logs\\n5_<tag>.log. Prints the exit code and the lines matching N5_SHOW (a regular expression).
KEY=(unset) removes a variable. No game content in this file.
"""
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
LOGS = os.path.join(HERE, 'logs')
SHOW = (r'\[n[23456]\]|\[registry\]|debug match: (requested|player|fight)|debug end|GUEST TRAP|HOST EXCEPTION|abort|terminate|out_of_range'
        r'|hook .* failed|mods?:|\[loose\]|fighter source: \w+: \d+ scripts|LoadModule: \w+ at|UnloadModule')


def main():
    tag = sys.argv[1]
    extra = dict(a.split('=', 1) for a in sys.argv[2:])
    quiet = os.path.join(HERE, 'QUIET_PLEASE')
    while os.path.exists(quiet):
        print('QUIET_PLEASE exists: waiting', flush=True)
        time.sleep(25)
    # N6: several agents of one session share this driver: one game at a time through a lock file of our own
    # (created exclusively, holds our pid; a lock older than 15 minutes is taken as abandoned)
    lock = os.path.join(HERE, 'n6_game.lock')
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) > 900:
                    os.remove(lock)
                    continue
            except OSError:
                pass
            time.sleep(5)
    try:
        # N9: tests\OWNER_PLAYING (the owner plays the real game): no game start while it exists, as for QUIET_PLEASE
        owner = os.path.join(HERE, 'OWNER_PLAYING')
        while os.path.exists(quiet) or os.path.exists(owner):
            print('QUIET_PLEASE or OWNER_PLAYING exists: waiting', flush=True)
            time.sleep(25)
        run(tag, extra)
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


def run(tag, extra):
    ud = os.path.join(HERE, 'n6_userdata_' + tag)
    shutil.rmtree(ud, ignore_errors=True)
    shutil.copytree(os.path.join(STUDY, '..', 'userdata'), ud, ignore=shutil.ignore_patterns('*.work.*'))
    log = os.path.join(LOGS, 'n6_%s.log' % tag)
    hashf = os.path.join(LOGS, 'n6_%s.hash.txt' % tag)
    if os.path.exists(hashf):
        os.remove(hashf)
    seq_file = extra.pop('N5_SEQ', os.environ.get('N5_SEQ', 'seq_n4_det.txt'))
    with open(os.path.join(HERE, seq_file)) as f:
        seq = ' '.join(l.strip() for l in f if not l.startswith('#'))
    env = dict(os.environ)
    env.update(SSBU_SEQ=seq, SSBU_USERDATA=ud, SSBU_AUDIO_MUTE='1', SSBU_SPEED='0', SSBU_SKIP_MOVIES='1', SSBU_VK_PREP='0',
               SSBU_FIXED_SEED='1', SSBU_PAIR_WARM='0', SSBU_FIGHT_HEALTH='5', SSBU_DEBUG_END='20s',
               SSBU_DETERMINISTIC='1', SSBU_FIGHT_HASH=hashf)
    secs = int(extra.pop('N5_SECS', os.environ.get('N5_SECS', '240')))
    exe = extra.pop('N5_EXE', os.environ.get('N5_EXE', 'ssbu_n6.exe'))
    show = extra.pop('N5_SHOW', os.environ.get('N5_SHOW', SHOW))
    maxlines = int(extra.pop('N5_MAXLINES', os.environ.get('N5_MAXLINES', '60')))
    for k, v in extra.items():
        if v == '(unset)':
            env.pop(k, None)
        else:
            env[k] = v
    t0 = time.time()
    with open(log, 'w') as out:
        p = subprocess.Popen([os.path.join(STUDY, exe), os.path.join(STUDY, '..', 'binaries', '13.0.4', 'main.elf'), str(secs + 60)],
                             cwd=STUDY, env=env, stdout=out, stderr=subprocess.STDOUT)
        verdict = 'TIMEOUT'
        while time.time() - t0 < secs:
            time.sleep(2)
            rc = p.poll()
            if rc is not None:
                verdict = 'EXIT %d' % rc
                break
            with open(log, 'r', errors='replace') as f:
                text = f.read()
            if 'GUEST TRAP' in text or 'HOST EXCEPTION' in text:
                verdict = 'TRAP'
                try:
                    p.wait(15)
                except subprocess.TimeoutExpired:
                    pass
                break
        if p.poll() is None:
            p.kill()
            p.wait(30)
    shutil.rmtree(ud, ignore_errors=True)
    with open(log, 'r', errors='replace') as f:
        lines = f.read().split('\n')
    pat = re.compile(show)
    hits = [l for l in lines if pat.search(l)]
    nhash = 0
    if os.path.exists(hashf):
        with open(hashf, 'r', errors='replace') as f:
            hl = f.read().split('\n')
        nhash = len(hl)
        last = [l for l in hl if l.strip()][-2:]
    print('%s: %s after %.0fs, %d log lines, log %s, hash lines %d' % (tag, verdict, time.time() - t0, len(lines), log, nhash))
    if nhash:
        for l in last:
            print('  hash: ' + l[:260])
    for l in hits[:maxlines]:
        print('  ' + l[:300])
    if len(hits) > maxlines:
        print('  ... %d more matching lines' % (len(hits) - maxlines))
        for l in hits[-6:]:
            print('  ' + l[:300])


if __name__ == '__main__':
    main()
