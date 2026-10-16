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
# what an integer register can hold that is a value (not a pointer); such a register may become a C++ variable
INTLIKE = ('int', 'luaconst', 'ref', 'conv', 'lvop', 'cond', 'var', 'ibin', 'u32', 'ext', 'mvn', 'luaconstv', 'luax')      # S20: the last three; S21 luax

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


# S18: "a pointer chosen on two paths" (`x0 = cond ? &a : &b; as_hash(x0)`): at a merge, an integer register that
# points to an L2CValue on every way in (an argument, a local value, NIL) but not to the same one becomes a pointer to
# a made-up slot whose value is a variable set at the end of each predecessor (a copy of what the pointer pointed to).
# The copy equals what the original reads only while nothing has happened since the merge, so the pointer is dropped
# at the first call / store of the merge block and at its end, and writing through it is refused.
SYNTH = -0x6000000


def rname(i):
    """the C++ name of a result: r<node>; held<n> for a value taken from mutable state before a call (FExec.hold)"""
    return 'r%d' % i if i < FExec.HELD else 'held%d' % (i - FExec.HELD + 1)


def synth_slot(reg):
    return SYNTH - 0x100 * int(reg[1:])


def is_synth(off):
    return isinstance(off, int) and -0x6800000 < off <= SYNTH


def has_elem(v):
    """does this expression read (or take the address of) a table element?"""
    if not isinstance(v, tuple):
        return False
    if v and v[0] in ('elem', 'elemptr'):
        return True
    return any(has_elem(x) for x in v[1:])


def has_var(v):
    if not isinstance(v, tuple):
        return False
    if v and v[0] == 'var':
        return True
    return any(has_var(x) for x in v[1:])


def has_kind(v, kind):
    """S21: does this expression contain a node of this kind ('str': a string value, see Printer2.expr)?"""
    if not isinstance(v, tuple) or not v:
        return False
    if v[0] == kind:
        return True
    return any(has_kind(x, kind) for x in v[1:])


# S21: the game's L2CValue(char const*) and ~L2CValue: gen_sdk.py gives them slots (S_lv_ctor_string, S_lv_dtor) only
# when a source uses a string value, and then defines FS_HAVE_LV_STRING (fighter_sdk.h: struct L2CString)
STR_SYMS = ('_ZN3lib8L2CValueC1EPKc', '_ZN3lib8L2CValueD1Ev')


