"""Status scripts and the shared state machine (lua2cpp_common: L2CFighterCommon::status_*, sub_*): the general
decompiler of l2c_decomp.py applied to named member functions.

    python status_decomp.py common --stats [regex]     which named functions decompile, and why not
    python status_decomp.py common --show <name>       print one function
    python status_decomp.py common [regex]             write fighters/common/status/*.cpp, generated/status_bindings.inc,
                                                       out/common_status.json

A function here is `L2CValue Class::name(L2CValue args...)`: x0 = the agent (this), x8 = result, x1.. = pointers to the
arguments. Calls to other named functions of the module are calls by name (they go through the SDK like imports).
SLICE is the part of the state machine session 2 worked on (ground movement, air dodge, landing, transition checks).
"""
import collections
import json
import os
import re
import sys

import acmd_decomp as A
import l2c_decomp as D
import luaconst
import mangle
from acmd_decomp import NotMechanical
from nrolib import STUDY, HERE, demangle_simple

SLICE = (r'L2CFighterCommon::(status_(pre_|end_)?(Dash|Turn|TurnDash|TurnRun|TurnRunBrake|Run|RunBrake|EscapeAir|Landing|JumpSquat)\w*'
         r'|sub_transition_group_check_\w+|sub_landing\w*|\w*escape_air\w*|sub_dash\w*|sub_jump_squat\w*)$')


BINARY = {'operator_rm': '%', 'operator_an': '&', 'operator_or': '|', 'operator_ls': '<<', 'operator_rs': '>>'}


