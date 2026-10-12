"""General decompiler for lua2cpp output (AArch64 -> readable C++ against the fighter SDK), with control flow.

    python l2c_decomp.py mario             ACMD scripts of one module: writes fighters/<name>/acmd/*.cpp,
                                           fighters/<name>/generated/bindings.inc, out/<name>_acmd.json
    python l2c_decomp.py mario --stats     only the numbers
    python l2c_decomp.py all --stats       numbers for all modules (nothing written)
    python l2c_decomp.py mario --fn 0xb1b60   print one function (debugging)

How (session 2; acmd_decomp.py is the instruction-level model this file builds on):
  1. the function is cut into basic blocks; only blocks reachable from the entry count (landing pads are not);
  2. each block is executed symbolically (acmd_decomp.Exec.step) from the merged state of its predecessors.
     Registers and stack cells that differ between predecessors become unknown. L2CValue stack slots that differ
     become C++ variables: a slot value that crosses a block boundary and is not a constant is a token
     ('var', slot, tag); only tokens that are read later get an assignment at the end of the block that made them;
  3. loops: the state at a loop header is checked against the state at the end of each back edge and the
     function is re-run with the differing parts forced to variables / unknown until it is stable;
  4. the block graph is turned into if / else / while(true) / break / continue / return by its dominator tree
     (merge blocks are written after the statement of the block that dominates them); a jump that has no
     structured form is a `goto` to a label (counted in the statistics).
Anything outside the model raises NotMechanical with the reason: the function stays lifted and is counted.
"""
import collections
import json
import os
import re
import sys

import acmd_decomp as A
import census
import luaconst
import mangle
from acmd_decomp import NotMechanical, UNDEF, AGENT, RET, split_ops, imm
from nrolib import STUDY, HERE, demangle_simple

NORETURN = ('_Unwind_Resume', '__cxa_throw', '__cxa_rethrow', 'abort', '__stack_chk_fail', 'terminate', '__cxa_bad_cast',
            '__cxa_pure_virtual', 'throw_exception')
CC_INT = {'eq': ('==', 's'), 'ne': ('!=', 's'), 'lt': ('<', 's'), 'ge': ('>=', 's'), 'gt': ('>', 's'), 'le': ('<=', 's'),
          'lo': ('<', 'u'), 'hs': ('>=', 'u'), 'hi': ('>', 'u'), 'ls': ('<=', 'u'), 'cc': ('<', 'u'), 'cs': ('>=', 'u'),
          'mi': ('<', 'z'), 'pl': ('>=', 'z')}
# after fcmp: (operator, negated) so that the unordered case is exact
CC_FLT = {'eq': ('==', 0), 'ne': ('!=', 0), 'mi': ('<', 0), 'ls': ('<=', 0), 'gt': ('>', 0), 'ge': ('>=', 0),
          'lt': ('>=', 1), 'le': ('>', 1), 'hi': ('<=', 1), 'pl': ('<', 1), 'hs': ('<', 1), 'cs': ('<', 1), 'lo': ('<', 0), 'cc': ('<', 0)}
NEG_OP = {'==': '!=', '!=': '==', '<': '>=', '>=': '<', '>': '<=', '<=': '>'}

MEMBERS = {0xc8: 'global_table'}       # L2CValue members of the fighter agent (lua2cpp::L2CFighterBase; reference/skyline-smash common.rs)
GLOBALS = {}                           # names of global_table indices, where a public source gives them (none used yet)
_rets = None


def ret_type(sym):
    """C++ return type the SDK wrapper of an imported function has (gen_sdk.py uses the same table)"""
    global _rets
    if _rets is None:
        import gen_sdk
        _rets = (gen_sdk.rust_returns(), gen_sdk.cpp_ret)
    return _rets[1](_rets[0].get(sym))


def has_var(v):
    if not isinstance(v, tuple):
        return False
    if v and v[0] == 'var':
        return True
    return any(has_var(x) for x in v[1:])


def collect_vars(v, out):
    if isinstance(v, tuple):
        if v and v[0] == 'var':
            out.add(v)
            return
        for x in v[1:]:
            collect_vars(x, out)


class Block:
    def __init__(self, start):
        self.start = start
        self.ins = []
        self.term = None            # ('ret',) ('jmp', t) ('cond', ins, t, fall) ('tail', t) ('noret',)
        self.succ = []
        self.preds = []
        self.nodes = []
        self.cond = None            # condition under which succ[0] (the branch target) is taken
        self.exit_tok = None
        self.exit_real = None
        self.exit_reg = None
        self.exit_mem = None
        self.exit_lua = None
        self.entry_lv = None
        self.entry_reg = None
        self.entry_mem = None
        self.ret = None


