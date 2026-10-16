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
    lua_vec = True                                       # S20: a script call's vector result is lua_vec(...) (acmd_decomp.lane_move)

    def __init__(self, mod, off):
        D.FExec.__init__(self, mod, off, 'macro')
        self.entry_reg['x8'] = A.RET
        if off in getattr(mod, 'static_fns', ()):
            # S8: a helper that is not a member: x0 = result buffer, x1 = the agent, x2.. = L2CValue arguments
            # (how the fighters' modules call their local helper functions; found at the call sites, see call_local)
            self.entry_reg['x0'] = A.RET
            self.entry_reg['x1'] = A.AGENT
            for k in range(2, 8):
                self.entry_reg['x%d' % k] = ('arg', k - 2)
            self.entry_reg['x8'] = A.UNDEF
        if off in getattr(mod, 'plain_fns', ()):
            # S18: a helper that takes no agent at all: x0 = result buffer, x1.. = L2CValue arguments (found at the
            # call sites, see call_local). Nothing in it is the agent, so it executes only if it never needs one.
            self.entry_reg['x0'] = A.RET
            for k in range(1, 8):
                self.entry_reg['x%d' % k] = ('arg', k - 1)
            self.entry_reg['x8'] = A.UNDEF

    def load_s20(self, a, size, is_float):
        # S20: a helper that is not a member (x0 = result, x1 = agent): its arguments start at x2, so the first one on
        # the caller's stack is argument 6, not 7 (acmd_decomp.Exec.load counts from x1)
        if (a[0] == 'stk' and a[1] >= 0 and a[1] not in self.mem and self.off in getattr(self.m, 'static_fns', ())
                and self.off not in getattr(self.m, 'plain_fns', ())):
            return ('arg', 6 + a[1] // 8)
        return D.FExec.load(self, a, size, is_float)

    # S21: lua2cpp::L2CAgentBase::coroutine_yield() called as the game's code calls it: through the agent's vtable
    # (`ldr x8, [x20]; ldr x8, [x8, #0x10]; mov x0, x20; blr x8`; slot 2 of every item class reads
    # _ZN7lua2cpp12L2CAgentBase15coroutine_yieldEv). The vtable is ('vtab', 0), the slot ('vfn', 0x10); only that one
    # slot is taken (see step: blr), printed fs_coroutine_yield(agent) (status_local.h: through the same vtable entry)
    def add(self, base, off):
        if base == ('agentfield', 0):
            return ('vtab', off)
        return D.FExec.add(self, base, off)

    def load(self, a, size, is_float):
        if a[0] == 'vtab' and size == 8 and not is_float:
            return ('vfn', a[1])
        return self.load_s20(a, size, is_float)

    @staticmethod
    def unstable(v):
        """reads memory that a later call can change (a table element, a member of the agent)"""
        if not isinstance(v, tuple):
            return False
        if v and v[0] in ('elem', 'member'):
            return True
        return any(MExec.unstable(x) for x in v[1:])

    @staticmethod
    def has_elem(v):
        if not isinstance(v, tuple):
            return False
        if v and v[0] in ('elem', 'elemptr'):
            return True
        return any(MExec.has_elem(x) for x in v[1:])

    def stable(self, v):
        # S18: the ADDRESS of a table element (what operator[] returned, kept in a register across a branch) is the
        # same element later, as the game's own code assumes, when the table it was taken from is named by something
        # that cannot change in between: the agent's own member table, a value held in a result variable, an
        # argument; and the key is a constant or such a value. An element of an element (table[a][b]) is NOT taken:
        # table[a] could be given another table in between and the address would still point into the old one.
        if v and v[0] == 'elemptr' and not D.has_var(v) and not self.has_elem(v[1]) and not self.unstable(v[2]):
            return True
        return not D.has_var(v) and not self.unstable(v)

    def lvalue(self, v, what):
        if v[0] == 'off' and v[1] == A.AGENT:
            # S19: an L2CValue member of the agent at another place than global_table (item agents keep several; no
            # public source names them): the game's own code passes its address where an L2CValue is expected, which
            # is what makes it one. Printed agent_value(agent, 0x...) (status_local.h). Only 16-byte aligned places
            # after the agent's base part (0x10 and on).
            if v[2] not in D.MEMBERS and (v[2] < 0x10 or v[2] % 8):
                self.fail('member of the agent +0x%x' % v[2])
            return ('member', v[2])
        if v[0] == 'elemptr':
            return ('elem', v[1], v[2])
        if v == A.RET and 'ret' in self.lv:
            # S20: the function reads back its own result after writing it (`result = x; ... if (result < y)`): the
            # value it wrote, like any slot of its own frame
            return self.lv['ret']
        if v[0] == 'sym' and mangle.gvalue_name(v[1]):
            # S20: a constant L2CValue of the game's script runtime (lib::L2CAgent::math_pi, math_FLT_MAX): read in place,
            # fs_gvalue(S_gvalue_<name>) (slot made by gen_sdk.py, helper in status_local.h)
            return ('gval', v[1])
        if (v[0] == 'off' and v[1][0] == 'arg' and v[2] in (0x10, 0x20, 0x30)
                and (self.off in getattr(self.m, 'static_fns', ()) or self.off in getattr(self.m, 'plain_fns', ()))):
            # S18: an argument that is a ROW of L2CValues on the caller's frame (three in a row = the x, y, z a helper
            # hands to Vector3__create): `add x1, x21, #0x10; bl L2CValue(const L2CValue &)`. Element k of argument i is
            # ('argel', i, k), printed a<i>[k]; the parameter is then `const L2CValue *` and the caller writes
            # row(x, y, z) (fighter_status.run_module checks that the caller really built that many values there).
            # Only in helpers called as plain C++ (not in a function the game calls through its address).
            if not hasattr(self, 'agg'):
                self.agg = {}
            self.agg[v[1][1]] = max(self.agg.get(v[1][1], 0), v[2] // 0x10)
            return ('argel', v[1][1], v[2] // 0x10)
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
                if t == ('ptr', ('const', 'c')):
                    # S21: lib::L2CValue::L2CValue(char const*) (main 0x71037341c0): type 8, the value OWNS a std::string
                    # the constructor allocates (game allocator, 0x18 bytes); ~L2CValue frees it, the copy constructor
                    # makes another one. Only a text of the module's read-only data (the item scripts' status names
                    # "INITIALIZE", "LOST" ...). ('str', offset): printed L2CString("TEXT") (fighter_sdk.h), a temporary
                    # built and destroyed by the game's own functions; l2c_decomp.Printer2 refuses it where it would
                    # outlive its statement (a variable, a returned value).
                    a = self.get('x1')
                    n = self.n
                    if a[0] != 'img' or not (n.ro_off <= a[1] < n.ro_off + n.ro_size):
                        self.fail('L2CValue constructor from a text that is not a constant')
                    try:
                        n.cstr(a[1]).encode('ascii')
                    except (UnicodeError, ValueError):
                        self.fail('L2CValue constructor from a text that is not plain ASCII')
                    self.setslot(x0, ('str', a[1]))
                    self.reg['x0'] = A.UNDEF
                    return
            if fn == 'length' and not params:
                # S21: lib::L2CValue::length() const -> unsigned 64-bit in x0 (fs_lv_length, fighter_sdk.h). A node of its
                # own at this point (the value may change later); its x0 an integer value like a script call's (luax)
                i = self.node(kind='lvlen', args=[self.lvalue(x0, fn)])
                self.reg['x0'] = ('luax', ('ref', i))
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
        if v[0] == 'img' and self.function_at(v[1]):     # S8: the address of a function of this module as an argument
            return v
        if v[0] == 'singleton':                          # S8: a manager object (lib::Singleton<app::X>::instance_) as an argument
            return v
        return D.FExec.scalar(self, v, name)

    def function_at(self, off):
        """S8: is this image offset a function the source can name (exported, or a local one the driver has named)?"""
        if off in getattr(self.m, 'locals', {}):
            return True
        sym = self.n.exports.get(off)
        return bool(sym and mangle.parse(sym) and self.n.func_size(off))

    def call_local(self, target):
        """S8: a direct call to a function of this module that has no exported name (a fighter's own status
        scripts and their helpers; fighter_status.py names them). Same convention as every lua2cpp function:
        x0 = the agent, x1.. = pointers to L2CValue arguments, x8 = result buffer. How many of the candidate
        arguments are real is decided by the driver from what the callee reads (truncated before printing)."""
        x0 = self.get('x0')
        static = plain = False
        if x0[0] == 'stk' and D.is_synth(x0[1]):         # S18: never a result buffer
            self.fail('local function called with a chosen pointer in x0')

        def is_value(a):
            return (a[0] == 'stk' and a[1] in self.lv) or a[0] == 'arg' or (a[0] == 'sym' and a[1] == '_ZN3lib8L2CValue3NILE')

        if x0 != A.AGENT:
            if self.reg['x1'] == A.AGENT and (x0 == A.RET or x0[0] == 'stk') and hasattr(self.m, 'static_fns'):
                if target in getattr(self.m, 'plain_fns', ()):
                    self.fail('local function called in two ways')
                static = True                            # result buffer in x0, agent in x1, arguments from x2
                self.m.static_fns.add(target)
            elif (x0 == A.RET or x0[0] == 'stk') and is_value(self.reg['x1']) and hasattr(self.m, 'plain_fns'):
                # S18: result buffer in x0, L2CValue arguments from x1, no agent (a helper that only computes on
                # values). The callee is then executed with exactly that: it stays refused if it needs an agent.
                # Nothing is recorded here: the driver (fighter_status.run_module) takes the plain callees from the
                # functions that executed, and refuses a caller whose call does not match what the callee became.
                plain = True
            else:
                self.fail('local function called on something else than the agent')
        elif target in getattr(self.m, 'static_fns', ()) or target in getattr(self.m, 'plain_fns', ()):
            self.fail('local function called in two ways')
        if self.lua:
            self.fail('local function called with values on the Lua stack')
        args = []
        rows = {}
        for k in range(2 if static else 1, 8):
            a = self.reg['x%d' % k]
            if is_value(a):
                if a[0] == 'stk':                        # S18: the values that stand right after it on the frame (a row argument, see lvalue)
                    more = []
                    while len(more) < 3 and a[1] + 0x10 * (len(more) + 1) in self.lv:
                        more.append(self.lv[a[1] + 0x10 * (len(more) + 1)])
                    rows[len(args)] = more
                args.append(self.lvalue(a, 'local call'))
            else:
                break
        else:
            # S20: every argument register holds a value: the eighth and later arguments are the pointers stored in
            # 8-byte cells at the stack pointer (as many as are values; the driver keeps as many as the callee reads)
            sp = self.reg['sp']
            for j in range(10):
                a = self.mem.get(sp[1] + 8 * j, A.UNDEF) if sp[0] == 'stk' else A.UNDEF
                if not is_value(a) or (a[0] == 'stk' and D.is_synth(a[1])):
                    break
                args.append(self.lvalue(a, 'local call'))
        x8 = x0 if static or plain else self.reg['x8']
        # S20: where each argument came from (a slot of this frame, or not); a callee that writes its argument k
        # (fighter_status.run_module: mod.arg_written) changes that slot: its value here is forgotten after the call
        first = 2 if static else 1
        src = [self.reg['x%d' % (first + k)] if first + k < 8 else self.mem.get(self.reg['sp'][1] + 8 * (first + k - 8), A.UNDEF)
               for k in range(len(args))]
        i = self.node(kind='local', target=target, args=args, static=static or plain, plain=plain, rows=rows,
                      argsrc=[s[0] == 'stk' for s in src])
        for k in getattr(self.m, 'arg_written', {}).get(target, ()):
            if k < len(src) and src[k][0] == 'stk':
                self.lv.pop(src[k][1], None)
        if x8 == A.RET:
            self.ret_value = ('ref', i)
        elif x8[0] == 'stk':
            self.lv[x8[1]] = ('ref', i)
        else:
            self.allnodes[i]['void'] = True

    def step(self, ins):
        if ins.mnemonic in ('orr', 'and'):               # S3: integer or / and of two values (flag constants), and with a mask
            ops = A.split_ops(ins.op_str)
            if len(ops) == 3 and ops[2] != '#1' and ops[1] not in ('wzr', 'xzr'):
                a = self.get(ops[1])
                b = ('int', A.imm(ops[2])) if ops[2].startswith('#') else self.get(ops[2])
                ok = ('int', 'luaconst', 'ref', 'conv', 'ibin', 'var', 'luax')      # (S21: luax, an integer a script call left in x0)
                if a[0] in ok and b[0] in ok:
                    if a[0] == 'int' and b[0] == 'int':
                        self.put(ops[0], ('int', a[1] | b[1] if ins.mnemonic == 'orr' else a[1] & b[1]))
                    else:
                        self.put(ops[0], ('ibin', '|' if ins.mnemonic == 'orr' else '&', a, b))
                    return None
        if ins.mnemonic == 'blr' and self.get(ins.op_str.strip()) == ('vfn', 0x10):
            if self.get('x0') != A.AGENT or self.lua:
                self.fail('coroutine_yield on something else than the agent')
            self.node(kind='yield', args=[])             # S21: see add
            self.allnodes[self.counter - 1]['void'] = True
            for r in range(0, 18):
                self.reg['x%d' % r] = A.UNDEF
            for r in range(0, 8):
                self.reg['v%d' % r] = A.UNDEF
            self.flags = None
            return None
        if ins.mnemonic == 'blr':
            v = self.get(ins.op_str.strip())
            if v[0] != 'conv' or v[1] != 'as_pointer' or self.get('x0') != A.AGENT:
                self.fail('indirect call')
            args = []
            for k in range(1, 8):
                a = self.reg['x%d' % k]
                if a[0] != 'stk' or a[1] not in self.lv or D.is_synth(a[1]):      # (S18: a chosen pointer is not counted as an argument here)
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
        if target in getattr(self.m, 'locals', {}) and target not in self.n.plt and target not in self.m.macros:
            self.call_local(target)                      # S8
            for r in range(0, 18):
                self.reg['x%d' % r] = A.UNDEF
            for r in range(0, 8):
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
    if os.environ.get('SSBU_FIGHTERS_ROOT'):             # S10: plus the refusals of the work run itself
        xw = os.path.join(STUDY, 'fighters', os.environ['SSBU_FIGHTERS_ROOT'], 'tools_out', mod.nro.short + '_status_exclude.json')
        if os.path.exists(xw):
            exclude.update(json.load(open(xw)))
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
        # S10: a work run (SSBU_FIGHTERS_ROOT, see below) writes its copy into its own folder; a --show / --stats run
        # writes nothing. (Defect found in S10: a --show run over a few functions rewrote this file with the statistics
        # of those few, e.g. sv_module_access::capture became "result always dropped", and the next gen_sdk.py
        # declared it void while the sources use its result.)
        if '--show' not in sys.argv and '--stats' not in sys.argv:
            if os.environ.get('SSBU_FIGHTERS_ROOT'):
                os.makedirs(os.path.join(STUDY, 'fighters', os.environ['SSBU_FIGHTERS_ROOT'], 'tools_out'), exist_ok=True)
                sp = os.path.join(STUDY, 'fighters', os.environ['SSBU_FIGHTERS_ROOT'], 'tools_out', 'status_lua_calls.json')
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
    # S10: SSBU_FIGHTERS_ROOT=<folder under fighters\>: a WORK run: sources, bindings and the result json go to
    # fighters\<root>\<name>\ and fighters\<root>\tools_out\ (build_fighter.py reads the same variable); the exclude
    # files are still read from fighters\tools_out. Without it: fighters\<name>\ as before.
    root = os.path.join(STUDY, 'fighters', os.environ.get('SSBU_FIGHTERS_ROOT') or '')
    fdir = os.path.join(root, short)
    os.makedirs(os.path.join(root, 'tools_out'), exist_ok=True)
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
    with open(os.path.join(root, 'tools_out', short + '_status.json'), 'w') as f:
        json.dump({'functions': res, 'imports_used': sorted(used), 'float_returns': sorted(mod.float_syms),
                   'void_calls': sorted(mod.void_syms - mod.value_syms), 'value_calls': sorted(mod.value_syms)}, f, indent=1)
    print('written: fighters/%s/status/*.cpp (%d files), %d bindings' % (short, len(files), len(binds)))


if __name__ == '__main__':
    main()
