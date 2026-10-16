"""S16: one game run of a four-fighter check match (like tests\\s11_run.py, but made to run two at a time).
    python tests/s16_run.py <tag> <bin folder> <seq file in tests\\> KEY=VALUE ...
Own copy of ..\\userdata in tests\\s16_ud_<tag>, own input recording; waits (checked again right before the process starts) while
tests\\QUIET_PLEASE or tests\\OWNER_PLAYING exists. Ends when the process exits, at a trap, or after S16_SECS (default 1500).
Log tests\\logs\\s11_<tag>.log, hash log s11_<tag>.fh.txt, report s11_<tag>.report.txt. Prints one summary line. No game content in this file."""
import os
import re
import shutil
import subprocess
import sys
import time

STUDY = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
LOGS = os.path.join(STUDY, 'tests', 'logs')


def lines(tag):
    try:
        with open(os.path.join(LOGS, 's11_%s.fh.txt' % tag), errors='replace') as f:
            return [l.rstrip('\n') for l in f if l.startswith('F ') and l.rstrip('\n').endswith('%)')]
    except OSError:
        return []


def blocked():
    if os.path.exists(os.path.join(STUDY, 'tests', 'QUIET_PLEASE')):
        return True
    if os.path.exists(os.path.join(STUDY, 'tests', 'OWNER_PLAYING')):      # counts only while the owner's game runs (a stale file does not)
        r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq ssbu_native.exe', '/NH'], capture_output=True, text=True)
        return 'ssbu_native.exe' in r.stdout
    return False


def main():
    tag, bindir, seqfile = sys.argv[1:4]
    ud = os.path.join(STUDY, 'tests', 's16_ud_' + tag)
    log = os.path.join(LOGS, 's11_%s.log' % tag)
    rep = os.path.join(LOGS, 's11_%s.report.txt' % tag)
    fh = os.path.join(LOGS, 's11_%s.fh.txt' % tag)
    with open(os.path.join(STUDY, 'tests', seqfile)) as f:
        seq = ' '.join(l.strip() for l in f if not l.startswith('#'))
    env = dict(os.environ)
    env.update(SSBU_SEQ=seq, SSBU_USERDATA=ud, SSBU_FIXED_SEED='1', SSBU_PAIR_WARM='0', SSBU_FIGHTER_REPORT=rep, SSBU_FIGHTER_REPORT_EVERY='500',
               SSBU_REC=os.path.join(LOGS, 's16_%s.rec' % tag), SSBU_TRACE=os.path.join(LOGS, 's11_%s.trace.txt' % tag), SSBU_FIGHT_HEALTH='5',
               SSBU_SPEED='0', SSBU_SKIP_MOVIES='1', SSBU_AUDIO_MUTE='1', SSBU_FIGHT_HASH=fh, SSBU_FIGHTER_BIN=bindir)
    for kv in sys.argv[4:]:
        k, v = kv.split('=', 1)
        env[k] = v
    secs = int(os.environ.get('S16_SECS', '1500'))
    while blocked():
        time.sleep(15)
    shutil.rmtree(ud, ignore_errors=True)
    shutil.copytree(os.path.join(STUDY, '..', 'userdata'), ud)
    for p in (log, rep, fh):
        if os.path.exists(p):
            os.remove(p)
    t0 = time.time()
    verdict = 'TIMEOUT'
    while blocked():                                    # again, right before the start (the copy takes a while)
        time.sleep(5)
    with open(log, 'w') as out:
        p = subprocess.Popen([os.path.join(STUDY, os.environ.get('S16_EXE', 'ssbu_s4.exe')), os.path.join(STUDY, '..', 'binaries', '13.0.4', 'main.elf'), str(secs + 60)],
                             cwd=STUDY, env=env, stdout=out, stderr=subprocess.STDOUT)
        t0 = time.time()
        while time.time() - t0 < secs:
            time.sleep(2)
            text = open(log, errors='replace').read()
            if 'GUEST TRAP' in text or 'HOST EXCEPTION' in text:
                verdict = 'TRAP'
                break
            if p.poll() is not None:
                verdict = 'EXITED %s' % p.returncode
                break
        if p.poll() is None:
            if verdict == 'TRAP':
                try:
                    p.wait(15)
                except subprocess.TimeoutExpired:
                    pass
            if p.poll() is None:
                p.kill()
                p.wait(30)
    text = open(log, errors='replace').read()
    m = re.search(r'(GUEST TRAP[^\n]*|HOST EXCEPTION[^\n]*)', text)
    ls = lines(tag)
    shutil.rmtree(ud, ignore_errors=True)
    print('%s: %s after %.0f s; hash lines %d (last: %s); %s' % (tag, verdict, time.time() - t0, len(ls), ls[-1][:40] if ls else '-', m.group(1)[:200] if m else 'no trap'))


main()