class FExec(A.Exec):
    """symbolic execution of one function over its block graph"""

    def __init__(self, mod, off, mode):
        A.Exec.__init__(self, mod, off, mode)
        self.allnodes = {}
        self.counter = 0
        self.entry_reg = dict(self.reg)
        self.build_cfg()

    def node(self, **kw):
        kw['id'] = self.counter
        self.counter += 1
        self.allnodes[kw['id']] = kw
        self.nodes.append(kw)
        return kw['id']

    # ---- block graph
    def build_cfg(self):
        n = self.n
        size = n.func_size(self.off)
        if not size:
            self.fail('no unwind entry')
        ins = n.disasm(self.off, size)
        end = self.off + size
        leaders = {self.off}
        kinds = {}
        for k, i in enumerate(ins):
            mn = i.mnemonic
            nxt = i.address + 4
            ops = split_ops(i.op_str)
            if mn == 'b':
                t = imm(ops[0])
                if self.off <= t < end:
                    kinds[i.address] = ('jmp', t)
                    leaders.add(t)
                else:
                    kinds[i.address] = ('tail', t)
                leaders.add(nxt)
            elif mn.startswith('b.') or mn in ('cbz', 'cbnz', 'tbz', 'tbnz'):
                t = imm(ops[-1])
                if not self.off <= t < end:
                    self.fail('conditional branch out of the function')
                kinds[i.address] = ('cond', i, t, nxt)
                leaders.add(t)
                leaders.add(nxt)
            elif mn == 'ret':
                kinds[i.address] = ('ret',)
                leaders.add(nxt)
            elif mn == 'bl':
                t = imm(ops[0])
                nm = n.plt.get(t, '')
                if any(x in nm for x in NORETURN):
                    kinds[i.address] = ('noret',)
                    leaders.add(nxt)
            elif mn == 'br':
                self.fail('indirect jump')
        blocks = {}
        cur = None
        for i in ins:
            if i.address in leaders:
                cur = Block(i.address)
                blocks[i.address] = cur
            if cur.term is not None:
                continue
            if i.address in kinds:
                cur.term = kinds[i.address]
                if cur.term[0] in ('tail', 'noret'):
                    cur.ins.append(i)
            else:
                cur.ins.append(i)
                if i.address + 4 in leaders and i.address + 4 < end:
                    cur.term = ('jmp', i.address + 4)
        for b in blocks.values():
            if b.term is None:
                b.term = ('noret',)
            t = b.term
            b.succ = [t[1]] if t[0] == 'jmp' else [t[2], t[3]] if t[0] == 'cond' else []
        # reachable part, reverse postorder (the lower address of two successors comes first)
        seen, post = set(), []
        stack = [(self.off, iter(sorted(blocks[self.off].succ, reverse=True)))]
        seen.add(self.off)
        while stack:
            a, it = stack[-1]
            for s in it:
                if s not in seen:
                    seen.add(s)
                    stack.append((s, iter(sorted(blocks[s].succ, reverse=True))))
                    break
            else:
                post.append(a)
                stack.pop()
        self.rpo = post[::-1]
        if len(self.rpo) > 400:
            self.fail('more than 400 blocks')
        self.rpo_i = {a: k for k, a in enumerate(self.rpo)}
        self.B = {a: blocks[a] for a in self.rpo}
        for a in self.rpo:
            b = self.B[a]
            if b.term[0] == 'noret':
                self.fail('throws')
            b.succ = list(dict.fromkeys(b.succ))
            if b.term[0] == 'cond' and len(b.succ) == 1:
                b.term = ('jmp', b.succ[0])
            for s in b.succ:
                self.B[s].preds.append(a)
        # dominators
        idom = {self.off: self.off}
        changed = True
        while changed:
            changed = False
            for a in self.rpo[1:]:
                new = None
                for p in self.B[a].preds:
                    if p in idom:
                        new = p if new is None else self.intersect(idom, p, new)
                if idom.get(a) != new:
                    idom[a] = new
                    changed = True
        self.idom = idom
        self.back = set()
        for a in self.rpo:
            for s in self.B[a].succ:
                if self.rpo_i[s] <= self.rpo_i[a]:
                    if not self.dominates(s, a):
                        self.fail('irreducible control flow')
                    self.back.add((a, s))

    def intersect(self, idom, a, b):
        while a != b:
            while self.rpo_i[a] > self.rpo_i[b]:
                a = idom[a]
            while self.rpo_i[b] > self.rpo_i[a]:
                b = idom[b]
        return a

    def dominates(self, d, a):
        while True:
            if a == d:
                return True
            if a == self.off:
                return False
            a = self.idom[a]

    # ---- execution
    def stable(self, v):
        return not has_var(v)

    def enter(self, b, forced_lv, forced_undef):
        fp = [p for p in b.preds if (p, b.start) not in self.back]
        if not fp:
            self.reg = collections.defaultdict(lambda: UNDEF, self.entry_reg)
            self.mem, self.lv, self.lua, self.flags = {}, {}, None, None
        else:
            P = [self.B[p] for p in fp]
            reg = collections.defaultdict(lambda: UNDEF)
            for k, v in P[0].exit_reg.items():
                if all(q.exit_reg.get(k, UNDEF) == v for q in P[1:]):
                    reg[k] = v
            if len(P) > 1:                               # an integer register set differently on each path: a variable
                for s, v in P[0].exit_tok.items():
                    if isinstance(s, tuple) and s[1] not in reg and all(q.exit_tok.get(s) is not None for q in P[1:]):
                        reg[s[1]] = v if all(q.exit_tok[s] == v for q in P[1:]) else ('var', s, ('phi', b.start))
            else:
                for s, v in P[0].exit_tok.items():
                    if isinstance(s, tuple) and s[1] not in reg:
                        reg[s[1]] = v
            mem = {k: v for k, v in P[0].exit_mem.items() if all(q.exit_mem.get(k, UNDEF) == v for q in P[1:])}
            lv = {}
            for s, v in P[0].exit_tok.items():
                if isinstance(s, tuple):
                    continue
                vals = [q.exit_tok.get(s) for q in P[1:]]
                if any(x is None for x in vals):
                    continue
                lv[s] = v if all(x == v for x in vals) else ('var', s, ('phi', b.start))
            for q in P[1:]:
                if q.exit_lua != P[0].exit_lua:
                    self.fail('Lua stack differs between paths')
            self.reg, self.mem, self.lv = reg, mem, lv
            self.lua = list(P[0].exit_lua) if P[0].exit_lua is not None else None
            self.flags = P[0].exit_flags if len(P) == 1 and len(b.preds) == 1 else None
        for s in forced_lv.get(b.start, ()):
            if s in self.lv:
                self.lv[s] = ('var', s, ('phi', b.start))
        for k in forced_undef.get(b.start, ()):
            if k[0] == 'r':
                self.reg[k[1]] = UNDEF
            else:
                self.mem.pop(k[1], None)
        b.entry_lv = dict(self.lv)
        b.entry_reg = dict(self.reg)
        b.entry_mem = dict(self.mem)

    def branch_cond(self, i):
        """condition under which the conditional branch `i` is taken"""
        mn = i.mnemonic
        ops = split_ops(i.op_str)
        if mn in ('tbz', 'tbnz'):
            if imm(ops[1]) != 0:
                self.fail('bit test')
            v = ('bit', self.truth(self.get(ops[0])))
            return v if mn == 'tbnz' else ('not', v)
        if mn in ('cbz', 'cbnz'):
            v = ('nz', self.truth(self.get(ops[0])))
            return v if mn == 'cbnz' else ('not', v)
        cc = mn[2:]
        if not self.flags:
            self.fail('conditional branch %s without a comparison' % cc)
        a, b, kind = self.flags
        if kind == 'f':
            if cc not in CC_FLT:
                self.fail('float condition %s' % cc)
            op, neg = CC_FLT[cc]
            c = ('fcmp', op, a, b)
            return ('not', c) if neg else c
        if cc not in CC_INT:
            self.fail('condition %s' % cc)
        op, sign = CC_INT[cc]
        if sign == 'z':
            if b != ('int', 0):
                self.fail('sign test')
            sign = 's'
        return ('icmp', op, a, b, ('int' if sign == 's' else 'uint') + ('32' if kind == 'w' else '64') + '_t')

    def step(self, ins):
        mn = ins.mnemonic
        if mn in ('cmp', 'fcmp'):
            ops = split_ops(ins.op_str)
            if len(ops) != 2:
                self.fail('compare with a shift')
            a, b = self.get(ops[0]), self.get(ops[1])
            if mn == 'fcmp' and ops[1].startswith('#'):
                b = ('f', 0.0)
            self.flags = (self.scalar(a, 'compare'), self.scalar(b, 'compare'), 'f' if mn == 'fcmp' else ops[0][0])
            return None
        if mn == 'and' and ins.op_str.replace(' ', '').endswith(',#1'):
            ops = split_ops(ins.op_str)
            v = self.get(ops[1])
            if v[0] in ('var', 'cond'):
                self.put(ops[0], ('cond', ('bit', v)))
                return None
        if mn == 'eor' and ins.op_str.replace(' ', '').endswith(',#1'):
            ops = split_ops(ins.op_str)
            self.put(ops[0], ('cond', ('not', ('bit', self.truth(self.get(ops[1]))))))
            return None
        if mn == 'cset':
            ops = split_ops(ins.op_str)
            fake = type('I', (), {'mnemonic': 'b.' + ops[1], 'op_str': '#0'})
            self.put(ops[0], ('cond', self.branch_cond(fake)))
            return None
        return A.Exec.step(self, ins)

    def get(self, tok):
        v = A.Exec.get(self, tok)
        if tok in A.VREG and v[0] == 'ref' and v[1] in self.allnodes:
            self.allnodes[v[1]]['fret'] = True          # the result is taken from the float register
        return v

    # S10: "x0 read after a float function". The game's own code sometimes reads the INTEGER register after a function
    # that returns a float (L2CValue(unsigned) of MotionModule::end_frame): what it gets is whatever the function left
    # in x0, not the float converted. After a call of a function the SDK declares float, x0 is ('x0of', ('ref', node));
    # when that value is copied into another register or stored (so: really used), the node is marked `xret` with the
    # width read, and the call is printed as gcall<uintNN_t>(slot, ...) = the content of x0, not through the wrapper.
    def call_import(self, sym):
        A.Exec.call_import(self, sym)
        v = self.reg['x0']
        if v[0] == 'ref' and self.reg['v0'] == v and v[1] in self.allnodes:
            nd = self.allnodes[v[1]]
            rt = ret_type(sym)                           # (also loads the table of the public bindings' return types)
            if nd['kind'] == 'call' and nd['sym'] == sym and rt == 'float':
                self.reg['x0'] = ('x0of', v)
            # S10: a function the public bindings declare as returning a phx::Vector2f/3f/4f BY VALUE: the result is
            # the whole vector register (the game's code stores q0 and reads its lanes)
            if nd['kind'] == 'call' and nd['sym'] == sym and re.fullmatch(r'(root::)?phx::Vector[234]f', _rets[0].get(sym) or ''):
                nd['vret'] = True
                self.reg['v0'] = ('vecret', v)
                self.reg['x0'] = UNDEF

    def put(self, tok, v):
        if v[0] == 'x0of' and tok not in ('x0', 'w0') and v[1][1] in self.allnodes:
            self.allnodes[v[1][1]]['xret'] = 'uint32_t' if tok[0] == 'w' else 'uint64_t'
        A.Exec.put(self, tok, v)

    def store(self, a, v):
        if v[0] == 'x0of' and v[1][1] in self.allnodes:
            self.allnodes[v[1][1]]['xret'] = 'uint64_t'
        A.Exec.store(self, a, v)

    def truth(self, v):
        if v[0] in ('conv', 'ref', 'lvop', 'not', 'cmp', 'cond', 'var'):
            return v
        self.fail('condition on %s' % (v[0],))

    def scalar(self, v, name):
        if v[0] in ('cond', 'var'):
            return v
        return A.Exec.scalar(self, v, name)

    def run_block(self, b):
        self.nodes = b.nodes = []
        self.ret_value = None
        for i in b.ins:
            if i.mnemonic == 'b':                      # tail call
                self.call(i.address, imm(split_ops(i.op_str)[0]))
                continue
            self.step(i)
            if self.ret_value is not None:
                self.lv['ret'] = self.ret_value
                self.ret_value = None
        b.cond = self.branch_cond(b.term[1]) if b.term[0] == 'cond' else None
        if b.term[0] == 'ret':
            b.ret = self.lv.get('ret')
        elif b.term[0] == 'tail':
            if self.ret_value is not None:              # the call that ends the function writes the result
                self.lv['ret'] = self.ret_value
                self.ret_value = None
            b.ret = self.lv.get('ret', ('tail',))
        b.exit_real = dict(self.lv)
        b.exit_tok = {}
        for s, v in self.lv.items():
            if self.stable(v) or (v[0] == 'var' and v[1] == s):
                b.exit_tok[s] = v
            else:
                b.exit_tok[s] = ('var', s, ('x', b.start))
        for k, v in self.reg.items():                   # integer registers holding a value (not a pointer): may become variables
            if k[0] == 'x' and k not in ('x29', 'x30') and v[0] in ('int', 'luaconst', 'ref', 'conv', 'lvop', 'cond', 'var'):
                s = ('reg', k)
                b.exit_real[s] = v
                b.exit_tok[s] = v if self.stable(v) or (v[0] == 'var' and v[1] == s) else ('var', s, ('x', b.start))
        b.exit_reg = {k: v for k, v in self.reg.items() if v != UNDEF and self.stable(v)}
        b.exit_mem = {k: v for k, v in self.mem.items() if self.stable(v)}
        b.exit_lua = list(self.lua) if self.lua is not None else None
        b.exit_flags = self.flags
        if b.exit_lua and any(has_var(v) for v in b.exit_lua):
            self.fail('variable pushed across a branch')

    def run(self):
        forced_lv = collections.defaultdict(set)
        forced_undef = collections.defaultdict(set)
        for rounds in range(12):
            self.allnodes = {}
            self.counter = 0
            for a in self.rpo:
                self.enter(self.B[a], forced_lv, forced_undef)
                self.run_block(self.B[a])
            changed = False
            for u, h in self.back:
                U, H = self.B[u], self.B[h]
                for s, v in H.entry_lv.items():
                    if v == ('var', s, ('phi', h)):
                        continue
                    if U.exit_tok.get(s) != v:
                        forced_lv[h].add(s)
                        changed = True
                for k, v in H.entry_reg.items():
                    if v != UNDEF and U.exit_reg.get(k, UNDEF) != v:
                        forced_undef[h].add(('r', k))
                        changed = True
                for k, v in H.entry_mem.items():
                    if U.exit_mem.get(k, UNDEF) != v:
                        forced_undef[h].add(('m', k))
                        changed = True
                first = [p for p in H.preds if (p, h) not in self.back]
                if first and self.B[first[0]].exit_lua != U.exit_lua:
                    self.fail('Lua stack differs around a loop')
            if not changed:
                return self
        self.fail('loop state does not settle')


