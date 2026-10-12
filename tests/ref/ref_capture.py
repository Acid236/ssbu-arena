"""Walk the scenario on the reference emulator and capture the checkpoints.

    python tests/ref/ref_capture.py [--save port|fresh|keep] [--out <dir>] [--golden] [--show]

--golden copies the captured checkpoints into tests/ref/golden (the cached reference of run_ref_compare.sh) and
relearns the screen signatures. Without it the captures stay in ref-emu/work/emu.
Screens are recognised from screenshots (screens.py); a screen without a signature yet (first ever run) is taken to be
"whatever the picture settles on after the press"."""
import os, shutil, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refcfg, scenario, screens
import emu as emu_mod

BURST_AFTER = 36                # screenshots of the battle kept in golden after its first frame
BURST_MIN = 120                 # the results screen is not looked for before this many battle screenshots
RESULT_KEEP = 40                # last screenshots kept in golden (end of the match, results)
MATCH, PASS_MATCH = 12.0, 22.0         # signature distances (see screens.py); different screens are 50..130 apart


class Walk:
    def __init__(self, e, out):
        self.e, self.out = e, out
        self.sigs = screens.load_signatures()
        self.n = 0
        self.events = []

    def grab(self):
        p = self.e.screenshot(os.path.join(self.out, 'live', 'live_%d.png' % (self.n % 4)))
        self.n += 1
        if not p:
            raise RuntimeError('the emulator gave no screenshot')
        a = screens.load(p)
        cls, d = screens.classify(a, self.sigs)
        return a, cls, d

    def settle(self, maxwait=8.0, limit=2.5):
        """screenshots until two in a row are (nearly) the same picture"""
        end = time.time() + maxwait
        a, cls, d = self.grab()
        while time.time() < end:
            time.sleep(0.25)
            b, cls2, d2 = self.grab()
            diff = screens.dist(screens.thumb(a), screens.thumb(b))
            a, cls, d = b, cls2, d2
            if diff < limit and cls != 'black':
                break
        return a, cls, d

    def is_pass(self, cls, d):
        return any(cls.startswith(p) for p in scenario.PASS_SCREENS) and d < PASS_MATCH

    def until(self, screen, key, timeout=900):
        end = time.time() + timeout
        last_press = 0
        while time.time() < end:
            a, cls, d = self.grab()
            if cls == screen and d < MATCH:
                self.e.say('reached', screen, 'distance %.1f' % d)
                return
            if time.time() - last_press > 3.3 and cls != 'black':          # nothing is pressed while the game boots
                self.e.pad.press(key)
                last_press = time.time()
                self.e.say('pressed', key, 'on', cls, '%.1f' % d)
            time.sleep(0.3)
        raise RuntimeError('screen %s not reached' % screen)

    def reach(self, screen, timeout=400):
        end = time.time() + timeout
        if screen not in self.sigs:
            self.e.say('no signature for', screen, '- taking the picture the screen settles on')
            time.sleep(1.5)
            self.settle(20)
            return
        passed = 0
        while time.time() < end:
            a, cls, d = self.settle(4)
            if cls == screen and d < MATCH:
                self.e.say('reached', screen, 'distance %.1f' % d)
                return
            if self.is_pass(cls, d):
                passed += 1
                self.events.append('%s shown on the way to %s' % (cls, screen))
                self.e.say('on the way to', screen, ': answering', cls, 'with A')
                self.e.pad.press('a')
                time.sleep(1.0)
                continue
            time.sleep(0.3)
        raise RuntimeError('screen %s not reached (last: %s %.1f)' % (screen, cls, d))

    def check(self, name, polls):
        time.sleep(polls / 60.0)
        self.settle(15)
        p = self.e.screenshot(os.path.join(self.out, name + '.png'))
        a = screens.load(p)
        cls, d = screens.classify(a, self.sigs)
        self.e.say('checkpoint', name, '->', p, '(looks like %s, %.1f)' % (cls, d))
        time.sleep(0.6)                 # a second frame of the same screen: what differs between the two is animation
        self.e.screenshot(os.path.join(self.out, name + '_b.png'))

    def burst(self, name, seconds):
        d = os.path.join(self.out, 'burst')
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(d):                 # screenshots of an earlier run (this tool's own files) must not mix in
            if f.startswith('b_') and f.endswith('.png'):
                os.remove(os.path.join(d, f))
        # until BURST_AFTER frames of the battle itself have been captured (the machine may be slow: no fixed time)
        import compare
        t0, k, times, thumbs = time.time(), 0, [], []
        still, battle_t0 = 0, None
        while time.time() - t0 < 900 and k < 1200:
            p = self.e.screenshot(os.path.join(d, 'b_%04d.png' % k), attempts=2)
            if not p:
                self.e.say('burst: the emulator stopped giving screenshots; ending the burst here')
                break
            times.append('%d %.2f' % (k, time.time() - t0))
            thumbs.append((os.path.basename(p), screens.thumb(screens.load(p))))
            k += 1
            vs, first = compare.phases(thumbs)
            if first is not None and battle_t0 is None:
                battle_t0 = time.time()
            # The match is over when the picture (nearly) stands still: the results screen waits for a button; only
            # its sparkles move. A fight never stays this still for 12 screenshots in a row.
            still = still + 1 if k > 1 and screens.dist(thumbs[-1][1], thumbs[-2][1]) < 6.0 and thumbs[-1][1].mean() > 25 else 0
            if first is not None and k - first >= BURST_MIN and still >= 12:
                self.e.say('burst: results screen reached at screenshot', k)
                break
            if battle_t0 is not None and time.time() - battle_t0 > 420:
                self.e.say('burst: 420 s after the first battle frame; ending the burst')
                break
        with open(os.path.join(d, 'times.txt'), 'w') as f:
            f.write('\n'.join(times) + '\n')
        self.e.say('burst', name, ':', k, 'frames in', d)

    def tas_loads(self):
        try:
            with open(os.path.join(refcfg.EMU_USER, 'log', 'eden_log.txt'), 'r', errors='replace') as f:
                return f.read().count('TAS file loaded')
        except OSError:
            return 0

    def run(self):
        end = time.time() + 240                # the game is up when the first screenshot arrives (boot takes 10..60 s)
        while not self.e.screenshot(os.path.join(self.out, 'live', 'boot.png'), timeout=6.0):
            if time.time() > end or not self.e.alive():
                raise RuntimeError('the emulator gave no screenshot in 240 s')
        groups = scenario.input_groups()
        tas = [i for i in sorted(groups) if any(s[0] == 'stick' for s in groups[i])]
        def write_tas(i):
            text = scenario.tas_script(groups[i])[0] if i is not None else '30 NONE 0;0 0;0\n'
            with open(refcfg.EMU_TAS, 'w', newline='\n') as f:
                f.write(text)
        # The emulator loads the script file when it starts (main() wrote the first one before the launch) and again
        # whenever a playback ends (the next one is written while the current one plays).
        skip = 0
        for idx, s in enumerate(scenario.STEPS):
            if idx < skip:
                continue
            if idx in tas:
                frames = scenario.tas_script(groups[idx])[1]
                loads = self.tas_loads()
                self.e.pad.press(['lstick', 'rstick'], 0.15)                       # controller hotkey "TAS Start/Stop"
                time.sleep(0.4)
                k = tas.index(idx)
                write_tas(tas[k + 1] if k + 1 < len(tas) else None)      # loaded when this playback ends
                self.e.say('TAS script of %d frames: %s' % (frames, ' '.join('%s%s' % (g[1], g[2] if g[0] == 'stick' else '') for g in groups[idx])))
                # the emulator logs "TAS file loaded" when a playback has ended (it reloads the script file then)
                deadline = time.time() + frames / 60.0 * 40 + 60
                while self.tas_loads() <= loads and time.time() < deadline:
                    time.sleep(0.25)
                if self.tas_loads() <= loads:
                    self.e.say('WARNING: the end of the TAS playback was not seen in the emulator log')
                self.settle(20)
                skip = idx + len(groups[idx])
                continue
            if s[0] == 'until':
                self.until(s[1], s[2])
            elif s[0] == 'press':
                self.e.pad.press(s[1])
                self.e.say('press', s[1])
            elif s[0] == 'reach':
                self.reach(s[1])
            elif s[0] == 'check':
                self.check(s[1], s[2])
            elif s[0] == 'burst':
                self.burst(s[1], s[2])


