/* nvn_vk_wd.c (session 12; included at the end of nvn_vk_draw.c: not a build unit of its own).
 *
 * THE FREEZE WATCHDOG. On by default in the Vulkan renderer (SSBU_VK_WATCHDOG=0 off, =<seconds> another limit; default 5).
 * A thread looks twice a second at the time of the last frame that reached the window. When no frame was presented for the
 * limit while the process is alive, a report is printed and appended to <exe name>_freeze.txt next to the exe:
 *   - what the renderer was doing (frames, present attempts, failures, queues of the workers, the preparation's state);
 *   - our locks (g_sh_lock, g_gpl_lock): the thread that owns each;
 *   - every wait of ours that was entered through WD_SLEEP (function, line, how long);
 *   - EVERY thread of the process: its name (guest thread name / render / main), whether it used CPU in the last 300 ms,
 *     and its call stack: host functions by name when <exe name>.map is next to the exe (build.py link writes it; without
 *     it: module + offset), functions of the lifted game as "guest f_<address>", system and driver DLLs by nearest export.
 * The report is repeated after 4x the time (5 s, 20 s, 80 s, ...), at most 6 times a run; a line says when frames come back.
 * With SSBU_MINIDUMP=freeze the first two reports of 5 s or more also write a minidump (<exe name>_freeze_last.dmp; hostrt.c
 * diag_minidump); the 1 s reports never do (a normal start has them). With SSBU_REPORT_DIR set, the report and the dump go
 * to that folder instead of next to the exe.
 * It only reads: nothing is unblocked or killed. Threads are suspended one at a time for the few microseconds of the unwind;
 * nothing is printed or allocated while one is suspended. */
