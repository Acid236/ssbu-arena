"""N6 (helper task "the names inside"): what the exported create_agent_* functions of a fighter's script module do,
read from the lifted C of the module (gen_nro_eh_o2\\<module>\\c_*.c) and the module image, and the same as C++ source.

    python tests\\n6_s_factories.py list  <donor>                 the factories: agent name hashes, object sizes, constructors, class tables
    python tests\\n6_s_factories.py tables <donor>                the same with every slot of every class table
    python tests\\n6_s_factories.py gen   <donor> <new name> [work root, default work_n6]
          writes fighters\\<root>\\<new name>\\factory\\n6_factory.cpp (the factories as source, comparing the NEW agent
          names), appends their bindings to fighters\\<root>\\<new name>\\generated\\status_bindings.inc, and makes the
          SDK folder fighters\\<root>\\sdk_factory = sdk_generated + the game symbols a factory needs (operator new, the
          agent classes' constructors, the registration function, the virtual functions of the class tables).
          Build with SSBU_FIGHTER_SDK=<root>/sdk_factory.
What is generated is game content (offsets, hashes, the script lists): it stays in the work folder. This tool has none.
"""
import os
import re
import shutil
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(STUDY, 'fighter_sdk', 'tools'))
import nrolib      # noqa: E402


def h40(s):
    return (len(s) << 32) | (zlib.crc32(s.encode()) & 0xffffffff)


def analyse(donor):
    mod = 'lua2cpp_' + donor
    n = nrolib.Nro(mod)
    base = n.base
    d = os.path.join(STUDY, 'gen_nro_eh_o2', mod)
    text = ''.join(open(os.path.join(d, f)).read() for f in sorted(os.listdir(d)) if f.startswith('c_'))
    plt = n.plt
    out = []
    for off, name in sorted(n.exports.items()):
        if 'create_agent' not in name:
            continue
        short = re.search(r'create_agent_\w+?(?=EN3phx)', name).group(0)
        m = re.search(r'^void u_%x\(Ctx \*c, uint64_t rp\) \{(.*?)^\}' % (base + off), text, re.S | re.M) or \
            re.search(r'^void f_%x\(Ctx \*c\) \{(.*?)^\}' % (base + off), text, re.S | re.M)
        x = {}
        pend = None          # the constant just compared with the hash
        cases = {}           # label -> hash
        blocks = []
        cur = None
        lab_hash = None
        for line in m.group(1).split('\n'):
            lm = re.match(r'L_([0-9a-f]+): (.*)', line)
            if not lm:
                continue
            a, s = int(lm.group(1), 16), lm.group(2)
            if a in cases:
                lab_hash = cases[a]
            mm = re.match(r'c->x\[(\d+)\] = \(uint64_t\)\((0x[0-9a-f]+)ULL\);', s)
            if mm:
                x[int(mm.group(1))] = int(mm.group(2), 16)
                continue
            mm = re.match(r'c->x\[(\d+)\] = \(uint64_t\)\(\(c->x\[(\d+)\] & ~(0x[0-9a-f]+)ULL\) \| (0x[0-9a-f]+)ULL\);', s)
            if mm and mm.group(1) == mm.group(2):
                r = int(mm.group(1))
                x[r] = (x.get(r, 0) & ~int(mm.group(3), 16)) | int(mm.group(4), 16)
                continue
            mm = re.match(r'c->x\[(\d+)\] = \(uint64_t\)\(c->x\[(\d+)\] \+ (\d+)ULL\);', s)
            if mm and mm.group(1) == mm.group(2) and int(mm.group(1)) in x:
                r = int(mm.group(1))
                x[r] += int(mm.group(3))
                if r == 8 and cur is not None and 'vt' not in cur:
                    cur['vt'] = x[8] - base
                continue
            if 'adds64(c, c->x[8], ~(c->x[9]), 1)' in s:
                pend = x.get(9)
                continue
            mm = re.match(r'if \(cond\(c, (\d+)\)\) goto L_([0-9a-f]+);', s)
            if mm and pend is not None:
                cc, t = int(mm.group(1)), int(mm.group(2), 16)
                if cc == 0:
                    cases[t] = pend
                elif cc == 1:
                    lab_hash = pend          # falls through when equal
                continue
            mm = re.match(r'c->x\[0\] = \(uint32_t\)\((0x[0-9a-f]+)ULL\);', s)
            if mm:
                cur = {'hash': lab_hash, 'size': int(mm.group(1), 16), 'calls': [], 'regs': []}
                blocks.append(cur)
                continue
            mm = re.search(r'f_([0-9a-f]+)\(c\);', s)
            if mm and cur is not None:
                callee = plt.get(int(mm.group(1), 16) - base, '?')
                if 'vt' not in cur:
                    cur['calls'].append(callee)
                elif 'sv_set_function_hash' in callee:
                    cur['regs'].append((x[1] - base, x[2]))
                else:
                    cur.setdefault('other', []).append(callee)
                continue
            if re.match(r'goto L_[0-9a-f]+;', s) and cur is not None and 'vt' in cur:
                cur = None
        for b in blocks:
            slots = []
            if 'vt' in b:
                i = 0
                while True:
                    o = b['vt'] + 8 * i
                    if o in n.rel_ptr:
                        slots.append(('L', n.rel_ptr[o]))
                    elif o in n.abs_ptr:
                        slots.append(('S', n.abs_ptr[o]))
                    else:
                        if n.u64(o) == 0 and n.u64(o + 8) == 0 and (o + 8) not in n.rel_ptr and (o + 8) not in n.abs_ptr:
                            break
                        slots.append(('R', n.u64(o)))
                    i += 1
            b['slots'] = slots
        out.append({'name': short, 'sym': name, 'off': off, 'classes': blocks})
    return n, out