def install_golden(out):
    """copy the checkpoints of a capture folder into tests/ref/golden and relearn the signatures"""
    for name in scenario.CHECKPOINTS:
        for suffix in ('', '_b'):
            p = os.path.join(out, name + suffix + '.png')
            if os.path.isfile(p):
                shutil.copyfile(p, os.path.join(refcfg.GOLDEN, name + suffix + '.png'))
    # the battle burst: keep the versus splash and the first GOLDEN_BATTLE_SECONDS of the battle
    import compare
    bdir, gdir = os.path.join(out, 'burst'), os.path.join(refcfg.GOLDEN, 'burst')
    frames = compare.burst_frames(bdir)
    tfile = os.path.join(bdir, 'times.txt')
    times = [float(l.split()[1]) for l in open(tfile) if l.strip()] if os.path.isfile(tfile) else [0.0, 0.0]
    step = (times[-1] - times[0]) / max(1, len(times) - 1)
    vs, first = compare.phases(frames)
    os.makedirs(gdir, exist_ok=True)
    for f in os.listdir(gdir):
        if f.startswith('b_') or f.startswith('old_b_'):
            os.remove(os.path.join(gdir, f))
    if vs and first is not None:
        keep = list(range(vs[0], vs[1] + 1))[:6] + [first - 1] + list(range(first, min(len(frames), first + BURST_AFTER)))
        keep += list(range(max(first, len(frames) - RESULT_KEEP), len(frames)))
        for k, i in enumerate(sorted(set(keep))):
            shutil.copyfile(os.path.join(bdir, frames[i][0]), os.path.join(gdir, 'b_%04d.png' % k))
        with open(os.path.join(gdir, 'phases.txt'), 'w') as f:      # golden frames 0..n-1 = versus splash, n.. = battle
            f.write('%d' % len(set(list(range(vs[0], vs[1] + 1))[:6] + [first - 1])))
        with open(os.path.join(gdir, 'step_seconds.txt'), 'w') as f:
            f.write('%.4f\n' % step)
        print('golden burst: %d frames (versus %s, battle from %d), %.3f s per frame' % (len(set(keep)), vs, first, step))
    else:
        print('golden burst: versus splash / battle start NOT found in the burst:', vs, first)
    shutil.copyfile(os.path.join(out, 'ref_capture.log'), os.path.join(refcfg.GOLDEN, 'ref_capture.log'))
    print('golden updated; signatures:', screens.learn(refcfg.GOLDEN, scenario.SIGNATURE_SCREENS))


