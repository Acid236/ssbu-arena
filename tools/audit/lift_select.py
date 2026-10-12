"""Select the imports whose real SDK code replaces a host re-implementation, and write
   * the managed block of sdklift_roots.txt (roots + `lift` + `cut` for interposed symbols)
   * sdklift_install.h (names nnsdk2.c installs over the host handlers)
    python tools_audit/lift_select.py        then: python sdklift.py gen
Selection = names of tools_audit/out/pure_names.txt (sdk_closure.py) matching the families below. A family is
taken only as a whole: mixing lifted and host members of one class would mix two object layouts."""
import os, re, struct, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
C_NAMES = """acosf asinf atan2f atanf ceilf cosf erfcf exp2 exp2f expf floorf fmod fmodf frexpf log10f log2f logf modff pow powf sin sinf
sqrt sqrtf tanf __floatditf __lttf2 __multf3 __subtf3
memchr memcmp memcpy memmove memset memset_s strcat strchr strcmp strcpy strcspn strdup strlen strncasecmp strcasecmp strncat strncmp
strncpy strnlen strpbrk strrchr strspn strstr wmemcpy
isalnum iscntrl ispunct isspace isxdigit tolower toupper atof atoi atol strtof strtol strtoul strtoull bsearch qsort ffsl
snprintf sprintf vsnprintf nnResultGetDescription nnResultGetModule nnResultIsFailure nnResultIsSuccess
__errno_location nnsocketInetHtons nnsocketInetNtohs time clock gettimeofday
pthread_mutex_init pthread_mutex_destroy pthread_mutex_lock pthread_mutex_unlock pthread_mutex_trylock pthread_mutexattr_init
pthread_mutexattr_settype pthread_mutexattr_destroy pthread_cond_broadcast pthread_cond_destroy pthread_join""".split()
# self-contained although they keep state: the state is a static of the SDK image that needs no start-up code
STATE_OK = "rand srand sscanf strcoll strerror getenv swprintf gmtime localeconv".split()
FAMILIES = [
    r'^_ZNK?2nn4util(16BinaryFileHeader|17BinaryBlockHeader|15RelocationTable|11ReferSymbol|8BitArray|27ConvertCharacterUtf8ToUtf32|30PickOutCharacterFromUtf8String|8SNPrintf|9VSNPrintf)',
    r'^_ZNK?2nn3err18ErrorResultVariant',
    r'^_ZNK?2nn3mii6detail(15BufferAllocator|25CalculateSizeAndAlignment)',
    r'^_ZN2nn3ldn15MakeIpv4Address', r'^_ZN2nn6socket9Inet(Hton|Ntoh)[sl]E',
    r'^_ZN2nn4time(11IsValidDateEiii|12GetDayOfWeekEiii|18ToPosixTimeFromUtc|19ToCalendarTimeInUtc|gtERKNS0_12CalendarTime)',
    r'^_ZN2nn5prepo10PlayReport(C1Ev|10SetEventId|9SetBuffer|3Add)',
    r'^_ZN2nn6crypto6detail7Md5Impl',     # GenerateSha1Hash uses the ARMv8 SHA-1 instructions, which the lifter does not translate: stays on the host (CryptoAPI)
    r'^_ZNK?2nn7friends(6FriendC1Ev|7ProfileC1Ev|12UserPresenceC1Ev|6Friend7IsValidEv|7Profile7IsValidEv|12AsyncContextC1Ev|17NotificationQueueC1Ev)',
    r'^_ZN2nn4time13ClockSnapshotC1Ev$',     # [sdk 0x38fc00] zeroes 0xd0 bytes and writes the default calendar / "UTC" fields; no service
    r'^_ZN2nn3hid2[35]Get(SixAxisSensor|VibrationDevice)HandlesE',
    r'^_ZN2nn4lmem(15CreateFrameHeap|21AllocateFromFrameHeap|16DestroyFrameHeap)',
    r'^_ZN2nn2os(13ConvertToTickE|17ConvertToTimeSpanE|22GetSystemTickFrequencyEv)',
    r'^_ZNK?St3__112basic_stringIcNS_11char_traitsIcEENS_9allocatorIcEEE', r'^_ZNSt3__19to_stringE[ij]$', r'^_ZNSt3__1plIcNS_11char_traitsIcEENS_9allocatorIcEEEENS_12basic_string',
    r'^_ZNSt3__112__next_primeEm$', r'^_ZNSt3__16__sortIRNS_6__lessI', r'^_ZNSt3__15alignEmmRPvRm$',
    r'^_ZNK?St3__119__shared_weak_count(4lockEv|14__release_weakEv|D2Ev|13__get_deleter)', r'^_ZNSt3__114__shared_countD2Ev$',
    # libc++ mutex / recursive_mutex / condition_variable: the library's own code down to nn::os (host)
    r'^_ZNSt3__1(5mutex|15recursive_mutex|18condition_variable)', r'^_ZNSt3__16chrono12(steady|system)_clock3nowEv$',
    r'^_ZN2nn7account9GetUserIdEPNS0_3UidERKNS0_10UserHandleE$',
]
# Families that reference writable SDK data, taken after reading the code: the data is plain zero-initialised .bss that
# needs no start-up code. (regex, what the data is)
STATE_FAMILIES = [
    (r'^_ZNK?2nn3mem19NumberLineAllocator', '[sdk 0x2e7f0c, 0x2e8328, ...] the only global is the pair of statistics counters at .bss+0xcb2c48 (count, bytes); the '
     'allocator state lives in the block obtained from the allocation callback the caller passes'),
    (r'^_ZNK?2nn3mem17StandardAllocator', 'nlib nmalloc: its globals are lazily initialised .bss (TLS key, heap list); the kernel and nn::os internals under it are cut '
     'to host handlers in nnsdk2.c (sdk_host_override)'),
]
rows = [l.rstrip('\n').split('\t') for l in open(os.path.join(HERE, 'tools_audit', 'out', 'pure_names.txt'))]
pure = {r[1] for r in rows if r[0] == 'PURE'}
state = {r[1] for r in rows if r[0] == 'STATE'}
sel, skipped = [], []
for n in C_NAMES:
    (sel if n in pure else skipped).append(n)
