"""S14: exclude the CLASS of status functions that compute with vectors held as tables (lib::L2CTable values), the class of the two
pikachu functions that were found with a type-5 argument (Vector2__normalize(table - table)) in the differential and crashed in the hit match.
Rule (text of the generated source, per function body):
  R1  the body calls Vector2/3/4 __normalize, __length, __length_square, __dot, __cross (any Vector<n>__ call that is not __create), or
  R2  a binary + - * / is applied to an L2CValue built from a Vector<n>__create call (a table operand), or
  R3  an L2CValue local that holds a Vector<n>__create result is an operand of + - * / (table arithmetic).
The decompiler's own cascade ("calls a local function that stays original") then keeps the callers lifted after the next decompile.
    python tests/s14_vec_exclude.py <workroot> [--write]     list per fighter; with --write add the names to tools_out/status/<f>_exclude.json
No game content in this file."""
import json
import os
import re
import sys

STUDY = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
root = os.path.join(STUDY, 'fighters', sys.argv[1])
write = '--write' in sys.argv
HEAD = re.compile(r'^(?:L2C_\w*FUNCTION\w*\(\s*\w+\s*,\s*(\w+)|L2CValue local::(\w+)\(|\w[\w:<>\* ]* local::(\w+)\()')
R1 = re.compile(r'Vector[234]__(?!create)\w+\(')
R2 = re.compile(r'[-+*/]\s*L2CValue\(\s*L2CFighterBase::Vector[234]__create|L2CFighterBase::Vector[234]__create\([^;]*\)\s*\)?\s*[-+*/]\s')
total = 0
rows = []
for f in sorted(os.listdir(root)):
    sd = os.path.join(root, f, 'status')
    if not os.path.isdir(sd):
        continue
    names = {}
    for fn in sorted(os.listdir(sd)):
        if not fn.endswith('.cpp'):
            continue
        cur, body = None, []
        for line in open(os.path.join(sd, fn), errors='replace'):
            m = HEAD.match(line)
            if m:
                cur, body = m.group(1) or m.group(2) or m.group(3), [line]
                continue
            if cur:
                body.append(line)
                if line.startswith('}'):
                    text = ''.join(body)
                    why = None
                    if R1.search(text):
                        why = 'R1'
                    elif R2.search(text):
                        why = 'R2'
                    else:
                        tabs = set(re.findall(r'L2CValue (\w+) = L2CFighterBase::Vector[234]__create', text))
                        for t in tabs:
                            if re.search(r'L2CValue\(%s\)\s*[-+*/]\s|[-+*/]\s*L2CValue\(%s\)|\b%s\s*[-+*/]\s' % (t, t, t), text):
                                why = 'R3'
                                break
                    if why:
                        names[cur] = 'S14 class "vector as table": %s (a table value compared by address in the differential, and the Final of one fighter crashed after such a mismatch); left lifted' % why
                    cur = None
    if names:
        rows.append((f, len(names)))
        total += len(names)
        xp = os.path.join(root, 'tools_out', 'status', f + '_exclude.json')
        old = json.load(open(xp)) if os.path.exists(xp) else {}
        new = {k: v for k, v in names.items() if k not in old}
        print('%-12s %3d in the class, %3d new' % (f, len(names), len(new)), ' '.join(sorted(names)[:4]))
        if write and new:
            old.update(new)
            json.dump(old, open(xp, 'w'), indent=1)
print('total', total)
