"""Finds every code site of main (13.0.4) that fixes the number of fighter kinds of the PARAMETER SINGLETON
(*(0x71052bb3b0), plan\\phases\\N3_new_kind.md) and writes the lifter patch list patches\\kinds.txt.

    python patches\\kinds_scan.py [NK]            NK = new number of kinds, default 0x72 (the most that fits, see below)

Layout of the object, original -> ours (NK kinds):
    +0x0000  0x60 bytes of members                                   unchanged
    +0x0060  array A, 0x5E rows of 0x38 bytes, ends at +0x14f0   ->  NK rows, ends at 0x60 + NK * 0x38 (<= 0x1958: NK <= 0x72)
    +0x14f0  array B, 0x5E rows of 0xc bytes (three row indexes) ->  moved to +0x19a8 (behind everything), NK rows
    +0x1958  0x50 bytes of members (accessed with constant offsets from many functions)    NOT moved
    size 0x19a8                                                  ->  0x19a8 + NK * 0xc
So only array B moves: its accesses are recognisable (32-bit loads / stores at +0x14f0.. from a base computed with
the stride 0xc, or at a constant row from the singleton pointer); array A grows in place over the old place of B.

A patch line is `<address> <old word> <new word>   # what`: one AArch64 instruction replaced by another of the same
form with a changed immediate. The lifter (recomp.py, RECOMP_PATCHES=<file>) lifts the new word in place of the old.
Sites found (the classes are printed; anything not recognised is printed and NOT patched):
  bound   cmp wN, #0x5e followed by b.hs/b.hi to an abort call (or b.lo over one): 0x5e -> NK
  B       32-bit load/store at +0x14f0 / +0x14f4 / +0x14f8 whose base register comes from a multiply-add: +0x4b8
  Bconst  load/store at +0x14f0..+0x1957 whose base register is the singleton pointer itself (constant kind): +0x4b8
  ctor    0x710066ee40: allocation size (3), the loop that builds the rows of A (start, 12 stores), the zero fill
  Aend    `mov w8, #0x14f0` = end of A in the destructor 0x7100709a80, the loader 0x7100709d60 and 0x710070c340
NOT patched on purpose: the loader's loop over the 94 kind hashes (0x710070a548: the mod fills the rows of new
kinds), the two other loops over all kinds (0x7100331db8, 0x71014f2510), the 30 switches on the kind.
No game content in this file: addresses and instruction words are read from the owner's own binary when it runs.
"""
import bisect
import os
import re
import struct
import sys

import capstone
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
BASE, FILE_OFF, TEXT = 0x7100000000, 0x1000, 0x39c7e90
SING = 0x71052bb3b0
ABORT = 0x71039c20a0
OLD_B, NEW_B, OLD_SIZE = 0x14f0, 0x19a8, 0x19a8
CTOR, DTOR, LOADER, CLEAR = 0x710066ee40, 0x7100709a80, 0x7100709d60, 0x710070c340


