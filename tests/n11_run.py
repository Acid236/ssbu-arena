"""N11 test driver (plan\\phases\\N11_visible_fighter.md): tests\\n6_run.py with

    python tests\\n11_run.py <tag> [KEY=VALUE ...]

- N5_SAVE=<folder>  the SOURCE save (default ..\\userdata; ..\\userdata_completo = everything unlocked). Only ever
  COPIED (to tests\\n11_userdata_<tag>, deleted after the game has ended); the source is never written.
- tests\\OWNER_PLAYING counts only while a process named ssbu_native.exe exists (the file alone = stale: one line, go on).
- no lock file (the session's agent starts at most two games itself); logs tests\\logs\\n11_<tag>.log / .hash.txt.
- N5_NORMAL=1: normal speed with sound (no SSBU_SPEED / SSBU_AUDIO_MUTE / SSBU_DETERMINISTIC / SSBU_FIXED_SEED).
- N5_NOSEQ=1: no scripted input at all.
- N5_STOP_ON=<regular expression>: the run ends when the log matches it (e.g. the last step of the input sequence).
Everything else as n6_run.py: fast mode, SSBU_DEBUG_END default 20s, KEY=(unset) removes a variable, N5_SECS limit
(only its own process is stopped, by handle), N5_SHOW lines printed. No game content in this file.
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
SHOW = (r'\[n[23456]\]|\[n10\]|\[registry\]|debug match: (requested|player|fight)|debug end|GUEST TRAP|HOST EXCEPTION|abort|terminate|out_of_range'
        r'|hook .* failed|mods?:|\[loose\] stage 2: (GROUP|fighter)|fighter source: \w+: \d+ scripts|LoadModule: \w+ at|UnloadModule|roster builder|picture of|\[debug\]')


def owner_plays():
    if not os.path.exists(os.path.join(HERE, 'OWNER_PLAYING')):
        return False
    try:
        out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq ssbu_native.exe', '/NH'], capture_output=True, text=True).stdout
    except OSError:
        return True
    if 'ssbu_native.exe' in out.lower():
        return True
    print('tests\\OWNER_PLAYING exists but no ssbu_native.exe process: stale, going on', flush=True)
    return False


def main():
    tag = sys.argv[1]
    extra = dict(a.split('=', 1) for a in sys.argv[2:])
    quiet = os.path.join(HERE, 'QUIET_PLEASE')
    while os.path.exists(quiet) or owner_plays():
        print('QUIET_PLEASE or the owner playing: waiting', flush=True)
        time.sleep(25)
    run(tag, extra)


def run(tag, extra):
    ud = os.path.join(HERE, 'n11_userdata_' + tag)
    save = extra.pop('N5_SAVE', os.environ.get('N5_SAVE', os.path.join(STUDY, '..', 'userdata')))
    if not os.path.isabs(save):
        save = os.path.join(STUDY, save)
    shutil.rmtree(ud, ignore_errors=True)
    shutil.copytree(save, ud, ignore=shutil.ignore_patterns('*.work.*'))
    log = os.path.join(LOGS, 'n11_%s.log' % tag)
    hashf = os.path.join(LOGS, 'n11_%s.hash.txt' % tag)
    if os.path.exists(hashf):
        os.remove(hashf)
    normal = extra.pop('N5_NORMAL', '0') == '1'
    noseq = extra.pop('N5_NOSEQ', '0') == '1'
    seq_file = extra.pop('N5_SEQ', os.environ.get('N5_SEQ', 'seq_n4_det.txt'))
    with open(os.path.join(HERE, seq_file)) as f:
        seq = ' '.join(l.strip() for l in f if not l.startswith('#'))
    env = dict(os.environ)
    env.update(SSBU_USERDATA=ud, SSBU_SKIP_MOVIES='1', SSBU_VK_PREP='0', SSBU_PAIR_WARM='0', SSBU_FIGHT_HEALTH='5', SSBU_DEBUG_END='20s')
    if not noseq:
        env['SSBU_SEQ'] = seq
    if not normal:
        env.update(SSBU_AUDIO_MUTE='1', SSBU_SPEED='0', SSBU_FIXED_SEED='1', SSBU_DETERMINISTIC='1', SSBU_FIGHT_HASH=hashf)
    secs = int(extra.pop('N5_SECS', os.environ.get('N5_SECS', '240')))
    exe = extra.pop('N5_EXE', os.environ.get('N5_EXE', 'ssbu_n11.exe'))
    show = extra.pop('N5_SHOW', os.environ.get('N5_SHOW', SHOW))
    maxlines = int(extra.pop('N5_MAXLINES', os.environ.get('N5_MAXLINES', '60')))
    stop_on = extra.pop('N5_STOP_ON', '')       # a regular expression: when the log matches, the run is over (own process stopped)
    for k, v in extra.items():
        if v == '(unset)':
            env.pop(k, None)
        else:
            env[k] = v
    if env.get('SSBU_SHOT_DIR'):
        os.makedirs(os.path.join(STUDY, env['SSBU_SHOT_DIR']), exist_ok=True)
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
            if stop_on and re.search(stop_on, text):
                verdict = 'STOPPED at N5_STOP_ON'
                time.sleep(4)
                break
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
