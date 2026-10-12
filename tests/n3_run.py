"""N3 test driver (plan\\phases\\N3_new_kind.md): one scripted game in the debug fast mode, proof by log lines.

    python tests\\n3_run.py <tag> [KEY=VALUE ...]

Always: SSBU_USERDATA = a fresh copy of ..\\userdata (tests\\n3_userdata_<tag>), SSBU_AUDIO_MUTE=1, SSBU_SPEED=0,
SSBU_SKIP_MOVIES=1, SSBU_VK_PREP=0, SSBU_FIXED_SEED=1, SSBU_FIGHT_HEALTH=5, SSBU_DEBUG_END=20s (override with KEY=VALUE),
sequence tests\\seq_battle_play_fast.txt (N3_SEQ=<file in tests> for another). Exe: N3_EXE (default ssbu_n3.exe).
Waits while tests\\QUIET_PLEASE exists. Stops only its own process (by handle) at N3_SECS (default 240).
Log: tests\\logs\\n3_<tag>.log. Prints the exit code and the lines matching N3_SHOW (a regular expression).
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
SHOW = r'\[n[23]\]|debug match: (requested|player|fight)|debug end|GUEST TRAP|HOST EXCEPTION|abort|\[health\]|hook .* failed|mods?:'


def main():
    tag = sys.argv[1]
    extra = dict(a.split('=', 1) for a in sys.argv[2:])
    quiet = os.path.join(HERE, 'QUIET_PLEASE')
    while os.path.exists(quiet):
        print('QUIET_PLEASE exists: waiting', flush=True)
        time.sleep(25)
    ud = os.path.join(HERE, 'n3_userdata_' + tag)
    shutil.rmtree(ud, ignore_errors=True)
    shutil.copytree(os.path.join(STUDY, '..', 'userdata'), ud, ignore=shutil.ignore_patterns('*.work.*'))
    log = os.path.join(LOGS, 'n3_%s.log' % tag)
    seq_file = extra.pop('N3_SEQ', os.environ.get('N3_SEQ', 'seq_battle_play_fast.txt'))
    with open(os.path.join(HERE, seq_file)) as f:
        seq = ' '.join(l.strip() for l in f if not l.startswith('#'))
    env = dict(os.environ)
    env.update(SSBU_SEQ=seq, SSBU_USERDATA=ud, SSBU_AUDIO_MUTE='1', SSBU_SPEED='0', SSBU_SKIP_MOVIES='1', SSBU_VK_PREP='0',
               SSBU_FIXED_SEED='1', SSBU_PAIR_WARM='0', SSBU_FIGHT_HEALTH='5', SSBU_DEBUG_END='20s')
    secs = int(extra.pop('N3_SECS', os.environ.get('N3_SECS', '240')))
    exe = extra.pop('N3_EXE', os.environ.get('N3_EXE', 'ssbu_n3.exe'))
    show = extra.pop('N3_SHOW', os.environ.get('N3_SHOW', SHOW))
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
    with open(log, 'r', errors='replace') as f:
        lines = f.read().split('\n')
    pat = re.compile(show)
    hits = [l for l in lines if pat.search(l)]
    print('%s: %s after %.0fs, %d log lines, log %s' % (tag, verdict, time.time() - t0, len(lines), log))
    for l in hits[:int(os.environ.get('N3_MAXLINES', '70'))]:
        print('  ' + l[:330])
    if len(hits) > 70:
        print('  ... %d more matching lines' % (len(hits) - 70))


if __name__ == '__main__':
    main()
