"""N4 test driver (plan\\phases\\N4_own_fighter.md): one scripted game in the debug fast mode, proof by log lines.

    python tests\\n4_run.py <tag> [KEY=VALUE ...]

As tests\\n3_run.py, with: exe default ssbu_n4k.exe (the patched game DLL), sequence default seq_n4_det.txt,
SSBU_DETERMINISTIC=1 and SSBU_FIGHT_HASH=tests\\logs\\n4_<tag>.hash.txt always, SSBU_MODS default mods_n4,
and the save copy (tests\\n4_userdata_<tag>, 149 MB) is DELETED when the game has ended.
Waits while tests\\QUIET_PLEASE exists. Stops only its own process (by handle) at N4_SECS (default 240).
Log: tests\\logs\\n4_<tag>.log. Prints the exit code and the lines matching N4_SHOW (a regular expression).
No game content in this file.
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
SHOW = (r'\[n[234]\]|debug match: (requested|player|fight)|debug end|GUEST TRAP|HOST EXCEPTION|abort|terminate|out_of_range'
        r'|hook .* failed|mods?:|\[loose\]')


def main():
    tag = sys.argv[1]
    extra = dict(a.split('=', 1) for a in sys.argv[2:])
    quiet = os.path.join(HERE, 'QUIET_PLEASE')
    while os.path.exists(quiet):
        print('QUIET_PLEASE exists: waiting', flush=True)
        time.sleep(25)
    ud = os.path.join(HERE, 'n4_userdata_' + tag)
    shutil.rmtree(ud, ignore_errors=True)
    shutil.copytree(os.path.join(STUDY, '..', 'userdata'), ud, ignore=shutil.ignore_patterns('*.work.*'))
    log = os.path.join(LOGS, 'n4_%s.log' % tag)
    hashf = os.path.join(LOGS, 'n4_%s.hash.txt' % tag)
    if os.path.exists(hashf):
        os.remove(hashf)
    seq_file = extra.pop('N4_SEQ', os.environ.get('N4_SEQ', 'seq_n4_det.txt'))
    with open(os.path.join(HERE, seq_file)) as f:
        seq = ' '.join(l.strip() for l in f if not l.startswith('#'))
    env = dict(os.environ)
    env.update(SSBU_SEQ=seq, SSBU_USERDATA=ud, SSBU_AUDIO_MUTE='1', SSBU_SPEED='0', SSBU_SKIP_MOVIES='1', SSBU_VK_PREP='0',
               SSBU_FIXED_SEED='1', SSBU_PAIR_WARM='0', SSBU_FIGHT_HEALTH='5', SSBU_DEBUG_END='20s',
               SSBU_DETERMINISTIC='1', SSBU_FIGHT_HASH=hashf, SSBU_MODS='mods_n4')
    secs = int(extra.pop('N4_SECS', os.environ.get('N4_SECS', '240')))
    exe = extra.pop('N4_EXE', os.environ.get('N4_EXE', 'ssbu_n4k.exe'))
    show = extra.pop('N4_SHOW', os.environ.get('N4_SHOW', SHOW))
    maxlines = int(extra.pop('N4_MAXLINES', os.environ.get('N4_MAXLINES', '60')))
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
        print('  ' + l[:420])
    if len(hits) > maxlines:
        print('  ... %d more matching lines' % (len(hits) - maxlines))
        for l in hits[-6:]:
            print('  ' + l[:420])


if __name__ == '__main__':
    main()
