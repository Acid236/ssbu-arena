"""S18 (generator coverage): tables and guards over the generated fighter status sources. Nothing here runs the game.

    python tests/s18_tool.py refusals <tree> [out.txt]      refused functions by reason (count, fighters, example, bytes),
                                                           and what the cascade ("calls a local function that stays
                                                           original") is blocked by
    python tests/s18_tool.py cover <tree>                   functions / source per fighter, worst five
    python tests/s18_tool.py guard <old tree> <new tree>    every function that is source in <old>: is its text in <new>
                                                           identical? lists changed / gone / new, and the fighters touched
    python tests/s18_tool.py check <tree> [names file]      static self-check of the generated text (see check())

<tree> is a folder under fighters\\ (work_s18). Functions are cut out of status\\*.cpp by their head line.
"""
import collections
import json
import os
import re
import sys

STUDY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIGHTERS = os.path.join(STUDY, 'fighters')
HEAD = re.compile(r'^(?:L2C_(?:VOID_)?FUNCTION\d*\((\w+), (\w+)[,)]|L2CValue local::(\w+)\()')


def status_json(tree):
    d = os.path.join(FIGHTERS, tree, 'tools_out', 'status')
    out = {}
    for nm in sorted(os.listdir(d)):
        if nm.endswith('_status.json') and not nm.startswith('_'):
            with open(os.path.join(d, nm)) as f:
                out[nm[:-len('_status.json')]] = json.load(f)
    return out


def key(why):
    why = why.split('+0x')[0]
    for k in ('differential test', 'does not compile', 'the offline test stops', 'calls a local function that stays original', 'S14 class "vector as table"'):
        if why.startswith(k):
            return k
    return re.sub(r'\b(v|x|w|s|d|q)\d+\b', r'\1N', why)[:64]


def refusals(tree, out=None):
    js = status_json(tree)
    cnt, byt, fighters, example = collections.Counter(), collections.Counter(), collections.defaultdict(set), {}
    blocked = collections.Counter()
    tot = ok = 0
    for name, j in js.items():
        for e in j['functions']:
            tot += 1
            if e['ok']:
                ok += 1
                continue
            k = key(e['why'])
            cnt[k] += 1
            byt[k] += e['size']
            fighters[k].add(name)
            example.setdefault(k, '%s:%s' % (name, e['ident']))
            if k.startswith('calls a local'):
                m = re.search(r'\((.*)\)$', e['why'])
                blocked[key(m.group(1)) if m else '?'] += 1
    lines = ['tree %s: %d functions, %d source (%.1f%%), %d refused' % (tree, tot, ok, 100.0 * ok / max(tot, 1), tot - ok), '',
             '%6s %8s %9s  %-64s %s' % ('count', 'fighters', 'bytes', 'reason', 'example')]
    for k, v in cnt.most_common():
        lines.append('%6d %8d %9d  %-64s %s' % (v, len(fighters[k]), byt[k], k, example[k]))
    lines += ['', 'the cascade, by the reason of the callee (first 40 characters of it; a chain shows as the cascade itself):']
    for k, v in blocked.most_common():
        lines.append('%6d  %s' % (v, k))
    text = '\n'.join(lines)
    if out:
        with open(out, 'w') as f:
            f.write(text + '\n')
    print(text)


def cover(tree):
    js = status_json(tree)
    rows = []
    for name, j in js.items():
        n = len(j['functions'])
        k = sum(1 for e in j['functions'] if e['ok'])
        rows.append((100.0 * k / max(n, 1), name, n, k))
    tn, tk = sum(r[2] for r in rows), sum(r[3] for r in rows)
    print('tree %s: %d fighters, %d functions, %d source (%.2f%%)' % (tree, len(rows), tn, tk, 100.0 * tk / max(tn, 1)))
    print('worst five: ' + '; '.join('%s %d of %d (%.1f%%)' % (nm, k, n, p) for p, nm, n, k in sorted(rows)[:5]))
    print('at 100%%: %d fighters' % sum(1 for r in rows if r[2] == r[3]))


