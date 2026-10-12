"""Run the port through the scenario and pick the checkpoint frames.

    python tests/ref/port_capture.py [--exe ssbu_ref.exe] [--seconds 1200] [--out <dir>] [--pick-only]

The port saves a frame every SHOT_EVERY presented frames (SSBU_SHOT_EVERY, nvn_gl.c) into ref-emu/work/port/frames
(same file names every run, so the folder does not grow). Its log interleaves "nvn_gl: saved ...frame_N.bmp" with the
input sequence's step lines; a checkpoint is the last frame saved before the first key step that follows it.
Checkpoints are written as PNG to <out>/<name>.png, the frames after the start of the battle to <out>/burst/."""
import os, re, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refcfg, scenario, screens

SHOT_EVERY = 15
BURST_SHOTS = 760            # frames kept after the start press: 11400 presented frames = 190 s of game, the whole match (2:30) and the results


def run(exe, seconds, frames_dir, log_path):
    seq, checks, burst = scenario.port_sequence()
    os.makedirs(frames_dir, exist_ok=True)
    env = dict(os.environ)
    env.update({'SSBU_SEQ': seq, 'SSBU_SHOT_EVERY': str(SHOT_EVERY), 'SSBU_SHOT_DIR': os.path.relpath(frames_dir, refcfg.STUDY).replace('\\', '/'),
                'SSBU_SHOT_FROM': '200', 'SSBU_LANGUAGE': 'it',
                'SSBU_REC': os.path.join(os.path.dirname(log_path), 'port_input.rec'),
                'SSBU_TRACE': os.path.join(os.path.dirname(log_path), 'port_trace.txt')})
    # the port never touches ..\\userdata: it gets its own copy of the save snapshot, a new folder per run
    import shutil
    user = os.path.join(refcfg.ROOT, 'ref-emu', 'port_userdata', time.strftime('%Y%m%d_%H%M%S'))
    shutil.copytree(refcfg.ensure_save_base(), os.path.join(user, 'save', 'save_data'))
    env['SSBU_USERDATA'] = user
    t0 = time.time()
    with open(log_path, 'wb') as log:
        p = subprocess.Popen([os.path.join(refcfg.STUDY, exe), '../binaries/13.0.4/main.elf', str(seconds)], cwd=refcfg.STUDY, env=env,
                             stdout=log, stderr=subprocess.STDOUT)
        # the time limit is only an upper bound (the machine may be busy: 4..60 fps seen); stop as soon as the log
        # shows BURST_SHOTS frames saved after the start press
        start_line = 'step %d keys' % burst
        while p.poll() is None and time.time() - t0 < seconds + 120:
            time.sleep(3)
            try:
                with open(log_path, 'r', errors='replace') as f:
                    text = f.read()
            except OSError:
                continue
            i = text.find(start_line)
            if i >= 0 and text.count('nvn_gl: saved', i) >= BURST_SHOTS:
                break
        if p.poll() is None:
            p.terminate()                                  # our own process only (by handle)
            p.wait(30)
    print('port: %s ran %.0f s, exit code %s, log %s' % (exe, time.time() - t0, p.returncode, log_path))


def pick(frames_dir, log_path, out):
    seq, checks, burst = scenario.port_sequence()
    saved = re.compile(r'nvn_gl: saved .*frame_(\d+)\.bmp')
    step = re.compile(r'input sequence: poll (\d+) step (\d+)')
    last_frame, by_step, after_burst, burst_seen = None, {}, [], False
    reached = -1
    with open(log_path, 'r', errors='replace') as f:
        for line in f:
            m = saved.search(line)
            if m:
                last_frame = int(m.group(1))
                if burst_seen:
                    after_burst.append(last_frame)
                continue
            m = step.search(line)
            if m and 'keys' in line:
                i = int(m.group(2))
                reached = max(reached, i)
                by_step.setdefault(i, last_frame)           # the last frame saved before this key step began
                if i >= burst:
                    burst_seen = True
            elif m:
                reached = max(reached, int(m.group(2)))
    result = {}
    os.makedirs(out, exist_ok=True)
    for name in checks:                                    # nothing of an earlier run may pass for this one
        for suffix in ('', '_b'):
            p = os.path.join(out, name + suffix + '.png')
            if os.path.isfile(p):
                os.replace(p, os.path.join(out, 'previous_' + name + suffix + '.png'))
    for name, i in checks.items():
        fr = by_step.get(i)
        if fr is None:
            print('port: checkpoint %-16s NOT REACHED (sequence stopped at step %d of %d)' % (name, reached, len(seq.split())))
            continue
        src = os.path.join(frames_dir, 'frame_%d.bmp' % fr)
        if not os.path.isfile(src):
            print('port: checkpoint %-16s frame %d missing' % (name, fr))
            continue
        screens.save(os.path.join(out, name + '.png'), screens.load(src))
        earlier = os.path.join(frames_dir, 'frame_%d.bmp' % (fr - 3 * SHOT_EVERY))      # same screen half a second before: animation mask
        if os.path.isfile(earlier):
            screens.save(os.path.join(out, name + '_b.png'), screens.load(earlier))
        result[name] = fr
        print('port: checkpoint %-16s frame %d' % (name, fr))
    bdir = os.path.join(out, 'burst')
    os.makedirs(bdir, exist_ok=True)
    n = 0
    for k, fr in enumerate(after_burst):
        src = os.path.join(frames_dir, 'frame_%d.bmp' % fr)
        if os.path.isfile(src):
            screens.save(os.path.join(bdir, 'b_%04d.png' % k), screens.load(src))
            n += 1
    for f in os.listdir(bdir):                             # frames of an earlier, longer run (this tool's own files)
        if (f.startswith('b_') and int(f[2:6]) >= len(after_burst)) or f.startswith('stale_'):
            os.remove(os.path.join(bdir, f))
    print('port: %d burst frames after the start press -> %s' % (n, bdir))
    return result


if __name__ == '__main__':
    a = sys.argv[1:]
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d
    out = opt('--out', os.path.join(refcfg.WORK, 'port'))
    frames = os.path.join(refcfg.WORK, 'port', 'frames')
    log = os.path.join(out, 'port_run.log')
    os.makedirs(out, exist_ok=True)
    if '--pick-only' not in a:
        run(opt('--exe', 'ssbu_ref.exe'), int(opt('--seconds', '1200')), frames, log)
    pick(frames, log, out)
