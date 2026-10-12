"""Differential test of the lifter against the Unicorn AArch64 emulator.

For every instruction shape found in the game binary, a few real instruction
words are executed twice from the same random machine state: once by Unicorn
(reference) and once by the C code recomp.py generates. Final registers, flags
and memory must be identical.

    python difftest.py sample     collect sample instructions from the binary -> difftest_samples.json
    python difftest.py gen        generate difftest_gen.c from the samples
    python difftest.py check      run difftest.exe and Unicorn, compare

difftest.exe is difftest_gen.c + difftest_host.c compiled with the flags of the build under test, e.g.
    C:\\llvm-8.0.0\\bin\\clang.exe -O0 -w -fno-strict-aliasing -I . difftest_gen.c difftest_host.c -o difftest.exe
(DIFFTEST_EXE=<path> selects another exe for `check`; DIFFTEST_NO_SPECIAL=1 makes `gen` write only the old list.)
"""
import collections
import json
import os
import re
import struct
import subprocess
import sys
import zlib

import recomp

REGION, REGION_SIZE = 0x7200000000, 0x400000
CODE, DATA = REGION + 0x200000, REGION + 0x300000
WIN_LO, WIN_HI = DATA - 0x1000, DATA + 0x12000
M64 = (1 << 64) - 1
PER_SHAPE = 3
HOST_EXE = os.environ.get('DIFFTEST_EXE') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'difftest.exe')


class Rng:
    def __init__(self, seed):
        self.s = (seed * 0x9E3779B97F4A7C15 + 0x1234567) & M64

    def next(self):
        self.s = (self.s + 0x9E3779B97F4A7C15) & M64
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & M64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & M64
        return z ^ (z >> 31)