def functions(tree, fighter):
    """{ident: text} of every function in fighters\\<tree>\\<fighter>\\status\\*.cpp"""
    d = os.path.join(FIGHTERS, tree, fighter, 'status')
    out = {}
    if not os.path.isdir(d):
        return out
    for nm in sorted(os.listdir(d)):
        if not nm.endswith('.cpp'):
            continue
        cur = None
        with open(os.path.join(d, nm)) as f:
            for line in f:
                m = HEAD.match(line)
                if m:
                    cur = m.group(2) or m.group(3)
                    out[cur] = [line]
                elif cur is not None:
                    out[cur].append(line)
                    if line.startswith('}'):
                        cur = None
    return {k: ''.join(v) for k, v in out.items()}


def fighters_of(tree):
    return sorted(n for n in os.listdir(os.path.join(FIGHTERS, tree)) if n != 'tools_out' and os.path.isdir(os.path.join(FIGHTERS, tree, n, 'status')))


def guard(old, new, listing=None):
    same = 0
    changed, gone, added = [], [], []
    touched = set()
    for f in sorted(set(fighters_of(old)) | set(fighters_of(new))):
        a, b = functions(old, f), functions(new, f)
        for k, t in a.items():
            if k not in b:
                gone.append('%s:%s' % (f, k))
                touched.add(f)
            elif b[k] != t:
                changed.append('%s:%s' % (f, k))
                touched.add(f)
            else:
                same += 1
        for k in b:
            if k not in a:
                added.append('%s:%s' % (f, k))
                touched.add(f)
    print('guard %s -> %s: %d functions of the old tree identical, %d changed, %d gone; %d new; fighters touched %d' %
          (old, new, same, len(changed), len(gone), len(added), len(touched)))
    for nm, l in (('CHANGED', changed), ('GONE', gone)):
        for x in l[:60]:
            print('  %s %s' % (nm, x))
        if len(l) > 60:
            print('  ... %d more' % (len(l) - 60))
    if listing:
        with open(listing, 'w') as f:
            f.write('# guard %s -> %s\n' % (old, new))
            for nm, l in (('changed', changed), ('gone', gone), ('new', added)):
                for x in l:
                    f.write('%s %s\n' % (nm, x))
            f.write('# fighters touched: %s\n' % ' '.join(sorted(touched)))
    print('fighters touched: ' + ' '.join(sorted(touched)))
    return changed, gone, added


def strip_text(t):
    t = re.sub(r'"(?:[^"\\]|\\.)*"', '""', t)
    return re.sub(r'//[^\n]*', '', t)


def call_args(text, pos):
    """number of top-level arguments of the call whose '(' is at text[pos]"""
    depth, n, seen = 0, 0, False
    for ch in text[pos:]:
        if ch in '([{':
            if depth == 1:
                seen = True                              # S20: an argument that starts with '(' is an argument too
            depth += 1
            continue
        if ch in ')]}':
            depth -= 1
            if depth == 0:
                return n + (1 if seen else 0)
            continue
        if depth == 1:
            if ch == ',':
                n += 1
            elif not ch.isspace():
                seen = True
    return -1