# ---------------------------------------------------------------- structure
class Structurer:
    def __init__(self, ex):
        self.ex = ex
        B = ex.B
        self.kids = collections.defaultdict(list)
        for a in ex.rpo[1:]:
            self.kids[ex.idom[a]].append(a)
        self.headers = sorted(set(h for u, h in ex.back), key=lambda a: ex.rpo_i[a])
        self.body = {}
        for h in self.headers:
            body = {h}
            work = [u for u, hh in ex.back if hh == h]
            while work:
                x = work.pop()
                if x not in body:
                    body.add(x)
                    work += B[x].preds
            self.body[h] = body
        self.after = collections.defaultdict(list)       # loop header -> blocks written after the loop
        self.merge = collections.defaultdict(list)       # block -> merge blocks written after its statement
        self.placed = set()
        for a in ex.rpo[1:]:
            d = ex.idom[a]
            outer = None
            for h in self.headers:                        # outermost first
                if d in self.body[h] and a not in self.body[h]:
                    outer = h
                    break
            fwd = [p for p in B[a].preds if (p, a) not in ex.back]
            if outer is not None:
                self.after[outer].append(a)
                self.placed.add(a)
            elif len(fwd) >= 2:
                self.merge[d].append(a)
                self.placed.add(a)
        self.labels = set()
        self.gotos = 0

    def trivial_return(self, t):
        b = self.ex.B[t]
        return b.term[0] == 'ret' and not b.nodes and not b.assigns

    def jump(self, src, t, follow, loops):
        ex = self.ex
        if (src, t) in ex.back:
            if follow == t:
                return []
            if loops and loops[-1][0] == t:
                return [('continue',)]
            self.labels.add(('c', t))
            self.gotos += 1
            return [('goto', ('c', t))]
        if t not in self.placed:
            return self.tree(t, follow, loops)
        if t == follow:
            return []
        if self.trivial_return(t):
            return [('return', ex.B[t].ret)]
        if loops and loops[-1][1] == t:
            return [('break',)]
        self.labels.add(('b', t))
        self.gotos += 1
        return [('goto', ('b', t))]

    def tree(self, x, follow, loops):
        ex = self.ex
        if x in self.body:
            afters = sorted(self.after[x], key=lambda a: ex.rpo_i[a])
            brk = afters[0] if afters else follow
            inner = self.node(x, x, loops + [(x, brk)], [m for m in self.merge[x]])
            out = [('label', ('c', x)), ('loop', inner)]
            for k, a in enumerate(afters):
                f = afters[k + 1] if k + 1 < len(afters) else follow
                out.append(('label', ('b', a)))
                out += self.tree(a, f, loops)
            return out
        return self.node(x, follow, loops, self.merge[x])

    def node(self, x, follow, loops, merges):
        ex = self.ex
        b = ex.B[x]
        chain = sorted(merges, key=lambda a: ex.rpo_i[a])
        f0 = chain[0] if chain else follow
        out = [('node', nd) for nd in b.nodes]
        cond = b.cond
        if b.term[0] == 'cond' and b.assigns:
            clob = set(s for s, e in b.assigns)
            used = set()
            collect_vars(cond, used)
            if any(v[1] in clob for v in used):
                out.append(('condvar', x, cond))
                cond = ('condname', x)
        out += [('assign', s, e) for s, e in b.assigns]
        t = b.term
        if t[0] in ('ret', 'tail'):
            out.append(('return', b.ret))
        elif t[0] == 'jmp':
            out += self.jump(x, b.succ[0], f0, loops)
        else:
            yes = self.jump(x, t[2], f0, loops)
            no = self.jump(x, t[3], f0, loops)
            out += self.make_if(cond, yes, no)
        for k, m in enumerate(chain):
            f = chain[k + 1] if k + 1 < len(chain) else follow
            out.append(('label', ('b', m)))
            out += self.tree(m, f, loops)
        return out

    @staticmethod
    def exits(stmts):
        return bool(stmts) and stmts[-1][0] in ('return', 'break', 'continue', 'goto')

    def make_if(self, cond, yes, no):
        if not yes and not no:
            return [('eval', cond)]
        if not yes:
            return [('if', ('not', cond), no, [])]
        if not no:
            return [('if', cond, yes, [])]
        if self.exits(yes) and not self.exits(no):
            return [('if', cond, yes, [])] + no
        if self.exits(no):
            return [('if', ('not', cond), no, [])] + yes
        return [('if', ('not', cond), no, yes)]