for n in STATE_OK:
    (sel if n in state or n in pure else skipped).append(n)
for rx in FAMILIES:
    members = sorted(n for n in pure | state if re.search(rx, n))
    bad = [n for n in members if n in state]
    if bad: skipped += ['FAMILY %s: not self-contained: %s' % (rx, ' '.join(bad))]
    else: sel += members
for rx, why in STATE_FAMILIES:
    sel += sorted(n for n in pure | state if re.search(rx, n))
sel = sorted(set(sel))
# symbols the GAME defines and the SDK also defines: on the console the SDK's own references bind to the game's
# definition (the application is first in the lookup order), so lifted SDK code must call the game's function
game_defined = set(re.findall(r'\{ "([^"]+)", 0x[0-9a-f]+ULL, 1 \}', open(os.path.join(HERE, 'gen_eh', 'imports.c'), errors='replace').read()))
sys.path.insert(0, HERE); os.chdir(HERE); sys.argv = ['x', 'none']
import sdklift as S
interposed = sorted(n for n in game_defined if n in S.syms and S.syms[n][2] == 2)
p = os.path.join(HERE, 'sdklift_roots.txt')
txt = open(p).read()
txt = re.sub(r'\n# >>> audit block.*?# <<< audit block\n', '\n', txt, flags=re.S).rstrip('\n') + '\n'
blk = ['', '# >>> audit block (generated by tools_audit/lift_select.py; do not edit by hand)',
       '# functions the game defines itself: the SDK\'s references to them go to the game (ELF interposition)']
blk += ['cut %s' % n for n in interposed if n not in sel]
blk += ['# real SDK code installed over a host re-implementation (plan/FAKE_AUDIT.md, part 2)']
for n in sel: blk += [n, 'lift %s' % n]
blk += ['# <<< audit block', '']
open(p, 'w', newline='\n').write(txt + '\n'.join(blk))
with open(os.path.join(HERE, 'sdklift_install.h'), 'w', newline='\n') as f:
    f.write('/* generated by tools_audit/lift_select.py: imports whose handler is the real code lifted from sdk.elf,\n * installed over the host re-implementation by nnsdk2.c */\nstatic const char *const sdk_install_names[] = {\n')
    for n in sel: f.write('    "%s",\n' % n)
    f.write('};\n')
print('selected %d names; interposed symbols cut to the game: %d (%s)' % (len(sel), len(interposed), ' '.join(interposed)[:400]))
for s in skipped: print('  skipped:', s[:300])