#include <tlhelp32.h>
#ifndef _WIN32
#include <dirent.h>
#endif
const char *guest_thread_name_of(DWORD tid);       /* os_threads.c */
int diag_report_path(char *out, size_t size, const char *suffix);     /* hostrt.c */
int diag_minidump(EXCEPTION_POINTERS *ep, const char *why);
/* fn_table / fn_table_count (runtime.h; -Dfn_table=(*game_fn_table_p)): the lifted game's functions, by guest address */
static volatile LONG g_wd_quit;
static HANDLE g_wd_thread;
static FILE *g_wd_fp;
static DWORD g_wd_main_tid;
typedef struct { uint32_t rva; char name[68]; } WdSym;
static WdSym *g_wd_sym;
static int g_wd_nsym, g_wd_map_tried;
static void wdp(const char *fmt, ...) {
    char b[1400];
    va_list ap;
    va_start(ap, fmt); vsnprintf(b, sizeof b, fmt, ap); va_end(ap);
    fputs(b, stdout);
    if (g_wd_fp) fputs(b, g_wd_fp);
}
static int wd_sym_cmp(const void *a, const void *b) { const WdSym *x = a, *y = b; return x->rva < y->rva ? -1 : x->rva > y->rva; }
#ifdef _WIN32
static void wd_map_load(void) {                    /* the linker's map of this exe, if it is there: "<exe without .exe>.map" */
    char path[MAX_PATH + 8], ln[1024], t1[64], t2[512], t3[64];
    unsigned long long base = 0x140000000ull;
    g_wd_map_tried = 1;
    DWORD n = GetModuleFileNameA(NULL, path, MAX_PATH);
    if (n < 5) return;
    strcpy(path + n - 4, ".map");
    FILE *fp = fopen(path, "rb");
    if (!fp) return;
    int cap = 0;
    while (fgets(ln, sizeof ln, fp)) {
        const char *p = strstr(ln, "Preferred load address is ");
        if (p) { base = strtoull(p + 26, NULL, 16); continue; }
        if (sscanf(ln, " %63s %511s %63s", t1, t2, t3) != 3 || strlen(t1) != 13 || t1[4] != ':' || strlen(t3) != 16) continue;
        unsigned long long va = strtoull(t3, NULL, 16);
        if (va <= base || va - base > 0x7fffffffull) continue;
        if (g_wd_nsym == cap) { cap = cap ? cap * 2 : 8192; g_wd_sym = realloc(g_wd_sym, (size_t)cap * sizeof *g_wd_sym); if (!g_wd_sym) { g_wd_nsym = 0; break; } }
        g_wd_sym[g_wd_nsym].rva = (uint32_t)(va - base);
        snprintf(g_wd_sym[g_wd_nsym].name, sizeof g_wd_sym[0].name, "%s", t2);
        g_wd_nsym++;
    }
    fclose(fp);
    if (g_wd_nsym) qsort(g_wd_sym, (size_t)g_wd_nsym, sizeof *g_wd_sym, wd_sym_cmp);
}
static void wd_export(HMODULE m, uint32_t rva, char *out, size_t n) {      /* the nearest exported name at or below rva */
    const uint8_t *b = (const uint8_t *)m;
    const IMAGE_DOS_HEADER *dh = (const IMAGE_DOS_HEADER *)b;
    out[0] = 0;
    if (dh->e_magic != IMAGE_DOS_SIGNATURE) return;
    const IMAGE_NT_HEADERS64 *nt = (const IMAGE_NT_HEADERS64 *)(b + dh->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE || nt->OptionalHeader.NumberOfRvaAndSizes < 1) return;
    IMAGE_DATA_DIRECTORY dd = nt->OptionalHeader.DataDirectory[0];
    if (!dd.VirtualAddress || !dd.Size) return;
    const IMAGE_EXPORT_DIRECTORY *ed = (const IMAGE_EXPORT_DIRECTORY *)(b + dd.VirtualAddress);
    const uint32_t *fn = (const uint32_t *)(b + ed->AddressOfFunctions), *nm = (const uint32_t *)(b + ed->AddressOfNames);
    const uint16_t *od = (const uint16_t *)(b + ed->AddressOfNameOrdinals);
    uint32_t best = 0;
    const char *bn = NULL;
    for (uint32_t i = 0; i < ed->NumberOfNames; i++) {
        uint32_t f = od[i] < ed->NumberOfFunctions ? fn[od[i]] : 0;
        if (!f || f > rva || f < best || (f >= dd.VirtualAddress && f < dd.VirtualAddress + dd.Size)) continue;
        best = f; bn = (const char *)(b + nm[i]);
    }
    if (bn) snprintf(out, n, "%.60s+0x%x", bn, (unsigned)(rva - best));
}
static void wd_addr(uint64_t pc, char *out, size_t n) {
    HMODULE m = NULL, exe = GetModuleHandleA(NULL), game = NULL;
    char mod[MAX_PATH] = "", sym[96] = "";
    if (!GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCSTR)(uintptr_t)pc, &m) || !m) { snprintf(out, n, "%llx (in no module)", (unsigned long long)pc); return; }
    GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCSTR)(uintptr_t)&fn_table[0], &game);
    GetModuleFileNameA(m, mod, sizeof mod);
    const char *bn = strrchr(mod, '\\');
    bn = bn ? bn + 1 : mod;
    uint32_t rva = (uint32_t)(pc - (uint64_t)(uintptr_t)m);
    if (m == exe) {
        if (!g_wd_map_tried) wd_map_load();
        int lo = 0, hi = g_wd_nsym - 1, at = -1;
        while (lo <= hi) { int mid = (lo + hi) / 2; if (g_wd_sym[mid].rva <= rva) { at = mid; lo = mid + 1; } else hi = mid - 1; }
        if (at >= 0) snprintf(sym, sizeof sym, "%s+0x%x", g_wd_sym[at].name, (unsigned)(rva - g_wd_sym[at].rva));
    } else if (m == game) {
        uint64_t best = 0, guest = 0;
        for (int i = 0; i < fn_table_count; i++) { uint64_t f = (uint64_t)(uintptr_t)fn_table[i].fn; if (f <= pc && f > best) { best = f; guest = fn_table[i].addr; } }
        if (best && pc - best < 0x400000) snprintf(sym, sizeof sym, "guest f_%llx (host +0x%x)", (unsigned long long)guest, (unsigned)(pc - best));
    } else wd_export(m, rva, sym, sizeof sym);
    snprintf(out, n, "%s+0x%x%s%s%s", bn, (unsigned)rva, sym[0] ? " [" : "", sym, sym[0] ? "]" : "");
}
/* The return addresses of another thread (suspended by the caller). Unwind data that cannot be read ends the walk. */
static int wd_walk(CONTEXT *ctx, uint64_t *pcs, int max) {
    int n = 0;
    __try {
        while (n < max && ctx->Rip) {
            DWORD64 base = 0, ef = 0;
            void *hd = NULL;
            pcs[n++] = ctx->Rip;
            PRUNTIME_FUNCTION rf = RtlLookupFunctionEntry(ctx->Rip, &base, NULL);
            if (!rf) { ctx->Rip = *(const DWORD64 *)(uintptr_t)ctx->Rsp; ctx->Rsp += 8; }      /* a leaf function: the return address is at the stack pointer */
            else RtlVirtualUnwind(0 /* UNW_FLAG_NHANDLER */, base, ctx->Rip, rf, ctx, &hd, &ef, NULL);
        }
    } __except (1) { }
    return n;
}
#endif
static const char *wd_tname(DWORD tid, char *buf, size_t n) {
    const char *g = tid == g_render_tid ? "render (host)" : tid == g_wd_main_tid ? "the process's first thread (boot.c main: waits for the game)" : guest_thread_name_of(tid);
    if (g) return g;
    for (int i = 0; i < g_pw_nthread; i++) if (g_pw_thread[i] && GetThreadId(g_pw_thread[i]) == tid) { snprintf(buf, n, "shader worker %d (host)", i); return buf; }
    if (g_prep_thread && GetThreadId(g_prep_thread) == tid) return "preparation (host)";
    return "host thread";
}
static void wd_owner(const char *name, CRITICAL_SECTION *cs) {
    char tb[48];
#ifdef _WIN32
    DWORD o = (DWORD)(uintptr_t)cs->OwningThread;
    if (o) wdp("  lock %s: OWNED by thread %lu (%s), recursion %ld, lock count %ld\n", name, (unsigned long)o, wd_tname(o, tb, sizeof tb), (long)cs->RecursionCount, (long)cs->LockCount);
#elif defined(__APPLE__)
    DWORD o = 0;                                                           /* macOS: a pthread mutex does not show its owner */
    (void)cs; (void)tb;
    if (o) wdp("  lock %s: owned\n", name);
#else
    DWORD o = (DWORD)cs->__data.__owner;                                   /* glibc: the owner's tid */
    if (o) wdp("  lock %s: OWNED by thread %lu (%s), recursion %ld\n", name, (unsigned long)o, wd_tname(o, tb, sizeof tb), (long)cs->__data.__count);
#endif
    else wdp("  lock %s: free\n", name);
}
unsigned long nvn_front_present_tid(void);         /* nvn_gl.c */
static void wd_dump(double stall_s, LONG64 tries_since) {
    static struct { DWORD tid; ULONGLONG cpu0, cpu1, born; int prio, nfr; uint64_t pc[28]; } th[400];
    char path[2 * MAX_PATH], tb[48], ab[400];
    LARGE_INTEGER fq; QueryPerformanceFrequency(&fq);
    SYSTEMTIME st; GetLocalTime(&st);
    DWORD me = GetCurrentThreadId(), pid = GetCurrentProcessId();
    int nt = 0;
    if (diag_report_path(path, sizeof path, "_freeze.txt")) g_wd_fp = fopen(path, "ab");
    wdp("\nnvn_vk_watchdog: ======== NO FRAME PRESENTED FOR %.1f s ======== %04d-%02d-%02d %02d:%02d:%02d, process %lu, game frame %lld\n", stall_s, st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond, (unsigned long)pid, (long long)nvn_front_frame_next());
    wdp("  presents: %lld frames reached the window so far; present attempts since the last one that did: %lld (%s); frames not presented %lld, failed Vulkan calls %lld, swapchain made again %lld times; window %s\n",
        (long long)g_vk_frames, (long long)tries_since, tries_since ? "the game still presents but nothing reaches the window: see the failures" : "none: the game's present never came, or the render thread is held",
        (long long)g_vk_skipped, (long long)g_vk_errors, (long long)g_vk_recreated, IsIconic((HWND)nvn_front_hwnd()) ? "MINIMISED" : "not minimised");
    wdp("  render thread %lu, place in its present: %s; %s; fight near: %s\n", (unsigned long)g_render_tid, g_wd_where == 1 ? "the loading barrier (waits for the workers, at most 20 s)" : g_wd_where == 2 ? "vkAcquireNextImageKHR" : g_wd_where == 3 ? "blit and submit" : g_wd_where == 4 ? "vkQueuePresentKHR" : "not in a present",
        g_in_fight ? "the last frame was a FIGHT frame" : "the last frame was not a fight frame", fight_recent() ? "yes" : "no");
    wdp("  workers: %d threads; foreground jobs %lld queued / %lld done, background %lld / %lld, preparation %lld / %lld (%lld running); preparation state %d (0 not started, 1 running, 2 finished, 3 no containers, 5 store being built)%s, %d of %d containers read; loading-barrier holds %lld (time-outs %lld)\n",
        g_pw_nthread, (long long)g_jq_queued, (long long)g_jq_done, (long long)g_bq_queued, (long long)g_bq_done, (long long)g_pq_queued, (long long)g_pq_done, (long long)g_pq_running, g_prep_state, g_prep_marked ? ", marked start" : "", g_prep_read, g_prep_nfiles,
        (long long)g_bar_n, (long long)g_bar_timeout);
    wd_owner("g_sh_lock (stage, pipeline and job tables)", &g_sh_lock);
    wd_owner("g_gpl_lock (vertex-input / fragment-output libraries, universal layout)", &g_gpl_lock);
    {   int any = 0;
        for (int i = 0; i < 64; i++) {
            WdWait w = g_wd_wait[i];
            if (!w.tid) continue;
            wdp("  wait of ours: thread %lu (%s) in %s, line %d of nvn_vk_m4.c / nvn_vk_draw.c, for %.1f s\n", (unsigned long)w.tid, wd_tname((DWORD)w.tid, tb, sizeof tb), w.fn ? w.fn : "?", w.line, (double)(tk() - w.since) / (double)fq.QuadPart);
            any = 1;
        }
        if (!any) wdp("  waits of ours (stage / library / pipeline being made by another thread, queues): none entered\n");
    }
#ifdef _WIN32
    { void os_wait_print(void (*pr)(const char *fmt, ...)); os_wait_print(wdp); }       /* os_threads.c: which event each guest thread waits on, who signalled it last */
    for (int pass = 0; pass < 2; pass++) {         /* CPU time of every thread, twice, 300 ms apart: who is running and who is blocked */
        HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
        THREADENTRY32 te;
        te.dwSize = sizeof te;
        if (snap == INVALID_HANDLE_VALUE) break;
        for (BOOL ok = Thread32First(snap, &te); ok; ok = Thread32Next(snap, &te)) {
            if (te.th32OwnerProcessID != pid || te.th32ThreadID == me) continue;
            int i;
            for (i = 0; i < nt && th[i].tid != te.th32ThreadID; i++) {}
            if (i == nt) { if (pass || nt == 400) continue; th[nt].tid = te.th32ThreadID; th[nt].cpu0 = th[nt].cpu1 = 0; th[nt].nfr = 0; th[nt].prio = 0; th[nt].born = ~0ull; nt++; }
            HANDLE h = OpenThread(THREAD_QUERY_INFORMATION, FALSE, te.th32ThreadID);
            FILETIME c, e, k, u;
            if (!h) continue;
            if (GetThreadTimes(h, &c, &e, &k, &u)) { ULONGLONG cpu = (((ULONGLONG)k.dwHighDateTime << 32) | k.dwLowDateTime) + (((ULONGLONG)u.dwHighDateTime << 32) | u.dwLowDateTime); if (pass) th[i].cpu1 = cpu; else th[i].cpu0 = th[i].cpu1 = cpu; th[i].born = ((ULONGLONG)c.dwHighDateTime << 32) | c.dwLowDateTime; }
            th[i].prio = GetThreadPriority(h);
            CloseHandle(h);
        }
        CloseHandle(snap);
        if (!pass) Sleep(300);
    }
    for (int i = 0; i < nt; i++) {                 /* the stacks: one thread suspended at a time, nothing else done meanwhile */
        HANDLE h = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION, FALSE, th[i].tid);
        static CONTEXT ctx;
        if (!h) continue;
        if (SuspendThread(h) != (DWORD)-1) {
            memset(&ctx, 0, sizeof ctx);
            ctx.ContextFlags = CONTEXT_CONTROL | CONTEXT_INTEGER;
            if (GetThreadContext(h, &ctx)) th[i].nfr = wd_walk(&ctx, th[i].pc, 28);
            ResumeThread(h);
        }
        CloseHandle(h);
    }
    { ULONGLONG first = ~0ull; for (int i = 0; i < nt; i++) if (th[i].born < first) { first = th[i].born; g_wd_main_tid = th[i].tid; } }      /* the process's first thread runs the guest's main thread (boot.c) */
    wdp("  threads: %d (the watchdog's own not listed); \"cpu\" = CPU time used in 300 ms: 0.0 means blocked or idle\n", nt);
    for (int i = 0; i < nt; i++) {
        wdp("  thread %lu  %s  priority %d  cpu %.1f ms of 300\n", (unsigned long)th[i].tid, wd_tname(th[i].tid, tb, sizeof tb), th[i].prio, (double)(th[i].cpu1 - th[i].cpu0) / 10000.0);
        for (int f = 0; f < th[i].nfr; f++) { wd_addr(th[i].pc[f], ab, sizeof ab); wdp("      %2d  %s\n", f, ab); }
    }
    {   /* session 14: the game's thread again, 12 samples 50 ms apart (8 frames each): a thread that is in the SAME innermost
         * frames every time is stuck in one loop; one whose frames change below a common caller is running a longer piece
         * of work (the owner's 5 s report of 2026-10-13 was one sample of the game's menu script interpreter: not enough to tell) */
        DWORD gt = (DWORD)nvn_front_present_tid();
        HANDLE h = gt ? OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION, FALSE, gt) : NULL;
        if (h) {
            wdp("  the game's thread %lu, 12 more samples 50 ms apart:\n", (unsigned long)gt);
            for (int s = 0; s < 12; s++) {
                static CONTEXT cx2;
                uint64_t pc[8]; int nf = 0;
                if (SuspendThread(h) != (DWORD)-1) {
                    memset(&cx2, 0, sizeof cx2);
                    cx2.ContextFlags = CONTEXT_CONTROL | CONTEXT_INTEGER;
                    if (GetThreadContext(h, &cx2)) nf = wd_walk(&cx2, pc, 8);
                    ResumeThread(h);
                }
                wdp("      sample %2d:", s);
                for (int f = 0; f < nf; f++) { wd_addr(pc[f], ab, sizeof ab); wdp(" | %s", ab); }
                wdp("\n");
                Sleep(50);
            }
            CloseHandle(h);
        }
    }
