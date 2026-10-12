"""S10: the offline synthetic differential of a folder of fighter DLLs, one process, no game.
    python tests/s10_offline.py <tag> <bin folder> <all | name,name> [KEY=VALUE ...]
Waits while tests\\QUIET_PLEASE exists (never starts the exe then). Log tests\\logs\\s10_off_<tag>.log. Prints the
totals, every module that is not fully equal, and the differing functions. If the run dies inside a module, that
module is traced once to name the function, and the run goes on with the remaining modules (the function is
reported, nothing is written to any exclude file). No game content in this file."""
import os
import re
import subprocess
import sys
import time

STUDY = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
EXE = os.environ.get('S10_EXE', 'ssbu_s4.exe')


def wait_quiet():
    told = False
    while os.path.exists(os.path.join(STUDY, 'tests', 'QUIET_PLEASE')):
        if not told:
            print('waiting: tests\\QUIET_PLEASE exists', flush=True)
            told = True
        time.sleep(25)


def run(mods, bindir, extra, trace=False, skip=None):
    wait_quiet()
    env = dict(os.environ)
    env.update(SSBU_FIGHTER_OFFLINE=mods, SSBU_FIGHTER_BIN=bindir, SSBU_USERDATA=os.path.join(STUDY, 'tests', 's2_userdata'),
               SSBU_FIGHTER_REPORT=os.path.join(STUDY, 'tests', 'logs', 's10_off_report.txt'), SSBU_PAIR_WARM='0', SSBU_SHADER_CACHE='0')
    if trace:
        env['SSBU_FIGHTER_OFFLINE_TRACE'] = '1'
    if skip:
        env['SSBU_FIGHTER_OFFLINE_SKIP'] = skip
    for kv in extra:
        k, v = kv.split('=', 1)
        env[k] = v
    try:
        r = subprocess.run([os.path.join(STUDY, EXE), os.path.join('..', 'binaries', '13.0.4', 'main.elf'), '900'], cwd=STUDY, env=env,
                           capture_output=True, text=True, errors='replace', timeout=1800)
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired as e:
        return (e.stdout or b'').decode(errors='replace') if isinstance(e.stdout, bytes) else (e.stdout or '')


def main():
    tag, bindir, mods = sys.argv[1], sys.argv[2], sys.argv[3]
    extra = sys.argv[4:]
    if mods == 'all':
        names = sorted(f[:-4] for f in os.listdir(os.path.join(STUDY, bindir)) if f.endswith('.dll') and '.run' not in f)
    else:
        names = mods.split(',')
    log = open(os.path.join(STUDY, 'tests', 'logs', 's10_off_%s.log' % tag), 'w', errors='replace')
    res = {}
    stops = []
    todo = list(names)
    while todo:
        text = run(','.join(todo), bindir, extra)
        log.write(text)
        got = re.findall(r'fighter synthetic differential: lua2cpp_(\w+): (\d+) scripts equal on all 3 passes, (\d+) differing, of (\d+)', text)
        for m in got:
            res[m[0]] = (int(m[1]), int(m[2]), int(m[3]))
        rest = [m for m in todo if m not in res]
        if 'fighter offline: finished' in text or not rest:
            for m in rest:
                print('no result: %s' % m)
            break
        # the registry order decides which module ran when the process died: trace each remaining one alone until one stops
        culprit = None
        for m in rest:
            t = run(m, bindir, extra, trace=True)
            log.write(t)
            g = re.search(r'fighter synthetic differential: lua2cpp_%s: (\d+) scripts equal on all 3 passes, (\d+) differing, of (\d+)' % m, t)
            if g:
                res[m] = (int(g.group(1)), int(g.group(2)), int(g.group(3)))
                text += t
                continue
            last = re.findall(r'^synth (\S+)', t, re.M)
            culprit = (m, last[-1] if last else '?')
            break
        if culprit:
            stops.append(culprit)
            print('STOPS the test: %s in %s' % (culprit[1], culprit[0]), flush=True)
            res[culprit[0]] = (0, 0, 0)
        todo = [m for m in rest if m not in res]
    log.close()
    text = open(log.name, errors='replace').read()
    eq = sum(r[0] for r in res.values())
    df = sum(r[1] for r in res.values())
    of = sum(r[2] for r in res.values())
    print('%s: %d modules with a result of %d; %d functions/scripts equal on all 3 passes, %d differing, of %d; %d stop the test' %
          (tag, len(res), len(names), eq, df, of, len(stops)))
    for m in sorted(res):
        if res[m][0] != res[m][2]:
            print('   %s: %d equal, %d differing, of %d' % ((m,) + res[m]))
    seen = set()
    for m in re.finditer(r'fighter synthetic diff: (\S+) differs: (.*)', text):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            print('   differs: %s: %s' % (m.group(1), m.group(2)[:150]))


main()
