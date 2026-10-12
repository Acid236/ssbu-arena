"""S10: the three lists of lua2cpp_common functions from the forced-entry sweeps and the old proven set.
    python tests/s10_lists.py <report> [<report> ...]
Reads fighters\\common\\proven_s9.txt (proven by normal play; lines "name [0xoffset]") and the sweep reports
(real-call differential under debug injection). Writes into fighters\\common\\:
    proven_s10_normal.txt   the old list, minus names that differ in a sweep
    proven_s10_forced.txt   not in the old list; compared 3 times or more in the sweeps, equal on every compared call
    proven_s10_weak.txt     not in the old list; compared 1 or 2 times, equal
    proven_s10_install.txt  normal + forced (what SSBU_FIGHTER_ONLY gets)
    s10_differing.txt       names with a differing call and the first difference
"forced" is not "normal play": the status was requested by a test command, the situation around it is not one the
game would have produced. No game content in this file beyond exported function names."""
import os
import re
import sys

STUDY = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
ROW = re.compile(r'^\s+(\S+)\s+calls\s+(\d+)\s+equal\s+(\d+)\s+equal-interrupted\s+(\d+)\s+differ\s+(\d+)\s+at\s+(0x[0-9a-f]+)(.*)')
tot = {}
for p in sys.argv[1:]:
    section = None
    for line in open(p, errors='replace'):
        if line.startswith('module '):
            section = line.split()[1].rstrip(':')
            continue
        m = ROW.match(line) if section == 'lua2cpp_common' else None
        if m:
            a = tot.setdefault(m.group(1), [0, 0, 0, ''])
            a[0] += int(m.group(2))
            a[1] += int(m.group(3)) + int(m.group(4))
            a[2] += int(m.group(5))
            f = re.search(r'first: (.*)', m.group(7))
            if f and not a[3]:
                a[3] = f.group(1).strip()
cdir = os.path.join(STUDY, 'fighters', 'common')
old_lines = [l.strip() for l in open(os.path.join(cdir, 'proven_s9.txt')) if l.strip()]
old = set(l.split()[0] for l in old_lines)
differ = sorted(n for n, v in tot.items() if v[2])
normal = [l for l in old_lines if l.split()[0] not in differ]
forced = sorted(n for n, v in tot.items() if n not in old and not v[2] and v[1] >= 3)
weak = sorted(n for n, v in tot.items() if n not in old and not v[2] and 1 <= v[1] <= 2)
never = sorted(n for n, v in tot.items() if not v[1] and not v[2])


def write(name, lines):
    with open(os.path.join(cdir, name), 'w', newline='\n') as f:
        f.write('\n'.join(lines) + ('\n' if lines else ''))


write('proven_s10_normal.txt', normal)
write('proven_s10_forced.txt', forced)
write('proven_s10_weak.txt', ['%s %d' % (n, tot[n][1]) for n in weak])
write('proven_s10_install.txt', normal + forced)
write('s10_differing.txt', ['%s\tcalls %d equal %d differ %d\t%s' % (n, tot[n][0], tot[n][1], tot[n][2], tot[n][3]) for n in differ])
print('sweeps (%d reports): names called %d, compared %d, equal on every compared call %d, differing %d, never compared %d' % (
    len(sys.argv) - 1, len(tot), sum(1 for v in tot.values() if v[1] or v[2]), sum(1 for v in tot.values() if v[1] and not v[2]), len(differ), len(never)))
print('old proven set (normal play): %d names; of them called in the sweeps %d, compared equal again %d, differing now %d (%s)' % (
    len(old), len(old & set(tot)), sum(1 for n in old if n in tot and tot[n][1] and not tot[n][2]), len(old & set(differ)), ' '.join(sorted(old & set(differ)))))
print('union old + sweeps, equal on every compared call: %d names' % len((old - set(differ)) | set(n for n, v in tot.items() if v[1] and not v[2])))
print('lists: normal %d names (%d lines), forced %d, weak %d, install %d lines' % (len(set(l.split()[0] for l in normal)), len(normal), len(forced), len(weak), len(normal) + len(forced)))
for n in differ:
    print('   DIFFERS %s: calls %d equal %d differ %d: %s' % (n, tot[n][0], tot[n][1], tot[n][2], tot[n][3][:170]))
