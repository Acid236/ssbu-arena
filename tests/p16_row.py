"""Round 16 (P3 section 15): one table row per timed-run log.
    python tests/p16_row.py tests/logs/vk13_p16t_<tag>.log [...]
From each log: frames per second over the battle and GPU ms (nvn_vk_gpu_fight), late fight frames (display-timing),
CPU ms per frame of the main, audio update, render and task-worker threads over the 300-frame windows that are fight
windows (the nvn_vk_perf line of the window reports 35 or more compute dispatches per frame; the nvn_perf line before
it is the same window), the render thread's own split, the timeline line and the compute-buffer counts of those
windows, hitch counts, white flashes, and the CPU frequency samples of tests/logs/p16_sys_<tag>.txt when present.
No game content."""
import os
import re
import sys


MIN_DISPATCH = float(os.environ.get('P16_MIN_DISPATCH', '35'))      # a fight window: at least this many compute dispatches per frame (four fighters: 35-45; zelda_temple's four and two-player fights: set 8)


def rng(v):
    return '-' if not v else ('%.1f' % v[0] if len(v) == 1 or max(v) - min(v) < 0.05 else '%.1f-%.1f' % (min(v), max(v)))


def one(path):
    lines = open(path, errors='replace').read().splitlines()
    cpu = {}
    perf = {'replay': [], 'dispatch': [], 'prep': [], 'wait': [], 'copyback': [], 'sets': [], 'subs': []}
    tl = []
    keep = []
    last_cpu = None
    fight_win = 0
    out = [os.path.basename(path)]
    hitch = [0, 0, 0, 0]
    for i, ln in enumerate(lines):
        if ln.startswith('nvn_perf: cpu ms/frame by thread'):
            last_cpu = ln
        elif ln.startswith('nvn_vk_perf:'):
            m = re.search(r'batch replay ([\d.]+) \(of it: dispatch ([\d.]+), draw preparation ([\d.]+).*?wait for the GPU ([\d.]+), copy-back ([\d.]+).*?per frame: ([\d.]+) dispatches, (\d+) descriptor sets allocated, (\d+) reused, ([\d.]+) submissions', ln)
            if not m or float(m.group(6)) < MIN_DISPATCH or last_cpu is None:
                fight_win = 0
                continue
            fight_win = 1
            for k, g in (('replay', 1), ('dispatch', 2), ('prep', 3), ('wait', 4), ('copyback', 5), ('sets', 7), ('subs', 9)):
                perf[k].append(float(m.group(g)))
            seen = set()
            for name, val in re.findall(r' ([A-Za-z0-9:() ]+?)\[\d+\] ([\d.]+)', last_cpu.split('):', 1)[1]):
                name = name.strip()
                if name in seen:
                    continue
                seen.add(name)
                cpu.setdefault(name, []).append(float(val))
        elif ln.startswith('nvn_vk_timeline:') and '300 frames with fighters' in ln:
            tl.append(ln.split('ms after the start of the batch replay: ', 1)[1])
        elif ln.startswith('nvn_vk_cbkeep:'):
            keep.append(ln.split('per frame: ', 1)[1])
        elif ln.startswith('hitch: frame'):
            m = re.match(r'hitch: frame \d+ ([\d.]+) ms', ln)
            if m:
                v = float(m.group(1))
                for j, t in enumerate((18, 20, 25, 33.4)):
                    hitch[j] += v > t
    for ln in lines:
        if ln.startswith('nvn_vk_gpu_fight:'):
            m = re.search(r'(\d+) battle frames: GPU ms per frame median ([\d.]+), p99 ([\d.]+).*?([\d.]+) frames per second', ln)
            if m:
                out.append('fps %s | GPU median %s / p99 %s ms (%s battle frames)' % (m.group(4), m.group(2), m.group(3), m.group(1)))
        elif ln.startswith('display-timing: fight frames:'):
            m = re.search(r'fight frames: (\d+) frames;.*?: (\d+) / (\d+) / (\d+) / (\d+) / (\d+) / (\d+) = ([\d.]+) %', ln)
            if m:
                tot = int(m.group(1))
                late = tot - int(m.group(4))
                out.append('late %d of %d (%.2f %%) [0/1/2/3/4/5+ refreshes: %s]' % (late, tot, 100.0 * late / max(tot, 1), '/'.join(m.group(k) for k in range(2, 8))))
        elif ln.startswith('nvn_vk_flash:') and 'WHITE FLASHES' in ln:
            out.append('flashes ' + re.search(r'(\d+) WHITE FLASHES', ln).group(1))
    out.append('CPU ms/frame: main %s, audio update %s, render %s, TaskWorker1 %s, TaskWorker2 %s' % (
        rng(cpu.get('main')), rng(cpu.get('nus3::audio update')), rng(cpu.get('render(host)')), rng(cpu.get('TaskWorker1')), rng(cpu.get('TaskWorker2'))))
    out.append('render thread: batch replay %s (dispatch %s, draw preparation %s), wait for the GPU %s, copy-back %s; %s descriptor sets allocated per frame; submissions %s' % (
        rng(perf['replay']), rng(perf['dispatch']), rng(perf['prep']), rng(perf['wait']), rng(perf['copyback']), rng(perf['sets']), rng(perf['subs'])))
    out.append('hitch lines over 18 / 20 / 25 / 33.4 ms: %d / %d / %d / %d' % tuple(hitch))
    if tl:
        out.append('timeline (middle fight window): ' + tl[len(tl) // 2])
    if keep:
        out.append('cbkeep (last window): ' + keep[-1])
    tag = os.path.basename(path)[len('vk13_p16t_'):-4] if os.path.basename(path).startswith('vk13_p16t_') else None
    sysf = os.path.join(os.path.dirname(path), 'p16_sys_%s.txt' % tag) if tag else None
    if sysf and os.path.exists(sysf):
        txt = open(sysf, errors='replace').read()
        out.append('system: ' + ' | '.join(l.strip() for l in txt.splitlines() if l.strip())[:700])
    return '\n    '.join(out)


for p in sys.argv[1:]:
    print(one(p))
