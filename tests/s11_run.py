"""S11: one game run in the debug FAST mode with the per-fight-frame hash log.
    python tests/s11_run.py <tag> <bin folder | -> <sequence file in tests\\> <fight frames | 0> [KEY=VALUE ...]
Defaults (override with KEY=VALUE, remove with KEY=(unset)): SSBU_SPEED=0 (uncapped), SSBU_SKIP_MOVIES=1,
SSBU_AUDIO_MUTE=1, SSBU_FIXED_SEED=1, SSBU_PAIR_WARM=0, SSBU_FIGHT_HEALTH=5, SSBU_FIGHT_HASH=tests\\logs\\s11_<tag>.fh.txt.
Exe S11_EXE (default ssbu_s4.exe), fresh copy of ..\\userdata in tests\\s11_userdata, never started while
tests\\QUIET_PLEASE exists. Ends when the hash log has <fight frames> frames of fighter 0 (0 = no such limit), when the
last `[debug]` command frame S11_DEBUG_END was executed, when the fighter modules are unloaded (results), at a trap,
or after S11_SECS (default 300). Log tests\\logs\\s11_<tag>.log, report .report.txt.
    python tests/s11_run.py diff <tagA> <tagB>        first differing line of two hash logs
No game content in this file."""
import os
import re
import shutil
import subprocess
import sys
import time

STUDY = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
LOGS = os.path.join(STUDY, 'tests', 'logs')


def fh_lines(tag):
    try:
        with open(os.path.join(LOGS, 's11_%s.fh.txt' % tag), errors='replace') as f:
            return [l.rstrip('\n') for l in f if l.startswith('F ') and l.rstrip('\n').endswith('%)')]      # a killed run leaves a cut last line
    except OSError:
        return []


def diff(a, b):
    la, lb = fh_lines(a), fh_lines(b)
    n = min(len(la), len(lb))
    for i in range(n):
        if la[i] != lb[i]:
            fa, fb = la[i].split(), lb[i].split()
            fields = [fa[j] for j in range(0, min(len(fa), len(fb)) - 1, 2) if fa[j] != 'H' and j + 1 < len(fb) and fa[j + 1] != fb[j + 1] and not fa[j].startswith('(')]
            print('%s vs %s: FIRST DIFFERENCE at line %d of %d / %d: fields %s' % (a, b, i + 1, len(la), len(lb), ' '.join(fields[:8])))
            for k in range(max(0, i - 2), min(n, i + 3)):
                print('   %s %s' % (a, la[k][:230]))
                print('   %s %s' % (b, lb[k][:230]))
            return i
    print('%s vs %s: IDENTICAL over %d common lines (%d / %d lines; last frame %s)' % (a, b, n, len(la), len(lb), la[n - 1].split()[1] if n else '-'))
    return -1


def main():
    if sys.argv[1] == 'diff':
        diff(sys.argv[2], sys.argv[3])
        return
    tag, bindir, seqfile, frames = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
    while os.path.exists(os.path.join(STUDY, 'tests', 'QUIET_PLEASE')) or os.path.exists(os.path.join(STUDY, 'tests', 'OWNER_PLAYING')):   # OWNER_PLAYING: the owner plays the real game (gioca_log.bat)
        time.sleep(25)
    ud = os.path.join(STUDY, 'tests', 's11_userdata')
    shutil.rmtree(ud, ignore_errors=True)
    shutil.copytree(os.path.join(STUDY, '..', 'userdata'), ud)
    log = os.path.join(LOGS, 's11_%s.log' % tag)
    rep = os.path.join(LOGS, 's11_%s.report.txt' % tag)
    fh = os.path.join(LOGS, 's11_%s.fh.txt' % tag)
    for p in (log, rep, fh):
        if os.path.exists(p):
            os.remove(p)
    with open(os.path.join(STUDY, 'tests', seqfile)) as f:
        seq = ' '.join(l.strip() for l in f if not l.startswith('#'))
    env = dict(os.environ)
    env.update(SSBU_SEQ=seq, SSBU_USERDATA=ud, SSBU_FIXED_SEED='1', SSBU_PAIR_WARM='0', SSBU_FIGHTER_REPORT=rep, SSBU_FIGHTER_REPORT_EVERY='500',
               SSBU_REC=os.path.join(LOGS, 's11_input.rec'), SSBU_TRACE=os.path.join(LOGS, 's11_%s.trace.txt' % tag), SSBU_FIGHT_HEALTH='5',
               SSBU_SPEED='0', SSBU_SKIP_MOVIES='1', SSBU_AUDIO_MUTE='1', SSBU_FIGHT_HASH=fh)
    if bindir != '-':
        env['SSBU_FIGHTER_BIN'] = bindir
    for kv in sys.argv[5:]:
        k, v = kv.split('=', 1)
        if v == '(unset)':
            env.pop(k, None)
        else:
            env[k] = v
    secs = int(os.environ.get('S11_SECS', '300'))
    dbg_end = int(os.environ.get('S11_DEBUG_END', '0'))
    t0 = time.time()
    verdict = 'TIMEOUT'
    with open(log, 'w') as out:
        p = subprocess.Popen([os.path.join(STUDY, os.environ.get('S11_EXE', 'ssbu_s4.exe')), os.path.join(STUDY, '..', 'binaries', '13.0.4', 'main.elf'), str(secs + 60)],
                             cwd=STUDY, env=env, stdout=out, stderr=subprocess.STDOUT)
        while time.time() - t0 < secs:
            time.sleep(2)
            text = open(log, errors='replace').read()
            if 'GUEST TRAP' in text or 'HOST EXCEPTION' in text:
                verdict = 'TRAP'
                break
            if p.poll() is not None:
                verdict = 'EXITED %s' % p.returncode
                break
            if frames:
                try:
                    with open(fh, 'rb') as f:
                        f.seek(0, 2)
                        f.seek(max(0, f.tell() - 600))
                        tail = f.read().decode('latin-1')
                    got = [int(m.group(1)) for m in re.finditer(r'^F (\d+) e 0 ', tail, re.M)]
                    if got and got[-1] >= frames:
                        verdict = 'FRAMES'
                        break
                except OSError:
                    pass
            if dbg_end:
                done = [int(m.group(1)) for m in re.finditer(r'\[debug\] frame (\d+) fighter', text)]
                if done and done[-1] >= dbg_end:
                    verdict = 'DONE'
                    time.sleep(3)
                    break
            rmod = os.environ.get('S11_RESULTS_MOD', 'mario')            # S13: the fighter module whose unload means the results (default as before)
            at = text.rfind('fighter source: ' + rmod)
            at = at if at >= 0 else text.find('first battle frame')
            if at >= 0 and 'nn::ro::UnloadModule: lua2cpp_' + rmod in text[at:]:
                verdict = 'RESULTS'
                time.sleep(4)
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
    health = re.findall(r'\[health\] t=[^\n]*', text)
    bad = [h for h in health if re.search(r'motion [0-9a-f]{11,}', h)]
    lines = fh_lines(tag)
    print('%s: %s after %.0f s; hash lines %d (last: %s); %d [health] lines, %d with a motion value of 11+ hex digits; %s' % (
        tag, verdict, time.time() - t0, len(lines), lines[-1][:40] if lines else '-', len(health), len(bad), m.group(1)[:200] if m else 'no trap'))


main()
