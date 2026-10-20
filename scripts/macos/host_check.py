"""macOS port, step 1 (plan/phases/MAC1_port.md): build the host runtime alone for macOS (Apple Silicon) and report what
does not compile. Needs no dump and reads nothing of the game: the sources are staged as scripts/setup.py stages them, the
host's own generated headers are made as scripts/make_release.py makes them, then tools/lifter/build.py host runs with
RECOMP_TARGET=macos. Used by .github/workflows/macos-runtime.yml; runs the same on a Mac:

    python3 scripts/macos/host_check.py --vulkan-headers <Khronos Vulkan-Headers> --suyu <Mii sources> [--work <folder>]

Exit code 0 when the exe links. Every file that fails is listed (build.py compiles all of them before it stops), and with
GITHUB_STEP_SUMMARY set the result goes to the job's summary page as well.
"""
import argparse
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, 'scripts'))
import setup  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--work', default=os.path.join(REPO, 'build-macos', 'work'))
    ap.add_argument('--vulkan-headers', required=True)
    ap.add_argument('--suyu', required=True)
    ap.add_argument('--clang', default='clang')
    a = ap.parse_args()

    cx = type('Cx', (), {})()
    cx.work = os.path.abspath(a.work)
    os.makedirs(cx.work, exist_ok=True)
    setup.step_stage(cx)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('RECOMP_', 'SSBU_'))}
    env.update(PYTHONIOENCODING='utf-8', RECOMP_TARGET='macos', RECOMP_CLANG=a.clang, RECOMP_EXE='ssbu_native',
               VULKAN_HEADERS=os.path.abspath(a.vulkan_headers), SUYU_ROOT=os.path.abspath(a.suyu),
               IMGUI_ROOT=os.path.join(cx.work, 'no-imgui'))

    def run(argv):
        r = subprocess.run(argv, cwd=cx.work, env=env, capture_output=True, text=True, errors='replace')
        return r.returncode, r.stdout + r.stderr

    # the host's own generated headers (none reads a dump), as scripts/make_release.py makes them
    for script in ('gen_quad_tests.py', 'gen_sdktest.py'):
        code, out = run([sys.executable, script])
        if code:
            sys.exit('%s failed:\n%s' % (script, out[-3000:]))
    with open(os.path.join(REPO, 'tools', 'lifter', 'sdklift_roots.txt'), encoding='utf-8', errors='replace') as f:
        with open(os.path.join(cx.work, 'sdklift_install.h'), 'w', newline='\n') as g:
            g.write(setup.install_header(f.read()))
    for name, var in (('fake_whitelist.h', 'audit_whitelist'), ('fake_openlist.h', 'audit_openlist')):
        with open(os.path.join(cx.work, name), 'w', newline='\n') as f:
            f.write(setup.STUB_LIST % var)

    code, out = run([sys.executable, 'build.py', 'host'])
    print(out)
    failed = re.findall(r'(?m)^FAILED (\S+)', out)
    errors = len(re.findall(r': error: ', out))
    if failed:
        verdict = '%d host file(s) do not compile (%d errors shown): %s' % (len(failed), errors, ' '.join(failed))
    elif code:
        verdict = 'every host file compiles; the link fails'
    else:
        verdict = 'the host runtime compiles and links for macOS'
    print('\nRESULT: ' + verdict)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as f:
            f.write('## macOS host runtime\n\n%s\n\n```\n%s\n```\n' % (verdict, out[-60000:]))
    return 1 if code else 0


if __name__ == '__main__':
    sys.exit(main())
