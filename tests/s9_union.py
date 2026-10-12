"""python tests/s9_union.py <report> [<report> ...]
Union of the real-call differential reports (module lua2cpp_common only): per name calls / equal (both kinds) / differ.
Prints the summary per report, then the union totals; with --lists writes tests/logs/s9_union.tsv."""
import re
import sys
from collections import defaultdict

ROW = re.compile(r'^\s+(\w+)\s+calls\s+(\d+)\s+equal\s+(\d+)\s+equal-interrupted\s+(\d+)\s+differ\s+(\d+)\s+at\s+(0x[0-9a-f]+)')
tot = defaultdict(lambda: [0, 0, 0, 0])      # calls, equal (incl. interrupted), differ, runs
runs = {}
for path in [a for a in sys.argv[1:] if not a.startswith('--')]:
    section = None
    names = {}
    head = ''
    for line in open(path, errors='replace'):
        if line.startswith('module '):
            section = line.split()[1].rstrip(':')
            if section == 'lua2cpp_common':
                head = line.strip()
            continue
        if section != 'lua2cpp_common':
            continue
        m = ROW.match(line)
        if m:
            n = m.group(1)
            c, e, ei, d = (int(m.group(i)) for i in (2, 3, 4, 5))
            a = names.setdefault(n, [0, 0, 0])
            a[0] += c; a[1] += e + ei; a[2] += d
        elif 'differential, by call' in line:
            head += ' | ' + line.strip()
    runs[path] = (head, names)
    t = [sum(v[0] for v in names.values()), sum(v[1] for v in names.values()), sum(v[2] for v in names.values())]
    print('%s\n   %s\n   names %d, calls %d, compared-equal %d, differ %d, names differing %s' % (
        path, head[:300], len(names), t[0], t[1], t[2], [n for n, v in names.items() if v[2]]))
    for n, v in names.items():
        a = tot[n]
        a[0] += v[0]; a[1] += v[1]; a[2] += v[2]; a[3] += 1
print('UNION: names %d, equal on every compared call %d, differing %s, never compared %d' % (
    len(tot), sum(1 for v in tot.values() if v[2] == 0 and v[1] > 0), sorted(n for n, v in tot.items() if v[2]),
    sum(1 for v in tot.values() if v[1] == 0 and v[2] == 0)))
if '--lists' in sys.argv:
    with open('tests/logs/s9_union.tsv', 'w') as f:
        for n, v in sorted(tot.items()):
            f.write('%s\t%d\t%d\t%d\t%d\n' % (n, v[0], v[1], v[2], v[3]))