def agent_names(donor, facts):
    """the agent names behind the hashes: <donor> and <donor>_<article>, the articles from the status constant names"""
    want = set(b['hash'] for f in facts for b in f['classes'])
    names = {h40(donor): donor}
    try:
        txt = open(os.path.join(STUDY, 'fighters', 'work_s12', donor, 'status', 'install.cpp')).read()
        for a in re.findall(r'L2C_VOID_FUNCTION\(\w+, (\w+)_install\)', txt):
            names[h40(a)] = a
    except OSError:
        pass
    return {h: names.get(h) for h in want}


def dem(s):
    return nrolib.demangle_simple(s) if s.startswith('_Z') else s


def cmd_list(donor, tables):
    n, facts = analyse(donor)
    names = agent_names(donor, facts)
    tot = regs = 0
    for f in facts:
        print('%s  +0x%x  %d objects made' % (f['name'], f['off'], len(f['classes'])))
        for b in f['classes']:
            if 'vt' not in b:
                print('   (hash 0x%010x)  new(0x%x) %s: not an agent class (no class table stored)' % (b['hash'] or 0, b['size'], dem(b['calls'][1]) if len(b['calls']) > 1 else '?'))
                continue
            tot += 1
            regs += len(b['regs'])
            print('   hash 0x%010x %-16s new(0x%x) ctor %s  class table +0x%x: %d slots (%d own functions)  %d scripts registered%s' % (
                b['hash'], names.get(b['hash']), b['size'], dem(b['calls'][1]), b['vt'], len(b['slots']), sum(1 for k, v in b['slots'] if k == 'L'), len(b['regs']),
                '  OTHER CALLS: %s' % ' '.join(dem(c) for c in b['other']) if b.get('other') else ''))
            if tables:
                for i, (k, v) in enumerate(b['slots']):
                    print('        [%2d] %s' % (i, 'this module +0x%x' % v if k == 'L' else dem(v) if k == 'S' else 'raw 0x%x' % v))
    print('%d factories, %d agent classes, %d script registrations' % (len(facts), tot, regs))