#else
    /* Linux build: every thread from /proc/self/task, its name, state and CPU time used in 300 ms (no call stacks) */
    {
        long hz = sysconf(_SC_CLK_TCK);
        for (int pass = 0; pass < 2; pass++) {
            DIR *d = opendir("/proc/self/task");
            struct dirent *de;
            if (!d) break;
            while ((de = readdir(d))) {
                DWORD tid = (DWORD)strtoul(de->d_name, NULL, 10);
                if (!tid || tid == me) continue;
                char sp[96], buf[512];
                snprintf(sp, sizeof sp, "/proc/self/task/%lu/stat", (unsigned long)tid);
                FILE *f = fopen(sp, "r");
                if (!f) continue;
                size_t k = fread(buf, 1, sizeof buf - 1, f); fclose(f); buf[k] = 0;
                const char *rp = strrchr(buf, ')');
                unsigned long long ut = 0, st2 = 0; char state = '?'; int prio = 0;
                if (rp) sscanf(rp + 2, "%c %*d %*d %*d %*d %*d %*u %*u %*u %*u %*u %llu %llu %*d %*d %d", &state, &ut, &st2, &prio);
                ULONGLONG cpu = (ut + st2) * 10000000ull / (ULONGLONG)(hz > 0 ? hz : 100);
                int i;
                for (i = 0; i < nt && th[i].tid != tid; i++) {}
                if (i == nt) { if (pass || nt == 400) continue; th[nt].tid = tid; th[nt].nfr = 0; nt++; th[i].cpu0 = th[i].cpu1 = cpu; }
                else th[i].cpu1 = cpu;
                th[i].prio = state;
            }
            closedir(d);
            if (!pass) Sleep(300);
        }
        wdp("  threads: %d (the watchdog's own not listed); \"cpu\" = CPU time used in 300 ms: 0.0 means blocked or idle; no call stacks in the Linux build\n", nt);
        for (int i = 0; i < nt; i++) wdp("  thread %lu  %s  state %c  cpu %.1f ms of 300\n", (unsigned long)th[i].tid, wd_tname(th[i].tid, tb, sizeof tb), (char)th[i].prio, (double)(th[i].cpu1 - th[i].cpu0) / 10000.0);
        (void)ab;
        {   void os_wait_report(FILE *out);           /* os_threads.c: what each game thread waits on (no call stacks here) */
            os_wait_report(stdout);
            if (g_wd_fp) os_wait_report(g_wd_fp);
        }
    }
