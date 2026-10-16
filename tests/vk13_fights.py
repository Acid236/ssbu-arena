"""Track V session 13: per-fight reading of a run's log (SSBU_HITCH=18 SSBU_VK_HOLDLOG=1 SSBU_VK_GPUTIME=1 SSBU_PERF lines).
    python tests/vk13_fights.py tests/logs/vk13_<tag>.log
For every fight (from the debug mode's "fight N on" to "fight off" / the end): frames, frames over 18 / 20 / 25 / 33.4 ms
(hitch lines), the three largest buckets named by the hitch table over those frames, holds and creations at a draw in the
fight ("nvn_vk_hold:", "nvn_vk_first:"), uploads in fight frames ("nvn_vk_upl:"), and the per-thread CPU lines inside it.
No game content in this file."""
import re
import sys

log = open(sys.argv[1], errors='replace').read().splitlines()
fights = []
cur = None
last_frame = 0
for ln in log:
    m = re.search(r'debug match: fight (\d+) on .*presented frame (\d+): p1 kind (-?\d+) \((\w*)\), p2 kind (-?\d+) \((\w*)\).*\((\w+)\) \|', ln)
    if m:
        cur = dict(n=int(m.group(1)), a=int(m.group(2)), b=10 ** 9, who='%s v %s on %s' % (m.group(4), m.group(6), m.group(7)))
        fights.append(cur)
    m = re.search(r'debug match: fight off .*presented frame (\d+) after (\d+)', ln)
    if m and cur:
        cur['b'] = int(m.group(1))
        cur = None
print('device:', next((l[:110] for l in log if 'nvn_vk: using device' in l or 'nvn_vk: device chosen' in l or 'nvn_vk: GPU' in l), '?'))
for f in fights:
    over = {18: 0, 20: 0, 25: 0, 33.4: 0, 50: 0}
    buckets = {}
    holds = firsts = upl = 0
    worst = 0.0
    firsts_ms = 0.0
    perf = []
    fps = []
    for ln in log:
        m = re.match(r'hitch: frame (\d+)(?: \(battle\))? ([\d.]+) ms \|(.*)', ln)
        if m and f['a'] <= int(m.group(1)) <= f['b']:
            ms = float(m.group(2))
            worst = max(worst, ms)
            for k in over:
                if ms > k:
                    over[k] += 1
            b = re.findall(r'\[([\d.]+) ms ([^\]]+)\]', m.group(3))
            if b:
                key = re.sub(r'[0-9a-f]{8,}', '#', b[0][1])[:70]
                buckets[key] = buckets.get(key, 0) + 1
            continue
        m = re.match(r'nvn_vk_(hold|first|upl): frame (\d+)', ln)
        if m and f['a'] <= int(m.group(2)) <= f['b']:
            if m.group(1) == 'hold':
                holds += 1
            elif m.group(1) == 'first':
                firsts += 1
                mm = re.search(r', ([\d.]+) ms \(the driver', ln)
                firsts_ms += float(mm.group(1)) if mm else 0
            else:
                upl += 1
            continue
        m = re.match(r'nvn_perf: frames (\d+)\.\.(\d+) frame time ms: avg ([\d.]+) min [\d.]+ median ([\d.]+) p99 ([\d.]+) max ([\d.]+) \| fps avg ([\d.]+), 1% low ([\d.]+)', ln)
        if m:
            inside = f['a'] <= int(m.group(1)) and int(m.group(2)) <= f['b']
            if inside:
                fps.append(float(m.group(7)))
                perf.append('      window %s..%s: avg %s ms, median %s, p99 %s, max %s, fps %s, 1%% low %s' % m.groups())
            want_cpu = inside
            continue
        if ln.startswith('nvn_perf: cpu ms/frame by thread') and perf and locals().get('want_cpu'):
            perf.append('        ' + ln[10:330])
            want_cpu = False
    n = (f['b'] if f['b'] < 10 ** 9 else 0) - f['a']
    print('fight %d %s: presented frames %d..%s (%s) | over 18 ms: %d, over 20: %d, over 25: %d, over 33.4: %d, over 50: %d, worst %.1f ms | holds at a draw %d, creations at a draw %d (%.2f ms), frames with late uploads %d | fps of whole 300-frame windows inside: %s' % (
        f['n'], f['who'], f['a'], f['b'] if f['b'] < 10 ** 9 else 'end', n if n > 0 else '?', over[18], over[20], over[25], over[33.4], over[50], worst, holds, firsts, firsts_ms, upl, ' '.join('%.1f' % x for x in fps) or '-'))
    for p in perf:
        print(p)
    for k, v in sorted(buckets.items(), key=lambda kv: -kv[1])[:4]:
        print('      largest bucket in %d of those frames: %s' % (v, k))
for ln in log:
    if ln.startswith(('nvn_vk_gpu_fight', 'nvn_vk_feedback', 'nvn_vk_flash: ', 'nvn_vk_gpl: pair')) or 'holds at a draw' in ln[:60]:
        print(ln[:700])
