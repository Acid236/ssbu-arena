"""Round 17: the slow 300-frame windows of an owner's play log, one block each.
    python tests/p17_playwin.py <log> [fps limit=59]
Per window under the limit: fps, p99 / max, fight or not (compute dispatches per frame), draws, GPU ms, CPU per thread,
and the hitch lines of its frames: how many, the largest bucket of each (histogram) and the three longest frames in full.
No game content."""
import collections
import re
import sys

path = sys.argv[1]
limit = float(sys.argv[2]) if len(sys.argv) > 2 else 59.0
hitch = {}
wins = collections.OrderedDict()
with open(path, errors='replace') as f:
    for line in f:
        if line.startswith('hitch: frame '):
            m = re.match(r'hitch: frame (\d+)( \(battle\))? ([\d.]+) ms(.*)', line)
            if m:
                b = re.findall(r'\[([\d.]+) ms ([^\]]+)\]', m.group(4))
                hitch[int(m.group(1))] = (float(m.group(3)), bool(m.group(2)), [(float(x), y.strip()) for x, y in b], line.strip())
            continue
        m = re.match(r'(nvn_perf|nvn_vk|nvn_vk_gpu|nvn_vk_perf): frames (\d+)\.\.(\d+)', line)
        if m:
            w = wins.setdefault((int(m.group(2)), int(m.group(3))), {})
            if 'frame time ms' in line:
                q = re.search(r'p99 ([\d.]+) max ([\d.]+) \| fps avg ([\d.]+)', line)
                if q:
                    w['p99'], w['max'], w['fps'] = float(q.group(1)), float(q.group(2)), float(q.group(3))
            elif m.group(1) == 'nvn_vk':
                q = re.search(r'(\d+) draws per frame', line)
                if q:
                    w['draws'] = int(q.group(1))
            elif m.group(1) == 'nvn_vk_gpu':
                q = re.search(r'GPU time ([\d.]+) ms', line)
                if q:
                    w['gpu'] = float(q.group(1))
            elif m.group(1) == 'nvn_vk_perf':
                q = re.search(r'batch replay ([\d.]+).*present ([\d.]+) \| per frame: ([\d.]+) dispatches', line)
                if q:
                    w['replay'], w['present'], w['disp'] = float(q.group(1)), float(q.group(2)), float(q.group(3))
        elif line.startswith('nvn_perf: cpu ms/frame by thread'):
            if wins:
                wins[next(reversed(wins))]['cpu'] = line.strip()[len('nvn_perf: cpu ms/frame by thread '):200]

nslow = 0
total = collections.Counter()
for (a, b), w in wins.items():
    if 'fps' not in w or w['fps'] >= limit:
        continue
    nslow += 1
    hs = [(n, hitch[n]) for n in range(a, b + 1) if n in hitch]
    top = collections.Counter()
    for n, h in hs:
        if h[2]:
            big = max(h[2])
            top[re.sub(r'\|f_[0-9a-f]+', '', big[1])[:70]] += 1
    kind = 'FIGHT' if w.get('disp', 0) > 0.5 else 'no fighters'
    total[kind] += 1
    print('frames %d..%d: %.1f fps, p99 %.1f, max %.1f ms | %s (%.1f dispatches, %d draws per frame) | GPU %.2f ms, replay %.2f, present %.2f'
          % (a, b, w['fps'], w.get('p99', 0), w.get('max', 0), kind, w.get('disp', 0), w.get('draws', 0), w.get('gpu', 0), w.get('replay', 0), w.get('present', 0)))
    print('    cpu %s' % w.get('cpu', '?'))
    print('    %d hitch lines; over 25 ms: %d, over 50 ms: %d; largest bucket: %s'
          % (len(hs), sum(1 for n, h in hs if h[0] > 25), sum(1 for n, h in hs if h[0] > 50), ', '.join('%s x%d' % kv for kv in top.most_common(5))))
    for n, h in sorted(hs, key=lambda x: -x[1][0])[:3]:
        print('    %s' % h[3][:520])
print('%d windows under %.0f fps of %d: %s' % (nslow, limit, len(wins), dict(total)))
