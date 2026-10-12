"""P3: summary of a run log: battle windows (those with compute dispatches) and the hitch table.

    python tests/p3_summary.py <log> [more logs]
"""
import re
import sys

for path in sys.argv[1:]:
    text = open(path, encoding='utf-8', errors='replace').read()
    perf = {}
    for m in re.finditer(r'nvn_perf: frames (\d+)\.\.(\d+) frame time ms: avg ([\d.]+) min ([\d.]+) median ([\d.]+) p99 ([\d.]+) max ([\d.]+) \| fps avg ([\d.]+)', text):
        perf[int(m.group(2))] = [float(x) for x in m.groups()[2:]]
    disp = {int(m.group(1)): int(m.group(2)) for m in re.finditer(r'nvn_gl: frames \d+\.\.(\d+): [\d.]+ fps, \d+ draws and (\d+) dispatches', text)}
    print('== %s' % path)
    battle = []
    for end in sorted(perf):
        avg, mn, med, p99, mx, fps = perf[end]
        is_battle = disp.get(end, 0) > 0
        if is_battle:
            battle.append(perf[end])
        print('  frames %5d..%5d %s avg %6.2f ms (%5.1f fps)  median %5.2f  p99 %7.2f  max %8.2f' % (end - 300, end, 'BATTLE' if is_battle else '      ', avg, fps, med, p99, mx))
    if battle:
        fps = sorted(b[5] for b in battle)
        print('  battle windows: %d | avg fps min %.1f median %.1f max %.1f | p99 worst %.1f ms, median %.1f ms | longest frame %.1f ms | windows at >= 59 fps: %d, with p99 <= 25 ms: %d, with max <= 34 ms: %d' % (
            len(battle), fps[0], fps[len(fps) // 2], fps[-1], max(b[3] for b in battle), sorted(b[3] for b in battle)[len(battle) // 2], max(b[4] for b in battle),
            sum(1 for b in battle if b[5] >= 59.0), sum(1 for b in battle if b[3] <= 25.0), sum(1 for b in battle if b[4] <= 34.0)))
    for line in text.splitlines():
        if line.startswith('hitch log') or line.startswith('nncxxrt: readable') or line.startswith('nvn_gl: shader binaries on disk') or line.startswith('nvn_gl: shader workers') or line.startswith('nvn_gl: shader variants') or line.startswith('unwind: '):
            if not line.startswith('unwind: throw') and not line.startswith('unwind:   '):
                print('  ' + line[:260])
    causes = [l for l in text.splitlines() if l.startswith('hitch-cause:')]
    tot = {}
    for l in causes:
        m = re.match(r'hitch-cause: (\w+)\s*\| (.*?)\s+(\d+) /\s+(\d+) frames\s+([\d.]+) ms\s+worst\s+([\d.]+)', l)
        if m and not m.group(2).startswith('(meanwhile)'):
            tot[m.group(1)] = tot.get(m.group(1), 0.0) + float(m.group(5))
    print('  time in frames over the threshold, by scene: ' + ', '.join('%s %.0f ms' % kv for kv in sorted(tot.items())))
    for l in causes[:int(__import__('os').environ.get('P3_TOP', '16'))]:
        print('  ' + re.sub(r'\s{2,}', '  ', l)[:230])
    slow = re.findall(r'so far: (\d+) pairs, slow first draws (\d+) \((\d+) ms\), slow later draws (\d+) \((\d+) ms\)', text)
    if slow:
        print('  draw calls over 4 ms: first draw of a program pair %s (%s ms) of %s pairs; later draws %s (%s ms)' % (slow[-1][1], slow[-1][2], slow[-1][0], slow[-1][3], slow[-1][4]))