def materialise(ex):
    """decide which slot variables are read, and put their assignments at the end of the blocks that set them"""
    B = ex.B
    need = set()
    work = []

    def want(v):
        found = set()
        collect_vars(v, found)
        for t in found:
            if t not in need:
                need.add(t)
                work.append(t)

    for b in B.values():
        b.assigns = []
        for nd in b.nodes:
            for a in nd.get('args', []):
                want(a)
        if b.cond is not None:
            want(b.cond)
        if b.ret is not None:
            want(b.ret)
    done = set()
    while work:
        t = work.pop()
        s, tag = t[1], t[2]
        if tag[0] == 'x':
            p = B[tag[1]]
            if (p.start, s) not in done:
                done.add((p.start, s))
                p.assigns.append((s, p.exit_real[s]))
                want(p.exit_real[s])
        else:
            for pa in B[tag[1]].preds:
                p = B[pa]
                e = p.exit_tok.get(s)
                if e is None:
                    raise NotMechanical('variable not set on every path')
                if e[0] == 'var' and e[1] == s:
                    want(e)
                elif (pa, s) not in done:
                    done.add((pa, s))
                    p.assigns.append((s, p.exit_real[s]))
                    want(p.exit_real[s])
    for b in B.values():
        # an assignment must not read a variable an earlier assignment of the same block has already changed
        order = []
        left = list(b.assigns)
        while left:
            for k, (s, e) in enumerate(left):
                others = set()
                for s2, e2 in left:
                    if s2 != s:
                        collect_vars(e2, others)
                if not any(v[1] == s for v in others):
                    order.append(left.pop(k))
                    break
            else:
                raise NotMechanical('variables exchanged in one step')
        b.assigns = order
    return sorted(set(t[1] for t in need), key=str)