def check(tree, names=None):
    """static self-check of generated text, per function (all, or those listed as `new fighter:ident` in a guard listing):
      1. braces and parentheses balance, the text ends at the closing brace of the function;
      2. every `goto L` has exactly one label `L:` in the same function and every label is the target of a goto;
      3. every `local::name(agent, ...)` passes exactly the number of arguments the callee is recorded to read
         (<tree>\\tools_out\\status\\<fighter>_status.json, 'arity'), and the callee is source (ok) in the same tree;
      4. every `rN` used is assigned or declared in the function, every vN / nN variable used is declared;
      5. break / continue only inside a loop.
    What it does NOT show: that the function behaves like the original."""
    want = None
    if names:
        want = set()
        with open(names) as f:
            for line in f:
                p = line.split()
                if len(p) == 2 and p[0] in ('new', 'changed'):
                    want.add(p[1])
    js = status_json(tree)
    bad = []
    n = gotos = 0
    for f in fighters_of(tree):
        info = {e['ident']: e for e in js[f]['functions']}
        for ident, text in functions(tree, f).items():
            if want is not None and '%s:%s' % (f, ident) not in want:
                continue
            n += 1
            t = strip_text(text)
            why = []
            for o, c in ('{}', '()', '[]'):
                if t.count(o) != t.count(c):
                    why.append('unbalanced %s%s' % (o, c))
            labels = re.findall(r'^\s*(L\d+): ;', t, re.M)
            targets = re.findall(r'\bgoto (L\d+);', t)
            gotos += 1 if targets else 0
            if len(labels) != len(set(labels)):
                why.append('label defined twice')
            if set(targets) - set(labels):
                why.append('goto without label')
            if set(labels) - set(targets):
                why.append('label without goto')
            for m in re.finditer(r'\blocal::(\w+)\(', t):
                if m.start() < 20 and t.startswith('L2CValue local::'):
                    continue
                callee = info.get(m.group(1))
                got = call_args(t, m.end() - 1)
                if callee is None or not callee['ok']:
                    why.append('calls local::%s which is not source' % m.group(1))
                elif got != callee['arity'] + (0 if callee.get('plain') else 1):      # a helper without an agent takes its arguments only
                    why.append('local::%s called with %d arguments in all, reads %d%s' % (m.group(1), got, callee['arity'], '' if callee.get('plain') else ' + the agent'))
            body = t[t.index('{') + 1:]
            decl = set(re.findall(r'\b(?:L2CValue|auto|uint64_t|uint32_t|int64_t|int32_t|float|bool|Vector4f|void)\s+((?:(?:[rvnc][0-9a-f]+|result|held\d+)(?:,\s*)?)+);', body))
            declared = set(x for d in decl for x in re.split(r',\s*', d))
            declared |= set(re.findall(r'\b(?:L2CValue|auto|bool)\s+([rvnc][0-9a-f]+)\s*=', body))
            used = set(re.findall(r'(?<![\w.:>])([rvn]\d+)\b(?!\s*\()', body))
            if used - declared:
                why.append('used but not declared: %s' % ' '.join(sorted(used - declared)[:4]))
            depth_loop = []
            depth = 0
            for line in body.split('\n'):
                s = line.strip()
                if s in ('break;', 'continue;') and not depth_loop:
                    why.append('%s outside a loop' % s[:-1])
                opens, closes = line.count('{'), line.count('}')
                if s.startswith('}'):
                    depth -= 1
                    closes -= 1
                    while depth_loop and depth_loop[-1] > depth:
                        depth_loop.pop()
                    if depth_loop and depth_loop[-1] == depth and s.startswith('} else'):
                        pass
                if s.startswith('while (true) {'):
                    depth_loop.append(depth + 1)
                depth += opens - closes
                while depth_loop and depth_loop[-1] > depth:
                    depth_loop.pop()
            if why:
                bad.append(('%s:%s' % (f, ident), why))
    print('check %s: %d functions checked, %d with a goto, %d FAIL' % (tree, n, gotos, len(bad)))
    for nm, why in bad[:40]:
        print('  FAIL %s: %s' % (nm, '; '.join(why)))
    return bad


def unexclude(tree, text, listing):
    """take out of <tree>'s exclude files every function whose reason contains `text` (to give it to the offline gate
    again after a generator fix; the gate puts back what still differs). The removed entries are written to `listing`."""
    d = os.path.join(FIGHTERS, tree, 'tools_out', 'status')
    out = []
    for nm in sorted(os.listdir(d)):
        if not nm.endswith('_exclude.json'):
            continue
        p = os.path.join(d, nm)
        with open(p) as f:
            cur = json.load(f)
        take = {k: v for k, v in cur.items() if text in v}
        if take:
            for k, v in take.items():
                out.append('%s %s %s' % (nm[:-len('_exclude.json')], k, v))
                del cur[k]
            with open(p, 'w') as f:
                json.dump(cur, f, indent=1, sort_keys=True)
    with open(listing, 'w') as f:
        f.write('\n'.join(out) + '\n')
    print('unexclude %s: %d functions in %d fighters (%s)' % (tree, len(out), len(set(x.split()[0] for x in out)), listing))
    print(' '.join(sorted(set(x.split()[0] for x in out))))