def cmd_gen(donor, new, root):
    n, facts = analyse(donor)
    names = agent_names(donor, facts)
    fdir = os.path.join(STUDY, 'fighters', root, new)
    binds = open(os.path.join(fdir, 'generated', 'bindings.inc')).read()
    acmd = {int(o, 16): nm for nm, o in re.findall(r'ACMD_BIND\(\s*\w+\s*,\s*(\w+)\s*,\s*(0x[0-9a-f]+)\)', binds)}
    stat = open(os.path.join(fdir, 'generated', 'status_bindings.inc')).read()
    l2c = {int(o, 16): nm for nm, o in re.findall(r'L2C_BIND\(\s*\w+\s*,\s*(\w+)\s*,\s*(0x[0-9a-f]+)\)', stat)}
    syms = []                       # mangled names the factories need

    def sym(s):
        if s not in syms:
            syms.append(s)
        return 'S_n6_%d' % syms.index(s)

    done, skipped = [], []
    body = ''
    nclass = nregs = nreg_src = nslot_own = nslot_src = 0
    for f in facts:
        if any('vt' not in b or b.get('other') for b in f['classes']):
            skipped.append(f)
            continue
        done.append(f)
        rows = ''
        for ci, b in enumerate(f['classes']):
            dn = names[b['hash']]
            nn = new + dn[len(donor):]                       # <donor>_<article> -> <new>_<article>
            tag = '%s_%d' % (f['name'], ci)
            body += '// %s: agent "%s" (the donor\'s: "%s", hash 0x%010x)\n' % (f['name'], nn, dn, b['hash'])
            body += 'static const N6Slot slots_%s[] = {\n' % tag
            for i, (k, v) in enumerate(b['slots']):
                if k == 'L':
                    nslot_own += 1
                    nslot_src += 1 if v in l2c else 0
                    body += '    { -1, 0x%x },      // [%d] a function of this module%s\n' % (v, i, ': ' + l2c[v] + ' (source)' if v in l2c else ' (no source: destructor)')
                elif k == 'S':
                    body += '    { %s, 0 },      // [%d] %s\n' % (sym(v), i, dem(v))
                else:
                    body += '    { -2, 0x%x },      // [%d] a plain word\n' % (v, i)
            body += '};\n'
            if b['regs']:
                body += 'static const N6Reg regs_%s[] = {\n' % tag
                for o, h in b['regs']:
                    nregs += 1
                    nreg_src += 1 if o in acmd else 0
                    body += '    { 0x%x, 0x%010xULL },      // %s\n' % (o, h, acmd.get(o, '(no source)'))
                body += '};\n'
            body += 'static uint64_t table_%s[%d];\n' % (tag, len(b['slots']) + 2)
            rows += '    { "%s", 0x%x, %s, slots_%s, %d, %s, %d, table_%s },\n' % (
                nn, b['size'], sym(b['calls'][1]), tag, len(b['slots']), 'regs_' + tag if b['regs'] else 'nullptr', len(b['regs']), tag)
            nclass += 1
        body += 'static N6Class classes_%s[] = {\n%s};\n' % (f['name'], rows)
        body += '// the game: %s at +0x%x of %s\n' % (f['name'], f['off'], n.name)
        body += 'extern "C" void fs_fn_n6_%s(Ctx *c) { n6_factory(c, classes_%s, %d); }\n\n' % (f['name'], f['name'], len(f['classes']))
    s_new, s_reg = sym('_Znwm'), sym('_ZN3lib8L2CAgent20sv_set_function_hashEPvN3phx6Hash40E')
    head = '''// GENERATED by tests\\n6_s_factories.py from %s for the fighter "%s" - game content, stays in the work folder.
// The agent factories of the script module as source. The game's create_agent_* functions do exactly this:
//   compare the 40-bit hash of the agent name (x0) with the names of the module's agent classes; no match: return 0;
//   operator new(size of the class); the base class constructor(object, battle object, module accessor, lua state);
//   store the address of the agent class's table of virtual functions at +0; for an animation-command class: one
//   lib::L2CAgent::sv_set_function_hash(agent, function, hash of the script name) per script; return the agent.
// Here the names compared are the NEW fighter's ("%s", "%s_<article>"). The class tables are built at first use
// from game functions bound by name and functions of this module (fs_module_function: this module's own address
// range). Not carried over: the game's cleanup when a constructor throws (operator delete, _Unwind_Resume).
#include "fighter_sdk.h"
#include "status_local.h"

namespace {
struct N6Slot { int sym; uint32_t off; };            // sym >= 0: a game function bound by name; -1: this module + off; -2: the word off
struct N6Reg { uint32_t off; uint64_t hash; };       // a script: its function in this module, the hash of its name
struct N6Class { const char *agent; uint32_t size; int ctor; const N6Slot *slots; int nslots; const N6Reg *regs; int nregs; uint64_t *table; };

void n6_factory(Ctx *c, N6Class *cls, int count) {
    const uint64_t hash = c->x[0] & 0xffffffffffULL;
    void *object = (void *)(uintptr_t)c->x[1], *accessor = (void *)(uintptr_t)c->x[2], *lua = (void *)(uintptr_t)c->x[3];
    for (int i = 0; i < count; i++) {
        N6Class &k = cls[i];
        if (hash40(k.agent).v != hash) continue;
        void *agent = (void *)(uintptr_t)gcall<uint64_t>(%s, (uint64_t)k.size);
        gcall<void>(k.ctor, agent, object, accessor, lua);
        if (!k.table[2]) {                           // the class table: two zero words (as in the image), then the slots
            for (int s = k.nslots - 1; s >= 0; s--)
                k.table[2 + s] = k.slots[s].sym >= 0 ? fs_addr[k.slots[s].sym] : k.slots[s].sym == -1 ? (uint64_t)(uintptr_t)fs_module_function(k.slots[s].off) : k.slots[s].off;
        }
        *(uint64_t *)agent = (uint64_t)(uintptr_t)(k.table + 2);
        for (int r = 0; r < k.nregs; r++)
            gcall<void>(%s, agent, fs_module_function(k.regs[r].off), Hash40{k.regs[r].hash});
        c->x[0] = (uint64_t)(uintptr_t)agent;
        return;
    }
    c->x[0] = 0;
}
}

''' % (n.name, new, new, new, s_new, s_reg)
    os.makedirs(os.path.join(fdir, 'factory'), exist_ok=True)
    with open(os.path.join(fdir, 'factory', 'n6_factory.cpp'), 'w', newline='\n') as fo:
        fo.write(head + body)
    mark = '// N6: the agent factories as source (tests\\n6_s_factories.py): bound at the places of the game\'s create_agent_* functions\n'
    if mark not in stat:
        with open(os.path.join(fdir, 'generated', 'status_bindings.inc'), 'a', newline='\n') as fo:
            fo.write(mark + ''.join('L2C_BIND(%s, n6_%s, 0x%x)\n' % (donor, f['name'], f['off']) for f in done))
    # the SDK with the symbols a factory needs: a copy, the generated SDK is not edited
    src, dst = os.path.join(STUDY, 'fighters', root, 'sdk_generated'), os.path.join(STUDY, 'fighters', root, 'sdk_factory')
    os.makedirs(dst, exist_ok=True)
    for fn in os.listdir(src):
        if fn not in ('fs_syms.inc', 'lua_bind.h'):
            shutil.copy(os.path.join(src, fn), os.path.join(dst, fn))
    t = open(os.path.join(src, 'fs_syms.inc')).read()
    t += '// N6 (tests\\n6_s_factories.py): what an agent factory written as source needs\n' + ''.join('    { "%s", "p" },\n' % s for s in syms)
    with open(os.path.join(dst, 'fs_syms.inc'), 'w', newline='\n') as fo:
        fo.write(t)
    t = open(os.path.join(src, 'lua_bind.h')).read()
    k = t.index('    S_COUNT\n')
    t = t[:k] + ''.join('    S_n6_%d,      // %s\n' % (i, dem(s)) for i, s in enumerate(syms)) + t[k:]
    with open(os.path.join(dst, 'lua_bind.h'), 'w', newline='\n') as fo:
        fo.write(t)
    print('%s from %s: %d factories as source (%d agent classes; %d class-table slots that are functions of the module, %d of them with source; '
          '%d script registrations, %d of them of scripts with source); %d game symbols added to fighters\\%s\\sdk_factory' % (
              new, n.name, len(done), nclass, nslot_own, nslot_src, nregs, nreg_src, len(syms), root))
    for f in skipped:
        print('   NOT written: %s (+0x%x): makes more than agent objects (%s)' % (f['name'], f['off'], ', '.join(
            'new(0x%x) %s' % (b['size'], dem(b['calls'][1]) if len(b['calls']) > 1 else '?') for b in f['classes'])))


def main():
    cmd = sys.argv[1]
    if cmd in ('list', 'tables'):
        cmd_list(sys.argv[2], cmd == 'tables')
    elif cmd == 'gen':
        cmd_gen(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else 'work_n6')
    return 0


if __name__ == '__main__':
    sys.exit(main())