# ---------------------------------------------------------------- C++ text
class Printer2(A.Printer):
    def __init__(self, ex, consts, varnames):
        self.ex = ex
        self.consts = consts
        self.nodes = ex.allnodes
        self.uses = collections.Counter()
        self.named = {}
        self.used_syms = set()
        self.varnames = varnames
        self.hoist = set()
        self.def_scope = {}
        self.scopes = []
        self.all_hoisted = False
        self.inline_ok = set()

    def call_text(self, nd):
        k = nd['kind']
        if k == 'store':
            return '%s = %s' % (self.expr(nd['args'][0]), self.value_text(nd['args'][1]))
        if k == 'snap':
            return self.value_text(nd['args'][0])
        if k == 'callptr':
            return 'call_function(%s)' % ', '.join(['agent'] + [self.expr(a) for a in nd['args']])
        if k == 'local':                                 # S8: a function of this module without an exported name
            return 'local::%s(%s)' % (self.ex.m.locals[nd['target']], ', '.join(['agent'] + [self.value_text(a) for a in nd['args']]))
        if nd.get('vret'):                               # S10: a vector result (its plain uses are printed as lane 0)
            return self.vret_text(nd)
        if nd.get('xret'):                               # S10: the content of x0 after a function that returns a float
            if nd.get('fret'):
                raise NotMechanical('result of a float function read from both the float and the integer register')
            self.used_syms.add(nd['sym'])
            slot = 'S_' + re.sub(r'\W', '_', A.wrapper_name(nd['sym']))
            return 'gcall<%s>(%s)' % (nd['xret'], ', '.join([slot] + [self.expr(a) for a in nd['args']]))
        if nd.get('fret'):
            self.ex.m.float_syms.add(nd['sym'])         # gen_sdk.py: this function's result is in the float register
        if nd.get('void'):
            self.ex.m.void_syms.add(nd['sym'])          # gen_sdk.py: called without a result buffer
        elif nd['kind'] == 'call':
            self.ex.m.value_syms.add(nd['sym'])
        return A.Printer.call_text(self, nd)

    def value_text(self, v):
        t = self.expr(v)
        return t if t.startswith('L2CValue(') or v[0] in ('var', 'ref', 'lvop', 'arg') else 'L2CValue(%s)' % t

    def node_type(self, nd):
        if nd.get('vret'):
            return 'Vector4f'
        if nd.get('xret'):
            return nd['xret']
        if nd.get('fret'):
            return 'float'
        if nd['kind'] in ('lua', 'snap', 'callptr', 'local'):
            return 'L2CValue'
        path = mangle.parse(nd['sym'])[0]
        if (path[0] == 'lua2cpp' and mangle.is_member(path)) or mangle.is_static_value(path):      # S13: lib::L2CAgent::math_* returns an L2CValue too
            return 'L2CValue'
        return ret_type(nd['sym'])

    def is_bool(self, v):
        if v[0] == 'ref':
            nd = self.nodes[v[1]]
            return nd['kind'] == 'call' and self.node_type(nd) == 'bool'
        return v[0] in ('lvop', 'cond', 'not', 'cmp') or (v[0] == 'conv' and v[1] in ('bool', 'as_bool'))

    def expr(self, v, want=None):
        k = v[0]
        if k == 'var':
            return self.varnames[v[1]]
        if k == 'member':
            return 'agent->%s' % MEMBERS[v[1]]
        if k == 'elem':
            key = self.expr(v[2])
            if v[2][0] == 'int' and v[2][1] in GLOBALS and v[1] == ('member', 0xc8):
                key = GLOBALS[v[2][1]]
            return '%s[%s]' % (self.expr(v[1]), key)
        if k == 'arg':
            return 'a%d' % v[1]
        if k == 'x0of':                                  # S10: see FExec.call_import
            if not self.nodes[v[1][1]].get('xret'):
                raise NotMechanical('x0 after a float function, not marked')
            return self.expr(v[1], want)
        if k == 'singleton':                           # S8: lib::Singleton<app::X>::instance_ (gen_sdk.py makes the slot and singleton())
            self.used_syms.add(v[1])
            return 'singleton(S_singleton_%s)' % A.singleton_name(v[1])
        if k == 'img' and v[1] in getattr(self.ex.m, 'locals', {}):      # S8: the address of a local function the driver named
            return 'status_function(%s)' % self.ex.m.locals[v[1]]
        if k in ('sym', 'img'):                          # the address of a named function (stored in a table, called later)
            sym = v[1] if k == 'sym' else self.ex.n.exports.get(v[1])
            if not sym or not mangle.parse(sym):
                raise NotMechanical('address of something without a name')
            self.used_syms.add(sym)
            return 'function_address(S_%s)' % ''.join(c if c.isalnum() else '_' for c in A.wrapper_name(sym))
        if k == 'lvneg':
            return '(-%s)' % self.value_text(v[1])
        if k == 'lvnot':                                 # S3: the game's L2CValue::operator!
            return '%s.lnot()' % self.value_text(v[1])
        if k == 'ibin':                                  # S3: integer | and & (flag constants)
            return '(%s %s %s)' % (self.expr(v[2]), v[1], self.expr(v[3]))
        if k == 'ref':
            i = v[1]
            lane0 = '.v[0]' if self.nodes[i].get('vret') and want != 'vec' else ''      # S10: a plain use of a vector result
            if i in self.named:
                if self.all_hoisted or self.def_scope.get(i) not in self.scopes:
                    self.hoist.add(i)
                return self.named[i] + lane0
            return self.call_text(self.nodes[i]) + lane0
        if k == 'cond':
            return self.cond(v[1])
        if k == 'lv' and v[1] == 'b' and v[2][0] not in ('int',):
            return 'L2CValue(%s)' % self.bit(v[2])
        if k == 'conv' and v[1] == 'bool':
            inner = self.expr(v[2])
            return inner if v[2][0] == 'ref' and self.nodes[v[2][1]]['kind'] == 'lua' and v[2][1] not in self.named else 'bool(%s)' % (inner if inner.startswith('L2CValue(') or v[2][0] in ('var', 'ref', 'lvop') else 'L2CValue(%s)' % inner)
        if k == 'asbool':
            return self.bit(v[1]) if v[1][0] != 'int' else A.Printer.expr(self, v, want)
        if k == 'lvop':
            def side(x):
                t = self.expr(x)
                return t if x[0] in ('var',) or t.startswith('L2CValue(') else 'L2CValue(%s)' % t
            return '(%s %s %s)' % (side(v[2]), v[1], side(v[3]))
        return A.Printer.expr(self, v, want)

    def bit(self, v):
        """C++ bool: bit 0 of v"""
        if v[0] == 'int':
            return 'true' if v[1] & 1 else 'false'
        t = self.expr(v)
        return t if self.is_bool(v) else '((%s) & 1) != 0' % t

    def cond(self, c, neg=False):
        k = c[0]
        if k == 'not':
            return self.cond(c[1], not neg)
        if k == 'condname':
            return ('!' if neg else '') + 'c%x' % (c[1] & 0xfffff)
        if k == 'bit' or k == 'nz':
            v = c[1]
            if v[0] == 'cond':
                return self.cond(v[1], neg)
            if v[0] == 'not':
                return self.cond((k, v[1]), not neg)
            if self.is_bool(v):
                t = self.expr(v)
                if not neg:
                    return t
                return '!' + (t if t.startswith('(') or t.replace('::', '').replace('_', '').isalnum() or (t.endswith(')') and ' ' not in t.split('(')[0]) else '(%s)' % t)
            t = self.expr(v)
            if k == 'bit':
                return '((%s) & 1) %s 0' % (t, '==' if neg else '!=')
            return '(%s) %s 0' % (t, '==' if neg else '!=')
        if k == 'icmp':
            op, a, b, cast = c[1], c[2], c[3], c[4]
            if neg:
                op = NEG_OP[op]

            def side(x):
                if x[0] == 'int':
                    return self.expr(x, 'i' if cast == 'int32_t' else 'u' if cast == 'uint32_t' else 'l' if cast == 'int64_t' else 'm')
                if x[0] == 'luaconst' and cast == 'int32_t':
                    return self.expr(x)
                return '%s(%s)' % (cast, self.expr(x))
            return '%s %s %s' % (side(a), op, side(b))
        if k == 'fcmp':
            t = '%s %s %s' % (self.expr(c[2]), c[1], self.expr(c[3]))
            return '!(%s)' % t if neg else t
        raise NotMechanical('cannot print condition %s' % k)

    # ---- statements
    def count_stmts(self, stmts):
        for st in stmts:
            k = st[0]
            if k == 'node':
                for a in st[1].get('args', []):
                    self.count(a)
            elif k in ('if', 'eval', 'condvar'):
                self.count(st[1] if k != 'condvar' else st[2])
                if k == 'if':
                    self.count_stmts(st[2])
                    self.count_stmts(st[3])
            elif k == 'loop':
                self.count_stmts(st[1])
            elif k == 'assign':
                self.count(st[2])
            elif k == 'return' and st[1] is not None:
                self.count(st[1])

    def stmt_refs(self, st):
        k = st[0]
        if k == 'node':
            return self.refs(('all',) + tuple(st[1].get('args', [])), [])
        if k in ('if', 'eval'):
            return self.refs(st[1], [])
        if k == 'condvar':
            return self.refs(st[2], [])
        if k == 'assign':
            return self.refs(st[2], [])
        if k == 'return' and st[1] is not None:
            return self.refs(st[1], [])
        return []

    def emit(self, stmts, depth, lines, mode):
        ind = '    ' * depth
        self.scopes.append(id(stmts))
        for n, st in enumerate(stmts):
            k = st[0]
            if k == 'node':
                nd = st[1]
                i = nd['id']
                u = self.uses[i]
                auto = nd['kind'] == 'lua' and nd['sym'] in self.ex.m.autopop
                if u == 0 and nd['kind'] == 'snap':
                    continue
                if u == 0:
                    tail = '.pop();' if nd['kind'] == 'lua' and nd.get('popped') and not auto else ';'
                    lines.append(ind + self.call_text(nd) + tail)
                else:
                    nxt = stmts[n + 1] if n + 1 < len(stmts) else None
                    if nxt is not None and u == 1 and nxt[0] in ('node', 'if', 'eval', 'return') and i in self.stmt_refs(nxt):
                        continue                        # written inside the next statement
                    self.named[i] = 'r%d' % i
                    self.def_scope[i] = id(stmts)
                    text = self.call_text(nd)
                    if i in self.hoist or self.all_hoisted:
                        self.hoist.add(i)
                        lines.append(ind + 'r%d = %s;' % (i, text))
                    else:
                        lines.append(ind + '%s r%d = %s;' % ('L2CValue' if self.node_type(nd) == 'L2CValue' else 'auto', i, text))
            elif k == 'assign':
                lines.append(ind + '%s = %s;' % (self.varnames[st[1]], self.expr(st[2])))
            elif k == 'condvar':
                lines.append(ind + 'bool c%x = %s;' % (st[1] & 0xfffff, self.cond(st[2])))
            elif k == 'eval':
                if self.refs(st[1], []):
                    lines.append(ind + '(void)(%s);' % self.cond(st[1]))
            elif k == 'if':
                lines.append(ind + 'if (%s) {' % self.cond(st[1]))
                self.emit(st[2], depth + 1, lines, mode)
                if st[3]:
                    lines.append(ind + '} else {')
                    self.emit(st[3], depth + 1, lines, mode)
                lines.append(ind + '}')
            elif k == 'loop':
                lines.append(ind + 'while (true) {')
                self.emit(st[1], depth + 1, lines, mode)
                lines.append(ind + '}')
            elif k == 'break' or k == 'continue':
                lines.append(ind + k + ';')
            elif k == 'goto':
                lines.append(ind + 'goto %s;' % self.label(st[1]))
            elif k == 'label':
                if st[1] in self.labels:
                    lines.append('  %s: ;' % self.label(st[1]))
            elif k == 'return':
                if mode == 'acmd':
                    no_result = self.ex.entry_reg.get('x0') == AGENT
                    if st[1] != ('lv', 'i', ('int', 0)) and st[1] != ('tail',) and not (st[1] is None and no_result):
                        raise NotMechanical('returns something else than 0')
                    if not (depth == 1 and n == len(stmts) - 1):
                        lines.append(ind + 'return;')
                elif getattr(self, 'void_fn', False):
                    if not (depth == 1 and n == len(stmts) - 1):
                        lines.append(ind + 'return;')
                else:
                    if st[1] is None or st[1] == ('tail',):
                        raise NotMechanical('return value not understood')
                    t = self.expr(st[1])
                    lines.append(ind + 'return %s;' % (t if t.startswith('L2CValue(') or st[1][0] in ('var', 'ref') else 'L2CValue(%s)' % t))
        self.scopes.pop()

    def label(self, l):
        return self.labelnames.setdefault(l, 'L%d' % (len(self.labelnames) + 1))

    def function_text(self, stmts, labels, mode, variables):
        self.labels = labels
        self.count_stmts(stmts)
        self.all_hoisted = bool(labels)
        for attempt in (0, 1):
            self.named = {}
            self.labelnames = {}
            self.def_scope = {}
            self.scopes = []
            lines = []
            before = set(self.hoist)
            self.emit(stmts, 1, lines, mode)
            if self.hoist == before:
                break
        else:
            lines = []
            self.named, self.labelnames, self.def_scope, self.scopes = {}, {}, {}, []
            before = set(self.hoist)
            self.emit(stmts, 1, lines, mode)
            if self.hoist != before:
                raise NotMechanical('result used outside its block')
        head = []
        values = [self.varnames[s] for s in variables if not isinstance(s, tuple)]
        scalars = [self.varnames[s] for s in variables if isinstance(s, tuple)]
        if values:
            head.append('    L2CValue %s;' % ', '.join(values))
        if scalars:
            head.append('    uint64_t %s;' % ', '.join(scalars))
        for i in sorted(self.hoist):
            head.append('    %s r%d;' % (self.node_type(self.nodes[i]), i))
        return head + lines


