"""Coordinator: summary of an owner's play log (gioca_log.bat -> logs_gioco\\play_*.log).
    python tests/coord_playlog.py <log>
Counts the attributed frames over the hitch limit (hitch: lines), groups their largest named buckets, lists the
creations / links / holds at a draw, the per-window frame-time lines and the fighters seen. No game content."""
import collections
import re
import sys

path = sys.argv[1]
hitch = []                 # (frame, battle, ms, buckets)
holds = collections.Counter()
first = collections.Counter()
perf = []
kinds = collections.Counter()
others = collections.Counter()
with open(path, errors='replace') as f:
    for line in f:
        if line.startswith('hitch: frame '):
            m = re.match(r'hitch: frame (\d+)( \(battle\))? ([\d.]+) ms', line)
            if m:
                b = re.findall(r'\[([\d.]+) ms ([^\]]+)\]', line)
                hitch.append((int(m.group(1)), bool(m.group(2)), float(m.group(3)), [(float(x), y.strip()) for x, y in b]))
        elif line.startswith('nvn_perf: frames'):
            m = re.search(r'frames (\d+)\.\.(\d+) frame time ms: avg ([\d.]+) .*?p99 ([\d.]+) max ([\d.]+) \| fps avg ([\d.]+), 1% low ([\d.]+)', line)
            if m:
                perf.append(tuple(float(x) for x in m.groups()))
        elif line.startswith('[health]'):
            m = re.search(r'fighter (\d+) kind (\d+)', line)
            if m:
                kinds[int(m.group(2))] += 1
        elif 'PIPELINE made at the draw' in line or 'PIPELINE waited' in line or 'STAGE ' in line and 'at the draw' in line:
            holds[re.sub(r'[\d.]+ ms.*', '', line.strip())[:60]] += 1
        elif line.startswith('nvn_vk_first:'):
            first[re.sub(r'\d+', 'N', line.strip())[:70]] += 1
        elif line.startswith(('nvn_vk_feedback:', 'display-timing:', 'nvn_vk_barrier:', 'nvn_vk_gpu', 'nvn_vk_path:', 'nvn_vk: device')):
            others[line.strip()[:230]] += 1

nb = [h for h in hitch if h[1]]
print('frames attributed over the limit: %d (%d in a battle)' % (len(hitch), len(nb)))
for lo, hi in ((18, 20), (20, 25), (25, 33.4), (33.4, 50), (50, 100), (100, 1e9)):
    print('  battle frames %5.1f..%-6s ms: %d' % (lo, ('%.1f' % hi) if hi < 1e8 else 'more', sum(1 for h in nb if lo <= h[2] < hi)))
top = collections.Counter()
tot = collections.Counter()
for h in nb:
    if h[3]:
        ms, name = max(h[3])
        name = re.sub(r'_Z\w+', lambda m: m.group(0)[:40], name)[:70]
        top[name] += 1
        tot[name] += ms
print('largest named bucket of each late battle frame:')
for name, n in top.most_common(18):
    print('  %5d frames  %8.0f ms  %s' % (n, tot[name], name))
print('frame-time windows (300 frames): %d' % len(perf))
low = [p for p in perf if p[5] < 59.0]
print('  windows under 59 fps: %d' % len(low))
for p in low[:25]:
    print('    frames %d..%d avg %.2f ms p99 %.1f max %.1f | %.1f fps, 1%% low %.1f' % (p[0], p[1], p[2], p[3], p[4], p[5], p[6]))
print('fighter kinds seen (health lines): %s' % dict(kinds))
print('creations at a draw:')
for k, n in holds.most_common(8):
    print('  %5d  %s' % (n, k))
for k, n in first.most_common(6):
    print('  %5d  %s' % (n, k))
print('other lines:')
for k, n in list(others.items())[:14]:
    print('  %s' % k)
