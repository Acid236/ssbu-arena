"""Build one fighter's C++ source into fighters_bin\\<name>.dll.

    python fighter_sdk/tools/build_fighter.py mario

Compiles fighters/<name>/**/*.cpp and fighter_sdk/src/fighter_rt.cpp (only what changed), links the DLL.
Neither the game code nor the exe is rebuilt. The game loads the DLL when it loads the fighter's script module.
"""
import concurrent.futures
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.normpath(os.path.join(HERE, '..', '..'))
CLANG = r'C:\llvm-8.0.0\bin\clang.exe'


def newest(paths):
    return max(os.path.getmtime(p) for p in paths)


def main():
    name = sys.argv[1]
    t0 = time.time()
    fdir = os.path.join(STUDY, 'fighters', name)
    inc = os.path.join(STUDY, 'fighter_sdk', 'include')
    src_rt = os.path.join(STUDY, 'fighter_sdk', 'src')
    objdir = os.path.join(STUDY, 'obj_fighters', name)
    bindir = os.path.join(STUDY, os.environ.get('SSBU_FIGHTER_BIN') or 'fighters_bin')     # S3: work in progress goes to its own folder
    os.makedirs(objdir, exist_ok=True)
    os.makedirs(bindir, exist_ok=True)
    sources = [os.path.join(src_rt, 'fighter_rt.cpp')]
    for root, dirs, files in os.walk(fdir):
        sources += [os.path.join(root, f) for f in sorted(files) if f.endswith('.cpp')]
    gen = os.path.join(STUDY, 'fighters', 'sdk_generated')      # lua_bind.h, lua_const.h, fs_syms.inc: made by gen_sdk.py from the game
    headers = [os.path.join(inc, f) for f in os.listdir(inc)] + [os.path.join(gen, f) for f in os.listdir(gen)] + [os.path.join(fdir, 'generated', 'bindings.inc')]
    dep = newest(headers)
    flags = ['-x', 'c++', '-std=c++14', '-O1', '-c', '-fno-exceptions', '-fno-rtti', '-Wall', '-Wno-unused-parameter', '-Wno-unused-variable',
             '-Wno-unused-const-variable', '-Wno-unused-function', '-I', inc, '-I', gen, '-I', src_rt, '-I', os.path.join(fdir, 'generated')]
    jobs = []
    objs = []
    for s in sources:
        o = os.path.join(objdir, os.path.relpath(s, STUDY).replace(os.sep, '_')[:-4] + '.obj')
        objs.append(o)
        if not os.path.exists(o) or os.path.getmtime(o) < max(os.path.getmtime(s), dep):
            jobs.append((s, o))

    def compile_one(job):
        r = subprocess.run([CLANG] + flags + [job[0], '-o', job[1]], capture_output=True, text=True)
        return job[0], r.returncode, (r.stdout + r.stderr)[-6000:]

    failed = 0
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        for s, code, err in pool.map(compile_one, jobs):
            if code or err.strip():
                print('%s %s\n%s' % ('FAILED' if code else 'warnings in', os.path.relpath(s, STUDY), err))
            failed += 1 if code else 0
    if failed:
        return 1
    dll = os.path.join(bindir, name + '.dll')
    r = subprocess.run([CLANG, '-shared'] + objs + ['-o', dll], capture_output=True, text=True)
    if r.returncode:
        print((r.stdout + r.stderr)[-4000:])
        return 1
    for ext in ('.lib', '.exp'):
        p = dll[:-4] + ext
        if os.path.exists(p):
            os.remove(p)
    print('%s: %d source files, %d compiled, %s %.0f KB, %.1f s' % (name, len(sources), len(jobs), os.path.relpath(dll, STUDY), os.path.getsize(dll) / 1024.0, time.time() - t0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