def c_string(s):
    """a C++ string literal of a text of the module (plain ASCII; checked by the caller)"""
    out = []
    for ch in s:
        if ch in '"\\':
            out.append('\\' + ch)
        elif 32 <= ord(ch) < 127 and ch != '?':          # ('?' escaped: no trigraphs)
            out.append(ch)
        else:
            out.append('\\x%02x""' % ord(ch))
    return '"%s"' % ''.join(out)


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
        self.held_n = 0
        self.entry_reg = dict(self.reg)
        self.build_cfg()

    def node(self, **kw):
        if kw.get('kind') != 'snap':
            self.hold()                                  # S18: what was read from mutable state before this point is kept (see hold)
        kw['id'] = self.counter
        self.counter += 1
        self.allnodes[kw['id']] = kw
        self.nodes.append(kw)
        self.drop_synth()                                # S18: a chosen pointer is good only until something happens
        return kw['id']

    # S18 (defect found by the fast check, peach special S: the original compares global_table[22] BEFORE set_situation and
    # uses the result after it; the source read the table again after the call). A value the original has already read
    # from memory a callee can write (an element of a table, a member of the agent: 'elem' / 'member') and still holds in
    # a register, a stack cell, an L2CValue temporary, the pushed Lua values or the flags was kept as an EXPRESSION and
    # printed where it was used: a fresh read, after whatever ran in between. Now, before every call / store, each such
    # read still held is taken into a variable of its own at this point (`L2CValue held1 = agent->global_table[22];`,
    # a 'snap' node; not printed when nothing uses it later). An ADDRESS of an element (what operator[] returned) is not a
    # read: it stays an address and is read where the original reads through it.
    HELD = 1000000

    def hold(self):
        memo = {}

        def fix(v):
            if not isinstance(v, tuple) or not v:
                return v
            if v[0] in ('elem', 'member'):
                if v not in memo:
                    i = self.HELD + self.held_n
                    self.held_n += 1
                    nd = {'kind': 'snap', 'args': [v], 'id': i}
                    self.allnodes[i] = nd
                    self.nodes.append(nd)
                    memo[v] = ('ref', i)
                return memo[v]
            if v[0] == 'elemptr':
                # the address of an element. Of an element of the agent's own table / of a held value: it stays an
                # address (read where the original reads through it); a key that was itself read from a table is held.
                # Of an element OF AN ELEMENT (table[a][b]): the call that follows may put another table into table[a],
                # and the original would still point into the old one, which a source expression cannot say: the
                # address is forgotten here, so a later use of it refuses the function instead of printing a re-read.
                if has_elem(v[1]):
                    return ('the address of an element of an element, held across a call',)
                key = fix(v[2])
                return v if key is v[2] else ('elemptr', v[1], key)
            if v[0] in ('ref', 'int', 'f', 'luaconst', 'arg', 'stk', 'sym', 'img', 'page', 'undef', 'agent', 'boma', 'L'):
                return v
            new = tuple(fix(x) for x in v[1:])
            return v if all(a is b for a, b in zip(new, v[1:])) else (v[0],) + new

        for k, v in list(self.reg.items()):
            w = fix(v)
            if w is not v:
                self.reg[k] = w
        for d in (self.lv, self.mem):
            for k, v in list(d.items()):
                w = fix(v)
                if w is not v:
                    d[k] = w
        if self.lua:
            self.lua = [fix(v) for v in self.lua]
        if self.flags and self.flags[0] == 'ccmp':       # S20
            self.flags = ('ccmp', fix(self.flags[1]), tuple(fix(v) for v in self.flags[2][:2]) + self.flags[2][2:], self.flags[3])
        elif self.flags:
            self.flags = tuple(fix(v) for v in self.flags)
        if self.ret_value is not None:
            self.ret_value = fix(self.ret_value)

    def drop_synth(self):
        cur = getattr(self, 'cur_synth', None)
        if not cur:
            return
        for k, v in list(self.reg.items()):
            if v[0] == 'stk' and v[1] in cur:
                self.reg[k] = UNDEF
        for k, v in list(self.mem.items()):
            if v[0] == 'stk' and v[1] in cur:
                del self.mem[k]
        for s in cur:
            self.lv.pop(s, None)
        self.cur_synth = set()

    def slot(self, v, what):
        if v[0] == 'stk' and is_synth(v[1]):
            self.fail('%s: write through a chosen pointer' % what)
        return A.Exec.slot(self, v, what)

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
        self.cur_synth = set()
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
            if len(P) > 1 and len(P) == len(b.preds):    # S18: a pointer chosen on the ways in (see SYNTH); not at a loop header
                for s in sorted(P[0].ptr_tok):
                    k = 'x%d' % ((SYNTH - s) // 0x100)
                    if k not in reg and all(s in q.ptr_tok for q in P[1:]):
                        lv[s] = ('var', s, ('phi', b.start))
                        reg[k] = ('stk', s)
                        self.cur_synth.add(s)
            self.reg, self.mem, self.lv = reg, mem, lv
            self.lua = list(P[0].exit_lua) if P[0].exit_lua is not None else None
            self.flags = P[0].exit_flags if len(P) == 1 and len(b.preds) == 1 else None
        for s in forced_lv.get(b.start, ()):
            if s in self.lv:
                self.lv[s] = ('var', s, ('phi', b.start))
        for k in getattr(self, 'forced_reg', {}).get(b.start, ()):       # S18: an integer register that changes around the loop (a counter)
            if self.reg[k][0] in INTLIKE:
                self.reg[k] = ('var', ('reg', k), ('phi', b.start))
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
            bit = imm(ops[1])
            if bit != 0:
                # S18: a test of one bit of an integer value. The top bit of the register read is the sign
                # (`tbnz w21, #31` after as_integer: "negative"); any other bit below 31 is `value & (1 << bit)`.
                # Only on values the comparisons take too (scalar: constants, conversions, integer results).
                wide = ops[0][0] == 'x'
                v = self.get(ops[0])
                # the C++ type of the value must hold the bit tested: as_integer() is int64_t, an integer variable
                # uint64_t; a constant of the game's table or the result of a function the SDK declares 32 / 64-bit
                # integer only for a 32-bit test (bits 0..31 of what the function left in x0)
                ok = v[0] == 'conv' and v[1] == 'as_integer'
                if not wide and (v[0] in ('luaconst', 'u32') or (v[0] == 'var' and isinstance(v[1], tuple))):
                    ok = True
                if not wide and v[0] == 'ref' and v[1] in self.allnodes:
                    nd = self.allnodes[v[1]]
                    ok = nd['kind'] == 'call' and ret_type(nd['sym']) in ('int32_t', 'uint32_t', 'int64_t', 'uint64_t')
                if not ok:
                    self.fail('bit test')
                if bit == (63 if wide else 31):
                    c = ('icmp', '<', v, ('int', 0), 'int64_t' if wide else 'int32_t')
                elif bit < 31:
                    c = ('icmp', '!=', ('ibin', '&', v, ('int', 1 << bit)), ('int', 0), 'uint64_t' if wide else 'uint32_t')
                else:
                    self.fail('bit test')
                return c if mn == 'tbnz' else ('not', c)
            v = ('bit', self.truth(self.get(ops[0])))
            return v if mn == 'tbnz' else ('not', v)
        if mn in ('cbz', 'cbnz'):
            v = ('nz', self.truth(self.get(ops[0])))
            return v if mn == 'cbnz' else ('not', v)
        cc = mn[2:]
        if not self.flags:
            self.fail('conditional branch %s without a comparison' % cc)
        if self.flags[0] == 'ccmp':                      # S20: see nzcv_holds
            _, p, inner, nzcv = self.flags
            if cc not in CC_INT:
                self.fail('condition %s after ccmp' % cc)
            self.flags = inner
            try:
                q = self.branch_cond(i)
            finally:
                self.flags = ('ccmp', p, inner, nzcv)
            return ('or', ('not', p), q) if self.nzcv_holds(cc, nzcv) else ('and', p, q)
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

    # S18: a value read through a pointer a game function returned (`bl PostureModule::pos; ldr s0, [x0]; ldr s0,
    # [x22, #4]`). The read is a node of its own (kind 'field'), written where the instruction stands, so it sees the
    # memory at the same moment as the original: `field<float>(r5, 4)`. Only plain `ldr` / `ldur` of an s, w or x
    # register, only through the result of a function the SDK declares as a raw 64-bit value or a pointer (or
    # through a 64-bit value read this way). Anything else on such a pointer stays refused.
    def raw_pointer(self, v):
        if v[0] != 'ref' or v[1] not in self.allnodes or self.mode == 'body':      # not in ACMD scripts: field<> is declared for status sources (status_local.h)
            return False
        nd = self.allnodes[v[1]]
        if nd['kind'] == 'field':
            return nd['ctype'] == 'uint64_t'
        if nd['kind'] != 'call' or nd.get('vret') or nd.get('xret'):
            return False
        path = mangle.parse(nd['sym'])[0]
        if (path[0] == 'lua2cpp' and mangle.is_member(path)) or mangle.is_static_value(path):
            return False
        if ret_type(nd['sym']) != 'uint64_t':
            return False
        rust = _rets[0].get(nd['sym'])
        return rust is None or rust in ('u64', 'usize') or rust.startswith('*')

    def add(self, base, off):
        if self.raw_pointer(base) or base[0] == 'vptr':
            return ('off', base, off) if off else base
        return A.Exec.add(self, base, off)

    def load(self, a, size, is_float):
        if a[0] == 'sym' and a[1] in ('_ZN2nn4util8Vector3f12ConstantZeroE', '_ZN2nn4util8Vector4f12ConstantZeroE'):
            # S20: `ldr q0, [nn::util::Vector3f::ConstantZero]`: the zero vector (main.elf keeps it in .bss), the same
            # value `movi v0.2d, #0` makes
            ins = getattr(self, 'cur_ins', None)
            if ins is not None and ins.mnemonic in ('ldr', 'ldur') and split_ops(ins.op_str)[0][:1] == 'q':
                return ('vec', ('f', 0.0), ('f', 0.0), ('f', 0.0), ('f', 0.0))
        if a[0] == 'ctabv':                              # S20: see addr_of
            if size != 4 or is_float:
                self.fail('load of the constant table at a variable place, not 32-bit')
            return ('luaconstv', a[1])
        if a[0] == 'stk':                                # S18: a lane of an output vector read back after the call (see Printer2.vecname)
            for k in range(4):
                rec = self.mem.get(a[1] - 4 * k)
                if rec is not None and rec[0] == 'vecout' and k < rec[3]:
                    ins = getattr(self, 'cur_ins', None)
                    tok = split_ops(ins.op_str)[0] if ins is not None else ''
                    if ins is None or ins.mnemonic not in ('ldr', 'ldur') or tok[:1] != 's' or rec[1] not in self.allnodes:
                        self.fail('read of an output vector that is not one float lane')
                    self.allnodes[rec[1]]['outread'] = True
                    return ('lane', ('outv', rec[1], rec[2]), k)
        base, off = (a[1], a[2]) if a[0] == 'off' else (a, 0)
        if base[0] == 'vptr' and base[1][1] in self.allnodes:
            # S20: the public bindings say this function returns a phx::Vector2f / 3f by value
            # (GroundModule::get_touch_pos, BattleObjectWorld::gravity_pos), but the game's code reads through x0: it
            # returns a POINTER. The call is then printed gcall<uint64_t>(...) (the content of x0) and the read is a
            # field<> of it like any pointer a game function returned; a lane of it read as a vector no longer compiles.
            nd = self.allnodes[base[1][1]]
            nd.pop('vret', None)
            nd['xret'] = 'uint64_t'
            base = base[1]
            ins = getattr(self, 'cur_ins', None)
            tok = split_ops(ins.op_str)[0] if ins is not None else ''
            if ins is None or ins.mnemonic not in ('ldr', 'ldur') or tok[:1] not in ('s', 'w', 'x') or off < 0:
                self.fail('load through the result of a function, not a plain one')
            ctype = 'float' if tok[0] == 's' else 'uint32_t' if tok[0] == 'w' else 'uint64_t'
            return ('ref', self.node(kind='field', args=[base], off=off, ctype=ctype))
        if self.raw_pointer(base):
            ins = getattr(self, 'cur_ins', None)
            tok = split_ops(ins.op_str)[0] if ins is not None else ''
            if ins is None or ins.mnemonic not in ('ldr', 'ldur') or tok[:1] not in ('s', 'w', 'x') or off < 0:
                self.fail('load through the result of a function, not a plain one')
            ctype = 'float' if tok[0] == 's' else 'uint32_t' if tok[0] == 'w' else 'uint64_t'
            return ('ref', self.node(kind='field', args=[base], off=off, ctype=ctype))
        return A.Exec.load(self, a, size, is_float)

    # S20: is v an integer VALUE (not a pointer) the source can compute with: constants, conversions, integer results,
    # integer variables and the integer expressions built from them
    def intval(self, v):
        if v[0] in ('int', 'luaconst', 'luaconstv', 'u32', 'ibin', 'ext', 'mvn') or (v[0] == 'luax' and len(v) == 3):      # (S21: luax)
            return True
        if v[0] == 'var':
            return isinstance(v[1], tuple)
        if v[0] == 'conv':
            return v[1] == 'as_integer'
        if v[0] == 'ref' and v[1] in self.allnodes:
            nd = self.allnodes[v[1]]
            if nd['kind'] == 'field':
                return nd['ctype'] != 'float'
            return (nd['kind'] == 'call' and not nd.get('vret') and not nd.get('fret')
                    and ret_type(nd['sym']) in ('int32_t', 'uint32_t', 'int64_t', 'uint64_t', 'bool'))
        return False

    def boolval(self, v):
        """S20: a value that is 0 or 1 in the register (a comparison, a bool conversion or result)"""
        if v[0] in ('cond', 'lvop', 'not', 'cmp'):
            return True
        if v[0] == 'conv':
            return v[1] in ('bool', 'as_bool')
        if v[0] == 'ref' and v[1] in self.allnodes:
            nd = self.allnodes[v[1]]
            return nd['kind'] == 'call' and not nd.get('fret') and ret_type(nd['sym']) == 'bool'
        return False

    # S20: the flags after `cmp a, b; ccmp c, d, #nzcv, cond`: when cond held on the first comparison, the flags of
    # c - d; otherwise the constant nzcv. A branch on them is (P && Q) || (!P && K), K the branch condition on nzcv.
    @staticmethod
    def nzcv_holds(cc, nzcv):
        n, z, c, v = (nzcv >> 3) & 1, (nzcv >> 2) & 1, (nzcv >> 1) & 1, nzcv & 1
        return {'eq': z, 'ne': not z, 'cs': c, 'hs': c, 'cc': not c, 'lo': not c, 'mi': n, 'pl': not n, 'vs': v, 'vc': not v,
                'hi': c and not z, 'ls': (not c) or z, 'ge': n == v, 'lt': n != v, 'gt': (not z) and n == v, 'le': z or n != v}[cc]

    def step_s20(self, ins):
        """S20: instructions the model did not take (each was a refusal reason): sign / zero extension, bitwise not,
        conditional compare, a 32-bit sum of two integer values, a byte store of a constant into the frame"""
        mn = ins.mnemonic
        ops = split_ops(ins.op_str)
        if mn in ('sxtb', 'sxth', 'sxtw', 'uxtb', 'uxth') and len(ops) == 2:
            v = self.get(ops[1])
            bits = {'b': 8, 'h': 16, 'w': 32}[mn[-1]]
            signed = mn[0] == 's'
            wide = ops[0][0] == 'x'
            if v[0] == 'int':
                x = v[1] & ((1 << bits) - 1)
                if signed and x >> (bits - 1):
                    x -= 1 << bits
                self.put(ops[0], ('int', x & (0xffffffffffffffff if wide else 0xffffffff)))
                return True
            if self.intval(v):
                # printed outer(inner(v)): int32_t(int8_t(get_x(...))) is what `sxtb w1, w0` leaves in w1
                self.put(ops[0], ('ext', ('int%d_t' if signed else 'uint%d_t') % bits, v,
                                  ('int64_t' if signed else 'uint64_t') if wide else ('int32_t' if signed else 'uint32_t')))
                return True
            self.fail('%s of %s' % (mn, v[0]))
        if mn == 'mvn' and len(ops) == 2:
            v = self.get(ops[1])
            wide = ops[0][0] == 'x'
            if v[0] == 'int':
                self.put(ops[0], ('int', ~v[1] & (0xffffffffffffffff if wide else 0xffffffff)))
                return True
            if self.intval(v) or self.boolval(v):
                self.put(ops[0], ('mvn', v, 'uint64_t' if wide else 'uint32_t'))     # (~uint32_t(x)): every bit, as the register
                return True
            self.fail('mvn of %s' % (v[0],))
        if mn == 'ccmp' and len(ops) == 4:
            if not self.flags or self.flags[0] == 'ccmp' or self.flags[2] == 'f' or not ops[2].startswith('#'):
                self.fail('ccmp without a plain integer comparison before')
            fake = type('I', (), {'mnemonic': 'b.' + ops[3], 'op_str': '#0'})
            p = self.branch_cond(fake)
            a = self.get(ops[0])
            b = ('int', imm(ops[1])) if ops[1].startswith('#') else self.get(ops[1])
            self.flags = ('ccmp', p, (self.scalar(a, 'compare'), self.scalar(b, 'compare'), ops[0][0]), imm(ops[2]))
            return True
        if mn in ('add', 'sub') and len(ops) == 3 and all(o[0] == 'w' and o in A.XREG and A.XREG[o] for o in ops):
            a, b = self.get(ops[1]), self.get(ops[2])
            if b[0] != 'int':                            # (b a constant: the old path, unchanged)
                if self.intval(a) and self.intval(b):
                    self.put(ops[0], ('u32', ('ibin', '+' if mn == 'add' else '-', a, b)))      # uint32_t(a + b): the 32-bit sum
                    return True
        if mn in ('strb', 'strh') and len(ops) == 2 and not ops[1].endswith('!'):
            a = self.addr_of(ops[1])
            v = self.get(ops[0])
            if a[0] == 'stk' and v[0] == 'int':          # a small argument passed on the stack (ninth and later)
                self.store(a, ('int', v[1] & (0xff if mn == 'strb' else 0xffff)))
                return True
            if a[0] == 'stk' and mn == 'strb' and self.boolval(v):
                self.store(a, v)
                return True
        return False

    def addr_of(self, memop):
        # S20: `ldr w1, [x21, x8]` with x21 the game's constant table and x8 an integer value (a byte offset chosen on
        # two paths): the constant at that place, lua_const_at(offset / 4)
        inner = memop.strip()
        if inner.startswith('[') and ']' in inner:
            parts = [p.strip() for p in inner[1:inner.index(']')].split(',')]
            if len(parts) == 2 and not parts[1].startswith('#') and parts[1] in A.XREG and A.XREG[parts[1]]:
                base, o = self.get(parts[0]), self.get(parts[1])
                if o[0] != 'int' and base[0] == 'sym' and 'const_value_table' in base[1] and self.intval(o):
                    return ('ctabv', o)
        return A.Exec.addr_of(self, memop)

    def step(self, ins):
        mn = ins.mnemonic
        self.cur_ins = ins
        if mn in ('sxtb', 'sxth', 'sxtw', 'uxtb', 'uxth', 'mvn', 'ccmp', 'add', 'sub', 'strb', 'strh') and self.step_s20(ins):
            return None
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
            if v[0] in ('var', 'cond', 'mvn', 'ext') or (v[0] == 'luax' and len(v) == 3):    # (S20: mvn, ext; S21: luax)
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
        if mn in ('add', 'sub'):
            # S18: 32-bit `constant of the game's table +- a number` (`ldr w8, [table, #off]; sub w1, w8, #1`:
            # FIGHTER_..._KIND_X - 1). The constant is an int32_t in the source, the sum an int32_t expression.
            # Only the 32-bit form with an immediate: anything else stays "pointer arithmetic".
            ops = split_ops(ins.op_str)
            if len(ops) == 3 and ops[0][0] == 'w' and ops[1][0] == 'w' and ops[2].startswith('#') and ops[1] in A.XREG and A.XREG[ops[1]]:
                a = self.reg[A.XREG[ops[1]]]
                if a[0] == 'luaconst':
                    self.put(ops[0], ('ibin', '+' if mn == 'add' else '-', a, ('int', imm(ops[2]))))
                    return None
                # the same on an integer variable (a loop counter: `add w27, w27, #1`). The variable is a uint64_t
                # whose low 32 bits are the register's; the 32-bit sum is written uint32_t(n + 1), which is what the
                # register holds (the upper half cleared).
                if (a[0] == 'var' and isinstance(a[1], tuple)) or a[0] == 'u32':
                    self.put(ops[0], ('u32', ('ibin', '+' if mn == 'add' else '-', a, ('int', imm(ops[2])))))
                    return None
                if a[0] == 'luax':                       # S21: the same on an integer a call left in x0 (read as 32 bits)
                    a = self.get(ops[1])
                    self.put(ops[0], ('u32', ('ibin', '+' if mn == 'add' else '-', a, ('int', imm(ops[2])))))
                    return None
        return A.Exec.step(self, ins)

    def get(self, tok):
        v = A.Exec.get(self, tok)
        if tok in A.VREG and v[0] == 'ref' and v[1] in self.allnodes:
            self.allnodes[v[1]]['fret'] = True          # the result is taken from the float register
        if v[0] == 'luax' and len(v) == 2 and tok in A.XREG:
            # S21: the integer a typed script call left in x0 (acmd_decomp.Exec.call_import), as wide as the register read
            v = ('luax', v[1], 'int32_t' if tok[0] == 'w' else 'int64_t')
        return v

    # S10: "x0 read after a float function". The game's own code sometimes reads the INTEGER register after a function
    # that returns a float (L2CValue(unsigned) of MotionModule::end_frame): what it gets is whatever the function left
    # in x0, not the float converted. After a call of a function the SDK declares float, x0 is ('x0of', ('ref', node));
    # when that value is copied into another register or stored (so: really used), the node is marked `xret` with the
    # width read, and the call is printed as gcall<uintNN_t>(slot, ...) = the content of x0, not through the wrapper.
    def mark_out_vectors(self, sym):
        """S18: after an ordinary imported call: a vector built on this frame and passed to a parameter that is a
        NON-const `phx::VectorNf &` / `*` (from the function's own mangled name) may have been written by the callee:
        the cell no longer holds the lanes that went in, it holds "output vector <argument> of this call"."""
        nd = self.nodes[-1] if self.nodes else None
        if nd is None or nd.get('kind') != 'call' or nd.get('sym') != sym or self.mode == 'body':
            return
        p = mangle.parse(sym)
        if not p or p[0][0] != 'app':
            return
        path, params = p[0], p[1]
        xi = ai = 1 if mangle.is_member(path) else 0
        for t in params:
            st = mangle.strip(t)
            if mangle.reg_class(t) == 'f':
                ai += 1
                continue
            reg, a = xi, ai
            xi += 1
            ai += 1
            inner = st[1] if isinstance(st, tuple) and st[0] in ('ref', 'ptr') else None
            if not (isinstance(inner, tuple) and inner[0] == 'class' and inner[1] in ('phx::Vector2f', 'phx::Vector3f', 'phx::Vector4f')):
                continue                                 # (a const vector has ('const', ...) here: the callee cannot write it)
            if a >= len(nd['args']) or nd['args'][a][0] != 'vecarg':
                continue
            v = self.reg['x%d' % reg] if 0 < reg < 8 else UNDEF
            if v[0] != 'stk' or self.mem.get(v[1], UNDEF)[0] != 'vec':
                self.fail('output vector whose place is not known after the call')
            self.mem[v[1]] = ('vecout', nd['id'], a, nd['args'][a][1])

    def call_import(self, sym):
        A.Exec.call_import(self, sym)
        self.mark_out_vectors(sym)
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
                self.reg['x0'] = ('vptr', v) if self.mode != 'body' else UNDEF      # S20: see load (was UNDEF)

    def put(self, tok, v):
        if v[0] == 'x0of' and tok not in ('x0', 'w0') and v[1][1] in self.allnodes:
            self.allnodes[v[1][1]]['xret'] = 'uint32_t' if tok[0] == 'w' else 'uint64_t'
        A.Exec.put(self, tok, v)

    def store(self, a, v):
        if v[0] == 'x0of' and v[1][1] in self.allnodes:
            self.allnodes[v[1][1]]['xret'] = 'uint64_t'
        A.Exec.store(self, a, v)

    def truth(self, v):
        if v[0] in ('conv', 'ref', 'lvop', 'not', 'cmp', 'cond', 'var', 'mvn', 'ext') or (v[0] == 'luax' and len(v) == 3):      # (S20: mvn, ext: printed as integers; S21: luax)
            return v
        self.fail('condition on %s' % (v[0],))

    def scalar(self, v, name):
        if v[0] in ('cond', 'var', 'u32', 'ext', 'mvn', 'luaconstv') or (v[0] == 'luax' and len(v) == 3):      # (S20: the last three; S21: luax)
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
        self.drop_synth()                                # S18: a chosen pointer does not leave the block it was made for
        b.exit_real = dict(self.lv)
        b.exit_tok = {}
        for s, v in self.lv.items():
            if self.stable(v) or (v[0] == 'var' and v[1] == s):
                b.exit_tok[s] = v
            else:
                b.exit_tok[s] = ('var', s, ('x', b.start))
        for k, v in self.reg.items():                   # integer registers holding a value (not a pointer): may become variables
            if k[0] == 'x' and k not in ('x29', 'x30') and v[0] in INTLIKE:      # S18: 'ibin' and 'u32' (sums) too
                s = ('reg', k)
                b.exit_real[s] = v
                b.exit_tok[s] = v if self.stable(v) or (v[0] == 'var' and v[1] == s) else ('var', s, ('x', b.start))
        b.ptr_tok = {}                                   # S18: what each pointer register points to here (see SYNTH); read only at merges
        for k, v in self.reg.items():
            if k[0] != 'x' or k in ('x29', 'x30', 'x8'):   # (x8 is where results are written: never a chosen pointer)
                continue
            if v[0] == 'arg' and len(v) == 2:
                e = v
            elif v[0] == 'stk' and v[1] in self.lv:
                e = self.lv[v[1]]
            elif v[0] == 'sym' and v[1] == '_ZN3lib8L2CValue3NILE':
                e = ('nil',)
            else:
                continue
            s = synth_slot(k)
            b.exit_real[s] = e
            b.ptr_tok[s] = e if self.stable(e) else ('var', s, ('x', b.start))
        b.exit_reg = {k: v for k, v in self.reg.items() if v != UNDEF and self.stable(v)}
        b.exit_mem = {k: v for k, v in self.mem.items() if self.stable(v)}
        b.exit_lua = list(self.lua) if self.lua is not None else None
        b.exit_flags = self.flags
        if b.exit_lua and any(has_var(v) for v in b.exit_lua):
            self.fail('variable pushed across a branch')

    def run(self):
        forced_lv = collections.defaultdict(set)
        forced_undef = collections.defaultdict(set)
        # S18: counted loops. An integer register whose value at the loop header differs from its value at the end of
        # a back edge used to become unknown inside the loop (so `add w27, w27, #1; cmp w27, w21; b.lt` was refused).
        # When it holds an integer value on the way in AND on every way back, it is a variable (uint64_t nK), set
        # before the loop and at the end of the block that changes it, like the L2CValue slots above.
        self.forced_reg = forced_reg = collections.defaultdict(set)
        for rounds in range(12):
            self.allnodes = {}
            self.counter = 0
            self.held_n = 0
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
                    s = ('reg', k)
                    if v == ('var', s, ('phi', h)):
                        if U.exit_tok.get(s) is None:    # not an integer value on this way back: not a variable after all
                            forced_reg[h].discard(k)
                            forced_undef[h].add(('r', k))
                            changed = True
                        continue
                    if v != UNDEF and U.exit_reg.get(k, UNDEF) != v:
                        if (k[0] == 'x' and k not in ('x29', 'x30') and v[0] in INTLIKE and U.exit_tok.get(s) is not None
                                and ('r', k) not in forced_undef[h]):
                            forced_reg[h].add(k)
                        else:
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
    def __init__(self, ex, compound=False):
        self.ex = ex
        B = ex.B
        # S18 (readability, OFF unless asked: fighter_status.py asks for the functions that are not in its list of
        # already-covered ones): compound conditions. A block that only tests a second condition and shares a target
        # with the block before it (`if (a) goto T; if (b) goto T; else F`) is one `if (a || b)` (or `&&`) instead of
        # nested ifs with a goto. Taken only when the second block has that one predecessor, sets no variable, and
        # everything it computes is used once, in order, inside its own condition (so it is evaluated exactly when and
        # in the order the original evaluates it: C++ short-circuit).
        self.fold = {}                                   # block -> (condition, (source, target if true), (source, target if false))
        self.absorbed = {}                               # folded block -> the block it is folded into
        self.folded = {}                                 # node id -> node, of the calls written inside a compound condition
        if compound:
            self.find_folds()
        rep = lambda a: self.absorbed.get(a, a)
        idom = {a: rep(d) for a, d in ex.idom.items()}
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
            if a in self.absorbed:
                continue
            d = idom[a]
            outer = None
            for h in self.headers:                        # outermost first
                if d in self.body[h] and a not in self.body[h]:
                    outer = h
                    break
            fwd = [p for p in B[a].preds if (p, a) not in ex.back]
            if self.absorbed:
                fwd = sorted(set(rep(p) for p in fwd))
            if outer is not None:
                self.after[outer].append(a)
                self.placed.add(a)
            elif len(fwd) >= 2:
                self.merge[d].append(a)
                self.placed.add(a)
        self.labels = set()
        self.gotos = 0

    def find_folds(self):
        ex = self.ex
        B = ex.B
        uses = collections.Counter()

        def count(v):
            if isinstance(v, tuple):
                if v and v[0] == 'ref':
                    uses[v[1]] += 1
                for x in v[1:]:
                    count(x)

        def refs(v, out):
            if isinstance(v, tuple):
                if v and v[0] == 'ref':
                    out.add(v[1])
                for x in v[1:]:
                    refs(x, out)
            return out

        for b in B.values():
            for nd in b.nodes:
                for a in nd.get('args', []):
                    count(a)
            for v in (b.cond, b.ret):
                if v is not None:
                    count(v)
            for s, e in b.assigns:
                count(e)
        headers = set(h for u, h in ex.back)

        def foldable(c, sources):
            cb = B[c]
            if cb.term[0] != 'cond' or cb.assigns or c in headers or len(cb.preds) != 1 or cb.preds[0] not in sources:
                return False
            nodes = [nd for nd in cb.nodes
                     if not (uses[nd['id']] == 0 and (nd['kind'] == 'field' or (nd['kind'] == 'snap' and nd['id'] >= FExec.HELD)))]
            for i, nd in enumerate(nodes):
                if uses[nd['id']] != 1 or nd.get('outread'):
                    return False
                nxt = tuple(nodes[i + 1].get('args', [])) if i + 1 < len(nodes) else (cb.cond,)
                if nd['id'] not in refs(('all',) + nxt, set()):
                    return False
            return True

        for x in ex.rpo:
            b = B[x]
            if x in self.absorbed or b.term[0] != 'cond' or b.assigns:
                continue
            cond, T, F, sT, sF, got = b.cond, b.term[2], b.term[3], x, x, []
            while True:
                if F != T and F not in self.absorbed and foldable(F, [sF]):
                    cb = B[F]
                    if cb.term[2] == T:
                        cond, nF = ('or', cond, cb.cond), cb.term[3]
                    elif cb.term[3] == T:
                        cond, nF = ('or', cond, ('not', cb.cond)), cb.term[2]
                    else:
                        nF = None
                    if nF is not None:
                        got.append(F)
                        sF, F = F, nF
                        continue
                if T != F and T not in self.absorbed and foldable(T, [sT]):
                    cb = B[T]
                    if cb.term[3] == F:
                        cond, nT = ('and', cond, cb.cond), cb.term[2]
                    elif cb.term[2] == F:
                        cond, nT = ('and', cond, ('not', cb.cond)), cb.term[3]
                    else:
                        nT = None
                    if nT is not None:
                        got.append(T)
                        sT, T = T, nT
                        continue
                break
            if got and T != F:
                self.fold[x] = (cond, (sT, T), (sF, F))
                for c in got:
                    self.absorbed[c] = x
                    for nd in B[c].nodes:                # its calls are written inside the condition, not as statements:
                        self.folded[nd['id']] = nd       # the printer must still count what THEY use (Printer2.count)

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
        elif x in self.fold:                             # S18: a compound condition (find_folds)
            cond, (st, tt), (sf, tf) = self.fold[x]
            yes = self.jump(st, tt, f0, loops)
            no = self.jump(sf, tf, f0, loops)
            out += self.make_if(cond, yes, no)
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
        # S18: in a fixed order. This was the iteration order of a set of tuples with strings (the per-process string
        # hash): the same input printed two independent assignments of one block in either order from run to run.
        for t in sorted(found, key=repr):
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
                if e is None and is_synth(s):            # S18: a chosen pointer: what it pointed to at the end of this predecessor
                    e = p.ptr_tok.get(s)
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
        self.outvecs = set()                             # S18: (node, argument, lanes) of named vectors (see vecname)
        self.addr_node = None

    def call_text(self, nd):
        if nd.get('outread'):                            # S18: output vectors: the vector arguments are passed by address (see vecname)
            self.addr_node = nd
            try:
                return self.call_text2(nd)
            finally:
                self.addr_node = None
        return self.call_text2(nd)

    def call_text2(self, nd):
        k = nd['kind']
        if k == 'lua' and (nd.get('iret') or nd.get('own_proto') or any('@' in p or ':' in p for p in nd.get('proto') or ())):
            # S21: a typed script call written with the conversions spelt out (status_local.h lua_ret): one that returns
            # an integer in x0, or one that takes a vector made of the pushed values (set_speed: '2' = Vector2f)
            if nd.get('vret') or nd.get('fret') or nd.get('popped'):
                raise NotMechanical('typed script call whose result is read in two ways')
            letters, pr = '', list(nd['proto'])
            while pr:
                p = pr.pop(0)
                if '@' in p:
                    lanes = int(p.split('@')[1])
                    letters += str(lanes)
                    del pr[:lanes - 1]
                else:
                    letters += {'as_integer': 'i', 'as_number': 'f', 'as_bool': 'b', 'as_hash': 'h', 'K:i': 'I', 'K:f': 'F'}[p]
            self.used_syms.add(nd['sym'])
            slot = 'S_' + re.sub(r'\W', '_', A.wrapper_name(nd['sym']))
            return 'lua_ret<%s>(%s)' % (nd.get('iret') or 'void', ', '.join(['agent', slot, '"%s"' % letters] + [self.expr(a) for a in nd['args']]))
        if k == 'lua' and nd.get('vret'):                # S20: a script call whose vector result (v0) is read: lua_vec (status_local.h)
            self.used_syms.add(nd['sym'])
            slot = 'S_' + re.sub(r'\W', '_', A.wrapper_name(nd['sym']))
            return 'lua_vec(%s)' % ', '.join(['agent', slot] + [self.expr(a) for a in nd['args']])
        if k == 'store':
            if nd['args'][0][0] == 'arg':                # S20: the function writes its argument (the caller's value), as the original does
                return 'const_cast<L2CValue &>(%s) = %s' % (self.expr(nd['args'][0]), self.value_text(nd['args'][1]))
            return '%s = %s' % (self.expr(nd['args'][0]), self.value_text(nd['args'][1]))
        if k == 'snap':
            return self.value_text(nd['args'][0])
        if (k == 'lua' and nd['sym'] in self.ex.m.autopop and self.uses[nd['id']] and not nd['proto'] and not nd.get('fret')
                and self.ex.mode != 'body'):
            # S18: a script call whose result every ACMD script drops (the SDK wrapper is `void`: it calls and pops),
            # but THIS status function uses what it popped. Written with the general form, which returns the popped
            # value: lua_result(agent, S_slot, args...) (status_local.h); the SDK wrapper is not changed.
            self.used_syms.add(nd['sym'])
            slot = 'S_' + re.sub(r'\W', '_', A.wrapper_name(nd['sym']))
            return 'lua_result(%s)' % ', '.join(['agent', slot] + [self.expr(a) for a in nd['args']])
        if k == 'lvlen':                                 # S21: status_decomp.MExec.call_import (L2CValue::length)
            self.used_syms.add('_ZNK3lib8L2CValue6lengthEv')
            t = 'fs_lv_length(%s)' % self.value_text(nd['args'][0])
            return '%s(%s)' % (nd['iret'], t) if nd.get('iret') else t
        if k == 'yield':                                 # S21: status_decomp.MExec.add (the agent's vtable, slot 2)
            return 'fs_coroutine_yield(agent)'
        if k == 'field':                                 # S18: a read through a pointer a game function returned
            return 'field<%s>(%s, %d)' % (nd['ctype'], self.expr(nd['args'][0]), nd['off'])
        if k == 'callptr':
            return 'call_function(%s)' % ', '.join(['agent'] + [self.expr(a) for a in nd['args']])
        if k == 'local':                                 # S8: a function of this module without an exported name
            first = [] if nd.get('plain') else ['agent']  # S18: a helper that takes no agent (status_decomp.call_local)
            return 'local::%s(%s)' % (self.ex.m.locals[nd['target']], ', '.join(first + [self.value_text(a) for a in nd['args']]))
        if nd.get('vret'):                               # S10: a vector result (its plain uses are printed as lane 0)
            return self.vret_text(nd)
        if nd.get('xret'):                               # S10: the content of x0 after a function that returns a float
            if nd.get('fret'):
                raise NotMechanical('result of a float function read from both the float and the integer register')
            self.used_syms.add(nd['sym'])
            slot = 'S_' + re.sub(r'\W', '_', A.wrapper_name(nd['sym']))
            return 'gcall<%s>(%s)' % (nd['xret'], ', '.join([slot] + [self.expr(a) for a in nd['args']]))
        if nd.get('fret'):
            # S18 (found by the offline gate: rockman_chargeshot_regular_main, GroundModule::get_width): the game's code
            # reads the FLOAT register after this call, but the public bindings declare an integer result and gen_sdk.py
            # follows them (the wrapper returns x0). `(float)r5` then converted the integer. Such a call is written
            # gcall<float>(slot, ...) = the content of the float register, as the x0 case above does the other way round.
            if k == 'call' and ret_type(nd['sym']) != 'float' and nd['sym'] in _rets[0]:
                self.used_syms.add(nd['sym'])
                slot = 'S_' + re.sub(r'\W', '_', A.wrapper_name(nd['sym']))
                return 'gcall<float>(%s)' % ', '.join([slot] + [self.expr(a) for a in nd['args']])
            self.ex.m.float_syms.add(nd['sym'])         # gen_sdk.py: this function's result is in the float register
        if nd.get('void'):
            self.ex.m.void_syms.add(nd['sym'])          # gen_sdk.py: called without a result buffer
        elif nd['kind'] == 'call':
            self.ex.m.value_syms.add(nd['sym'])
        return A.Printer.call_text(self, nd)

    def value_text(self, v):
        t = self.expr(v)
        return t if t.startswith('L2CValue(') or v[0] in ('var', 'ref', 'lvop', 'arg', 'row', 'str') else 'L2CValue(%s)' % t

    def node_type(self, nd):
        if nd['kind'] == 'field':
            return nd['ctype']
        if nd.get('vret'):
            return 'Vector4f'
        if nd.get('xret'):
            return nd['xret']
        if nd.get('fret'):
            return 'float'
        if nd.get('iret'):                               # S21
            return nd['iret']
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

    # S18: output vectors. A game function that takes `phx::Vector2f &` (NOT const: its own mangled name says so) writes
    # into the vector the caller built on its frame, and the caller reads the lanes back after the call. Such a call,
    # WHEN a lane is read back (node mark 'outread'), is written with named vectors passed by address:
    #     vec7_3 = Vector2f{(float)x, (float)y};  ...  r7 = GroundModule::ray_check_hit_pos_normal(boma, &vec7_1, &vec7_2, &vec7_3, &vec7_4, flag);
    # and a lane read back is vec7_3.v[0]. (Before, the cell kept the lanes that went IN: lane 0 read after the call
    # was printed as the input value, the other lanes were unknown = "cannot print undef".)
    def count(self, v):
        # S18: as A.Printer.count, and through the calls that are written inside a compound condition (Structurer.folded):
        # what such a call uses is used once more. (Without this a result computed before the `if` and used only by
        # those calls looked single-use and was written out again at each use: the call made two or three times.
        # Found by the offline gate: szerosuit_special_lw_step_init_status.)
        if not isinstance(v, tuple):
            return
        if v[0] == 'luax' and len(v) == 3:               # S21: this script call's x0 is used: written lua_ret<type>(...)
            nd = self.nodes[v[1][1]]
            if nd.get('iret', v[2]) != v[2]:
                raise NotMechanical('integer result of a script call read at two widths')
            nd['iret'] = v[2]
        if v[0] == 'ref':
            self.uses[v[1]] += 1
            nd = getattr(self.ex, 'folded', {}).get(v[1])
            if nd is not None:
                for a in nd.get('args', []):
                    self.count(a)
        for x in v[1:]:
            self.count(x)

    @staticmethod
    def vecname(i, ai):
        return 'vec%d_%d' % (i, ai)

    def out_lines(self, nd, ind):
        """the statements that build the named vectors of a call with output vectors (before the call)"""
        if not nd.get('outread'):
            return []
        out = []
        for ai, a in enumerate(nd['args']):
            if a[0] == 'vecarg':
                self.outvecs.add((nd['id'], ai, a[1]))
                out.append(ind + '%s = %s;' % (self.vecname(nd['id'], ai), A.Printer.expr(self, a)))
        return out

    def expr(self, v, want=None):
        k = v[0]
        if k == 'vecarg' and getattr(self, 'addr_node', None) is not None:
            nd = self.addr_node
            return '&' + self.vecname(nd['id'], next(i for i, a in enumerate(nd['args']) if a is v))
        if k == 'outv':
            return self.vecname(v[1], v[2])
        if k == 'var':
            return self.varnames[v[1]]
        if k == 'member':
            return 'agent->%s' % MEMBERS[v[1]] if v[1] in MEMBERS else 'agent_value(agent, 0x%x)' % v[1]      # S19: see status_decomp.MExec.lvalue
        if k == 'elem':
            key = self.expr(v[2])
            if v[2][0] == 'int' and v[2][1] in GLOBALS and v[1] == ('member', 0xc8):
                key = GLOBALS[v[2][1]]
            return '%s[%s]' % (self.expr(v[1]), key)
        if k == 'arg':                                   # S18: [0] when the argument is a row of values (status_decomp.MExec.lvalue)
            return 'a%d%s' % (v[1], '[0]' if v[1] in getattr(self.ex, 'agg', {}) else '')
        if k == 'argel':
            return 'a%d[%d]' % (v[1], v[2])
        if k == 'row':                                   # S18: the caller's side of a row argument
            return 'row(%s)' % ', '.join(self.value_text(x) for x in v[1:])
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
        if k == 'u32':                                   # S18: a 32-bit sum on an integer variable
            t = self.expr(v[1])
            return 'uint32_t%s' % (t if t.startswith('(') and t.endswith(')') else '(%s)' % t)
        if k == 'ext':                                   # S20: sign / zero extension (FExec.step_s20)
            return '%s(%s(%s))' % (v[3], v[1], self.expr(v[2]))
        if k == 'mvn':                                   # S20: bitwise not of the whole register
            return '(~%s(%s))' % (v[2], self.expr(v[1]))
        if k == 'gval':                                  # S20: see status_decomp.MExec.lvalue
            self.used_syms.add(v[1])
            return 'fs_gvalue(S_gvalue_%s)' % mangle.gvalue_name(v[1])
        if k == 'luaconstv':                             # S20: the game's constant at a byte offset held in a value
            return 'lua_const_at(int32_t(uint32_t(%s) >> 2))' % self.expr(v[1])
        if k == 'luax':                                  # S21: see FExec.get; the call itself is lua_ret<...> (call_text2)
            if len(v) != 3 or self.nodes[v[1][1]].get('iret') != v[2]:
                raise NotMechanical('integer result of a script call, not marked')
            return self.expr(v[1])
        if k == 'str':                                   # S21: see status_decomp.MExec.call_import (L2CValue(char const*))
            self.used_syms.update(STR_SYMS)
            return 'L2CString(%s)' % c_string(self.ex.n.cstr(v[1]))
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
        if k in ('or', 'and'):                           # S18: compound condition; the negation goes inside (De Morgan)
            def par(t):
                depth = 0
                for i, ch in enumerate(t):
                    depth += ch == '('
                    depth -= ch == ')'
                    if depth == 0 and i < len(t) - 1:
                        return '(%s)' % t if ' ' in t else t
                return t
            op = '||' if (k == 'or') != neg else '&&'
            return '%s %s %s' % (par(self.cond(c[1], neg)), op, par(self.cond(c[2], neg)))
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
            c = st[1]
            # S18: of a compound condition only the part that is always evaluated, and first (the leftmost test): a
            # result computed before the `if` must not be written into a part that `||` / `&&` may skip
            while c[0] in ('or', 'and', 'not'):
                c = c[1]
            return self.refs(c, [])
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
                if u == 0 and nd['kind'] in ('snap', 'field'):
                    continue
                if u == 0:
                    tail = '.pop();' if nd['kind'] == 'lua' and nd.get('popped') and not auto else ';'
                    lines += self.out_lines(nd, ind)
                    lines.append(ind + self.call_text(nd) + tail)
                else:
                    m = n + 1                            # S18: (a held read / field read nothing uses is not printed: it is not "the next statement")
                    while (m < len(stmts) and stmts[m][0] == 'node' and self.uses[stmts[m][1]['id']] == 0
                           and (stmts[m][1]['kind'] == 'field' or (stmts[m][1]['kind'] == 'snap' and stmts[m][1]['id'] >= FExec.HELD))):
                        m += 1
                    nxt = stmts[m] if m < len(stmts) else None
                    if (nxt is not None and u == 1 and nxt[0] in ('node', 'if', 'eval', 'return') and i in self.stmt_refs(nxt)
                            and not nd.get('outread')):
                        continue                        # written inside the next statement
                    self.named[i] = rname(i)
                    self.def_scope[i] = id(stmts)
                    lines += self.out_lines(nd, ind)
                    text = self.call_text(nd)
                    if i in self.hoist or self.all_hoisted:
                        self.hoist.add(i)
                        lines.append(ind + '%s = %s;' % (rname(i), text))
                    else:
                        lines.append(ind + '%s %s = %s;' % ('L2CValue' if self.node_type(nd) == 'L2CValue' else 'auto', rname(i), text))
            elif k == 'assign':
                if has_kind(st[2], 'str'):
                    # S21: a variable would keep a plain copy of a string value whose L2CString dies at the end of the
                    # statement (the SDK's L2CValue copies by bits): refused, not printed
                    raise NotMechanical('string value kept in a variable')
                if st[2][0] == 'int' and st[2][1] >> 32 and isinstance(st[1], tuple):
                    lines.append(ind + '%s = 0x%xULL;' % (self.varnames[st[1]], st[2][1]))       # S15: a 64-bit constant (hash40 with its length byte) is not cut to 32 bits
                else:
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
                    if has_kind(st[1], 'str'):           # S21: see 'assign'
                        raise NotMechanical('string value returned')
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
            head.append('    %s %s;' % (self.node_type(self.nodes[i]), rname(i)))
        for i, ai, n in sorted(self.outvecs):            # S18: the named vectors of calls with output vectors
            head.append('    Vector%df %s;' % (n, self.vecname(i, ai)))
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
