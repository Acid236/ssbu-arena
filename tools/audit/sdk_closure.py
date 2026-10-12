"""For every import of the game: what its real implementation in sdk.elf needs.
    python tools_audit/sdk_closure.py > tools_audit/out/sdk_closure.tsv
columns: name, in_sdk, functions in the call closure, instructions, untranslated, svc, writable-data refs (.data/.bss
addresses materialised by adrp), host callees (SDK exports the game imports, cut to the host handler), traps."""
import os, sys, struct, re, io, contextlib
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE); os.chdir(HERE)
ARGS = sys.argv[1:]
sys.argv = ['sdklift.py', 'none']
import sdklift as S
R = S.R
d = S.d
shoff, = struct.unpack_from('<Q', d, 0x28); shnum, shstrndx = struct.unpack_from('<HH', d, 0x3c)
secs = [struct.unpack_from('<IIQQQQIIQQ', d, shoff + i * 64) for i in range(shnum)]
st = d[secs[shstrndx][4]:secs[shstrndx][4] + secs[shstrndx][5]]
sec = {st[s[0]:st.index(b'\0', s[0])].decode(): (s[3], s[5]) for s in secs}
def where(a):
    a -= S.SDK_BASE
    for n, (va, sz) in sec.items():
        if n and va <= a < va + sz: return n
    return '?'
def data_refs(env, a):
    end = env.extent(a); page = {}; out = set()
    for pc in range(a, end, 4):
        w = R.word(pc)
        if (w & 0x9f000000) == 0x90000000:
            imm = R.sext((((w >> 5) & 0x7ffff) << 2) | ((w >> 29) & 3), 21)
            page[w & 31] = (pc & ~0xfff) + (imm << 12)
        elif (w & 0xffc00000) == 0x91000000 and ((w >> 5) & 31) in page:
            out.add(page[(w >> 5) & 31] + ((w >> 10) & 0xfff))
        elif (w & 0x3b000000) == 0x39000000 and ((w >> 5) & 31) in page:      # ldr/str [xn, #imm]
            size = w >> 30
            out.add(page[(w >> 5) & 31] + (((w >> 10) & 0xfff) << size))
    return out
names = [l.split('\t')[1] for l in open(os.path.join(HERE, 'tools_audit', 'out', 'bind.tsv')) if l.startswith('import\t') and l.split('\t')[4] != '-1']
if len(ARGS) > 0: names = ARGS
cfg = S.Config()
_orig = R.Env.compute_starts
_cache = {}
def _cached(self):
    if 'starts' not in _cache:
        _orig(self); _cache['starts'] = list(self.starts)
    self.starts = list(_cache['starts'])
R.Env.compute_starts = _cached
print('# name\tin_sdk\tfns\tinsns\tbad\tsvc\twritable_refs\thost_callees\ttraps')
for n in names:
    if n not in S.syms or S.syms[n][2] != 2: print('%s\t0' % n); continue
    root = S.SDK_BASE + S.syms[n][0]
    cfg.lift = set([n])
    try:
        env, bodies, done, total, bad, svc = S.closure(cfg, [root], 20000)
    except Exception as e:
        print('%s\t1\tERROR %s' % (n, e)); continue
    wr = set()
    for a in done:
        for t in data_refs(env, a):
            s = where(t)
            if s in ('.bss', '.data', '.got', '.got.plt') or s == '?': wr.add('%s+%x' % (s, t - S.SDK_BASE))
    traps = sorted(set(re.findall(r'sdk_trap_call\(c, "([^"]*)"\)', '\n'.join(bodies))))
    print('%s\t1\t%d\t%d\t%d\t%d\t%s\t%s\t%s' % (n, len(done), total, len(bad), len(svc), ' '.join(sorted(wr)[:8]) + (' ...' if len(wr) > 8 else ''), ' '.join(env.host_names), ' '.join(t[:40] for t in traps)))
    sys.stdout.flush()