#endif
    wdp("nvn_vk_watchdog: ======== end of the report%s%s ========\n\n", g_wd_fp ? "; also appended to " : "", g_wd_fp ? path : "");
    fflush(stdout);
    if (g_wd_fp) { fclose(g_wd_fp); g_wd_fp = NULL; }
}
/* Session 13, THE STALL LOG: every gap of more than 250 ms between two frames that reached the window is appended to
 * <exe>_stalls.txt next to the exe (at most 300 lines a run; nothing is written once the file is over 2 MB), so that a
 * freeze shorter than the watchdog's first report still leaves evidence. When a gap passes 150 ms the two threads that
 * matter are sampled ONCE (suspended one at a time for the walk, as in the big report): the game thread that queues the
 * presents and the render thread, 10 return addresses each; the line is written when the next frame arrives, with the
 * length, where the render thread was in its present, whether a fight was near, the workers' queues, the page faults
 * and the CPU time of the process during the gap. Gaps while the window is minimised are not written. */
unsigned long nvn_front_present_tid(void);         /* nvn_gl.c */
#ifndef _WIN32
static void wd_stall_sample(char *out, size_t cap) { snprintf(out, cap, "    (no call stacks in the Linux build)\n"); }
#else
static void wd_stall_sample(char *out, size_t cap) {
    DWORD tids[2] = {(DWORD)nvn_front_present_tid(), g_render_tid};
    size_t at = 0;
    out[0] = 0;
    for (int i = 0; i < 2; i++) {
        static CONTEXT ctx;
        uint64_t pc[10]; int nf = 0; char ab[400];
        HANDLE h = tids[i] ? OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION, FALSE, tids[i]) : NULL;
        if (!h) continue;
        if (SuspendThread(h) != (DWORD)-1) {
            memset(&ctx, 0, sizeof ctx);
            ctx.ContextFlags = CONTEXT_CONTROL | CONTEXT_INTEGER;
            if (GetThreadContext(h, &ctx)) nf = wd_walk(&ctx, pc, 10);
            ResumeThread(h);
        }
        CloseHandle(h);
        at += (size_t)snprintf(out + at, cap - at, "    %s thread %lu:", i ? "render" : "game (queues the presents)", (unsigned long)tids[i]);
        for (int f = 0; f < nf && at + 420 < cap; f++) { wd_addr(pc[f], ab, sizeof ab); at += (size_t)snprintf(out + at, cap - at, " | %s", ab); }
        if (at + 2 < cap) { out[at++] = '\n'; out[at] = 0; }
    }
}
#endif
static void wd_stall_write(double ms, LONG64 frame, const char *sample, int where, int fight, DWORD faults, double cpu_ms, LONG64 holds) {
    static int lines;
    char path[MAX_PATH + 16];
    DWORD n = GetModuleFileNameA(NULL, path, MAX_PATH);
    SYSTEMTIME st; GetLocalTime(&st);
    if (lines >= 300 || n <= 4) return;
    strcpy(path + n - 4, "_stalls.txt");
    { WIN32_FILE_ATTRIBUTE_DATA fa; if (GetFileAttributesExA(path, GetFileExInfoStandard, &fa) && (fa.nFileSizeHigh || fa.nFileSizeLow > 2u * 1024 * 1024)) return; }
    FILE *fp = fopen(path, "ab");
    if (!fp) return;
    lines++;
    fprintf(fp, "%04d-%02d-%02d %02d:%02d:%02d pid %lu: %.0f ms without a frame, before game frame %lld (%s) | render thread at 150 ms: %s | workers: foreground %lld queued / %lld done, background %lld / %lld, preparation %lld / %lld (state %d) | barrier holds so far %lld, holds at a draw so far %lld | %lu page faults and %.0f ms of CPU (all threads) in the gap\n%s",
            st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond, (unsigned long)GetCurrentProcessId(), ms, (long long)frame, fight ? "a fight is near" : "no fight near",
            where == 1 ? "in the loading barrier (waits for the workers)" : where == 2 ? "in vkAcquireNextImageKHR" : where == 3 ? "in blit and submit" : where == 4 ? "in vkQueuePresentKHR" : "not in a present (drawing, or waiting for the game)",
            (long long)g_jq_queued, (long long)g_jq_done, (long long)g_bq_queued, (long long)g_bq_done, (long long)g_pq_queued, (long long)g_pq_done, g_prep_state, (long long)g_bar_n, (long long)holds, (unsigned long)faults, cpu_ms, sample);
    fclose(fp);
}
static void wd_proc(DWORD *faults, double *cpu_ms) {
    PROCESS_MEMORY_COUNTERS pmc; FILETIME c, e, k, u;
    memset(&pmc, 0, sizeof pmc); pmc.cb = sizeof pmc;
    GetProcessMemoryInfo(GetCurrentProcess(), &pmc, sizeof pmc);
    *faults = pmc.PageFaultCount; *cpu_ms = 0;
    if (GetProcessTimes(GetCurrentProcess(), &c, &e, &k, &u)) *cpu_ms = (double)((((ULONGLONG)k.dwHighDateTime << 32) | k.dwLowDateTime) + (((ULONGLONG)u.dwHighDateTime << 32) | u.dwLowDateTime)) / 10000.0;
}
static LONG64 g_wd_stalls, g_wd_stall_max;
static DWORD WINAPI wd_main(void *arg) {
    double limit = *(double *)arg, next = limit, reported = 0;
    LONG64 seen = 0, try0 = 0;
    int dumps = 0, sampled = 0, s_where = 0, s_fight = 0, stall_on = !(getenv("SSBU_VK_STALLLOG") && !atoi(getenv("SSBU_VK_STALLLOG")));
    static char sample[9000];
    DWORD f_prev = 0, f_seen = 0; double c_prev = 0, c_seen = 0;
    LARGE_INTEGER fq; QueryPerformanceFrequency(&fq);
    while (!g_wd_quit) {
        Sleep(50);
        LONG64 b = g_wd_beat;
        if (!b || !V.alive || g_wd_quit) continue;  /* armed by the first frame that reaches the window */
        if (b != seen) {
            double gap = seen ? (double)(b - seen) * 1000.0 / (double)fq.QuadPart : 0;
            if (reported > 0) { printf("nvn_vk_watchdog: frames reach the window again (the stall lasted between %.1f and %.1f s)\n", reported, reported + (double)(b - seen) / (double)fq.QuadPart); fflush(stdout); }
            if (stall_on && sampled && gap > 250.0) {
                DWORD f_now; double c_now; LONG64 holds = 0;
                wd_proc(&f_now, &c_now);
                for (int i = 0; i < H_N; i++) holds += g_hold_n[i];
                g_wd_stalls++; if ((LONG64)gap > g_wd_stall_max) g_wd_stall_max = (LONG64)gap;
                wd_stall_write(gap, nvn_front_frame_next(), sample, s_where, s_fight, f_now - f_seen, c_now - c_seen, holds);
            }
            seen = b; try0 = g_wd_try; next = limit; reported = 0; sampled = 0;
            f_seen = f_prev; c_seen = c_prev;
            wd_proc(&f_prev, &c_prev);              /* the counters about 0-50 ms after a frame: the base of the next gap */
            f_seen = f_prev; c_seen = c_prev;
            continue;
        }
        double s = (double)(tk() - b) / (double)fq.QuadPart;
        if (stall_on && !sampled && s > 0.150) {
            sampled = 1;
            if (IsIconic((HWND)nvn_front_hwnd())) sampled = 0, seen = 0;      /* minimised: no frames by design */
            else { s_where = g_wd_where; s_fight = fight_recent(); wd_stall_sample(sample, sizeof sample); }
        }
        static int dumps_short;                     /* reports of stalls under 5 s (loading screens can make them) have their own limit of 6 */
        if (s < next || dumps >= 6 || (s < 4.0 && dumps_short >= 6)) continue;
        if (IsIconic((HWND)nvn_front_hwnd()) && g_wd_try != try0) { next = s + limit; continue; }      /* a minimised window: presents are skipped, the game runs */
        if (s < 4.0) dumps_short++; else dumps++;
        wd_dump(s, g_wd_try - try0);
        if (s >= 4.0) { static int minidumps; if (minidumps < 2) minidumps += diag_minidump(NULL, "freeze"); }      /* only with SSBU_MINIDUMP=freeze, never for the 1 s reports */
        reported = s; next = s < 4.0 ? 5.0 : s * 4;      /* session 13: 1 s, then 5 s, 20 s, 80 s, ... */
    }
    return 0;
}
static void wd_start(void) {
    static double limit = 1.0;                      /* session 13: was 5 s; the owner's freezes left no report */
    const char *e = getenv("SSBU_VK_WATCHDOG");
    if (e) limit = atof(e);
    if (limit <= 0 || g_offline) { printf("nvn_vk_watchdog: off (SSBU_VK_WATCHDOG=0)\n"); return; }
    if (limit < 1) limit = 1;
    g_wd_thread = CreateThread(NULL, 0, wd_main, &limit, 0, NULL);
    if (g_wd_thread) SetThreadPriority(g_wd_thread, THREAD_PRIORITY_ABOVE_NORMAL);
    printf("nvn_vk_watchdog: on: a report of every thread (locks, waits, call stacks) is written to the log and to <exe>_freeze.txt when no frame reaches the window for %.0f s (SSBU_VK_WATCHDOG=<seconds>, 0 = off; SSBU_MINIDUMP=freeze: also a minidump from 5 s)\n", limit);
}
/* Session 13, TEST ONLY (SSBU_STACKS_AT=<seconds>, read in nvn_gl.c): the report of every thread once, with either renderer
 * (found with it: why SSBU_RENDERER=gl stood still at its start). The Vulkan fields of the report are zero under OpenGL. */
