"""Round 16 (P3 section 15): the long frames of a fight, one by one, with their cause from the hitch table.
    python tests/p16_late.py <log> [threshold ms = 20] [list = 0|1]
Takes the "hitch: frame N T ms | ... | [x ms bucket] ..." lines after the first battle frame + 60 (the frames before are
the stage's entrance) whose time is over the threshold, and groups them by the largest bucket that is not the pacer's
wait ("pace" = the frame was finished and waited for its tick: when it is the largest bucket the line before it is the
frame that was late). Renderer events of the same frame (nvn_vk_hold / nvn_vk_upl / nvn_vk_first lines) are attached.
Prints the groups and, with list = 1, every frame. No game content."""
import collections
import re
import sys

path = sys.argv[1]
thr = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
show = len(sys.argv) > 3 and sys.argv[3] == '1'
lines = open(path, errors='replace').read().splitlines()
first = None
events = collections.defaultdict(list)
rows = []
for ln in lines:
    if first is None:
        m = re.search(r'first battle frame is frame (\d+)', ln)
        if m:
            first = int(m.group(1))
    m = re.match(r'nvn_vk_(hold|upl|first): frame (\d+)', ln)
    if m:
        events[int(m.group(2))].append(m.group(1) + ': ' + ln.split(':', 2)[2].strip()[:150])
    m = re.match(r'hitch: frame (\d+) ([\d.]+) ms \|.*?\| (\d+) page faults \| (.*)', ln)
    if m:
        rows.append((int(m.group(1)), float(m.group(2)), int(m.group(3)), re.findall(r'\[([\d.]+) ms ([^\]]*)\]', m.group(4))))
groups = collections.Counter()
gtime = collections.Counter()
n = 0
for fr, ms, pf, buckets in rows:
    if first is None or fr < first + 60 or ms <= thr:
        continue
    n += 1
    real = [(float(a), b) for a, b in buckets if not b.startswith('pace')]
    pace = sum(float(a) for a, b in buckets if b.startswith('pace'))
    if real and real[0][0] >= 2.5:
        name = re.sub(r'\|.*', '', real[0][1]).strip()
        name = re.sub(r'lifted code$', 'lifted code', name)
    elif pace >= 5.0:
        name = 'pace only (the frame BEFORE it was late, or the tick was missed by little): no bucket of 2.5 ms'
    else:
        name = 'no single bucket of 2.5 ms (budget: many small ones)'
    ev = events.get(fr, []) + events.get(fr - 1, [])
    if ev:
        name += '  + RENDERER EVENT in the frame'
    groups[name] += 1
    gtime[name] += ms
    if show:
        print('frame %d: %.1f ms, %d page faults: %s%s' % (fr, ms, pf, ' '.join('[%s %s]' % (a, b[:60]) for a, b in buckets[:4]), (' || ' + ' ; '.join(ev)) if ev else ''))
print('%s: first battle frame %s; %d hitch lines over %.0f ms in the fight' % (path, first, n, thr))
for name, c in groups.most_common():
    print('  %4d  (mean %.1f ms)  %s' % (c, gtime[name] / c, name))
for ln in lines:
    if ln.startswith('display-timing: fight frames') or ln.startswith('nvn_vk_first: ') and 'battle frames' in ln:
        print('  ' + ln[:420])
# SSBU_LATELOG=1: the frames that really were late ("display-late:" lines), each with the hitch lines of the two
# presented frames before it and the renderer events of those frames
by_frame = {fr: (ms, pf, buckets) for fr, ms, pf, buckets in rows}
late = []
for ln in lines:
    m = re.match(r'display-late: the frame shown before presented frame (\d+) was on screen for (-?\d+) refreshes; ([\d.]+) ms', ln)
    if m and first is not None and int(m.group(1)) >= first + 60:
        late.append((int(m.group(1)), int(m.group(2)), float(m.group(3))))
if late:
    cause = collections.Counter()
    print('  %d late fight frames (display-late lines after the entrance):' % len(late))
    for fr, refs, ms in late:
        best = None
        ev = []
        for f in (fr - 2, fr - 1, fr, fr + 1):
            ev += events.get(f, [])
            if f in by_frame:
                real = [(float(a), b) for a, b in by_frame[f][2] if not b.startswith('pace')]
                if real and (best is None or real[0][0] > best[0]):
                    best = (real[0][0], re.sub(r'\|.*', '', real[0][1]).strip(), f)
        if refs < 2:
            name = 'SHORT (1 refresh): the frame after a late one'
        elif best is None or best[0] < 2.5:
            name = 'no single bucket of 2.5 ms in the hitch lines around it (budget, or under the 18 ms hitch threshold)'
        else:
            name = best[1]
        if ev:
            name += '  + RENDERER EVENT'
        cause[name] += 1
        if show:
            print('    frame %d: %d refreshes, %.1f ms; largest bucket near it: %s%s' % (fr, refs, ms, ('%.1f ms %s (frame %d)' % best) if best else '-', (' || ' + ' ; '.join(ev[:3])) if ev else ''))
    for name, c in cause.most_common():
        print('    %4d  %s' % (c, name))
