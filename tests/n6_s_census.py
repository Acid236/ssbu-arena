"""N6 (helper task "the names inside"): what a new fighter's module still takes from the donor's image, as counts.

    python tests\\n6_s_census.py <donor> <work root\\name of the clone, e.g. work_n6/fact/n3test>

Functions of the module image (unwind entries + import stubs) against the bindings of the clone's DLL; the data of
the image (sections, relocated pointers, class tables). Counts only; no game content in this file.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(STUDY, 'fighter_sdk', 'tools'))
sys.path.insert(0, HERE)
import nrolib      # noqa: E402
import n6_s_factories as F      # noqa: E402


def main():
    donor, clone = sys.argv[1], sys.argv[2]
    n, facts = F.analyse(donor)
    gen = os.path.join(STUDY, 'fighters', clone, 'generated')
    bound = {}
    for fn in ('bindings.inc', 'status_bindings.inc'):
        for kind, nm, o in re.findall(r'(ACMD|L2C)_BIND\(\s*\w+\s*,\s*(\w+)\s*,\s*(0x[0-9a-f]+)\)', open(os.path.join(gen, fn)).read()):
            bound[int(o, 16)] = (kind, nm)
    fdes = n.fdes
    plt = n.plt
    starts = sorted(set(s for s, _ in fdes))
    print('%s: image text 0x%x bytes, read-only data 0x%x, data 0x%x, bss 0x%x' % (n.name, n.text_size, n.ro_size, n.data_size, n.bss_size))
    print('functions with unwind info: %d; import stubs: %d; sum %d' % (len(starts), len(plt), len(starts) + len(plt)))
    fact_off = {f['off']: f for f in facts}
    regs = set(o for f in facts for b in f['classes'] for o, h in b['regs'])
    slot_own = set(v for f in facts for b in f['classes'] for k, v in b['slots'] if k == 'L')
    ai_from = min(f['off'] for f in facts if '_ai_' in f['name'])
    acmd_from = min(f['off'] for f in facts if 'animcmd' in f['name'])
    cls = {}
    size = {}
    for s, sz in fdes:
        if s in bound:
            k = 'SOURCE: ' + ('factory' if s in fact_off else 'animation-command script' if bound[s][0] == 'ACMD' else 'status function / install / helper')
        elif s in fact_off:
            k = 'no source: AI factory (create_agent_fighter_ai_*)'
        elif s in regs:
            k = 'no source: registered script function without source'
        elif s in slot_own:
            k = 'no source: class-table function (destructors; AI class functions)'
        elif s >= ai_from:
            k = 'no source: AI region (after the first AI factory)'
        elif s >= acmd_from:
            k = 'no source: animation-command region, not registered directly (script bodies / coroutine parts / helpers)'
        else:
            k = 'no source: status region (helpers, destructors)'
        cls[k] = cls.get(k, 0) + 1
        size[k] = size.get(k, 0) + sz
    for k in sorted(cls):
        print('   %5d functions %8d bytes  %s' % (cls[k], size[k], k))
    print('   %5d import stubs (no source needed: a DLL binds game functions by name)' % len(plt))
    # who branches (bl / b) to the functions without source: only functions that have source, or others too?
    import bisect
    import struct
    ends = {s: s + sz for s, sz in fdes}

    def owner(a):
        i = bisect.bisect_right(starts, a) - 1
        return starts[i] if i >= 0 and a < ends[starts[i]] else None
    callers = {}
    for s, sz in fdes:
        for o in range(s, s + sz, 4):
            w = struct.unpack_from('<I', n.d, o)[0]
            if (w & 0x7c000000) == 0x14000000:
                d = w & 0x3ffffff
                d -= (1 << 26) if d & (1 << 25) else 0
                t = o + 4 * d
                if t in ends and t != s:
                    callers.setdefault(t, set()).add(s)
    pointed = set(n.rel_ptr.values())
    only_src = [s for s in starts if s not in bound and s in callers and all(c in bound for c in callers[s]) and s not in pointed]
    none = [s for s in starts if s not in bound and s not in callers and s not in pointed and s not in regs and s not in fact_off]
    print('of the functions without source: %d are branched to ONLY from functions that have source (the lifted body behind a script that is '
          'source now: not needed), %d bytes; %d have no direct branch and no data pointer to them (reached by an address computed in code)' % (
              len(only_src), sum(ends[s] - s for s in only_src), len(none)))
    src = sum(v for k, v in cls.items() if k.startswith('SOURCE'))
    print('with source: %d; without source: %d (+ %d import stubs)' % (src, len(starts) - src, len(plt)))
    # data
    tables = [b for f in facts for b in f['classes'] if 'vt' in b]
    done = [b for f in facts if not any('vt' not in b or b.get('other') for b in f['classes']) for b in f['classes']]
    print('class tables: %d (%d slots); built by the source factories: %d (%d slots); still the image\'s: %d (%d slots)' % (
        len(tables), sum(len(b['slots']) for b in tables), len(done), sum(len(b['slots']) for b in done),
        len(tables) - len(done), sum(len(b['slots']) for b in tables) - sum(len(b['slots']) for b in done)))
    ro0, ro1, d0, d1 = n.ro_off, n.ro_off + n.ro_size, n.data_off, n.data_off + n.data_size
    rel_d = [o for o in n.rel_ptr if d0 <= o < d1]
    abs_d = [o for o in n.abs_ptr if d0 <= o < d1]
    print('relocated pointers in the data section: %d to places of the image, %d to symbols by name (of them import slots of the stubs: %d)' % (
        len(rel_d), len(abs_d), len(set(n.got) & set(abs_d)) if isinstance(n.got, dict) else -1))
    print('dynamic symbols: %d (defined here: %d = the exported factories)' % (len(n.syms), len(n.exports)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
