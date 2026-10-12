"""S10: one game run with a debug-injection script (or none), stopped when the script's last frame has been executed.
    python tests/s10_run.py <tag> <bin folder> <debug script | -> <end frame> [KEY=VALUE ...]
ssbu exe S10_EXE (default ssbu_s4.exe), tests\\seq_battle.txt (S10_SEQ), fresh copy of ..\\userdata, never started
while tests\\QUIET_PLEASE exists. With `-` as script: no SSBU_FIGHTER_DEBUG; the run ends at the results screen
(fighter modules unloaded) or after S10_SECS (default 400). Log tests\\logs\\s10_<tag>.log, report .report.txt.
No game content in this file."""
import os
import re
import shutil
import subprocess
import sys
import time

STUDY = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
LOGS = os.path.join(STUDY, 'tests', 'logs')
tag, bindir, script, end = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
while os.path.exists(os.path.join(STUDY, 'tests', 'QUIET_PLEASE')):
    time.sleep(25)
ud = os.path.join(STUDY, 'tests', 's10_userdata')
shutil.rmtree(ud, ignore_errors=True)
shutil.copytree(os.path.join(STUDY, '..', 'userdata'), ud)
log = os.path.join(LOGS, 's10_%s.log' % tag)
rep = os.path.join(LOGS, 's10_%s.report.txt' % tag)
for p in (log, rep):
    if os.path.exists(p):
        os.remove(p)
with open(os.path.join(STUDY, 'tests', os.environ.get('S10_SEQ', 'seq_battle.txt'))) as f:
    seq = ' '.join(l.strip() for l in f if not l.startswith('#'))
env = dict(os.environ)
env.update(SSBU_SEQ=seq, SSBU_USERDATA=ud, SSBU_FIXED_SEED='1', SSBU_PAIR_WARM='0', SSBU_FIGHTER_REPORT=rep, SSBU_FIGHTER_REPORT_EVERY='200',
           SSBU_REC=os.path.join(LOGS, 's10_input.rec'), SSBU_TRACE=os.path.join(LOGS, 's10_%s.trace.txt' % tag), SSBU_FIGHT_HEALTH='5')
if bindir != '-':
    env['SSBU_FIGHTER_BIN'] = bindir
if script != '-':
    env['SSBU_FIGHTER_DEBUG'] = os.path.join(STUDY, script)
for kv in sys.argv[5:]:
    k, v = kv.split('=', 1)
    if v == '(unset)':
        env.pop(k, None)
    else:
        env[k] = v
secs = int(os.environ.get('S10_SECS', '400'))
t0 = time.time()
verdict = 'TIMEOUT'
with open(log, 'w') as out:
    p = subprocess.Popen([os.path.join(STUDY, os.environ.get('S10_EXE', 'ssbu_s4.exe')), os.path.join(STUDY, '..', 'binaries', '13.0.4', 'main.elf'), str(secs + 60)],
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
        frames = [int(m.group(1)) for m in re.finditer(r'\[debug\] frame (\d+) fighter', text)]
        if script != '-' and frames and frames[-1] >= end:
            verdict = 'DONE'
            time.sleep(3)
            break
        at = text.rfind('fighter source: mario')
        if at >= 0 and 'nn::ro::UnloadModule: lua2cpp_mario' in text[at:]:
            verdict = 'RESULTS'
            time.sleep(6)
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
print('%s: %s after %.0f s; %d [health] lines, %d with a motion value of 11+ hex digits; %s' % (tag, verdict, time.time() - t0, len(health), len(bad), m.group(1)[:200] if m else 'no trap'))
for h in health[-2:]:
    print('   ' + h[:260])
