"""S18: the shared state machine (lua2cpp_common) with ONLY the two generator fixes of S1 section 24.1.

    python tests/s18_common.py tree      fighters\\work_s18cfix\\common = a copy of fighters\\common (the installed source) in which only
                                         the functions whose regenerated text (fighters\\work_s18common\\common, current generator)
                                         differs by a held read or by gcall<float> carry the new text; every other difference is
                                         listed, not taken. Writes tests\\logs\\s18_common_held.txt and s18_common_other.txt
    python tests/s18_common.py guard     installed source against the fix tree, function by function
    python tests/s18_common.py build     build_fighter.py common from the fix tree into fighters_bin_s18fix\\common.dll
    python tests/s18_common.py test      the offline synthetic test of that DLL (one exe run; waits for QUIET_PLEASE / OWNER_PLAYING)

Nothing is written to fighters\\common or fighters_bin\\.
"""
import collections
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import s18_tool as T      # noqa: E402

OLD = os.path.join(STUDY, 'fighters', 'common')
NEW = os.path.join(STUDY, 'fighters', 'work_s18common', 'common')
FIX = os.path.join(STUDY, 'fighters', 'work_s18cfix', 'common')
BIN = 'fighters_bin_s18fix'

# which shared mechanic a function belongs to, in plain words (from its name; the owner knows the game)
MECH = [('bossdead', 'the slow-motion sequence when a boss is defeated (which way the fighter faces)'),
        ('getMotionKind', 'shared helper that picks the animation while being grabbed (called by the capture helpers)'),
        ('ItemGrassPull', 'pulling a plant item out of the ground (leaving that status)'),
        ('jostle', 'fighters pushing each other apart when they overlap (how fast the push fades)'),
        ('GimmickPipe', 'stage gimmick: travelling through a pipe'), ('fly_uniq', 'flying (the "Fly" status some fighters use, e.g. after a special)'),
        ('attach_wall', 'clinging to a wall'), ('BuryWait', 'being buried in the ground (waiting to get out)'), ('ItemSwingS4', 'side smash with a battering item in hand'),
        ('SwimWait', 'swimming: floating in place'), ('SwimEnd', 'swimming: leaving the water'), ('SwimTurn', 'swimming: turning around'), ('Swim', 'swimming'),
        ('dash_uniq', 'dash (the first step of running), every frame'), ('fall_uniq', 'falling, every frame'), ('Damage', 'being hit / hit stun'),
        ('Guard', 'shield'), ('Escape', 'dodge'), ('Ladder', 'ladder'), ('rebirth', 'respawn platform'), ('Jump', 'jump'), ('Landing', 'landing'),
        ('Catch', 'grab'), ('Throw', 'throw'), ('Cliff', 'ledge'), ('Item', 'item handling'), ('Attack', 'attack'), ('Run', 'run'), ('Turn', 'turn'), ('Walk', 'walk')]


def mechanic(name):
    for k, w in MECH:
        if k.lower() in name.lower():
            return w
    return 'shared helper (' + name + ')'


def functions(d):
    out = {}
    d = os.path.join(d, 'status')
    for nm in sorted(os.listdir(d)):
        if nm.endswith('.cpp'):
            cur = None
            with open(os.path.join(d, nm)) as f:
                for line in f:
                    m = T.HEAD.match(line)
                    if m:
                        cur = m.group(2) or m.group(3)
                        out[cur] = [line]
                    elif cur is not None:
                        out[cur].append(line)
                        if line.startswith('}'):
                            cur = None
    return {k: ''.join(v) for k, v in out.items()}


def classify(t, n):
    al, bl = t.split('\n'), n.split('\n')
    added = [l for l in bl if l not in al]
    removed = [l for l in al if l not in bl]
    if any('held' in l for l in added):
        return 'held', removed, added
    if added and all('gcall<float>' in l for l in added):
        return 'float', removed, added
    return 'other', removed, added