class MExec(D.FExec):
    """a named member function: this in x0, result buffer in x8, L2CValue arguments by pointer"""

    def __init__(self, mod, off):
        D.FExec.__init__(self, mod, off, 'macro')
        self.entry_reg['x8'] = A.RET

    @staticmethod
    def unstable(v):
        """reads memory that a later call can change (a table element, a member of the agent)"""
        if not isinstance(v, tuple):
            return False
        if v and v[0] in ('elem', 'member'):
            return True
        return any(MExec.unstable(x) for x in v[1:])

    def stable(self, v):
        return not D.has_var(v) and not self.unstable(v)

    def lvalue(self, v, what):
        if v[0] == 'off' and v[1] == A.AGENT:
            if v[2] not in D.MEMBERS:
                self.fail('member of the agent +0x%x' % v[2])
            return ('member', v[2])
        if v[0] == 'elemptr':
            return ('elem', v[1], v[2])
        return D.FExec.lvalue(self, v, what)

    def setslot(self, where, e):
        s = self.slot(where, 'result')
        if s == 'ret':
            self.ret_value = e
        else:
            self.lv[s] = e

    def snapshot(self, e):
        if self.unstable(e):
            return ('ref', self.node(kind='snap', args=[e]))
        return e

    def call_import(self, sym):
        p = mangle.parse(sym)
        x0 = self.get('x0')
        if p and p[0][:2] == ['lib', 'L2CValue']:
            fn, params = p[0][2], p[1]
            if fn == 'operator_ix':
                base = self.lvalue(x0, fn)
                t = mangle.strip(params[0])
                if t == 'i':
                    key = self.scalar(self.get('w1'), fn)
                elif t == ('class', 'phx::Hash40'):
                    key = ('hash', self.scalar(self.get('x1'), fn))
                else:
                    key = self.lvalue(self.get('x1'), fn)
                self.reg['x0'] = ('elemptr', base, key)
                return
            if fn == 'operator_aS':
                src = self.lvalue(self.get('x1'), fn)
                if x0[0] in ('elemptr', 'off', 'arg'):
                    self.node(kind='store', args=[self.lvalue(x0, fn), src])
                else:
                    self.setslot(x0, self.snapshot(src))
                self.reg['x0'] = A.UNDEF
                return
            if fn == 'L2CValue':
                t = mangle.strip(params[0]) if params else None
                if t is None:
                    self.setslot(x0, ('nil',))
                    self.reg['x0'] = A.UNDEF
                    return
                if isinstance(t, tuple) and t[0] == 'ref':
                    self.setslot(x0, self.snapshot(self.lvalue(self.get('x1'), 'copy')))
                    self.reg['x0'] = A.UNDEF
                    return
            if fn == 'operator_ng':
                self.setslot(self.get('x8'), ('lvneg', self.lvalue(x0, fn)))
                return
            if fn == 'operator_nt':                      # S3: L2CValue::operator!() -> L2CValue
                self.setslot(self.get('x8'), ('lvnot', self.lvalue(x0, fn)))
                return
            if fn in BINARY:
                self.setslot(self.get('x8'), ('lvop', BINARY[fn], self.lvalue(x0, fn), self.lvalue(self.get('x1'), fn)))
                return
            if fn in A.ARITH and self.get('x8') == A.RET:
                self.ret_value = ('lvop', A.ARITH[fn], self.lvalue(x0, fn), self.lvalue(self.get('x1'), fn))
                return
        if p and ((p[0][0] == 'lua2cpp' and mangle.is_member(p[0])) or mangle.is_static_value(p[0])) and self.reg['x8'][0] != 'stk':
            # result written straight into this function's own result, or (no buffer given) a function without a result
            is_ret = self.reg['x8'] == A.RET
            self.reg['x8'] = ('stk', -0x7ffff0)
            D.FExec.call_import(self, sym)
            v = self.lv.pop(-0x7ffff0)
            if is_ret:
                self.ret_value = v
            else:
                self.allnodes[v[1]]['void'] = True
            return
        D.FExec.call_import(self, sym)

    def thisval(self, v, name):
        return D.FExec.thisval(self, v, name)

    def scalar(self, v, name):
        if v[0] == 'ibin':
            return v
        return D.FExec.scalar(self, v, name)

    def step(self, ins):
        if ins.mnemonic in ('orr', 'and'):               # S3: integer or / and of two values (flag constants), and with a mask
            ops = A.split_ops(ins.op_str)
            if len(ops) == 3 and ops[2] != '#1' and ops[1] not in ('wzr', 'xzr'):
                a = self.get(ops[1])
                b = ('int', A.imm(ops[2])) if ops[2].startswith('#') else self.get(ops[2])
                if a[0] in ('int', 'luaconst', 'ref', 'conv', 'ibin', 'var') and b[0] in ('int', 'luaconst', 'ref', 'conv', 'ibin', 'var'):
                    if a[0] == 'int' and b[0] == 'int':
                        self.put(ops[0], ('int', a[1] | b[1] if ins.mnemonic == 'orr' else a[1] & b[1]))
                    else:
                        self.put(ops[0], ('ibin', '|' if ins.mnemonic == 'orr' else '&', a, b))
                    return None
        if ins.mnemonic == 'blr':
            v = self.get(ins.op_str.strip())
            if v[0] != 'conv' or v[1] != 'as_pointer' or self.get('x0') != A.AGENT:
                self.fail('indirect call')
            args = []
            for k in range(1, 8):
                a = self.reg['x%d' % k]
                if a[0] != 'stk' or a[1] not in self.lv:
                    break
                args.append(self.lv[a[1]])
            i = self.node(kind='callptr', args=[v[2]] + args)
            self.setslot(self.reg['x8'], ('ref', i))
            for r in range(0, 18):
                self.reg['x%d' % r] = A.UNDEF
            for r in range(0, 8):
                self.reg['v%d' % r] = A.UNDEF
            self.flags = None
            return None
        return D.FExec.step(self, ins)

    def call(self, pc, target):
        sym = self.n.exports.get(target)
        if sym and target not in self.n.plt and mangle.parse(sym):
            self.call_import(sym)
            for r in range(1, 18):
                self.reg['x%d' % r] = A.UNDEF
            for r in range(1, 8):
                self.reg['v%d' % r] = A.UNDEF
            self.flags = None
            return
        D.FExec.call(self, pc, target)


def functions(mod, pattern):
    rx = re.compile(pattern)
    out = []
    for off, sym in sorted(mod.nro.exports.items()):
        d = demangle_simple(sym)
        if 'bind_address_call_' in d:                    # 4-byte jumps to the function of the same name: nothing to convert
            continue
        if rx.search(d) and mod.nro.func_size(off):
            out.append((off, sym, d))
    return out


def execute(mod, off):
    ex = MExec(mod, off)
    ex.run()
    variables = D.materialise(ex)
    st = D.Structurer(ex)
    stmts = st.tree(ex.off, None, [])
    ex.stmts, ex.labels, ex.variables, ex.gotos, ex.loops = stmts, st.labels, variables, st.gotos, len(st.headers)
    return ex


