"""Track V, session 3 (M4): the fight windows of a Vulkan run against the goal (>= 59.5 fps and p99 <= 25 ms).

    python tests/vk3_windows.py <log>...

Uses the front end's "nvn_perf: frames a..b frame time ms: ..." lines (300-frame windows) and the back end's
"nvn_vk_perf: frames a..b ..." lines (where the render thread's time went; a window is a FIGHT window when it has
compute dispatches). Same goal and same window size as tests/p4_windows.py, which reads the OpenGL log format."""
import re, sys

for path in sys.argv[1:]:
    text = open(path, errors='replace').read()
    perf = {}
    for m in re.finditer(r'nvn_perf: frames (\d+)\.\.(\d+) frame time ms: avg ([\d.]+) min ([\d.]+) median ([\d.]+) p99 ([\d.]+) max ([\d.]+) \| fps avg ([\d.]+)', text):
        perf[int(m.group(2))] = (float(m.group(8)), float(m.group(5)), float(m.group(6)), float(m.group(7)))
    vk = {}
    for m in re.finditer(r'nvn_vk_perf: frames (\d+)\.\.(\d+) ms/frame: batch replay ([\d.]+) \(of it: dispatch ([\d.]+), draw preparation ([\d.]+), pipelines ([\d.]+), shader modules ([\d.]+)\), wait for the GPU ([\d.]+), '
                         r'copy-back ([\d.]+) \(waiting at batch start ([\d.]+)\), present ([\d.]+) \| per frame: ([\d.]+) dispatches, (\d+) descriptor sets allocated, (\d+) reused, ([\d.]+) submissions \| pipelines not made ahead so far: (\d+)', text):
        vk[int(m.group(2))] = [float(m.group(i)) for i in range(3, 16)] + [int(m.group(16))]
    rows, prev_miss = [], 0
    for end in sorted(perf):
        v = vk.get(end)
        if not v:
            continue
        miss = v[13] - prev_miss
        prev_miss = v[13]
        if v[9] <= 0:
            continue
        rows.append((end, perf[end], v, miss))
    ok = [r for r in rows if r[1][0] >= 59.5 and r[1][2] <= 25.0]
    print('%s: %d fight windows (300 frames, with compute dispatches), %d at >= 59.5 fps and p99 <= 25 ms' % (path.replace('\\', '/').split('/')[-1], len(rows), len(ok)))
    print('  window end |  fps  median   p99     max | replay (dispatch, prepare, pipelines, modules) GPU-wait copy-back present | sets alloc/reused | new pipelines')
    for end, p, v, miss in rows:
        print('  %10d | %5.1f %6.2f %6.1f %7.1f | %6.2f (%5.2f, %5.2f, %6.2f, %5.2f) %6.2f %6.2f %6.2f | %4d / %4d | %3d %s' % (
            end, p[0], p[1], p[2], p[3], v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[8], v[10], v[11], miss, '' if (p[0] >= 59.5 and p[2] <= 25.0) else '  <-- not clean'))
    if rows:
        import statistics
        print('  all fight windows: fps min %.1f / median %.1f; p99 median %.1f, worst %.1f; longest frame %.0f ms; render thread replay median %.2f ms per frame' % (
            min(r[1][0] for r in rows), statistics.median(r[1][0] for r in rows), statistics.median(r[1][2] for r in rows), max(r[1][2] for r in rows), max(r[1][3] for r in rows), statistics.median(r[2][0] for r in rows)))