def fixtree(old, new, fix, listing):
    """<fix> = a copy of <old> in which ONLY the functions that were source in <old> and whose text differs in <new>
    (other than by the order of the same lines) carry the text of <new>. Nothing that is new in <new> goes in: the
    generated headers, bindings, json and every other function stay those of <old>. Writes the list (fighter, function,
    class: held = a value kept before a call, float = float register, other) and prints it per fighter."""
    import shutil
    src, dst = os.path.join(FIGHTERS, old), os.path.join(FIGHTERS, fix)
    if os.path.exists(dst):
        raise SystemExit('%s exists' % dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns('offline_*', 'sdk_generated'))
    rows, gone = [], []
    for f in fighters_of(old):
        a, b = functions(old, f), functions(new, f)
        todo = {}
        for k, t in a.items():
            if k not in b:
                gone.append('%s:%s' % (f, k))
            elif b[k] != t and sorted(b[k].split('\n')) != sorted(t.split('\n')):
                added = [l for l in b[k].split('\n') if l not in t.split('\n')]
                cls = 'held' if any('held' in l for l in added) else 'float' if all('gcall<float>' in l for l in added) else 'other'
                todo[k] = cls
                rows.append((f, k, cls))
        if not todo:
            continue
        d = os.path.join(dst, f, 'status')
        left = dict(todo)
        for nm in sorted(os.listdir(d)):
            if not nm.endswith('.cpp'):
                continue
            p = os.path.join(d, nm)
            with open(p, newline='') as fh:
                text = fh.read()
            changed = False
            for k in list(left):
                if a[k] in text:
                    text = text.replace(a[k], b[k], 1)
                    del left[k]
                    changed = True
            if changed:
                with open(p, 'w', newline='') as fh:
                    fh.write(text)
        if left:
            raise SystemExit('%s: not found in the files: %s' % (f, ' '.join(left)))
    with open(listing, 'w') as fh:
        for f, k, cls in rows:
            fh.write('%s %s %s\n' % (f, k, cls))
        for g in gone:
            fh.write('# source in %s, not in %s: %s\n' % (old, new, g))
    by = collections.defaultdict(list)
    for f, k, cls in rows:
        by[f].append('%s(%s)' % (k, cls))
    c = collections.Counter(cls for f, k, cls in rows)
    print('fixtree %s: %d functions in %d fighters changed (%s); %d source in %s but not in %s' %
          (fix, len(rows), len(by), ', '.join('%s %d' % kv for kv in sorted(c.items())), len(gone), old, new))
    for f in sorted(by):
        print('  %s: %s' % (f, ' '.join(by[f])))
    with open(os.path.join(os.path.dirname(listing), os.path.basename(listing).replace('.txt', '_names.txt')), 'w') as fh:
        fh.write(' '.join(sorted(by)) + '\n')


WORDS = [('SPECIAL_AIR_N', 'neutral special in the air'), ('SPECIAL_AIR_S', 'side special in the air'), ('SPECIAL_AIR_HI', 'up special in the air'),
         ('SPECIAL_AIR_LW', 'down special in the air'), ('SPECIAL_N', 'neutral special'), ('SPECIAL_S', 'side special'), ('SPECIAL_HI', 'up special'),
         ('SPECIAL_LW', 'down special'), ('FINAL', 'Final Smash'), ('ATTACK_AIR', 'aerial attack'), ('ATTACK_S4', 'side smash'), ('ATTACK_HI4', 'up smash'),
         ('ATTACK_LW4', 'down smash'), ('ATTACK_S3', 'side tilt'), ('ATTACK_HI3', 'up tilt'), ('ATTACK_LW3', 'down tilt'), ('ATTACK_DASH', 'dash attack'),
         ('CATCH', 'grab'), ('THROW', 'throw'), ('WAIT', 'standing / waiting'), ('TURN_DASH', 'turn dash'), ('DASH', 'dash'), ('WALK', 'walk'),
         ('JUMP_AERIAL', 'double jump'), ('JUMP', 'jump'), ('LANDING', 'landing'), ('FALL', 'fall'), ('SQUAT', 'crouch'), ('SWIM', 'swim')]
