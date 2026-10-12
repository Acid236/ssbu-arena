"""S10: regenerate lua2cpp_common's status sources in a WORK folder and build them, refusing what does not compile.
    python tests/s10_work_common.py <root under fighters\\> <bin folder> [offline]
decompile (status_decomp.py, SSBU_FIGHTERS_ROOT) -> gen_sdk.py into <root>\\sdk_generated -> build_fighter.py; a
function that does not compile goes to <root>\\tools_out\\common_status_exclude.json and the loop repeats.
With `offline`: afterwards the offline synthetic test (exe S10_EXE, default ssbu_s4.exe); differing functions are
refused in the same file and everything repeats. Never runs while tests\\QUIET_PLEASE exists. No game content here."""
import json
import os
import re
import subprocess
import sys
import time

STUDY = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
TOOLS = os.path.join(STUDY, 'fighter_sdk', 'tools')
root, bindir = sys.argv[1], sys.argv[2]
ROOT = os.path.join(STUDY, 'fighters', root)
XP = os.path.join(ROOT, 'tools_out', 'common_status_exclude.json')
EXTRA = os.path.join(STUDY, 'fighters', 'tools_out', 'status_s8', '_merged_status.json')


def wait_quiet():
    while os.path.exists(os.path.join(STUDY, 'tests', 'QUIET_PLEASE')):
        time.sleep(25)


def run(args, env_extra):
    env = dict(os.environ)
    env.update(env_extra)
    r = subprocess.run([sys.executable] + args, capture_output=True, text=True, env=env, cwd=STUDY)
    return r.returncode, r.stdout + r.stderr


def ident_at(src, line):
    ident = None
    with open(src) as f:
        for k, text in enumerate(f, 1):
            if text.startswith('L2C_'):
                ident = text[text.index(',') + 1:].split(',')[0].split(')')[0].strip()
            if k >= line:
                break
    return ident


def offline(skipfile):
    wait_quiet()
    env = dict(os.environ)
    env.update(SSBU_FIGHTER_OFFLINE='common', SSBU_FIGHTER_BIN=bindir, SSBU_USERDATA=os.path.join(STUDY, 'tests', 's2_userdata'),
               SSBU_FIGHTER_REPORT=os.path.join(ROOT, 'tools_out', 'offline_report.txt'), SSBU_PAIR_WARM='0', SSBU_SHADER_CACHE='0',
               SSBU_FIGHTER_OFFLINE_TRACE='1', SSBU_FIGHTER_OFFLINE_SKIP=skipfile)
    try:
        r = subprocess.run([os.path.join(STUDY, os.environ.get('S10_EXE', 'ssbu_s4.exe')), os.path.join('..', 'binaries', '13.0.4', 'main.elf'), '900'],
                           cwd=STUDY, env=env, capture_output=True, text=True, errors='replace', timeout=1500)
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired as e:
        return (e.stdout or b'').decode(errors='replace') if isinstance(e.stdout, bytes) else (e.stdout or '')


def main():
    os.makedirs(os.path.join(ROOT, 'tools_out'), exist_ok=True)
    cur = json.load(open(XP)) if os.path.exists(XP) else {}
    env = {'SSBU_FIGHTERS_ROOT': root}
    sdk_env = {'SSBU_SDK_DIR': os.path.join(root, 'sdk_generated'), 'SSBU_SDK_STATUS_CALLS': os.path.join(ROOT, 'tools_out', 'status_lua_calls.json'),
               'SSBU_SDK_EXTRA': EXTRA + ';' + os.path.join(ROOT, 'tools_out', 'common_status.json')}
    build_env = {'SSBU_FIGHTERS_ROOT': root, 'SSBU_FIGHTER_SDK': os.path.join(root, 'sdk_generated'), 'SSBU_FIGHTER_BIN': bindir}
    for rounds in range(40):
        code, text = run([os.path.join(TOOLS, 'status_decomp.py'), 'common', 'L2CFighterCommon::'], env)
        print(text.strip().splitlines()[0] if text.strip() else '?', flush=True)
        code, text = run([os.path.join(TOOLS, 'gen_sdk.py')], sdk_env)
        if code:
            print(text[-800:])
            return 1
        code, text = run([os.path.join(TOOLS, 'build_fighter.py'), 'common'], build_env)
        if code:
            bad = {}
            for m in re.finditer(r'status[\\/](\w+)\.cpp:(\d+):\d+: error: ([^\n]*)', text):
                ident = ident_at(os.path.join(ROOT, 'common', 'status', m.group(1) + '.cpp'), int(m.group(2)))
                if ident and ident not in bad:
                    bad[ident] = 'does not compile: ' + m.group(3)[:90]
            if not bad:
                print(text[-1500:])
                return 1
            print('refused by the compiler: ' + ' '.join(sorted(bad)), flush=True)
            cur.update(bad)
            json.dump(cur, open(XP, 'w'), indent=1, sort_keys=True)
            continue
        print(text.strip().splitlines()[-1], flush=True)
        if 'offline' not in sys.argv[3:]:
            return 0
        skip = []
        skipfile = os.path.join(ROOT, 'tools_out', 'offline_skip_common.txt')
        while True:
            with open(skipfile, 'w', newline='\n') as f:
                f.write('\n'.join(skip) + '\n')
            out = offline(skipfile)
            m = re.search(r'fighter synthetic differential: lua2cpp_common: (\d+) scripts equal on all 3 passes, (\d+) differing, of (\d+)', out)
            if m:
                break
            last = re.findall(r'^synth (\S+)', out, re.M)
            if not last or last[-1] in skip or len(skip) > 100:
                print('the offline test gives no result:\n' + out[-800:])
                return 1
            skip.append(last[-1])
            cur[last[-1]] = 'the offline test stops in it (crash or endless run)'
        with open(os.path.join(ROOT, 'tools_out', 'offline_common.log'), 'w', errors='replace') as f:
            f.write(out)
        bad = {}
        for d in re.finditer(r'fighter synthetic diff: (\S+) differs: (.*)', out):
            bad[d.group(1)] = 'differential test: ' + d.group(2)[:110]
        print('offline: %s equal on all 3 passes, %s differing, of %s; %d stop the test' % (m.group(1), m.group(2), m.group(3), len(skip)), flush=True)
        for k, v in sorted(bad.items()):
            print('   differs: %s: %s' % (k, v))
        if not bad and not skip:
            return 0
        cur.update(bad)
        json.dump(cur, open(XP, 'w'), indent=1, sort_keys=True)
    return 1


sys.exit(main())
