"""python tests/s9_lists.py <report> ...   -> fighters/common/proven_s9.txt, proven_s9_weak.txt (+ a summary on stdout)
Rule (conservative, S7 counts of the weak names were 1-2 and are not kept per name):
  any differing call in a new run              -> not proven (listed)
  S7 strong (proven_s7 minus weak)             -> stays strong
  S7 weak, new runs compared >= 2 times        -> strong (1-2 old + >= 2 new >= 3)
  S7 weak, fewer                               -> stays weak
  not in S7, new runs compared >= 3            -> strong; 1-2 -> weak
status_end_EscapeAir: counted like any other name (its source was changed in S9)."""
import os
import re
import subprocess
import sys
from collections import defaultdict

ROW = re.compile(r'^\s+(\w+)\s+calls\s+(\d+)\s+equal\s+(\d+)\s+equal-interrupted\s+(\d+)\s+differ\s+(\d+)\s+at\s+(0x[0-9a-f]+)')
new = defaultdict(lambda: [0, 0])      # compared-equal, differ
for path in sys.argv[1:]:
    sec = None
    for line in open(path, errors='replace'):
        if line.startswith('module '):
            sec = line.split()[1].rstrip(':')
            continue
        m = ROW.match(line)
        if m and sec == 'lua2cpp_common':
            new[m.group(1)][0] += int(m.group(3)) + int(m.group(4))
            new[m.group(1)][1] += int(m.group(5))
d = 'fighters/common/'
s7 = [l.split()[0] for l in open(d + 'proven_s7.txt') if l.strip()]
weak7 = set(l.strip() for l in open(d + 'proven_s7_weak.txt') if l.strip())
strong, weak, bad = set(), set(), []
for n in set(s7) | set(new):
    eq, df = new[n] if n in new else (0, 0)
    if df:
        bad.append(n)
        continue
    if n in s7 and n not in weak7:
        strong.add(n)
    elif n in weak7:
        (strong if eq >= 2 else weak).add(n)
    elif eq >= 3:
        strong.add(n)
    elif eq >= 1:
        weak.add(n)
# S9: source changed after its S7 proof (x0 after a float function), compared again in a new run or out
for n in ('sub_attack_s4_uniq_process_exit', 'sub_escape_air_uniq', 'status_end_EscapeAir'):
    if new.get(n, [0, 0])[0] < 1:
        strong.discard(n); weak.discard(n)
promoted = sorted(n for n in weak7 if n in strong)
newly = sorted(n for n in strong | weak if n not in s7)
keep = strong | weak
lines = {}                                  # keep the S7 line (a name with the offset the runs saw, or a bare name) as it was
for l in open(d + 'proven_s7.txt'):
    if l.strip() and l.split()[0] in keep:
        lines[l.split()[0]] = l.strip()
open(d + 'proven_s9.txt', 'w').write(''.join(lines.get(n, n) + '\n' for n in sorted(keep)))
open(d + 'proven_s9_weak.txt', 'w').write(''.join(n + '\n' for n in sorted(weak)))
print('strong %d, weak %d, total %d; differing %s; S7 weak promoted %d; new names %d (%d strong)' % (
    len(strong), len(weak), len(strong | weak), bad, len(promoted), len(newly), len([n for n in newly if n in strong])))
print('S7 weak compared again in new runs: ' + ', '.join('%s(%d)' % (n, new[n][0]) for n in sorted(weak7) if n in new))
print('NEW:', ' '.join(newly))