def main():
    a = sys.argv[1:]
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d
    out = opt('--out', os.path.join(refcfg.WORK, 'emu'))
    os.makedirs(out, exist_ok=True)
    if '--install-only' in a:                 # make an existing capture folder the golden reference
        install_golden(out)
        return 0
    lines = []
    def log(*x):
        s = ' '.join(str(v) for v in x)
        print(s, flush=True)
        lines.append(s)
    emu_mod.prepare_save(opt('--save', 'port'), log)
    os.makedirs(os.path.dirname(refcfg.EMU_TAS), exist_ok=True)
    groups = scenario.input_groups()
    first = [i for i in sorted(groups) if any(g[0] == 'stick' for g in groups[i])]
    with open(refcfg.EMU_TAS, 'w', newline='') as f:
        f.write(scenario.tas_script(groups[first[0]])[0] if first else '30 NONE 0;0 0;0' + chr(10))
    e = emu_mod.Emulator(log).start('normal' if '--show' in a else 'min')
    ok = False
    w = Walk(e, out)
    try:
        if not e.wait_pad():
            raise RuntimeError('the emulator never asked the DSU server for the pad')
        w.run()
        ok = True
    except Exception as ex:
        log('FAILED:', ex)
    finally:
        e.stop()
        for ev in sorted(set(w.events)):
            log('event:', ev)
        with open(os.path.join(out, 'ref_capture.log'), 'w') as f:
            f.write('\n'.join(lines) + '\n')
    if ok and '--golden' in a:
        install_golden(out)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