def pattern():
    r = Rng(0xABCDEF)
    return b''.join(struct.pack('<Q', r.next()) for _ in range(REGION_SIZE // 8))


def initial_state(idx, mem, rn, rm):
    r = Rng(idx)
    x = [r.next() for _ in range(31)] + [DATA + 0x800]
    v = []
    for _ in range(32):
        lanes = [(r.next() % 200001 - 100000) / 64.0 for _ in range(4)]
        v.append(struct.pack('<4f', *lanes))
    flags = r.next() & 0xf
    if mem:
        base = DATA + 0x100 * (r.next() % 8)
        index = r.next() % 0x40
        if rn != 31:
            x[rn] = base
        if 0 <= rm < 31 and rm != rn:
            x[rm] = index
    return x, v, flags


# ---- floating-point special operands (added for the FMAX/FMIN and FCVT-half fixes) ----------------------------------
# Random states never contain a NaN, a signed zero, a subnormal or a half-precision rounding tie, so the instructions
# below are also run from states built out of these tables: operand registers get every pair (two-operand instructions)
# or every value (one-operand ones). The first tests of the list are the old random-state tests, in the old order.
SPECIAL = {32: [0x00000000, 0x80000000, 0x3f800000, 0xbf800000, 0x40200000, 0xc0200000, 0x7f800000, 0xff800000, 0x7fc00000, 0xffc00000, 0x7fc12345, 0x7f800001, 0xffa00000, 0x00000001, 0x007fffff, 0x80000400, 0x00800000, 0x7f7fffff, 0x477fe000, 0x477ff000, 0x477fefff, 0x33800000, 0x33000000, 0x33000001, 0x38800000, 0x387fffff, 0x3f801000, 0x3f803000, 0x3f801001],
           64: [0x0000000000000000, 0x8000000000000000, 0x3ff0000000000000, 0xbff0000000000000, 0x4004000000000000, 0xc004000000000000, 0x7ff0000000000000, 0xfff0000000000000, 0x7ff8000000000000, 0xfff8000000000000, 0x7ff8000000012345, 0x7ff0000000000001, 0xfff4000000000000, 0x0000000000000001, 0x000fffffffffffff, 0x8000000000000400, 0x0010000000000000, 0x7fefffffffffffff, 0x40effc0000000000, 0x40effe0000000000, 0x40effdffffffffff, 0x3e70000000000000, 0x3e60000000000000, 0x3e60000000000001, 0x3f10000000000000, 0x3f0fffffffffffff, 0x3ff0020000000000, 0x3ff0060000000000, 0x3ff0020000001000],
           16: [0x0000, 0x8000, 0x3c00, 0xbc00, 0x7c00, 0xfc00, 0x7e00, 0xfe00, 0x7e01, 0x7c01, 0xfd55, 0x0001, 0x03ff, 0x8200, 0x0400, 0x7bff, 0x3555, 0xc123]}
FP_SPECIAL_MNEMONICS = ('fmax', 'fmin', 'fmaxnm', 'fminnm', 'fcvt')
if os.environ.get('DIFFTEST_FP_ALL'):                    # close5: NaN operand selection of every arithmetic instruction (measures the row 'NaN propagation')
    FP_SPECIAL_MNEMONICS += ('fadd', 'fsub', 'fmul', 'fdiv', 'fnmul', 'fmadd', 'fmsub', 'fnmadd', 'fnmsub', 'fsqrt', 'fabd', 'faddp', 'fmulx', 'fmla', 'fmls',
                             'frinta', 'frinti', 'frintm', 'frintn', 'frintp', 'frintx', 'frintz', 'fmaxp', 'fminp', 'fmaxnmp', 'fminnmp', 'frecpe', 'frsqrte', 'fneg', 'fabs')
# Encodings the game does not contain but the lifter translates (other directions / widths of the same instructions).
FP_EXTRA_WORDS = [0x1e63c020, 0x1ee24020, 0x1ee2c020, 0x1e624820, 0x1e627820, 0x1e625820, 0x1e626820,
                  0x4e22c420, 0x4ea2c420, 0x4e62f420, 0x4ee2f420, 0x4e62c420, 0x4ee2c420, 0x0e22f420, 0x0ea2f420]


def fp_mode(w):
    """Width of the source operands of a floating-point instruction word: 16, 32 or 64."""
    if recomp.bits(w, 28, 24) == 0x1e:                     # scalar
        return {0: 32, 1: 64, 3: 16}.get(recomp.bits(w, 23, 22), 0)
    return 64 if recomp.bits(w, 22, 22) else 32            # vector three-same


def special_v(t):
    """The 32 vector registers of special test t: lane l of register r holds table[(base + 7 * l) % n]."""
    mode, k = t['fpmode'], t['k']
    table = SPECIAL[mode]
    n = len(table)
    ia, ib = k % n, (k // n) % n
    v = []
    for r in range(32):
        b = ib if r == t['frm'] else ia if r == t['rn'] else (k + r) % n
        lanes = [table[(b + 7 * l) % n] for l in range(128 // mode)]
        v.append(b''.join(x.to_bytes(mode // 8, 'little') for x in lanes))
    return v


def build_special(env_fn, old):
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    words = [(t['key'], t['word']) for t in old if t['key'].split()[0] in FP_SPECIAL_MNEMONICS]
    shapes = json.load(open('difftest_samples.json'))
    for key, ws in sorted(shapes.items()):                 # words the old lifter could not translate (fcvt h, s)
        if key.split()[0] in FP_SPECIAL_MNEMONICS:
            words += [(key, w) for w in ws if (key, w) not in words]
    for w in FP_EXTRA_WORDS:
        ins = list(md.disasm(struct.pack('<I', w), CODE))
        words.append(('(not in the game) %s %s' % (ins[0].mnemonic, ins[0].op_str), w))
    tests = []
    for key, w in words:
        try:
            stmt = env_fn.lift(w, CODE)
        except recomp.Unimpl:                              # counted as different: the host does nothing
            stmt = 'guest_unimpl(0, 0, "untranslated");'
        mode = fp_mode(w)
        if mode not in SPECIAL: continue                   # close5: not a floating-point operand width (DIFFTEST_FP_ALL)
        unary = key.split()[0] == 'fcvt' or 'fcvt' in key
        n = len(SPECIAL[mode])
        for k in range(n if unary else n * n):
            tests.append({'key': key + ' [special]', 'word': w, 'stmt': stmt, 'mem': 0, 'rn': recomp.bits(w, 9, 5), 'rm': -1,
                          'fpmode': mode, 'k': k, 'frm': -1 if unary else recomp.bits(w, 20, 16)})
    return tests


def cmd_sample():
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    text = recomp.IMG[recomp.FILE_OFF:recomp.FILE_OFF + recomp.TEXT_SIZE]
    seen = set()
    shapes = collections.defaultdict(list)
    for (w,) in struct.iter_unpack('<I', text):
        if w in seen:
            continue
        seen.add(w)
        ins = list(md.disasm(struct.pack('<I', w), CODE))
        if not ins:
            continue
        shape = re.sub(r'#-?(0x)?[0-9a-f.e+-]+', '#', ins[0].op_str)
        shape = re.sub(r'\b([vqdshbwx])\d+\b', r'\1', shape)
        key = ins[0].mnemonic + ' ' + shape
        if len(shapes[key]) < PER_SHAPE:
            shapes[key].append(w)
    json.dump(shapes, open('difftest_samples.json', 'w'))
    print('shapes:', len(shapes), ' sample words:', sum(len(v) for v in shapes.values()))


def build_tests():
    shapes = json.load(open('difftest_samples.json'))
    env = recomp.Env()
    env.imports = set()
    fn = recomp.Fn(CODE, CODE + 4, env)
    tests = []
    for key, words in sorted(shapes.items()):
        for w in words:
            op0 = recomp.bits(w, 28, 25)
            if op0 in (10, 11):
                continue                                  # branches / system: not straight-line
            mem = op0 in (4, 6, 12, 14)
            if mem and recomp.bits(w, 29, 24) == 8 and not recomp.bits(w, 26, 26):
                continue                                  # exclusives: single-thread model differs by design
            try:
                stmt = fn.lift(w, CODE)
            except recomp.Unimpl:
                continue
            if any(t in stmt for t in ('goto', 'return', 'call_indirect', 'guest_', 'f_7')):
                continue
            rn = recomp.bits(w, 9, 5)
            rm = -1
            if mem and recomp.bits(w, 29, 27) == 7 and recomp.bits(w, 24, 24) == 0 and recomp.bits(w, 21, 21) and recomp.bits(w, 11, 10) == 2:
                rm = recomp.bits(w, 20, 16)
            tests.append({'key': key, 'word': w, 'stmt': stmt, 'mem': int(mem), 'rn': rn, 'rm': rm, 'fpmode': 0, 'k': 0, 'frm': -1})
    if os.environ.get('DIFFTEST_NO_SPECIAL'):              # the old list only (3,120 tests before the FP fixes)
        return tests
    return tests + build_special(fn, tests)


def cmd_gen():
    tests = build_tests()
    with open('difftest_gen.c', 'w') as f:
        f.write('#include "runtime.h"\n\n')
        for i, t in enumerate(tests):
            f.write('static void t_%d(Ctx *c) { %s }\n' % (i, t['stmt']))
        f.write('\ntypedef struct { void (*fn)(Ctx *); uint32_t word; int mem, rn, rm, fpmode, k, frm; } Test;\n')
        f.write('const Test tests[] = {\n')
        for i, t in enumerate(tests):
            f.write('  { t_%d, 0x%08xU, %d, %d, %d, %d, %d, %d },\n' % (i, t['word'], t['mem'], t['rn'], t['rm'], t['fpmode'], t['k'], t['frm']))
        f.write('};\nconst int test_count = %d;\n' % len(tests))
    json.dump(tests, open('difftest_tests.json', 'w'))
    print('tests generated: %d (random state: %d, floating-point special operands: %d)'
          % (len(tests), sum(1 for t in tests if not t['fpmode']), sum(1 for t in tests if t['fpmode'])))


def cmd_check():
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UcError
    from unicorn import arm64_const as A
    tests = json.load(open('difftest_tests.json'))
    out = subprocess.run([HOST_EXE], capture_output=True, text=True).stdout.split('\n')
    host = {}
    for line in out:
        p = line.split()
        if len(p) == 3:
            host[int(p[0])] = (int(p[1], 16), int(p[2], 16))
    pat = pattern()
    window = pat[WIN_LO - REGION:WIN_HI - REGION]
    uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    uc.mem_map(REGION, REGION_SIZE)
    uc.mem_write(REGION, pat)
    uc.reg_write(A.UC_ARM64_REG_CPACR_EL1, 0x300000)
    xr = [getattr(A, 'UC_ARM64_REG_X%d' % i) for i in range(29)] + [A.UC_ARM64_REG_X29, A.UC_ARM64_REG_X30]
    vr = [getattr(A, 'UC_ARM64_REG_V%d' % i) for i in range(32)]
    bad = collections.defaultdict(list)
    ok = errors = ok_special = 0
    for i, t in enumerate(tests):
        x, v, flags = initial_state(i, t['mem'], t['rn'], t['rm'])
        if t.get('fpmode'):
            v = special_v(t)
        for r, val in zip(xr, x[:31]):
            uc.reg_write(r, val)
        uc.reg_write(A.UC_ARM64_REG_SP, x[31])
        for r, val in zip(vr, v):
            uc.reg_write(r, int.from_bytes(val, 'little'))
        uc.reg_write(A.UC_ARM64_REG_NZCV, flags << 28)
        uc.mem_write(WIN_LO, window)
        uc.mem_write(CODE, struct.pack('<I', t['word']))
        try:
            uc.emu_start(CODE, CODE + 4, count=1)
        except UcError as e:
            errors += 1
            bad['(reference emulator fault: %s) %s' % (e, t['key'])].append(i)
            continue
        regs = b''.join(struct.pack('<Q', uc.reg_read(r)) for r in xr) + struct.pack('<Q', uc.reg_read(A.UC_ARM64_REG_SP))
        regs += b''.join(uc.reg_read(r).to_bytes(16, 'little') for r in vr)
        regs += struct.pack('<I', (uc.reg_read(A.UC_ARM64_REG_NZCV) >> 28) & 0xf)
        ref = (zlib.crc32(regs), zlib.crc32(bytes(uc.mem_read(WIN_LO, WIN_HI - WIN_LO))))
        if host.get(i) == ref:
            ok += 1
            ok_special += 1 if t.get('fpmode') else 0
        else:
            bad[t['key']].append(i)
    n_special = sum(1 for t in tests if t.get('fpmode'))
    print('tests: %d   identical: %d   different: %d   (reference faults: %d)' % (len(tests), ok, len(tests) - ok, errors))
    print('  random-state tests: %d identical of %d   floating-point special-operand tests: %d identical of %d'
          % (ok - ok_special, len(tests) - n_special, ok_special, n_special))
    for key, idxs in sorted(bad.items(), key=lambda kv: -len(kv[1]))[:60]:
        t = tests[idxs[0]]
        print('  %-52s %d   e.g. #%d %08x' % (key[:52], len(idxs), idxs[0], t['word']))
    json.dump({k: v for k, v in bad.items()}, open('difftest_bad.json', 'w'))


def cmd_show(idx):
    """Print reference vs host state for one test (host state via `difftest.exe <idx>`)."""
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
    from unicorn import arm64_const as A
    tests = json.load(open('difftest_tests.json'))
    t = tests[idx]
    print('#%d %08x %s\n  %s' % (idx, t['word'], t['key'], t['stmt']))
    pat = pattern()
    uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    uc.mem_map(REGION, REGION_SIZE)
    uc.mem_write(REGION, pat)
    uc.reg_write(A.UC_ARM64_REG_CPACR_EL1, 0x300000)
    xr = [getattr(A, 'UC_ARM64_REG_X%d' % i) for i in range(29)] + [A.UC_ARM64_REG_X29, A.UC_ARM64_REG_X30]
    vr = [getattr(A, 'UC_ARM64_REG_V%d' % i) for i in range(32)]
    x, v, flags = initial_state(idx, t['mem'], t['rn'], t['rm'])
    if t.get('fpmode'):
        v = special_v(t)
    for r, val in zip(xr, x[:31]):
        uc.reg_write(r, val)
    uc.reg_write(A.UC_ARM64_REG_SP, x[31])
    for r, val in zip(vr, v):
        uc.reg_write(r, int.from_bytes(val, 'little'))
    uc.reg_write(A.UC_ARM64_REG_NZCV, flags << 28)
    uc.mem_write(CODE, struct.pack('<I', t['word']))
    uc.emu_start(CODE, CODE + 4, count=1)
    ref = {}
    for i, r in enumerate(xr):
        ref['x%d' % i] = uc.reg_read(r)
    ref['sp'] = uc.reg_read(A.UC_ARM64_REG_SP)
    for i, r in enumerate(vr):
        ref['v%d' % i] = uc.reg_read(r)
    ref['nzcv'] = (uc.reg_read(A.UC_ARM64_REG_NZCV) >> 28) & 0xf
    host = {}
    for line in subprocess.run([HOST_EXE, str(idx)], capture_output=True, text=True).stdout.split('\n'):
        p = line.split()
        if len(p) == 2:
            host[p[0]] = int(p[1], 16)
    init = {('x%d' % i): x[i] for i in range(31)}
    init['sp'] = x[31]
    init.update({('v%d' % i): int.from_bytes(v[i], 'little') for i in range(32)})
    init['nzcv'] = flags
    for k in ref:
        if ref[k] != host.get(k):
            print('  %-5s init %x\n        ref  %x\n        host %x' % (k, init[k], ref[k], host.get(k, -1)))


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'sample':
        cmd_sample()
    elif cmd == 'gen':
        cmd_gen()
    elif cmd == 'check':
        cmd_check()
    else:
        cmd_show(int(sys.argv[2]))
