"""Track V, session 7: the fight windows of a Vulkan run against the owner's target:
NO frame over twice the frame time (33.4 ms) in any 300-frame window of the scripted fight.

    python tests/vk7_clean.py <log>...          the run must have been made with SSBU_HITCH=30 (or less) and SSBU_VK_HOLDLOG=1

A window is a FIGHT window when its "nvn_vk_perf:" line has compute dispatches (as tests/vk4_windows.py). For every fight
window: the frames over 33.4 ms (from the "hitch: frame" lines), the longest one, and for each of those frames its two
largest buckets that are not the frame limiter ("pace"). Then the holds of the render thread at a draw ("nvn_vk_hold:"
lines) that fell in fight frames, and the GPU time per frame of the fight windows when SSBU_VK_GPUTIME=1 was set."""
import re, sys, collections

LIMIT = 33.4
for path in sys.argv[1:]:
    text = open(path, errors='replace').read()
    fight = []
    for m in re.finditer(r'nvn_vk_perf: frames (\d+)\.\.(\d+) .*?per frame: ([\d.]+) dispatches', text):
        if float(m.group(3)) > 0:
            fight.append((int(m.group(1)), int(m.group(2))))
    mx = {}
    for m in re.finditer(r'nvn_perf: frames (\d+)\.\.(\d+) frame time ms: avg ([\d.]+) min ([\d.]+) median ([\d.]+) p99 ([\d.]+) max ([\d.]+) \| fps avg ([\d.]+)', text):
        mx[int(m.group(2))] = (float(m.group(7)), float(m.group(8)), float(m.group(6)))
    gpu = {}
    for m in re.finditer(r'nvn_vk_gpu: frames (\d+)\.\.(\d+): GPU time ([\d.]+) ms', text):
        gpu[int(m.group(2))] = float(m.group(3))
    hitches = []
    for m in re.finditer(r'hitch: frame (\d+) ([\d.]+) ms \|[^\[\n]*(.*)', text):
        buckets = [(float(a), b) for a, b in re.findall(r'\[([\d.]+) ms ([^\]]*)\]', m.group(3))]
        hitches.append((int(m.group(1)), float(m.group(2)), buckets))
    holds = []
    for m in re.finditer(r'nvn_vk_hold: frame (\d+) \((fight|no fight)\): (.*)', text):
        holds.append((int(m.group(1)), m.group(2), m.group(3)))
    name = path.replace('\\', '/').split('/')[-1]
    clean = 0
    causes = collections.Counter()
    cause_ms = collections.Counter()
    lines = []
    for a, b in fight:
        over = [h for h in hitches if a < h[0] <= b and h[1] > LIMIT]
        # the hitch log may be missing (run without SSBU_HITCH): then only the window's longest frame is known
        longest = mx.get(b, (0, 0, 0))[0]
        ok = not over and longest <= LIMIT
        clean += ok
        detail = []
        for fr, ms, bk in over:
            top = sorted([x for x in bk if not x[1].startswith('pace')], reverse=True)[:2]
            detail.append('%d: %.0f ms (%s)' % (fr, ms, '; '.join('%.0f ms %s' % (t, n[:60]) for t, n in top)))
            if top:
                causes[top[0][1][:60]] += 1
                cause_ms[top[0][1][:60]] += ms
        nh = [h for h in holds if a < h[0] <= b]
        lines.append('  %6d..%-6d | fps %5.1f p99 %5.1f longest %6.1f ms | %d frames over %.1f ms | %d holds | GPU %s ms%s%s' % (
            a, b, mx.get(b, (0, 0, 0))[1], mx.get(b, (0, 0, 0))[2], longest, len(over), LIMIT, len(nh), ('%.2f' % gpu[b]) if b in gpu else '-',
            '' if ok else '   <-- NOT clean', ''.join('\n        ' + d for d in detail[:6])))
    print('%s: %d fight windows, %d clean by the target (no frame over %.1f ms)' % (name, len(fight), clean, LIMIT))
    print('\n'.join(lines))
    if causes:
        print('  largest bucket of the frames over the limit in fight windows (frames, ms of those frames):')
        for c, n in causes.most_common(8):
            print('    %3d frames %7.0f ms  %s' % (n, cause_ms[c], c))
    # session 9, shader_wait = skip: draws left out because a stage or pipeline was not ready ("nvn_vk_skipf:" per frame)
    skips = [(int(m.group(1)), m.group(2), int(m.group(3))) for m in re.finditer(r'nvn_vk_skipf: frame (\d+) \((fight|no fight)\): (\d+) draws', text)]
    if skips or 'shader_wait = skip' in text:
        progs = collections.Counter(m.group(1) for m in re.finditer(r'nvn_vk_skip: frame \d+: a draw left out.*?: (vertex code \w+, fragment code \w+)', text))
        print('  draws LEFT OUT (shader_wait = skip): %d in %d frames (%d of the frames in a fight); per fight window: %s' % (
            sum(s[2] for s in skips), len(skips), sum(1 for s in skips if s[1] == 'fight'),
            ', '.join('%d..%d: %d draws / %d frames' % (a, b, sum(s[2] for s in skips if a < s[0] <= b), sum(1 for s in skips if a < s[0] <= b)) for a, b in fight if any(a < s[0] <= b for s in skips)) or 'none'))
        for p, n in progs.most_common(12):
            print('    %4d draws: %s' % (n, p))
    hf = [h for h in holds if h[1] == 'fight']
    print('  holds at a draw: %d in all, %d in fight frames' % (len(holds), len(hf)))
    for fr, _, what in hf[:12]:
        print('    frame %d: %s' % (fr, what[:230]))
