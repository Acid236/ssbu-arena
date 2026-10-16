"""Track R1 round 3: run-time module DLLs whose lifted stores mark dirty pages (-DR1_MARK), into nro_bin_r1\ (the other
modules are copied from nro_bin\ unchanged). Run the game with SSBU_NRO_BIN=nro_bin_r1.
    python tests/r1_nro_build.py <jobs> <module> [<module> ...]      (names without the lua2cpp_ prefix)
Same sources (gen_nro) and flags as nro_bin (-O0), plus -DR1_MARK; shim nro_shim_r1.c. No game content."""
import concurrent.futures, os, shutil, subprocess, sys, time
HERE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
CLANG = os.environ.get('RECOMP_CLANG', r'C:\llvm-8.0.0\bin\clang.exe')
BIN = os.path.join(HERE, 'nro_bin_r1')
os.makedirs(BIN, exist_ok=True)
for n in os.listdir(os.path.join(HERE, 'nro_bin')):
    if n.endswith('.dll') and not os.path.exists(os.path.join(BIN, n)):
        shutil.copy2(os.path.join(HERE, 'nro_bin', n), os.path.join(BIN, n))
jobs = int(sys.argv[1])
for m in sys.argv[2:]:
    name = m if m.startswith('lua2cpp_') else 'lua2cpp_' + m
    gen, obj = os.path.join(HERE, 'gen_nro', name), os.path.join(HERE, 'obj_nro_r1', name)
    os.makedirs(obj, exist_ok=True)
    flags = ['-c', '-O0', '-w', '-fno-strict-aliasing', '-DR1_MARK', '-I', HERE, '-I', gen]
    todo = [(flags + [os.path.join(gen, n), '-o', os.path.join(obj, n[:-2] + '.obj')]) for n in sorted(os.listdir(gen)) if n.endswith('.c') and not os.path.exists(os.path.join(obj, n[:-2] + '.obj'))]
    todo.append([f for f in flags if f != '-DR1_MARK'] + ['-DNRO_MODULE=' + name, os.path.join(HERE, 'nro_shim_r1.c'), '-o', os.path.join(obj, '_shim.obj')])
    t = time.time()
    with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
        bad = [r for r in pool.map(lambda a: subprocess.run([CLANG] + a, capture_output=True, text=True), todo) if r.returncode]
    if bad:
        print(name, 'FAILED', (bad[0].stdout + bad[0].stderr)[-1500:]); sys.exit(1)
    objs = sorted(os.path.join(obj, n) for n in os.listdir(obj) if n.endswith('.obj'))
    rsp = os.path.join(obj, 'link.rsp')
    open(rsp, 'w').write('\n'.join('"%s"' % o.replace(chr(92), '/') for o in objs))
    r = subprocess.run([CLANG, '-shared', '@' + rsp, '-o', os.path.join(BIN, name + '.dll')], capture_output=True, text=True)
    print('%s: %d files compiled in %.0fs, link exit %d %s' % (name, len(todo), time.time() - t, r.returncode, (r.stdout + r.stderr)[-500:]), flush=True)