def var_names(variables):
    """names of the C++ variables: L2CValue slots v1.., integer registers n1.., the function result"""
    names = {}
    k = j = 0
    for s in variables:
        if s == 'ret':
            names[s] = 'result'
        elif isinstance(s, tuple):
            j += 1
            names[s] = 'n%d' % j
        else:
            k += 1
            names[s] = 'v%d' % k
    return names


def one_arg_body(mod, off):
    """does this script body take only the agent (x0)? (the unused result pointer was removed by the compiler)"""
    size = mod.nro.func_size(off) or 0
    for i in mod.nro.disasm(off, min(size, 80)):
        ops = split_ops(i.op_str)
        if i.mnemonic == 'mov' and len(ops) == 2 and ops[1] == 'x1':
            return False
        if i.mnemonic in ('bl', 'b', 'ret'):
            break
    return True


def execute_function(mod, off, mode):
    ex = FExec(mod, off, mode)
    if mode == 'body' and one_arg_body(mod, off):
        ex.entry_reg['x0'] = AGENT
        ex.entry_reg['x1'] = UNDEF
    ex.run()
    variables = materialise(ex)
    for b in ex.B.values():
        if b.exit_lua and b.term[0] in ('ret', 'tail'):
            raise NotMechanical('values left on the Lua stack')
    st = Structurer(ex)
    stmts = st.tree(ex.off, None, [])
    ex.stmts, ex.labels, ex.variables, ex.gotos = stmts, st.labels, variables, st.gotos
    ex.loops = len(st.headers)
    p = Printer2(ex, [], {})
    p.count_stmts(stmts)
    for nd in ex.allnodes.values():
        if nd['kind'] == 'lua':
            s = mod.lua_stats.setdefault(nd['sym'], {'protos': set(), 'dropped': 0, 'other': 0})
            s['protos'].add(nd['proto'])
            s['dropped' if nd['popped'] and p.uses[nd['id']] == 0 else 'other'] += 1
    return ex