LINES = {'STATUS_PRE': 'set-up before the status', 'STATUS_MAIN': 'main (start of the status)', 'STATUS_END': 'end of the status', 'INIT_STATUS': 'init',
         'EXEC_STATUS': 'every frame', 'EXEC_STOP': 'every frame during hit stop', 'EXIT_STATUS': 'exit', 'FIX_POS_SLOW': 'position fix', 'CHECK_ATTACK': 'on hit',
         'CHECK_DAMAGE': 'on being hit', 'MAP_CORRECTION': 'ground correction', 'FIX_CAMERA': 'camera', 'LEAVE_STOP': 'after hit stop', 'NOTIFY_DAMAGE': 'damage notice'}


def plain(kind, line):
    k = re.sub(r'^.*?STATUS_KIND_', '', kind)
    words = k
    for tok, w in WORDS:
        if tok in words:
            words = words.replace(tok, w, 1)
            break
    words = words.replace('_', ' ').lower().replace('final smash', 'Final Smash')
    ln = re.sub(r'^LUA_SCRIPT_STATUS_FUNC_', '', line)
    return '%s [%s]: %s' % (words, kind, LINES.get(ln, ln.lower()))


def moves(tree, fixlist, out):
    """for every function of the fix list: the status / move it belongs to, in plain words, from the registration
    (status kind constant + script line). A main loop belongs to the function that hands it to the game; a helper to
    the registered functions that reach it through calls between source functions (up to 6 named)."""
    js = status_json(tree)
    rows = [l.split() for l in open(fixlist) if l.strip() and not l.startswith('#')]
    lines = ['# fighter | function | class of the fix | status / move (from the registration: kind constant, script line)',
             '# class: held = a value read from the table before a call was read again after it; float = a float result was taken from the integer register;',
             '#        outvec = a vector a game function writes its result into was read back as the value that went in']
    for f, ident, cls in rows:
        j = js[f]
        by = {e['ident']: e for e in j['functions']}
        byoff = {e['off']: e for e in j['functions']}
        reg = collections.defaultdict(list)
        for ag in j['agents']:
            for kt, lt, fn, nm in ag['entries']:
                if nm:
                    reg[nm].append((ag['name'], kt, lt))
        callers = collections.defaultdict(set)
        for e in j['functions']:
            for t in e.get('calls', []):
                if t in byoff:
                    callers[byoff[t]['ident']].add(e['ident'])

        def owner(name):
            m = re.match(r'(.*?)_loop(_\d+)?$', name)
            return m.group(1) if m and m.group(1) in by else None

        def describe(name):
            if name in reg:
                return ['%s%s' % ('' if ag == f or ag.startswith('agent_') else 'article %s: ' % ag, plain(kt, lt)) for ag, kt, lt in reg[name]]
            o = owner(name)
            if o:
                return ['the loop that runs every frame of: %s' % d for d in describe(o)] or \
                    ['a callback set up by %s (at creation: runs in no particular status)' % o if o.endswith('_install') else 'a function whose address %s hands to the game' % o]
            return []

        d = describe(ident)
        if not d:
            seen, work, found = {ident}, [ident], []
            while work:
                x = work.pop(0)
                for c in sorted(callers.get(x, ())):
                    if c in seen:
                        continue
                    seen.add(c)
                    dc = describe(c)
                    if dc:
                        found += ['%s (%s)' % (dc[0], c)]
                    else:
                        work.append(c)
            d = ['helper used by: ' + '; '.join(found[:6]) + (' ... %d more' % (len(found) - 6) if len(found) > 6 else '')] if found else \
                ['helper: no source function calls it by name (reached through an address or from original code)']
        lines.append('%s | %s | %s | %s' % (f, ident, cls, ' ;; '.join(d[:4])))
    with open(out, 'w') as fh:
        fh.write('\n'.join(lines) + '\n')
    print('moves: %d functions -> %s' % (len(rows), out))


