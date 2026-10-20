"""The lifter's differential test (tools/lifter/difftest.py) without the game: only the instruction words difftest.py writes
out itself (extra_words: every arrangement of the instructions Rust-compiled modules use; exclusive sequences), lifted to C,
compiled for this host (arm64 on a Mac) and compared with the Unicorn emulator from the same random states.

recomp.py reads the layout of main.elf at import; here it reads a stand-in made below: an ELF header, one PT_LOAD, a MOD0
header and an empty dynamic section. No byte of it comes from the game. Run in a folder staged by host_check.py
(build-<target>/work):

    python3 scripts/macos/difftest_synthetic.py --work build-macos/work [--clang clang] [--max-different N]

Exit code 0 when the host build runs every test and at most --max-different results differ (default 0).
"""
import argparse
import os
import re
import struct
import subprocess
import sys


def stand_in_elf(path):
    """64-bit little-endian ELF: header, one program header (PT_LOAD, 0x1000 bytes of code), at 0x1000 a branch word and
    the MOD0 offset, MOD0 with its dynamic section (tags 7 8 23 2 6 5 = 0, then DT_NULL)."""
    img = bytearray(0x2000)
    img[0:16] = b'\x7fELF\x02\x01\x01' + bytes(9)
    struct.pack_into('<HHIQQQIHHHHHH', img, 16, 3, 0xB7, 1, 0, 0x40, 0, 0, 64, 56, 1, 0, 0, 0)
    struct.pack_into('<IIQQQQQQ', img, 0x40, 1, 5, 0x1000, 0, 0, 0x1000, 0x1000, 0x1000)
    mod0 = 0x100                                            # relative to 0x1000
    struct.pack_into('<II', img, 0x1000, 0x14000000, mod0)  # b .+0 ; MOD0 offset
    dyn = 0x40                                              # relative to MOD0
    img[0x1000 + mod0:0x1000 + mod0 + 4] = b'MOD0'
    struct.pack_into('<i', img, 0x1000 + mod0 + 4, dyn)
    at = 0x1000 + mod0 + dyn
    for tag in (7, 8, 23, 2, 6, 5, 0):
        struct.pack_into('<qQ', img, at, tag, 0)
        at += 16
    with open(path, 'wb') as f:
        f.write(img)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--work', required=True)
    ap.add_argument('--clang', default='clang')
    ap.add_argument('--max-different', type=int, default=0)
    ap.add_argument('--cflags', default='', help='more compiler flags, e.g. -mcx16 (as the Linux build uses)')
    ap.add_argument('--opt', default='-O0', help='optimisation of the test program (-O1: as the game library is built)')
    a = ap.parse_args()
    work = os.path.abspath(a.work)
    bin_dir = os.path.join(work, 'difftest_synthetic_bin')
    os.makedirs(bin_dir, exist_ok=True)
    stand_in_elf(os.path.join(bin_dir, 'main.elf'))
    env = {k: v for k, v in os.environ.items() if not k.startswith(('RECOMP_', 'SSBU_'))}
    exe = os.path.join(work, 'difftest_synth' + ('.exe' if os.name == 'nt' else ''))
    env.update(PYTHONIOENCODING='utf-8', RECOMP_BIN=bin_dir, DIFFTEST_EXE=exe)
    with open(os.path.join(work, 'difftest_samples.json'), 'w') as f:
        f.write('{}')                                       # no sampled game instructions: only difftest.py's own list

    def run(argv):
        r = subprocess.run(argv, cwd=work, env=env, capture_output=True, text=True, errors='replace')
        print('$ ' + ' '.join(argv))
        print((r.stdout + r.stderr)[-6000:])
        if r.returncode:
            sys.exit('failed (exit %d)' % r.returncode)
        return r.stdout

    run([sys.executable, 'difftest.py', 'gen'])
    run([a.clang, a.opt, '-w', '-fno-strict-aliasing', '-I', '.', 'difftest_gen.c', 'difftest_host.c', '-o', exe] + a.cflags.split() + ([] if os.name == 'nt' else ['-lm']))
    out = run([sys.executable, 'difftest.py', 'check'])
    m = re.search(r'tests: (\d+)\s+identical: (\d+)\s+different: (\d+)', out)
    if not m:
        sys.exit('difftest printed no result')
    total, same, diff = map(int, m.groups())
    verdict = 'lifted code (' + a.opt + ') on this host vs Unicorn, game-free instruction list: %d tests, %d identical, %d different' % (total, same, diff)
    print('RESULT: ' + verdict)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as f:
            f.write('## Differential test (no game data)\n\n%s\n\n```\n%s\n```\n' % (verdict, out[-6000:]))
    return 0 if total and diff <= a.max_different else 1


if __name__ == '__main__':
    sys.exit(main())
