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
    ap.add_argument('--target', choices=('macos', 'linux'), default='macos')
    ap.add_argument('--work', default=None)
    ap.add_argument('--vulkan-headers', required=True)
    ap.add_argument('--suyu', required=True)
    ap.add_argument('--clang', default='clang')
    ap.add_argument('--imgui', default=None, help='Dear ImGui v1.91.9b folder: the settings menu (F1) is built too (U2)')
    a = ap.parse_args()

    mac = a.target == 'macos'
    cx = type('Cx', (), {})()
    cx.linux, cx.mac, cx.posix = not mac, mac, True
    cx.work = os.path.abspath(a.work or os.path.join(REPO, 'build-' + a.target, 'work'))
    os.makedirs(cx.work, exist_ok=True)
    setup.step_stage(cx)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('RECOMP_', 'SSBU_'))}
    env.update(PYTHONIOENCODING='utf-8', RECOMP_TARGET=a.target, RECOMP_CLANG=a.clang, RECOMP_EXE='ssbu_native',
               VULKAN_HEADERS=os.path.abspath(a.vulkan_headers), SUYU_ROOT=os.path.abspath(a.suyu),
               IMGUI_ROOT=os.path.abspath(a.imgui) if a.imgui else os.path.join(cx.work, 'no-imgui'))

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
        verdict = 'the host runtime compiles and links for %s' % ('macOS' if mac else 'Linux')
    print('\nRESULT: ' + verdict)
    if a.imgui and not code:
        menu_ok, menu_out = menu_symbols(cx.work, mac)
        print(menu_out)
        verdict += '; ' + menu_out.splitlines()[-1]
        if not menu_ok:
            code = 1
    mod_ok, mod_out = module_check(cx.work, run, a.clang, mac)
    print(mod_out)
    mod_verdict = ('a module library built as build_nro.py builds one (%s) loads' % ('.dylib' if mac else '.so') + ' through LoadLibraryA("<name>.dll") and runs'
                   if mod_ok else 'the module library check FAILED')
    print('RESULT: ' + mod_verdict)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as f:
            f.write('## ' + a.target + ' host runtime\n\n%s\n\n%s\n\n```\n%s\n```\n\n```\n%s\n```\n' % (verdict, mod_verdict, mod_out[-8000:], out[-60000:]))
    return 1 if code or not mod_ok else 0


def menu_symbols(work, mac):
    """U2: the host link of this check leaves undefined names to load time (no game library here), so a name the settings menu
    needs and nothing defines would only show when the game starts. Every undefined name of the menu's objects must be defined
    by another host object or by the system's C / C++ / SDL3 libraries (Linux: their dynamic symbols; macOS: listed only)."""
    objdir = os.path.join(work, 'obj_host', 'ssbu_native')
    menu = [os.path.join(objdir, n) for n in os.listdir(objdir) if n.endswith('_cxx.obj')]
    if not menu:
        return False, 'settings menu: no menu object was built (Dear ImGui not found?)'

    def syms(argv, kinds=None):
        r = subprocess.run(argv, capture_output=True, text=True, errors='replace')
        return {ln.split()[-1] for ln in r.stdout.splitlines() if ln.strip() and not ln.endswith(':') and (not kinds or (len(ln.split()) >= 2 and ln.split()[-2] in kinds))}
    undef = set()
    for o in menu:
        undef |= syms(['nm', '-u', o], None if mac else ('U',))      # (Linux: weak undefined names may stay undefined; macOS nm -u prints names only)
    defined = set()
    for n in os.listdir(objdir):
        if n.endswith('.obj'):
            defined |= syms(['nm', '-gU', os.path.join(objdir, n)] if mac else ['nm', '-g', '--defined-only', os.path.join(objdir, n)])
    left = sorted(undef - defined)
    if mac:
        return True, 'settings menu: names left to the system libraries (macOS, not checked): %s\nsettings menu: built' % ' '.join(left)
    libs = []
    for name in ('libc.so.6', 'libm.so.6', 'libstdc++.so.6', 'libgcc_s.so.1'):
        r = subprocess.run(['gcc', '-print-file-name=' + name], capture_output=True, text=True)
        if r.stdout.strip() and os.path.isabs(r.stdout.strip()):
            libs.append(r.stdout.strip())
    sdl = subprocess.run(['pkg-config', '--variable=libdir', 'sdl3'], capture_output=True, text=True).stdout.strip()
    if sdl:
        libs.append(os.path.join(sdl, 'libSDL3.so'))
    sys_defined = set()
    for lib in libs:
        sys_defined |= {n.split('@')[0] for n in syms(['nm', '-D', '--defined-only', os.path.realpath(lib)])}
    linker = {'__dso_handle', '_GLOBAL_OFFSET_TABLE_'}      # made by the link itself (crtbegin.o, the linker)
    missing = [n for n in left if n not in sys_defined and n not in linker]
    text = 'settings menu: %d undefined names: %d from other host objects, %d from %s' % (
        len(undef), len(undef) - len(left), len(left) - len(missing), ' '.join(os.path.basename(x) for x in libs))
    if missing:
        return False, text + '\nsettings menu: NOT DEFINED anywhere: ' + ' '.join(missing)
    return True, text + '\nsettings menu: every name it needs is defined'


