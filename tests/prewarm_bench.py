#!/usr/bin/env python3
"""PR #33: measure the whole start-up prewarm of ..\\cache\\vk\\pipes.bin, without starting the game.

The runtime's SSBU_VK_PREWARM_BENCH=1 path skips the background container preparation, waits for the prewarm in
vkd_init and ends the process there (exit 0) without saving any cache. Run one at a time, on a cache that is not
changing, and after a reboot for a cold start (the OS file cache holds the stage records and SPIR-V files otherwise).

Two layouts:
  - the public build layout (build\\state.json, build\\work\\<exe>, build\\binaries\\13.0.4\\main.elf): --build <folder>;
  - the private working tree (the exe beside this folder, ..\\binaries\\13.0.4\\main.elf): used when --build has no
    state.json. SSBU_ROMFS is passed on from the caller's environment there.

    python tests/prewarm_bench.py --exe ssbu_native.exe --cache ..\\cache\\vk --log logs\\pw1.txt [--workers 16] [--no-profile]

Prints a JSON summary (also written next to the log) and the nvn_vk_prewarm_profile lines.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


def main():
    here = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', type=Path, default=here / 'build', help='the public build folder (with state.json)')
    ap.add_argument('--exe', required=True, help='the executable: inside build\\work, or beside tests\\ in the private tree')
    ap.add_argument('--cache', type=Path, required=True, help='the Vulkan cache folder (SSBU_VK_CACHE)')
    ap.add_argument('--workers', type=int, choices=range(1, 17), default=16)
    ap.add_argument('--log', type=Path, required=True)
    ap.add_argument('--timeout', type=int, default=300)
    ap.add_argument('--no-profile', action='store_true', help='without SSBU_VK_PREWARM_PROFILE (what the measuring costs)')
    a = ap.parse_args()
    build, cache, log = a.build.resolve(), a.cache.resolve(), a.log.resolve()
    log.parent.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('SSBU_', 'RECOMP_'))}
    state = build / 'state.json'
    if state.is_file():                                  # public layout
        romfs = json.loads(state.read_text())['dump']['romfs']
        exe, elf, cwd = build / 'work' / a.exe, build / 'binaries' / '13.0.4' / 'main.elf', build / 'work'
    else:                                                # private working tree
        romfs = os.environ.get('SSBU_ROMFS')
        exe, elf, cwd = here / a.exe, here.parent / 'binaries' / '13.0.4' / 'main.elf', here
    if romfs:
        env['SSBU_ROMFS'] = romfs
    env.update(SSBU_SHOW='0', SSBU_RENDERER='vk', SSBU_VK_CACHE=str(cache), SSBU_VK_WORKERS=str(a.workers),
               SSBU_VK_PREWARM_BENCH='1', SSBU_VK_PREWARM_PROFILE='0' if a.no_profile else '1')
    with tempfile.TemporaryDirectory(prefix='prewarm-', dir=log.parent) as scratch:
        env['SSBU_USERDATA'] = scratch
        env['SSBU_TRACE'] = str(Path(scratch) / 'boot_trace.txt')
        started = time.perf_counter()
        timed_out = False
        with log.open('w', encoding='utf-8') as output:
            try:
                process = subprocess.run([str(exe), str(elf)], cwd=cwd, env=env, stdout=output,
                                         stderr=subprocess.STDOUT, timeout=a.timeout)
                exit_code = process.returncode
            except subprocess.TimeoutExpired:
                timed_out, exit_code = True, None
        elapsed = time.perf_counter() - started
    text = log.read_text(encoding='utf-8', errors='replace')
    match = re.search(r'pipelines made ahead: (\d+) of (\d+) listed \((\d+) stages from their records, '
                      r'(\d+) entries without their stage files\) in (\d+) ms on (\d+) threads; '
                      r'the first batch waited (\d+) ms', text)
    summary = dict(exe=str(exe), workers=a.workers, cache=str(cache), log=str(log),
                   exit_code=exit_code, timed_out=timed_out, process_seconds=round(elapsed, 3))
    if match:
        summary.update(zip(('made', 'listed', 'stages', 'missing', 'prewarm_ms', 'threads', 'wait_ms'),
                           map(int, match.groups())))
    summary['complete'] = exit_code == 0 and match is not None and 'nvn_vk_prewarm_bench: complete' in text
    log.with_suffix('.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    for line in text.splitlines():
        if line.startswith('nvn_vk_prewarm_profile:'):
            print(line)
    return 0 if summary['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
