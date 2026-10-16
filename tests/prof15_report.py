"""Round "four players": turn a prof15.c dump (SSBU_PROF15) into tables.
    python tests/prof15_report.py <dump file> <exe .map> <frames in the window> [top N] [thread name filter]
Per sampled thread: CPU ms per frame, the share of samples per CLASS (by innermost frame), the top N functions by self
samples and by inclusive samples, each as ms per frame of that thread's CPU (waiting samples are left out of the
scale: innermost frame in ntdll / win32u / kernelbase wait stubs under a thread that used no CPU cannot be told from
a system call that works, so the scale is cpu_ms / (samples that are not in those modules)). No game content."""
import bisect
import collections
import re
import sys

dump, mapf, frames = sys.argv[1], sys.argv[2], float(sys.argv[3])
topn = int(sys.argv[4]) if len(sys.argv) > 4 else 40
only = sys.argv[5] if len(sys.argv) > 5 else None

syms = []
for line in open(mapf, errors='replace'):
    m = re.match(r'\s*[0-9a-f]{4}:[0-9a-f]{8}\s+(\S+)\s+([0-9a-f]{16})\s+(f\s+)?(i\s+)?(\S+)', line)
    if m and int(m.group(2), 16) >= 0x140000000:
        syms.append((int(m.group(2), 16) - 0x140000000, m.group(1), m.group(5)))
syms.sort()
rvas = [s[0] for s in syms]
exe = dump and None


def host_name(mod, off):
    if mod.lower().startswith('ssbu_') and mod.lower().endswith('.exe'):
        i = bisect.bisect_right(rvas, off) - 1
        if i >= 0:
            return syms[i][1], syms[i][2]
        return 'exe+%x' % off, '?'
    return '%s+%x' % (mod, off), mod


WAIT_MODS = ('ntdll.dll', 'win32u.dll')


def klass(kind, mod, name, obj):
    if kind == 'G':
        a = int(name, 16)
        return 'lifted game (main)' if a < 0x7200000000 else 'lifted game (script modules / fighter source)'
    m = mod.lower()
    if m.startswith('ssbu_') and m.endswith('.exe'):
        o = obj.lower()
        if name.startswith('f_75') or 'sdklift' in o:
            return 'lifted SDK'
        if o.startswith('nvn_vk') or o.startswith('vk_'):
            return 'renderer (nvn_vk*: front + back)'
        if o.startswith('nvn_'):
            return 'renderer front (nvn_gl / stub / sdk)'
        if 'libucrt' in o or 'libcmt' in o or 'libvcruntime' in o or 'clang_rt' in o:
            return 'C runtime (ours, static)'
        return 'our runtime (%s)' % obj
    if m.startswith('ssbu_game'):
        return 'game DLL helper (not a lifted function)'
    if m in WAIT_MODS:
        return 'ntdll / win32u (wait or system call)'
    if m.startswith('nvoglv') or m.startswith('nvgpucomp') or m.startswith('nvppe') or m.startswith('nvwgf') or m.startswith('nv'):
        return 'NVIDIA driver'
    if m.startswith('vulkan'):
        return 'Vulkan loader'
    if m.endswith('.nro.dll') or 'nro' in m or m.startswith('lua2cpp') or m.startswith('common') or m.endswith('_src.dll'):
        return 'lifted game (script modules / fighter source)'
    return 'other DLL (%s)' % mod


threads = {}
fns = collections.defaultdict(list)
pairs = collections.defaultdict(list)
for line in open(dump, errors='replace'):
    p = line.split()
    if len(p) < 3 or p[0] != '[p15]':
        continue
    if p[1] == 'T':
        threads[int(p[2])] = dict(tid=p[4], cpu=float(p[6]), samples=int(p[8]), name=' '.join(p[10:]))
    elif p[1] == 'F':
        fns[int(p[2])].append((p[3], p[4], p[5], int(p[6]), int(p[7])))
    elif p[1] == 'P':
        m = re.match(r'\[p15\] P (\d+) (\S+) ([0-9a-f]+) <- (\S+) ([0-9a-f]+) \| guest ([0-9a-f]+) : (\d+)', line)
        if m:
            pairs[int(m.group(1))].append((m.group(2), int(m.group(3), 16), m.group(4), int(m.group(5), 16), int(m.group(6), 16), int(m.group(7))))
    elif p[1] == 'window':
        print(line.strip())

for t in sorted(threads, key=lambda t: -threads[t]['cpu']):
    th = threads[t]
    if only and only.lower() not in th['name'].lower() and only != str(t):
        continue
    rows = []
    for kind, mod, a, s, inc in fns[t]:
        if kind == 'G':
            name, obj = 'f_' + a, ''
            k = klass('G', mod, a, '')
        else:
            name, obj = host_name(mod, int(a, 16))
            k = klass('H', mod, name, obj)
        rows.append((name, k, s, inc, mod))
    busy = sum(r[2] for r in rows if r[4].lower() not in WAIT_MODS)
    waits = th['samples'] - busy
    scale = th['cpu'] / frames / busy if busy else 0.0
    print('\n=== thread %d "%s" tid %s: CPU %.2f ms per frame (%.0f ms over %.0f frames); %d samples, %d with the innermost frame in ntdll / win32u (waiting or system call)'
          % (t, th['name'], th['tid'], th['cpu'] / frames, th['cpu'], frames, th['samples'], waits))
    by = collections.Counter()
    for name, k, s, inc, mod in rows:
        if mod.lower() not in WAIT_MODS:
            by[k] += s
    print('  by class of the innermost frame (ms per frame, share of busy samples):')
    for k, s in by.most_common():
        if s * scale >= 0.005:
            print('    %6.2f  %5.1f %%  %s' % (s * scale, 100.0 * s / busy, k))
    print('  top %d by SELF (ms per frame, %% busy, function, class):' % topn)
    for name, k, s, inc, mod in sorted((r for r in rows if r[4].lower() not in WAIT_MODS), key=lambda r: -r[2])[:topn]:
        if s:
            print('    %6.3f  %5.1f %%  %-44s %s' % (s * scale, 100.0 * s / busy, name[:44], k))
    print('  top %d by INCLUSIVE (ms per frame, %% of all samples, function, class):' % topn)
    for name, k, s, inc, mod in sorted(rows, key=lambda r: -r[3])[:topn]:
        print('    %6.3f  %5.1f %%  %-44s %s' % (inc * scale, 100.0 * inc / max(1, th['samples']), name[:44], k))
    pr = collections.Counter()
    for m1, o1, m2, o2, g, n in pairs[t]:
        if m1.lower() in WAIT_MODS:
            continue
        leaf = host_name(m1, o1)[0]
        par = ('f_%x' % o2) if m2 == 'guest' else host_name(m2, o2)[0]
        pr[(leaf, par, 'f_%x' % g if g else '-')] += n
    print('  innermost host frames with their caller and the nearest lifted function (top 25, ms per frame):')
    for (leaf, par, g), n in pr.most_common(25):
        print('    %6.3f  %-34s <- %-34s | %s' % (n * scale, leaf[:34], par[:34], g))