def main():
    name = sys.argv[1]
    args = [a for a in sys.argv[2:] if not a.startswith('--')]
    pattern = args[0] if args else SLICE
    mod = A.Module(name)
    mod.lua_stats, mod.autopop = {}, set()
    mod.float_syms, mod.void_syms, mod.value_syms = set(), set(), set()
    xp = os.path.join(STUDY, 'fighters', 'tools_out', mod.nro.short + '_status_exclude.json')
    exclude = json.load(open(xp)) if os.path.exists(xp) else {}      # function -> why it stays lifted (differential test, compiler)
    mod.glob = D.load_global()
    if mod.glob:
        mod.autopop = set(s for s, st in mod.glob.items() if st['autopop'])
    consts = luaconst.table_names()
    fns = functions(mod, pattern)
    # S3: script calls (app::sv_*::X(lua_State *)) that no ACMD script makes: how the state machine itself uses them
    # (one way of passing arguments? result always dropped?) decides their SDK wrapper, as batch.py collect does for
    # ACMD. Kept in out/status_lua_calls.json; gen_sdk.py reads it after lua_calls_global.json.
    cache = {}
    if mod.glob is not None:
        extra = {}
        for off, sym, d in fns:
            try:
                if not mangle.parse(sym):
                    continue
                ex = cache[off] = execute(mod, off)
                p = D.Printer2(ex, [], {})
                p.count_stmts(ex.stmts)
                for nd in ex.allnodes.values():
                    if nd['kind'] == 'lua' and nd['sym'] not in mod.glob:
                        s = extra.setdefault(nd['sym'], {'protos': set(), 'dropped': 0, 'other': 0})
                        s['protos'].add(nd['proto'])
                        s['dropped' if nd['popped'] and p.uses[nd['id']] == 0 else 'other'] += 1
            except (NotMechanical, RecursionError) as x:
                cache[off] = x
        sp = os.path.join(STUDY, 'fighters', 'tools_out', 'status_lua_calls.json')
        old = json.load(open(sp)) if os.path.exists(sp) else {}
        for s, e in extra.items():
            old[s] = {'protos': len(e['protos']), 'proto': list(sorted(e['protos'])[0]), 'autopop': bool(e['dropped'] and not e['other'])}
        with open(sp, 'w') as f:
            json.dump(old, f, indent=1, sort_keys=True)
        for s, e in old.items():
            if s not in mod.glob:
                mod.glob[s] = e
        mod.autopop = set(s for s, st in mod.glob.items() if st['autopop'])
    reasons = collections.Counter()
    ok = bytes_ok = bytes_all = 0
    res = []
    for off, sym, d in fns:
        size = mod.nro.func_size(off)
        bytes_all += size
        e = {'off': off, 'sym': sym, 'name': d, 'size': size}
        try:
            ident = d.split('::')[-1]
            if ident in exclude:
                raise NotMechanical(exclude[ident])
            parsed = mangle.parse(sym)
            if not parsed:
                raise NotMechanical('mangled name not understood')
            arity = len(parsed[1])
            if arity > 6:
                raise NotMechanical('more than 6 arguments')
            if arity > 2 and any(mangle.strip(t) != ('class', 'lib::L2CValue') for t in parsed[1]):
                raise NotMechanical('argument that is not an L2CValue')
            ex = cache.get(off) or execute(mod, off)
            if isinstance(ex, RecursionError):
                raise RecursionError()
            if isinstance(ex, Exception):
                raise ex
            for nd in ex.allnodes.values():
                if nd['kind'] == 'lua' and mod.glob is not None and mod.glob.get(nd['sym'], {}).get('protos', 1) != 1:
                    raise NotMechanical('script call made in more than one way')
            p = D.Printer2(ex, consts, D.var_names(ex.variables))
            rets = [b.ret for b in ex.B.values() if b.term[0] in ('ret', 'tail')]
            p.void_fn = all(r is None or r == ('tail',) for r in rets)
            lines = p.function_text(ex.stmts, ex.labels, 'fn', ex.variables)
            for nd in ex.allnodes.values():
                if nd['kind'] == 'lua' and nd['sym'] in mod.autopop and p.uses[nd['id']]:
                    raise NotMechanical('uses the result of a script call the SDK declares without one')
                if nd['kind'] == 'lua' and mod.glob is not None and nd['sym'] not in mod.glob:
                    raise NotMechanical('script call no ACMD script uses')
            e.update(ok=True, lines=lines, used=sorted(p.used_syms), gotos=ex.gotos, void=p.void_fn, arity=arity, ident=ident)
            ok += 1
            bytes_ok += size
        except NotMechanical as x:
            e.update(ok=False, why=str(x))
            reasons[str(x).split('+0x')[0][:60]] += 1
        except RecursionError:
            e.update(ok=False, why='too deeply nested')
            reasons['too deeply nested'] += 1
        res.append(e)
    if '--show' in sys.argv:
        for e in res:
            print('// %s (+0x%x, %d bytes)%s' % (e['name'], e['off'], e['size'], '' if e['ok'] else '   NOT: ' + e['why']))
            if e['ok']:
                print('\n'.join(e['lines']))
        return
    print('%s: %d named functions match (%d bytes); decompiled %d (%.1f%%), bytes %d (%.1f%%)' %
          (name, len(fns), bytes_all, ok, 100.0 * ok / max(len(fns), 1), bytes_ok, 100.0 * bytes_ok / max(bytes_all, 1)))
    for w, c in reasons.most_common(40):
        print('  %5d  %s' % (c, w))
    if '--stats' in sys.argv:
        return
    short = mod.nro.short
    fdir = os.path.join(STUDY, 'fighters', short)
    os.makedirs(os.path.join(fdir, 'status'), exist_ok=True)
    os.makedirs(os.path.join(fdir, 'generated'), exist_ok=True)
    head = ['// %s: functions of the shared fighter state machine (lua2cpp::L2CFighterCommon), decompiled by' % short,
            '// fighter_sdk/tools/status_decomp.py from the game\'s own module. From here on this file is source:',
            '// edit it, then `python fighter_sdk/tools/build_fighter.py %s`.' % short, '#include "fighter_sdk.h"', '']
    files = {}                                           # S3: one file per family of names (status_Dash*, sub_transition_*, ...)
    binds = []
    used = set()
    used_names = set()
    for e in res:
        if not e['ok']:
            continue
        if e['ident'] in used_names:
            e.update(ok=False, why='second function of the same name (overload)')
            e.pop('lines', None)
            continue
        used_names.add(e['ident'])
        m = re.match(r'(?:bind_address_call_)?status_(?:pre_|end_|init_|exec_|exit_)?([A-Z][a-z0-9]*)', e['ident'])
        fam = 'status_' + m.group(1) if m else '_'.join(e['ident'].split('_')[:2]) if e['ident'].startswith('sub_') else e['ident'].split('_')[0]
        fam = re.sub(r'\W', '_', fam) or 'misc'
        text = files.setdefault(fam if len(fns) > 200 else 'state_machine', list(head))
        args = ''.join(', a%d' % k for k in range(e['arity']))
        text.append('L2C_%sFUNCTION%s(%s, %s%s) {' % ('VOID_' if e['void'] else '', str(e['arity']) if e['arity'] else '', short, e['ident'], args))
        text += e.pop('lines')
        text += ['}', '']
        binds.append((e['off'], e['ident']))
        # the game is given `bind_address_call_<name>` (a 4-byte jump to the function) when a function is registered
        # by pointer; calls from inside the module's lifted code are direct and are NOT redirected (S1 doc, section 7)
        for o, s in mod.nro.exports.items():
            if demangle_simple(s).endswith('::bind_address_call_' + e['ident']) and mod.nro.func_size(o):
                binds.append((o, e['ident']))
        used |= set(e['used'])
    for n in os.listdir(os.path.join(fdir, 'status')):   # generated files of an earlier run (regenerating overwrites edits)
        if n.endswith('.cpp'):
            os.remove(os.path.join(fdir, 'status', n))
    small = [k for k, v in files.items() if sum(1 for l in v if l.startswith('L2C_')) < 4 and k != 'state_machine']
    for k in small:                                      # families of fewer than 4 functions share one file
        files.setdefault('misc', list(head)).extend(files.pop(k)[len(head):])
    for k, text in files.items():
        with open(os.path.join(fdir, 'status', k + '.cpp'), 'w', newline='\n') as f:
            f.write('\n'.join(text))
    with open(os.path.join(fdir, 'generated', 'bindings.inc'), 'w', newline='\n') as f:
        f.write('// GENERATED by status_decomp.py: where each function\'s original lives in lua2cpp_%s.\n' % short)
        for off, ident in sorted(binds):
            f.write('L2C_BIND(%s, %s, 0x%x)\n' % (short, ident, off))
    for e in res:
        e.pop('lines', None)
    with open(os.path.join(STUDY, 'fighters', 'tools_out', short + '_status.json'), 'w') as f:
        json.dump({'functions': res, 'imports_used': sorted(used), 'float_returns': sorted(mod.float_syms),
                   'void_calls': sorted(mod.void_syms - mod.value_syms)}, f, indent=1)
    print('written: fighters/%s/status/*.cpp (%d files), %d bindings' % (short, len(files), len(binds)))


if __name__ == '__main__':
    main()