GLOBAL_STATS = os.path.join(STUDY, 'fighters', 'tools_out', 'lua_calls_global.json')


def load_global():
    """how every script call (app::sv_animcmd::* ...) is used over ALL modules: batch.py writes it, one SDK serves all"""
    if not os.path.exists(GLOBAL_STATS):
        return None
    with open(GLOBAL_STATS) as f:
        return json.load(f)


def print_function(ex, consts, mode):
    g = getattr(ex.m, 'glob', None)
    for nd in ex.allnodes.values():
        if nd['kind'] == 'lua':
            n = len(ex.m.lua_stats[nd['sym']]['protos']) if g is None else g.get(nd['sym'], {}).get('protos', 0)
            if n != 1:
                raise NotMechanical('%s is called in more than one way' % demangle_simple(nd['sym']))
    p = Printer2(ex, consts, var_names(ex.variables))
    lines = p.function_text(ex.stmts, ex.labels, mode, ex.variables)
    return lines, p.used_syms


def resolve_body(mod, body):
    """a body that only jumps to another local function is that function"""
    n = mod.nro
    for _ in range(4):
        size = n.func_size(body) or 0
        if size > 16 or not size:
            break
        ins = n.disasm(body, size)
        if ins and ins[0].mnemonic == 'b':
            t = imm(split_ops(ins[0].op_str)[0])
            if t in mod.r['start_set'] and t not in n.plt and t not in mod.macros:
                body = t
                continue
        break
    return body


def write_module(short, mod, res, out, syms):
    """the fighter's source files, its bindings (script -> offset of the original) and the per-script result"""
    fdir = os.path.join(STUDY, 'fighters', short)
    os.makedirs(os.path.join(fdir, 'acmd'), exist_ok=True)
    os.makedirs(os.path.join(fdir, 'generated'), exist_ok=True)
    binds = []
    seen = {}
    for kind in sorted(set(list(out) + list(census.ACMD_KINDS))):
        scripts = out.get(kind, [])
        path = os.path.join(fdir, 'acmd', kind + '.cpp')
        if not scripts:
            if os.path.exists(path):
                os.remove(path)
            continue
        text = ['// %s: ACMD scripts "%s_*". Decompiled by fighter_sdk/tools/l2c_decomp.py from the game\'s own module;' % (short, kind),
                '// from here on this file is source: edit it, then `python fighter_sdk/tools/build_fighter.py %s`.' % short,
                '#include "fighter_sdk.h"', '']
        for sname, thunk, lines in sorted(scripts):
            ident = sname
            if ident in seen:                      # the same script name registered for several agents (mario, mario_fireball ...)
                seen[ident] += 1
                ident = '%s__%d' % (sname, seen[ident])
            else:
                seen[ident] = 0
            text.append('ACMD(%s, %s) {' % (short, ident))
            text += lines
            text.append('}')
            text.append('')
            binds.append((thunk, ident, sname))
        with open(path, 'w', newline='\n') as f:
            f.write('\n'.join(text))
    with open(os.path.join(fdir, 'generated', 'bindings.inc'), 'w', newline='\n') as f:
        f.write('// GENERATED by l2c_decomp.py: where each script\'s original lives in lua2cpp_%s (offset of the registered function).\n' % short)
        f.write('// The only place with addresses; the move logic never names one.\n')
        for thunk, ident, sname in sorted(binds):
            f.write('ACMD_BIND(%s, %s, 0x%x)\n' % (short, ident, thunk))
    ident_of = {thunk: (ident, sname) for thunk, ident, sname in binds}
    for e in res:
        if e['thunk'] in ident_of:
            e['ident'] = ident_of[e['thunk']][0]
    with open(os.path.join(STUDY, 'fighters', 'tools_out', short + '_acmd.json'), 'w') as f:
        json.dump({'scripts': res, 'imports_used': sorted(syms), 'float_returns': sorted(mod.float_syms), 'void_calls': sorted(mod.void_syms)}, f, indent=1)