def oldlist(ref, tree):
    """<tree>\\tools_out\\status\\_old_functions.json = the functions that are source in <ref> (per fighter): the generator
    keeps their structure as it is and uses the readable structure (compound conditions) only for the others."""
    js = status_json(ref)
    out = {f: sorted(e['ident'] for e in j['functions'] if e['ok']) for f, j in js.items()}
    p = os.path.join(FIGHTERS, tree, 'tools_out', 'status', '_old_functions.json')
    with open(p, 'w') as fh:
        json.dump(out, fh)
    print('oldlist: %d functions of %d fighters -> %s' % (sum(len(v) for v in out.values()), len(out), p))


def gotos(tree, listing=None):
    """functions with at least one goto, and gotos in all: over the tree, and over the functions a guard listing calls new"""
    new = None
    if listing:
        new = set(l.split()[1] for l in open(listing) if l.startswith('new '))
    c = collections.Counter()
    for f in fighters_of(tree):
        for k, t in functions(tree, f).items():
            n = len(re.findall(r'\bgoto L\d+;', t))
            grp = 'new' if new is not None and '%s:%s' % (f, k) in new else 'old' if new is not None else 'all'
            c[grp + ' functions'] += 1
            c[grp + ' with goto'] += 1 if n else 0
            c[grp + ' gotos'] += n
            c[grp + ' compound'] += 1 if (' || ' in t or ' && ' in t) else 0
    print('gotos %s: %s' % (tree, ', '.join('%s %d' % kv for kv in sorted(c.items()))))


def fixadd(new, fix, listing, cls, names):
    """put the text <new> has for the named functions (fighter:function ...) into the existing fix tree <fix> and add
    them to the fix list with class <cls> (a later fix of already-covered functions)"""
    done = []
    for x in names:
        f, k = x.split(':')
        a, b = functions(fix, f), functions(new, f)
        if a[k] == b[k]:
            continue
        d = os.path.join(FIGHTERS, fix, f, 'status')
        for nm in sorted(os.listdir(d)):
            p = os.path.join(d, nm)
            if not nm.endswith('.cpp'):
                continue
            with open(p, newline='') as fh:
                text = fh.read()
            if a[k] in text:
                with open(p, 'w', newline='') as fh:
                    fh.write(text.replace(a[k], b[k], 1))
                done.append(x)
                break
        else:
            raise SystemExit('%s not found' % x)
    with open(listing) as fh:
        lines = [l for l in fh.read().split('\n') if l]
    have = set(tuple(l.split()[:2]) for l in lines if not l.startswith('#'))
    for x in done:
        f, k = x.split(':')
        if (f, k) in have:
            lines = [l + '+' + cls if l.split()[:2] == [f, k] else l for l in lines]
        else:
            lines.append('%s %s %s' % (f, k, cls))
    with open(listing, 'w') as fh:
        fh.write('\n'.join(lines) + '\n')
    print('fixadd: %d functions put into %s: %s' % (len(done), fix, ' '.join(done)))


def main():
    cmd = sys.argv[1]
    a = sys.argv[2:]
    if cmd == 'fixadd':
        return fixadd(a[0], a[1], a[2], a[3], a[4:])
    if cmd == 'oldlist':
        return oldlist(a[0], a[1])
    if cmd == 'gotos':
        return gotos(a[0], a[1] if len(a) > 1 else None)
    if cmd == 'moves':
        return moves(a[0], a[1], a[2])
    if cmd == 'fixtree':
        return fixtree(a[0], a[1], a[2], a[3])
    if cmd == 'unexclude':
        return unexclude(a[0], a[1], a[2])
    if cmd == 'refusals':
        refusals(a[0], a[1] if len(a) > 1 else None)
    elif cmd == 'cover':
        cover(a[0])
    elif cmd == 'guard':
        guard(a[0], a[1], a[2] if len(a) > 2 else None)
    elif cmd == 'check':
        check(a[0], a[1] if len(a) > 1 else None)


if __name__ == '__main__':
    main()