def main():
    nk = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x72
    a_end = 0x60 + nk * 0x38
    if not 0x5e <= nk <= 0x72 or nk % 2:
        sys.exit('NK must be even and 0x5e..0x72 (array A may not reach the members at +0x1958; the constructor builds two rows per turn)')
    img = open(os.path.join(STUDY, '..', 'binaries', '13.0.4', 'main.elf'), 'rb').read()
    W = np.frombuffer(img, dtype='<u4', count=TEXT // 4, offset=FILE_OFF)
    starts = sorted(int(m, 16) for m in re.findall(r'void f_([0-9a-f]+)\(', open(os.path.join(STUDY, 'gen_eh_o2', 'funcs.h')).read()))
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)

    def word(a): return int(W[(a - BASE) // 4])
    def fn_of(a): return starts[bisect.bisect_right(starts, a) - 1]
    def addrs(mask, val): return [BASE + 4 * int(i) for i in np.nonzero((W & mask) == val)[0]]
    def dis(a):
        for i in md.disasm(img[FILE_OFF + a - BASE: FILE_OFF + a - BASE + 4], a):
            return '%s %s' % (i.mnemonic, i.op_str)
        return '?'
    patches, notes = {}, []
    def patch(a, new, what):
        old = word(a)
        if a in patches and patches[a][1] != new:
            sys.exit('conflicting patches at %x' % a)
        patches[a] = (old, new, what)
    def set_imm12(w, v): return (w & ~(0xfff << 10)) | (v << 10)
    def set_imm16(w, v): return (w & ~(0xffff << 5)) | (v << 5)
    def ls_off(w): return ((w >> 10) & 0xfff) << (w >> 30)
    def ls_with(w, off):
        size = w >> 30
        if off % (1 << size) or off >> size > 0xfff: sys.exit('offset %x not encodable' % off)
        return set_imm12(w, off >> size)
    def is_ls(w): return (w & 0x3b000000) == 0x39000000                 # load/store, unsigned scaled offset (integer and fp)
    def base_def(a, reg, depth=60):
        """address of the instruction that last wrote X<reg> before a (linear walk back inside the function), following plain moves"""
        f = fn_of(a)
        for _ in range(4):
            p = a - 4
            found = None
            while p >= f and (a - p) // 4 <= depth:
                w = word(p)
                rd = w & 31
                writes = False
                if is_ls(w) and (w >> 22) & 3 != 0: writes = rd == reg and not (w >> 26) & 1                      # ldr (integer)
                elif (w & 0x1f000000) in (0x11000000, 0x12000000, 0x13000000, 0x0a000000, 0x0b000000, 0x1b000000, 0x1a000000, 0x10000000): writes = rd == reg   # data processing
                elif (w & 0x3a000000) == 0x28000000 and (w >> 22) & 1: writes = reg in (rd, (w >> 10) & 31)        # ldp
                elif (w & 0xfc000000) == 0x94000000 or (w & 0xfffffc1f) == 0xd63f0000: writes = reg <= 18          # a call clobbers x0..x18
                if writes:
                    found = p; break
                p -= 4
            if found is None: return None
            w = word(found)
            if (w & 0xffe0ffe0) == 0xaa0003e0:                          # mov xD, xS: follow the source
                a, reg = found, (w >> 16) & 31
                continue
            return found
        return None

    # ---- singleton pointer loads
    sing_loads = set()
    for i in np.nonzero((W & 0x9f000000) == 0x90000000)[0]:
        w = int(W[i]); a = BASE + 4 * int(i)
        imm = ((w >> 5) & 0x7ffff) << 2 | ((w >> 29) & 3)
        if imm & (1 << 20): imm -= 1 << 21
        if (a & ~0xfff) + (imm << 12) != (SING & ~0xfff): continue
        rd = w & 31
        for k in range(1, 9):
            w2 = int(W[i + k])
            if (w2 & 0xffffffe0) == (0xf9400000 | ((SING & 0xfff) // 8 << 10) | (rd << 5)):
                sing_loads.add(a + 4 * k); break
    sing_fns = set(fn_of(a) for a in sing_loads)

    # ---- bounds
    n_bound = 0
    for a in addrs(0x7ffffc1f, 0x7100001f | (0x5e << 10)):
        nxt = [word(a + 4 * k) for k in range(1, 5)]
        br = next(((a + 4 * (k + 1), w) for k, w in enumerate(nxt) if (w & 0xff000010) == 0x54000000), None)
        if not br: continue
        cond = br[1] & 15
        target = br[0] + ((br[1] >> 5 & 0x7ffff) - (1 << 19 if br[1] >> 23 & 1 else 0)) * 4
        def calls_abort(t): return any((word(t + 4 * k) & 0xfc000000) == 0x94000000 and t + 4 * k + (((word(t + 4 * k) & 0x3ffffff) ^ 0x2000000) - 0x2000000) * 4 == ABORT for k in range(3))
        if cond in (2, 8) and calls_abort(target):                      # b.hs / b.hi -> abort
            pass
        elif cond == 3 and fn_of(a) == 0x710167a270:                    # b.lo over the abort (three sites of one function)
            pass
        else:
            continue
        if a == 0x710068d530: continue                                  # the callbacks table (not the singleton; it does not abort either)
        patch(a, set_imm12(word(a), nk), 'bound 0x5e -> NK   fn %x' % fn_of(a)); n_bound += 1

    # ---- array B: variable kind
    n_b = 0
    for v in (0x14f0, 0x14f4, 0x14f8):
        for a in addrs(0xff3ffc00, 0xb9000000 | ((v // 4) << 10)):
            w = word(a)
            d = base_def(a, (w >> 5) & 31)
            if d is not None and (word(d) & 0x7f008000) == 0x1b000000 and ((word(d) >> 21) & 7) in (0, 1, 5):      # madd / smaddl / umaddl
                patch(a, ls_with(w, v - OLD_B + NEW_B), 'B +0x%x -> +0x%x   %s   fn %x' % (v, v - OLD_B + NEW_B, dis(a), fn_of(a))); n_b += 1
            elif fn_of(a) in sing_fns or CTOR <= a < 0x7100730000:
                notes.append('NOT PATCHED %x %s (base not from a multiply-add) fn %x' % (a, dis(a), fn_of(a)))
    # ---- array B: constant kind (base = the singleton pointer)
    n_c = 0
    cand = np.nonzero((W & 0x3b000000) == 0x39000000)[0]
    for i in cand:
        w = int(W[i])
        off = ls_off(w)
        if not OLD_B <= off < 0x1958: continue
        a = BASE + 4 * int(i)
        if a in patches or fn_of(a) not in sing_fns: continue
        d = base_def(a, (w >> 5) & 31)
        if d in sing_loads:
            if (w >> 30) != 2 or (w >> 26) & 1 or (off - OLD_B) % 4:
                notes.append('NOT PATCHED %x %s: singleton + 0x%x with another width' % (a, dis(a), off)); continue
            patch(a, ls_with(w, off - OLD_B + NEW_B), 'Bconst kind 0x%x field %d   %s   fn %x' % ((off - OLD_B) // 12, (off - OLD_B) % 12 // 4, dis(a), fn_of(a))); n_c += 1

    # ---- constructor (in 0x710066ee40)
    n_ctor = 0
    a = CTOR
    while a < CTOR + 0x130:
        w = word(a)
        if (w & 0x7fffffe0) == (0x52800000 | (OLD_SIZE << 5)): patch(a, set_imm16(w, NEW_B + nk * 12), 'ctor: object size'); n_ctor += 1
        elif (w & 0x7fffffe0) == (0x52800000 | (OLD_B << 5)): patch(a, set_imm16(w, a_end), 'ctor: end of A = start of the zero fill'); n_ctor += 1
        elif (w & 0xffffffe0) == (0x92800000 | (0x148f << 5)): patch(a, set_imm16(w, nk * 0x38 - 1), 'ctor: -(size of A)'); n_ctor += 1
        elif (w & 0x7fffffe0) == (0x52800000 | (0x47c << 5)): patch(a, set_imm16(w, NEW_B + nk * 12 - a_end), 'ctor: zero fill length (members behind A + B)'); n_ctor += 1
        elif (w & 0xffc003e0) == (0xf9000000 | (11 << 5)) and 0x14f8 <= ls_off(w) <= 0x1558:
            patch(a, ls_with(w, ls_off(w) + (nk - 0x5e) * 0x38), 'ctor: row store %s' % dis(a)); n_ctor += 1
        a += 4
    # ---- end of A in the three loops over A
    n_end = 0
    for f in (DTOR, LOADER, CLEAR):
        hits = [x for x in range(f, f + 0x400, 4) if (word(x) & 0x7fffffe0) == (0x52800000 | (OLD_B << 5)) and fn_of(x) == f]
        if len(hits) != 1: sys.exit('end-of-A constant not found once in %x' % f)
        patch(hits[0], set_imm16(word(hits[0]), a_end), 'end of A   fn %x' % f); n_end += 1

    # ---- SECOND per-kind container *(0x71052bb3a8) (found by run ii2: a fighter of kind 0x5E crashed in it):
    # 0x5E list heads of 0x18 bytes {prev, next, count} at +0, a 3-byte lock at +0x8d0, size 0x8f0; 5 functions use it.
    # Ours: NK list heads, the lock at NK * 0x18, size NK * 0x18 + 0x20. The constructor (inside 0x710066ee40) is
    # unrolled, one group of stores per row: it cannot be extended by changing immediates, so the rows 0x5E.. are
    # zero after it (the object is zero-filled) and whoever adds a kind has to make them empty lists (n3_kind.cpp).
    n_c2 = 0
    lock_old, lock_new = 0x5e * 0x18, nk * 0x18
    for a in range(0x710066f37c, 0x710066f970, 4):
        w = word(a)
        if (w & 0x7fffffe0) == (0x52800000 | (0x8f0 << 5)): patch(a, set_imm16(w, lock_new + 0x20), 'container 2 ctor: size (allocation / zero fill)'); n_c2 += 1
        elif (w & 0xffc003e0) == (0x39000000 | (20 << 5)) and lock_old <= ((w >> 10) & 0xfff) < lock_old + 3:
            patch(a, set_imm12(w, ((w >> 10) & 0xfff) - lock_old + lock_new), 'container 2 ctor: lock byte %s' % dis(a)); n_c2 += 1
    for f in (0x71006deca0, 0x71006df660, 0x71006e4eb0, 0x71014f10c0):
        end = starts[bisect.bisect_right(starts, f)]
        while fn_of(end) != end or end - f < 0x40: end = starts[bisect.bisect_right(starts, end)]
        hits = 0
        for a in range(f, min(end, f + 0x4000), 4):
            w = word(a)
            if (w & 0xffc00000) == 0x91000000 and ((w >> 10) & 0xfff) == lock_old:
                d = base_def(a, (w >> 5) & 31)
                if d is not None and (word(d) & 0xffc00000) == 0xf9400000 and ((word(d) >> 10) & 0xfff) == 0x3a8 // 8:
                    patch(a, set_imm12(w, lock_new), 'container 2: lock address %s   fn %x' % (dis(a), f)); n_c2 += 1; hits += 1
            elif is_ls(w) and lock_old <= ls_off(w) < lock_old + 0x20:
                d = base_def(a, (w >> 5) & 31)
                if d is not None and (word(d) & 0xffc00000) == 0xf9400000 and ((word(d) >> 10) & 0xfff) == 0x3a8 // 8:
                    notes.append('NOT PATCHED %x %s: container 2 + 0x%x accessed directly' % (a, dis(a), ls_off(w)))
        if hits != 1: notes.append('container 2: %d lock addresses in fn %x (expected 1)' % (hits, f))
    w = word(0x71014f2510)
    if (w & 0x7ffffc1f) != (0x7100001f | (0x5e << 10)): sys.exit('container 2: loop bound not found')
    patch(0x71014f2510, set_imm12(w, nk), 'container 2: loop over all kinds 0x5e -> NK   fn 71014f10c0'); n_c2 += 1

    out = os.path.join(HERE, 'kinds.txt')
    with open(out, 'w') as fo:
        fo.write('# generated by patches\\kinds_scan.py %#x -- the parameter singleton with %#x fighter kinds (plan\\phases\\N3_new_kind.md)\n' % (nk, nk))
        fo.write('# <address> <original word> <new word>   # what.  Used by the lifter with RECOMP_PATCHES=patches\\kinds.txt\n')
        for a in sorted(patches):
            old, new, what = patches[a]
            if old != new:
                fo.write('%x %08x %08x   # %s\n' % (a, old, new, what))
    fns = set(fn_of(a) for a in patches)
    files = set((a - BASE) // 0xC000 for a in patches)
    print('NK = %#x: %d patches in %d functions, %d generated files -> %s' % (nk, len(patches), len(fns), len(files), out))
    print('  bounds %d, B (variable kind) %d, B (constant kind) %d, constructor %d, end of A %d; second container %d' % (n_bound, n_b, n_c, n_ctor, n_end, n_c2))
    print('  singleton pointer loads: %d in %d functions' % (len(sing_loads), len(sing_fns)))
    for n in notes:
        print('  ' + n)


if __name__ == '__main__':
    main()