def run_module(name, collect_only=False):
    mod = A.Module(name)
    consts = luaconst.table_names()
    res = []
    reasons = collections.Counter()
    out = collections.defaultdict(list)
    syms = set()
    mod.lua_stats = {}
    mod.autopop = set()
    mod.float_syms, mod.void_syms, mod.value_syms = set(), set(), set()
    execs = {}
    scripts = [(t, resolve_body(mod, b) if b else b, s, k) for t, b, s, k in mod.scripts()]
    for thunk, body, sname, kind in scripts:
        if body and body not in execs:
            try:
                execs[body] = execute_function(mod, body, 'body')
            except NotMechanical as ex:
                execs[body] = str(ex)
            except RecursionError:
                execs[body] = 'too deeply nested'
    mod.autopop = set(s for s, st in mod.lua_stats.items() if st['dropped'] and not st['other'])
    if collect_only:
        return {s: {'protos': sorted(st['protos']), 'dropped': st['dropped'], 'other': st['other']} for s, st in mod.lua_stats.items()}
    mod.glob = load_global()
    if mod.glob is not None:
        mod.autopop = set(s for s, st in mod.glob.items() if st['autopop'])
    exclude = {}
    xp = os.path.join(STUDY, 'fighters', 'tools_out', mod.nro.short + '_exclude.json')
    if os.path.exists(xp):
        with open(xp) as f:
            exclude = json.load(f)
    done = {}
    tot = collections.Counter()
    for thunk, body, sname, kind in scripts:
        size = (mod.nro.func_size(body) or 0) if body else 0
        entry = {'thunk': thunk, 'body': body, 'name': sname, 'kind': kind, 'size': size}
        first = body not in done
        try:
            if body is None:
                raise NotMechanical('no body of its own (forwards to a shared function)')
            if first:
                if isinstance(execs[body], str):
                    done[body] = execs[body]
                else:
                    try:
                        done[body] = print_function(execs[body], consts, 'acmd')
                    except NotMechanical as ex:
                        done[body] = str(ex)
            if isinstance(done[body], str):
                raise NotMechanical(done[body])
            lines, used = done[body]
            entry['ok'] = True
            entry['gotos'] = execs[body].gotos
            entry['loops'] = execs[body].loops
            syms |= used
            if not sname or sname.startswith('hash_'):
                entry['unnamed'] = True                 # the label lists do not have this name: the script is named by its hash
            if not sname:
                raise NotMechanical('registered without a readable hash')
            key = '%s@%x' % (sname, thunk)
            if key in exclude:
                raise NotMechanical(exclude[key])
            out[kind].append((sname, thunk, lines))
        except NotMechanical as ex:
            entry['ok'] = False
            entry['why'] = str(ex)
            reasons[str(ex).split('+0x')[0][:70]] += 1
        if body and first:
            tot['bytes_all'] += size
            tot['bytes_ok'] += size if entry['ok'] else 0
        res.append(entry)
    return mod, res, reasons, out, syms, tot['bytes_ok'], tot['bytes_all']


def main():
    what = sys.argv[1]
    stats_only = '--stats' in sys.argv
    if '--fn' in sys.argv:
        mod = A.Module(what)
        mod.lua_stats, mod.autopop = {}, set()
        mod.float_syms, mod.void_syms, mod.value_syms = set(), set(), set()
        off = int(sys.argv[sys.argv.index('--fn') + 1], 16)
        mode = sys.argv[sys.argv.index('--mode') + 1] if '--mode' in sys.argv else 'body'
        ex = execute_function(mod, off, mode)
        print('\n'.join(print_function(ex, luaconst.table_names(), 'acmd' if mode == 'body' else 'fn')[0]))
        return
    mods = [e['name'] for e in census.nro_map()] if what == 'all' else [what]
    tot = collections.Counter()
    all_reasons = collections.Counter()
    for m in mods:
        mod, res, reasons, out, syms, bytes_ok, bytes_all = run_module(m)
        ok = sum(1 for e in res if e['ok'])
        own = sum(1 for e in res if e['body'])
        tot['scripts'] += len(res)
        tot['own'] += own
        tot['ok'] += ok
        tot['bytes_ok'] += bytes_ok
        tot['bytes_all'] += bytes_all
        tot['goto'] += sum(1 for e in res if e.get('gotos'))
        tot['unnamed'] += sum(1 for e in res if e.get('unnamed'))
        all_reasons.update(reasons)
        print('%-22s scripts %5d  with own body %5d  decompiled %5d (%.1f%% of own; body bytes %.1f%%)  with goto %d' %
              (m, len(res), own, ok, 100.0 * ok / max(own, 1), 100.0 * bytes_ok / max(bytes_all, 1), sum(1 for e in res if e.get('gotos'))), flush=True)
        if not stats_only:
            write_module(mod.nro.short, mod, res, out, syms)
    if len(mods) > 1:
        print('TOTAL scripts %d, with own body %d, decompiled %d (%.1f%%), body bytes %.1f%%; with a goto %d; named by hash only %d' %
              (tot['scripts'], tot['own'], tot['ok'], 100.0 * tot['ok'] / max(tot['own'], 1), 100.0 * tot['bytes_ok'] / max(tot['bytes_all'], 1), tot['goto'], tot['unnamed']))
    print('reasons a script is not mechanical:')
    for w, c in all_reasons.most_common(30):
        print('  %6d  %s' % (c, w))


if __name__ == '__main__':
    main()