static DWORD WINAPI wd_once(void *a) { Sleep((DWORD)(uintptr_t)a * 1000); wd_dump(0, 0); return 0; }
void nvn_vk_stacks_at(int seconds) { HANDLE h = CreateThread(NULL, 0, wd_once, (void *)(uintptr_t)seconds, 0, NULL); if (h) CloseHandle(h); }
static void wd_stop(void) {
    g_wd_quit = 1;
    if (g_wd_thread) { WaitForSingleObject(g_wd_thread, 3000); CloseHandle(g_wd_thread); g_wd_thread = NULL; }
}
/* TEST ONLY, SSBU_HWWATCH=<command file>: data watchpoints (x64 debug registers) set while the game runs, to find which
 * lifted functions read or write a guest address (used to follow the local pad through the local-wireless input queue).
 * The file is read again whenever it changes (every 500 ms): up to 4 lines "<hex address> <1|2|4|8> <w|rw>" (an empty
 * file clears them). Every thread of the process gets them; each new place that touches an address is logged once,
 * "hwwatch: #<slot> <address> = <value> by <host pc [guest f_..]>" with the 8 callers under it, at most 40 places a slot. */
static volatile uint64_t g_hw_addr[4]; static volatile int g_hw_len[4], g_hw_rw[4], g_hw_n;
static uint64_t g_hw_seen[4][40]; static volatile LONG g_hw_nseen[4]; static volatile LONG64 g_hw_hits[4];
static DWORD g_hw_tid;
static LONG CALLBACK hw_veh(EXCEPTION_POINTERS *ep) {
    if (ep->ExceptionRecord->ExceptionCode != EXCEPTION_SINGLE_STEP) return EXCEPTION_CONTINUE_SEARCH;
    CONTEXT *c = ep->ContextRecord;
    DWORD64 dr6 = c->Dr6;
    if (!(dr6 & 15)) return EXCEPTION_CONTINUE_SEARCH;
    c->Dr6 = 0;
    for (int k = 0; k < 4; k++) {
        if (!(dr6 & (1u << k))) continue;
        InterlockedIncrement64(&g_hw_hits[k]);
        uint64_t pc = c->Rip;
        int seen = 0, n = g_hw_nseen[k];
        for (int i = 0; i < n && i < 40; i++) if (g_hw_seen[k][i] == pc) seen = 1;
        if (seen || n >= 40) continue;
        g_hw_seen[k][InterlockedIncrement(&g_hw_nseen[k]) - 1] = pc;
        char s[300]; uint64_t v = 0, pcs[10]; CONTEXT cc = *c;
        memcpy(&v, (const void *)(uintptr_t)g_hw_addr[k], (size_t)g_hw_len[k]);
        wd_addr(pc, s, sizeof s);
        printf("hwwatch: #%d %llx = %llx (%s) by %s, thread %lu\n", k, (unsigned long long)g_hw_addr[k], (unsigned long long)v, g_hw_rw[k] ? "read/write" : "write", s, GetCurrentThreadId());
        {   Ctx *hostrt_cur_ctx(void); Ctx *g = hostrt_cur_ctx();
            if (g) { printf("hwwatch:   guest fn f_%llx regs", (unsigned long long)g->fn); for (int r = 0; r < 32; r++) printf(" x%d=%llx", r, (unsigned long long)g->x[r]); printf("\n"); }
        }
        int m = wd_walk(&cc, pcs, 10);
        for (int i = 1; i < m; i++) { wd_addr(pcs[i], s, sizeof s); printf("hwwatch:      %d %s\n", i, s); }
        fflush(stdout);
    }
    return EXCEPTION_CONTINUE_EXECUTION;
}
static void hw_apply(void) {
    HANDLE sn = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    THREADENTRY32 te; te.dwSize = sizeof te;
    DWORD64 dr7 = 0;
    for (int k = 0; k < g_hw_n; k++) {
        int len = g_hw_len[k] == 1 ? 0 : g_hw_len[k] == 2 ? 1 : g_hw_len[k] == 8 ? 2 : 3;
        dr7 |= 1ull << (2 * k) | (uint64_t)(g_hw_rw[k] ? 3 : 1) << (16 + 4 * k) | (uint64_t)len << (18 + 4 * k);
    }
    if (sn == INVALID_HANDLE_VALUE) return;
    for (BOOL ok = Thread32First(sn, &te); ok; ok = Thread32Next(sn, &te)) {
        if (te.th32OwnerProcessID != GetCurrentProcessId() || te.th32ThreadID == g_hw_tid) continue;
        HANDLE t = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_SET_CONTEXT, FALSE, te.th32ThreadID);
        if (!t) continue;
        if (SuspendThread(t) != (DWORD)-1) {
            CONTEXT c; memset(&c, 0, sizeof c); c.ContextFlags = CONTEXT_DEBUG_REGISTERS;
            if (GetThreadContext(t, &c)) {
                c.Dr0 = g_hw_addr[0]; c.Dr1 = g_hw_addr[1]; c.Dr2 = g_hw_addr[2]; c.Dr3 = g_hw_addr[3]; c.Dr7 = dr7; c.Dr6 = 0;
                SetThreadContext(t, &c);
            }
            ResumeThread(t);
        }
        CloseHandle(t);
    }
    CloseHandle(sn);
}
static DWORD WINAPI hw_main(void *arg) {
    const char *path = arg;
    FILETIME last = {0, 0};
    g_hw_tid = GetCurrentThreadId();
    for (int tick = 0;; tick++) {
        Sleep(500);
        WIN32_FILE_ATTRIBUTE_DATA fa;
        int changed = GetFileAttributesExA(path, GetFileExInfoStandard, &fa) && CompareFileTime(&fa.ftLastWriteTime, &last) != 0;
        if (changed) {
            last = fa.ftLastWriteTime;
            FILE *f = fopen(path, "r");
            int n = 0; char ln[256];
            while (f && n < 4 && fgets(ln, sizeof ln, f)) {
                unsigned long long a; int len; char m[8];
                if (sscanf(ln, "%llx %d %7s", &a, &len, m) != 3 || (len != 1 && len != 2 && len != 4 && len != 8)) continue;
                g_hw_addr[n] = a & ~(unsigned long long)(len - 1); g_hw_len[n] = len; g_hw_rw[n] = !strcmp(m, "rw");
                g_hw_nseen[n] = 0; g_hw_hits[n] = 0; n++;
            }
            if (f) fclose(f);
            for (int k = n; k < 4; k++) g_hw_addr[k] = 0;
            g_hw_n = n;
            printf("hwwatch: %d watch(es) from %s\n", n, path);
            for (int k = 0; k < n; k++) printf("hwwatch:   #%d %llx len %d %s\n", k, (unsigned long long)g_hw_addr[k], g_hw_len[k], g_hw_rw[k] ? "read/write" : "write");
            fflush(stdout);
        }
        if (changed || (g_hw_n && tick % 2 == 0)) hw_apply();      /* threads made since get them too */
        if (g_hw_n && tick % 20 == 0) { printf("hwwatch: hits"); for (int k = 0; k < g_hw_n; k++) printf(" #%d %lld", k, (long long)g_hw_hits[k]); printf("\n"); fflush(stdout); }
    }
    return 0;
}
void hwwatch_start(void) {
    static char path[MAX_PATH];
    const char *e = getenv("SSBU_HWWATCH");
    if (!e || !e[0]) return;
    snprintf(path, sizeof path, "%s", e);
    AddVectoredExceptionHandler(1, hw_veh);
    HANDLE h = CreateThread(NULL, 0, hw_main, path, 0, NULL);
    if (h) CloseHandle(h);
    printf("hwwatch: TEST ONLY: data watchpoints from %s\n", path);
}
void hwwatch_stack(const char *tag) {               /* TEST ONLY (SSBU_HWWATCH): this thread's callers, symbolized */
    CONTEXT c; uint64_t pcs[14]; char s[300];
    RtlCaptureContext(&c);
    int m = wd_walk(&c, pcs, 14);
    for (int i = 1; i < m; i++) { wd_addr(pcs[i], s, sizeof s); printf("hwwatch: %s %d %s\n", tag, i, s); }
    fflush(stdout);
}