MODULE_C = r'''/* a stand-in for a lifted module (no game code): an exported entry, its own data, a call back into the host */
#include <stdint.h>
static int64_t table[4] = {1, 2, 3, 4};
__declspec(dllexport) int64_t nro_test_bind(int64_t (*host)(int64_t), int64_t x) { return host(x) + table[3]; }
'''
LOADER_C = r'''/* loads module_check/test_mod as nnro.c loads a module: LoadLibraryA("<path>.dll"), GetProcAddress */
#include <windows.h>
#include <stdio.h>
static int64_t host_twice(int64_t v) { return v * 2; }
int main(void) {
    HMODULE m = LoadLibraryA("module_check\\test_mod.dll");
    if (!m) { printf("LoadLibraryA failed (%lu)\n", (unsigned long)GetLastError()); return 1; }
    int64_t (*bind)(int64_t (*)(int64_t), int64_t) = (int64_t (*)(int64_t (*)(int64_t), int64_t))(void *)GetProcAddress(m, "nro_test_bind");
    char path[MAX_PATH] = "";
    GetModuleFileNameA(m, path, MAX_PATH);
    if (!bind) { printf("GetProcAddress(nro_test_bind) failed\n"); return 1; }
    int64_t r = bind(host_twice, 19);
    printf("module %s: nro_test_bind(host_twice, 19) = %lld (want 42)\n", path, (long long)r);
    return r == 42 ? 0 : 1;
}
'''
MODULE_BUILD = '''import os, subprocess, sys, build, build_nro
d = "module_check"; obj = os.path.join(d, "mod.obj"); lib = os.path.join(d, "test_mod" + build_nro.LIB_EXT)
r = subprocess.run([build.CLANG, "-c", "-O1", "-w"] + build_nro.PLAT_FLAGS + [os.path.join(d, "mod.c"), "-o", obj], capture_output=True, text=True)
print("compile", r.returncode, r.stdout + r.stderr)
r = build.link_dll([obj], lib, os.path.join(d, "link.rsp"), implib=False)
print("link", lib, r.returncode, r.stdout + r.stderr)
sys.exit(1 if r.returncode or not os.path.exists(lib) else 0)
'''


def module_check(work, run, clang, mac=True):
    """The module path of the macOS build without any game code: a small C file compiled with build_nro.py's flags and
    linked by build.py's link_dll (-dynamiclib, @rpath install name, undefined names left to load time) into
    module_check/test_mod<LIB_EXT>, then loaded by a program on plat_posix.c the way nnro.c loads a module."""
    d = os.path.join(work, 'module_check')
    os.makedirs(d, exist_ok=True)
    for name, text in (('mod.c', MODULE_C), ('loader.c', LOADER_C)):
        with open(os.path.join(d, name), 'w', newline='\n') as f:
            f.write(text)
    code, out = run([sys.executable, '-c', MODULE_BUILD])
    if code:
        return False, 'module build:\n' + out
    pkg = subprocess.run(['pkg-config', '--cflags', '--libs', 'sdl3', 'openssl'], capture_output=True, text=True).stdout.split()
    exe = os.path.join(d, 'loader')
    c2, o2 = run([clang, '-O1', '-w'] + (['-mmacosx-version-min=14.4'] if mac else []) + ['-include', 'plat/plat_pre.h', '-I', 'plat', os.path.join(d, 'loader.c'), 'plat_posix.c', '-o', exe] + pkg
                 + ([] if mac else ['-lm', '-ldl', '-lpthread']))
    if c2:
        return False, out + '\nloader build:\n' + o2
    c3, o3 = run([exe])
    c4, o4 = run(['otool', '-L', os.path.join(d, 'test_mod.dylib')] if mac else ['readelf', '-d', os.path.join(d, 'test_mod.so')])
    return c3 == 0, out + o3 + o4


if __name__ == '__main__':
    sys.exit(main())