def tree():
    fresh = not os.path.exists(os.path.dirname(FIX))     # (when the tree exists only the two list files are written again)
    if fresh:
        shutil.copytree(OLD, FIX)
    a, b = functions(OLD), functions(NEW)
    take, other = [], []
    for k, t in a.items():
        if k in b and b[k] != t:
            cls, rem, add = classify(t, b[k])
            (take if cls in ('held', 'float') else other).append((k, cls, rem, add))
    left = {k: cls for k, cls, rem, add in take}
    d = os.path.join(FIX, 'status')
    for nm in sorted(os.listdir(d)) if fresh else ():
        if not nm.endswith('.cpp'):
            continue
        p = os.path.join(d, nm)
        with open(p, newline='') as f:
            text = f.read()
        ch = False
        for k in list(left):
            if a[k] in text:
                text = text.replace(a[k], b[k], 1)
                del left[k]
                ch = True
        if ch:
            with open(p, 'w', newline='') as f:
                f.write(text)
    if left and fresh:
        raise SystemExit('not found: %s' % ' '.join(left))
    with open(os.path.join(HERE, 'logs', 's18_common_held.txt'), 'w') as f:
        bound = set(l.split()[0] for l in open(os.path.join(OLD, 'proven_s10_install.txt')) if l.strip())
        f.write('# function | shared mechanic it belongs to | class (held = a value read before a call was read again after it; float = a float result taken from the integer register)'
                ' | does the INSTALLED common.dll run it as source (it binds only the 489 proven names)?\n')
        for k, cls, rem, add in take:
            f.write('%s | %s | %s | %s\n' % (k, mechanic(k), cls, 'RUNS AS SOURCE in the installed game' if k in bound else 'not bound: the game runs the original'))
    with open(os.path.join(HERE, 'logs', 's18_common_other.txt'), 'w') as f:
        f.write('# differences between the installed fighters\\common source and what the current generator prints, NOT taken into the fix tree\n')
        f.write('# function | what changed | first removed line -> first added line\n')
        for k, cls, rem, add in other:
            what = 'only the declared type of a result: `auto rN = math_...` is now `L2CValue rN = math_...` (the wrapper returns an L2CValue either way: same meaning; the S13 node_type fix)' \
                if len(rem) == len(add) and all(r.strip().startswith('auto r') and x.strip().startswith('L2CValue r') and r.strip()[5:] == x.strip()[9:] for r, x in zip(rem, add)) else 'OTHER, to be read'
            f.write('%s | %s | %s -> %s\n' % (k, what, rem[0].strip()[:90] if rem else '', add[0].strip()[:90] if add else ''))
    c = collections.Counter(cls for k, cls, rem, add in take)
    print('fix tree %s: %d functions replaced (%s); %d other differences listed, not taken; source in the installed tree but not regenerated: %d' %
          (FIX, len(take), ', '.join('%s %d' % kv for kv in sorted(c.items())), len(other), len([k for k in a if k not in b])))


def guard():
    a, b = functions(OLD), functions(FIX)
    same = sum(1 for k in a if b.get(k) == a[k])
    ch = [k for k in a if k in b and b[k] != a[k]]
    print('guard fighters\\common -> work_s18cfix\\common: %d functions identical, %d changed, %d gone, %d new' %
          (same, len(ch), len([k for k in a if k not in b]), len([k for k in b if k not in a])))
    for nm in sorted(os.listdir(os.path.join(OLD, 'generated'))):
        x, y = open(os.path.join(OLD, 'generated', nm), 'rb').read(), open(os.path.join(FIX, 'generated', nm), 'rb').read()
        print('  generated\\%s: %s' % (nm, 'identical' if x == y else 'DIFFERENT'))
    print('  changed: ' + ' '.join(ch))


def build():
    # the installed common.dll binds only the proven names (S1 section 16.3: 489 names, 712 bindings): the same list here
    env = dict(os.environ, SSBU_FIGHTERS_ROOT='work_s18cfix', SSBU_FIGHTER_BIN=BIN, SSBU_BUILD_JOBS='6',
               SSBU_FIGHTER_ONLY=os.path.join(FIX, 'proven_s10_install.txt'))
    t0 = time.time()
    r = subprocess.run([sys.executable, os.path.join(STUDY, 'fighter_sdk', 'tools', 'build_fighter.py'), 'common'], capture_output=True, text=True, env=env)
    print((r.stdout + r.stderr)[-1500:])
    print('build common: exit %d, %.0f s -> %s\\common.dll' % (r.returncode, time.time() - t0, BIN))


def test():
    sys.path.insert(0, os.path.join(STUDY, 'fighter_sdk', 'tools'))
    os.environ['SSBU_FIGHTERS_ROOT'] = 'work_s18cfix'
    os.environ['SSBU_FIGHTER_BIN'] = BIN
    import batch
    import fighter_status as FS
    while any(os.path.exists(os.path.join(HERE, n)) for n in ('QUIET_PLEASE', 'OWNER_PLAYING')):
        time.sleep(20)
    os.makedirs(FS.OUT, exist_ok=True)
    skip = []
    skipfile = os.path.join(FS.OUT, 'offline_skip_common.txt')
    while True:
        with open(skipfile, 'w', newline='\n') as f:
            f.write('\n'.join(skip) + '\n')
        text = FS.run_offline(['common'], trace=True, skipfile=skipfile)
        res, finished, last = batch.parse_offline(text)
        if 'common' in res or not last or last in skip or len(skip) > 700:
            break
        skip.append(last)
    with open(os.path.join(HERE, 'logs', 's18_common_offline.log'), 'w', errors='replace') as f:
        f.write(text)
    if 'common' not in res:
        print('no result; tail:\n' + text[-800:])
        return
    r = res['common']
    print('offline test of common (%s): %d equal on all 3 passes, %d differing, of %d; stopped in (skipped): %d' % (BIN, r['equal'], r['differ'], r['of'], len(skip)))
    held = [l.split(' | ')[0] for l in open(os.path.join(HERE, 'logs', 's18_common_held.txt')) if not l.startswith('#')]
    print('of the %d replaced functions: differing %s; skipped %s' % (len(held), [k for k in held if k in r['bad']] or 'none', [k for k in held if k in skip] or 'none'))
    for k, v in list(r['bad'].items())[:20]:
        print('  differs: %s: %s' % (k, v[:120]))


if __name__ == '__main__':
    {'tree': tree, 'guard': guard, 'build': build, 'test': test}[sys.argv[1]]()
