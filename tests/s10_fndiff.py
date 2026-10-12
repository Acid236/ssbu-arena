"""S10: function-by-function comparison of two trees of generated status sources.
    python tests/s10_fndiff.py <old status dir> <new status dir> [names file ...]
Prints every function whose text changed with a reason class, and counts; with names files (one name per line, a
second column is ignored) says for each list how many of its names changed. No game content in this file."""
import difflib
import glob
import os
import re
import sys


def functions(d):
    out = {}
    for p in glob.glob(os.path.join(d, '*.cpp')):
        s = open(p, encoding='utf-8', newline='').read()
        for m in re.finditer(r'^(L2C_\w+\(\w+, (\w+)[^\n]*\{\n)(.*?)^\}\n?', s, re.S | re.M):
            out[m.group(2)] = (m.group(1), m.group(3), os.path.basename(p))
    return out


def classify(old, new):
    d = [l for l in difflib.unified_diff(old.split('\n'), new.split('\n'), lineterm='', n=0) if l[:1] in '+-' and l[:3] not in ('+++', '---')]
    minus = '\n'.join(l[1:] for l in d if l[0] == '-')
    plus = '\n'.join(l[1:] for l in d if l[0] == '+')
    cls = []
    if 'gcall<uint' in plus or 'gcall<uint' in minus:
        cls.append('x0 after a float function')
    if re.search(r'get_speed|get_value_float|= (sv_|app::)|float v\d+ = \w+\(agent', plus) and not cls:
        cls.append('stale float (result of a script call that returns a float)')
    if 'lerp(' in plus or 'lerp(' in minus:
        cls.append('lerp')
    if 'singleton(' in plus:
        cls.append('singleton argument')
    if 'status_function(' in plus or 'function_address(' in plus:
        cls.append('function address')
    return cls or ['other'], d


def main():
    old, new = functions(sys.argv[1]), functions(sys.argv[2])
    lists = {os.path.basename(p): set(l.split()[0] for l in open(p) if l.strip()) for p in sys.argv[3:]}
    changed = {}
    for k in sorted(set(old) & set(new)):
        if old[k][1] != new[k][1] or old[k][0] != new[k][0]:
            changed[k] = classify(old[k][1], new[k][1])
    print('functions: old %d, new %d, in both %d, text changed %d, only old %d, only new %d' %
          (len(old), len(new), len(set(old) & set(new)), len(changed), len(set(old) - set(new)), len(set(new) - set(old))))
    by = {}
    for k, (cls, d) in changed.items():
        by.setdefault(' + '.join(cls), []).append(k)
    for c, names in sorted(by.items()):
        print('class "%s": %d' % (c, len(names)))
    for k, (cls, d) in changed.items():
        tags = [n for n, s in lists.items() if k in s]
        print('CHANGED %s  [%s]%s' % (k, ' + '.join(cls), '  IN ' + ','.join(tags) if tags else ''))
        for l in d[:8]:
            print('    ' + l[:230])
    print('only old: ' + ' '.join(sorted(set(old) - set(new))))
    print('only new: ' + ' '.join(sorted(set(new) - set(old))))
    for n, s in lists.items():
        print('list %s: %d names, changed %d (%s), missing in new %d (%s)' % (n, len(s), len(s & set(changed)), ' '.join(sorted(s & set(changed))),
                                                                              len(s - set(new)), ' '.join(sorted(s - set(new)))))


main()
