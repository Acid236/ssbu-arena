"""Build one fighter's C++ source into fighters_bin\\<name>.dll.

    python fighter_sdk/tools/build_fighter.py mario

Compiles fighters/<name>/**/*.cpp and fighter_sdk/src/fighter_rt.cpp (only what changed), links the DLL.
Neither the game code nor the exe is rebuilt. The game loads the DLL when it loads the fighter's script module.
"""
import concurrent.futures
import os
import re
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
    # S10: SSBU_FIGHTERS_ROOT=<folder under fighters\>: the sources of a work run (status_decomp.py); own object folder
    froot = os.environ.get('SSBU_FIGHTERS_ROOT') or ''
    fdir = os.path.join(STUDY, 'fighters', froot, name)
    inc =os.path.join(STUDY, 'fighter_sdk', 'include')
    src_rt = os.path.join(STUDY, 'fighter_sdk', 'src')
    objdir = os.path.join(STUDY, 'obj_fighters', name)
    bindir = os.path.join(STUDY, os.environ.get('SSBU_FIGHTER_BIN') or 'fighters_bin')     # S3: work in progress goes to its own folder
    os.makedirs(objdir, exist_ok=True)
    os.makedirs(bindir, exist_ok=True)
    # S8 options (the default build is unchanged):
    #   SSBU_FIGHTER_STATUS=1    also build the fighter's own status scripts (fighters\<name>\status\*.cpp, bindings in
    #                            generated\status_bindings.inc). Without it a fighter's status\ folder is NOT compiled:
    #                            those sources are work in progress (fighter_status.py) and need their own SDK folder.
    #   SSBU_FIGHTER_SDK=<dir>   folder under fighters\ with lua_bind.h / lua_const.h / fs_syms.inc (default
    #                            sdk_generated); objects of another SDK go to their own object folder.
    with_status = name == 'common' or os.environ.get('SSBU_FIGHTER_STATUS') == '1'
    sdk = os.environ.get('SSBU_FIGHTER_SDK') or 'sdk_generated'
    if sdk != 'sdk_generated' or (with_status and name != 'common'):
        objdir = os.path.join(STUDY, 'obj_fighters', '%s_%s%s' % (name, sdk, '_status' if with_status else ''))
        os.makedirs(objdir, exist_ok=True)
    if froot:
        objdir = objdir + '_root_' + froot.replace('\\', '_').replace('/', '_')
        os.makedirs(objdir, exist_ok=True)
    sources = [os.path.join(src_rt, 'fighter_rt.cpp')]
    for root, dirs, files in os.walk(fdir):
        if not with_status and os.path.relpath(root, fdir).split(os.sep)[0] == 'status':
            continue
        sources += [os.path.join(root, f) for f in sorted(files) if f.endswith('.cpp')]
    gen = os.path.join(STUDY, 'fighters', sdk)                  # lua_bind.h, lua_const.h, fs_syms.inc: made by gen_sdk.py from the game
    bind_src = os.path.join(fdir, 'generated', 'bindings.inc')
    status_binds = os.path.join(fdir, 'generated', 'status_bindings.inc')
    merged_dir = None
    if with_status and name != 'common' and os.path.exists(status_binds):
        merged_dir = os.path.join(objdir, 'status_bind')        # a build product: ACMD bindings + status bindings
        os.makedirs(merged_dir, exist_ok=True)
        text = (open(bind_src).read() if os.path.exists(bind_src) else '') + open(status_binds).read()
        bind_src = os.path.join(merged_dir, 'bindings.inc')
        if not os.path.exists(bind_src) or open(bind_src).read() != text:
            with open(bind_src, 'w', newline='\n') as f:
                f.write(text)
    # S10 (part D): a function defined in the sources that the game does not have (no line in the binding files) is
    # NEW: it gets a synthetic place in the module (an odd offset: never a function entry; nnro.c hands a call of
    # such an address to the fighter host) and the constant FS_OFF_<name>, so status_function(name), the install
    # tables and the script registration take it like any other. Build products only; no generated file is edited.
    new_flags = []
    bound = set(re.findall(r'_BIND\(\s*\w+\s*,\s*(\w+)\s*,', open(bind_src).read())) if os.path.exists(bind_src) else set()
    new = []
    for s in sources[1:]:
        for m in re.finditer(r'^(ACMD|L2C_(?:VOID_)?FUNCTION\d?)\(\s*\w+\s*,\s*(\w+)', open(s, errors='replace').read(), re.M):
            if m.group(2) not in bound and m.group(2) not in [n for _, n in new]:
                new.append(('ACMD' if m.group(1) == 'ACMD' else 'L2C', m.group(2)))
    if new and os.environ.get('SSBU_FIGHTER_NEW', '1') != '0':
        if not merged_dir:
            merged_dir = os.path.join(objdir, 'status_bind')
            os.makedirs(merged_dir, exist_ok=True)
        text = (open(bind_src).read() if os.path.exists(bind_src) else '') + '// S10: functions that exist only in the source (synthetic places)\n'
        text += ''.join('%s_BIND(%s, %s, 0x%x)\n' % (k, name, n, 1 + 4 * i) for i, (k, n) in enumerate(new))
        head = '// build product (build_fighter.py): places of the functions that exist only in the source\n#include <stdint.h>\nenum : uint32_t {\n'
        head += ''.join('    FS_OFF_%s = 0x%x,\n' % (n, 1 + 4 * i) for i, (k, n) in enumerate(new)) + '};\n'
        for path, body in ((os.path.join(merged_dir, 'bindings.inc'), text), (os.path.join(merged_dir, 'fs_new_functions.h'), head)):
            if not os.path.exists(path) or open(path).read() != body:
                with open(path, 'w', newline='\n') as f:
                    f.write(body)
        bind_src = os.path.join(merged_dir, 'bindings.inc')
        new_flags = ['-include', os.path.join(merged_dir, 'fs_new_functions.h')]
        print('%s: %d functions exist only in the source: %s' % (name, len(new), ' '.join(n for k, n in new)[:400]))
    # S11 (part 4): registry of NEW work variables. `FS_NEW_WORK_VAR(INSTANCE|STATUS, INT|FLOAT|FLAG, NAME);` in a source
    # or header of the fighter declares a variable the game does not have; it gets the first free index of that kind
    # (above every index a named constant of ANY fighter uses, so nothing named can collide; if that does not fit,
    # above the indices of the shared machine + this fighter) and the build product fs_new_work.h defines NAME.
    # The storage is NOT enlarged: more variables than the free room is a build error that states the limit.
    work_new = []
    for root, dirs, files in os.walk(fdir):
        for fn in sorted(files):
            if fn.endswith(('.cpp', '.h')):
                for m in re.finditer(r'^\s*FS_NEW_WORK_VAR\(\s*(INSTANCE|STATUS)\s*,\s*(INT|FLOAT|FLAG)\s*,\s*(\w+)\s*\)', open(os.path.join(root, fn), errors='replace').read(), re.M):
                    if m.groups() not in work_new:
                        work_new.append(m.groups())
    if work_new:
        import luaconst
        # capacity of the work areas: read from Mario's work module in a match (S11, tests\logs\s11_w1.log): area + 8 / + 0x18 / + 0x28
        CAP = {('INSTANCE', 'FLOAT'): 120, ('INSTANCE', 'INT'): 270, ('INSTANCE', 'FLAG'): 288, ('STATUS', 'FLOAT'): 40, ('STATUS', 'INT'): 32, ('STATUS', 'FLAG'): 96}
        TAG = {'FLOAT': 0, 'INT': 1, 'FLAG': 2}
        others = set(d.upper() for d in os.listdir(os.path.join(STUDY, 'fighters')) if os.path.isdir(os.path.join(STUDY, 'fighters', d))) - {name.upper(), 'COMMON'}
        used_all, used_own = {k: -1 for k in CAP}, {k: -1 for k in CAP}
        for nm, v in luaconst.table_names():
            if not nm or v is None or not nm.startswith('FIGHTER_') or (v & 0xffffff) >= 0x1000 or v < 0 or (v >> 28) > 2 or ((v >> 24) & 0xf) > 1:
                continue
            ty = ('FLOAT', 'INT', 'FLAG')[v >> 28]
            if not re.search(r'WORK_(ID_)?%s_' % ty, nm) or 'KEEP_FLAG' in nm:
                continue
            sc = 'STATUS' if (v >> 24) & 0xf else 'INSTANCE'
            if (sc == 'INSTANCE') != ('INSTANCE_WORK' in nm):
                continue
            used_all[(sc, ty)] = max(used_all[(sc, ty)], v & 0xffffff)
            if nm.split('_')[1] not in others:
                used_own[(sc, ty)] = max(used_own[(sc, ty)], v & 0xffffff)
        text = '// build product (build_fighter.py): ids of the NEW work variables declared with FS_NEW_WORK_VAR\n#include <stdint.h>\n'
        nxt = {}
        for sc, ty, nm in work_new:
            k = (sc, ty)
            want = sum(1 for a, b, c in work_new if (a, b) == k)
            base = used_all[k] + 1 if used_all[k] + want < CAP[k] else used_own[k] + 1
            idx = nxt.get(k, base)
            if idx >= CAP[k]:
                print('%s: FS_NEW_WORK_VAR(%s, %s, %s): no room: the game\'s %s %s storage has %d places, the shared machine + this fighter use indices up to %d, '
                      'all fighters up to %d; %d new variables asked' % (name, sc, ty, nm, sc.lower(), ty.lower(), CAP[k], used_own[k], used_all[k], want))
                return 1
            nxt[k] = idx + 1
            vid = (TAG[ty] << 28) | ((1 if sc == 'STATUS' else 0) << 24) | idx
            text += 'static const int32_t %s = 0x%X;      // %s %s, index %d of %d (named constants use up to %d; this fighter + shared up to %d)\n' % (nm, vid, sc.lower(), ty.lower(), idx, CAP[k], used_all[k], used_own[k])
        text += 'static const int32_t FS_NEW_WORK_CHECK[6] = {%s};      // highest new index + 1: instance float, int, flag, status float, int, flag (fs_new_work_fits)\n' % ', '.join(
            str(nxt.get(k, 0)) for k in (('INSTANCE', 'FLOAT'), ('INSTANCE', 'INT'), ('INSTANCE', 'FLAG'), ('STATUS', 'FLOAT'), ('STATUS', 'INT'), ('STATUS', 'FLAG')))
        if not merged_dir:
            merged_dir = os.path.join(objdir, 'status_bind')
            os.makedirs(merged_dir, exist_ok=True)
        path = os.path.join(merged_dir, 'fs_new_work.h')
        if not os.path.exists(path) or open(path).read() != text:
            with open(path, 'w', newline='\n') as f:
                f.write(text)
        new_flags += ['-include', path]
        print('%s: %d new work variables: %s' % (name, len(work_new), ' '.join('%s=%s' % (c, re.search(r'%s = (0x[0-9A-F]+)' % c, text).group(1)) for a, b, c in work_new)))
    headers = [os.path.join(inc, f) for f in os.listdir(inc)] + [os.path.join(gen, f) for f in os.listdir(gen)] + [bind_src]
    if with_status and os.path.exists(os.path.join(fdir, 'generated', 'status_local.h')):
        headers.append(os.path.join(fdir, 'generated', 'status_local.h'))
    dep = newest(headers)
    flags = ['-x', 'c++', '-std=c++14', '-O1', '-c', '-fno-exceptions', '-fno-rtti', '-Wall', '-Wno-unused-parameter', '-Wno-unused-variable',
             '-Wno-unused-const-variable', '-Wno-unused-function', '-I', inc, '-I', gen, '-I', src_rt, '-I', os.path.join(fdir, 'generated')] + new_flags
    # S6: SSBU_FIGHTER_SCRIBBLE=1: a TEST build (own object folder; put it in its own SSBU_FIGHTER_BIN) in which the dead
    # stack is overwritten before every game call (fighter_sdk.h FS_SCRIBBLE); =byvalue also puts the S4 bug back, to
    # show that the offline test then reports it. Never install such a DLL.
    scribble = os.environ.get('SSBU_FIGHTER_SCRIBBLE')
    if scribble:
        # =byvalue_quiet: the bug without the scribble (the control: the offline test of S4, which did not see it)
        flags += ([] if scribble == 'byvalue_quiet' else ['-DFS_SCRIBBLE']) + (['-DFS_TEST_BYVALUE'] if scribble.startswith('byvalue') else [])
        objdir = objdir + '_scribble_' + scribble         # S8: next to the object folder in use (the default one: obj_fighters\<name>_scribble_<x>, as before)
        os.makedirs(objdir, exist_ok=True)
    jobs = []
    objs = []
    # S6: SSBU_FIGHTER_ONLY=<file, one function name per line>: only these functions are BOUND (run as source); the
    # others are compiled but the game keeps running their lifted originals. Used to install only what the real-call
    # differential has proven. The filtered binding list is a build product (obj_fighters\<name>\only\bindings.inc).
    only = os.environ.get('SSBU_FIGHTER_ONLY')
    only_dir = os.path.join(objdir, 'only')
    if only:
        # a line is "<name> 0x<offset>" (one binding: a name can be bound at two addresses) or "<name>" (all its bindings)
        with open(only) as f:
            keep = set(tuple(l.split()) for l in f if l.strip())
        os.makedirs(only_dir, exist_ok=True)
        kept = 0
        with open(bind_src) as f, open(os.path.join(only_dir, 'bindings.inc'), 'w') as g:
            for line in f:
                parts = line.split(',')
                if len(parts) >= 3:
                    ident, off = parts[1].strip(), '0x%x' % int(parts[2].strip().rstrip(')'), 16)
                    if (ident,) not in keep and (ident, off) not in keep:
                        continue
                    kept += 1
                g.write(line)
        print('%s: SSBU_FIGHTER_ONLY: %d bindings kept for %d lines of the list' % (name, kept, len(keep)))
    for s in sources:
        o = os.path.join(objdir, os.path.relpath(s, STUDY).replace(os.sep, '_')[:-4] + '.obj')
        rt_only = only and os.path.basename(s) == 'fighter_rt.cpp'
        if rt_only:
            o = o[:-4] + '.only.obj'
        objs.append(o)
        if rt_only or not os.path.exists(o) or os.path.getmtime(o) < max(os.path.getmtime(s), dep):
            jobs.append((s, o))

    def compile_one(job):
        extra = ['-I', only_dir] if job[1].endswith('.only.obj') else []
        if merged_dir and os.path.basename(job[0]) == 'fighter_rt.cpp':
            extra += ['-I', merged_dir]                  # S8: found before generated\bindings.inc (the -I of flags comes later)
        r = subprocess.run([CLANG] + extra + flags + [job[0], '-o', job[1]], capture_output=True, text=True)
        return job[0], r.returncode, (r.stdout + r.stderr)[-6000:]

    failed = 0
    with concurrent.futures.ThreadPoolExecutor(int(os.environ.get('SSBU_BUILD_JOBS') or 8)) as pool:      # S18: SSBU_BUILD_JOBS=<n> compiles of one fighter at a time (default 8, as before)
        for s, code, err in pool.map(compile_one, jobs):
            if code or err.strip():
                print('%s %s\n%s' % ('FAILED' if code else 'warnings in', os.path.relpath(s, STUDY), err))
            failed += 1 if code else 0
    if failed:
        return 1
    dll = os.path.join(bindir, name + '.dll')
    link = [CLANG, '-shared'] + objs + ['-o', dll]
    if sum(len(a) + 3 for a in link) > 30000:             # S8: a fighter with hundreds of status files (kirby): Windows' command-line limit
        rsp = os.path.join(objdir, 'link.rsp')
        with open(rsp, 'w') as f:
            f.write('\n'.join('"%s"' % o.replace('\\', '/') for o in objs))
        link = [CLANG, '-shared', '@' + rsp, '-o', dll]
    r = subprocess.run(link, capture_output=True, text=True)
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
