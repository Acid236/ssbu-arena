/* coverage.c - which lifted game functions a run executes (SSBU_COVERAGE=<file>; for the reduced "competitive" build,
 * tools/competitive/prune.py). Contains nothing of the game.
 *
 * Every page of the game DLL's code is made a guard page. The first time any thread executes (or reads) a page, the
 * CPU raises STATUS_GUARD_PAGE_VIOLATION, the guard is gone from that page by itself, and the handler below marks the
 * page and lets the instruction run again: one exception per page per run, nothing after. Every 10 s (and at exit) the
 * lifted functions (fn_table: guest address -> host function) whose host code touches a marked page are added to the
 * file, one "<guest address hex>" per line; what the file already lists is kept, so several runs add up.
 * The page is the unit: a function that shares a page with a used one counts as used (the list errs on keeping). */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <windows.h>
#include "runtime.h"

__declspec(dllimport) void game_bind(void *h, void *t);

static uint8_t *g_cov_base;
static size_t g_cov_size;
static volatile uint8_t *g_cov_page;        /* one byte per 4 KB page of the DLL image */
static char g_cov_path[MAX_PATH];
static volatile LONG g_cov_hits;

static LONG CALLBACK cov_veh(EXCEPTION_POINTERS *ep) {
    if (ep->ExceptionRecord->ExceptionCode == EXCEPTION_ACCESS_VIOLATION) {
        static volatile LONG n;
        if (InterlockedIncrement(&n) <= 3)
            fprintf(stderr, "coverage: access violation at rip %llx (exe +%llx), %s %llx (thread %lu)\n", (unsigned long long)ep->ContextRecord->Rip,
                    (unsigned long long)(ep->ContextRecord->Rip - (uint64_t)(uintptr_t)GetModuleHandleA(NULL)),
                    ep->ExceptionRecord->ExceptionInformation[0] == 1 ? "writing" : ep->ExceptionRecord->ExceptionInformation[0] == 8 ? "executing" : "reading",
                    (unsigned long long)ep->ExceptionRecord->ExceptionInformation[1], GetCurrentThreadId());
        return EXCEPTION_CONTINUE_SEARCH;
    }
    if (ep->ExceptionRecord->ExceptionCode != STATUS_GUARD_PAGE_VIOLATION) return EXCEPTION_CONTINUE_SEARCH;
    uint8_t *a = (uint8_t *)(uintptr_t)ep->ExceptionRecord->ExceptionInformation[1];
    if (a < g_cov_base || a >= g_cov_base + g_cov_size) return EXCEPTION_CONTINUE_SEARCH;
    g_cov_page[(size_t)(a - g_cov_base) >> 12] = 1;
    InterlockedIncrement(&g_cov_hits);
    return EXCEPTION_CONTINUE_EXECUTION;     /* the guard is already off this page */
}

static int cov_cmp(const void *x, const void *y) {
    uint64_t a = *(const uint64_t *)x, b = *(const uint64_t *)y;
    return a < b ? -1 : a > b;
}
static void cov_write(void) {
    static SRWLOCK lock = SRWLOCK_INIT;
    AcquireSRWLockExclusive(&lock);
    int n = fn_table_count;
    /* host address -> guest address, sorted by host address: a function's code runs to the next one's start */
    uint64_t (*v)[2] = malloc((size_t)n * 16);
    uint64_t *keep = malloc((size_t)n * 8 + 8);
    size_t nk = 0;
    if (!v || !keep) { free(v); free(keep); ReleaseSRWLockExclusive(&lock); return; }
    for (int i = 0; i < n; i++) { v[i][0] = (uint64_t)(uintptr_t)fn_table[i].fn; v[i][1] = fn_table[i].addr; }
    qsort(v, (size_t)n, 16, cov_cmp);
    for (int i = 0; i < n; i++) {
        uint64_t s = v[i][0], e = i + 1 < n ? v[i + 1][0] : s + 1;
        if (s < (uint64_t)(uintptr_t)g_cov_base || s >= (uint64_t)(uintptr_t)(g_cov_base + g_cov_size)) continue;
        if (e <= s) e = s + 1;
        size_t p0 = (size_t)(s - (uint64_t)(uintptr_t)g_cov_base) >> 12, p1 = (size_t)(e - 1 - (uint64_t)(uintptr_t)g_cov_base) >> 12;
        for (size_t p = p0; p <= p1 && p < (g_cov_size >> 12); p++) if (g_cov_page[p]) { keep[nk++] = v[i][1]; break; }
    }
    /* merge with the file */
    FILE *f = fopen(g_cov_path, "r");
    char ln[64];
    while (f && fgets(ln, sizeof ln, f)) {
        uint64_t a = strtoull(ln, NULL, 16);
        if (a && nk < (size_t)n) keep[nk++] = a;
        else if (a) { keep = realloc(keep, (nk + 1) * 8); if (keep) keep[nk++] = a; }
    }
    if (f) fclose(f);
    qsort(keep, nk, 8, cov_cmp);
    char tmp[MAX_PATH + 8];
    snprintf(tmp, sizeof tmp, "%s.tmp", g_cov_path);
    f = fopen(tmp, "w");
    size_t out = 0;
    for (size_t i = 0; f && i < nk; i++) if (!i || keep[i] != keep[i - 1]) { fprintf(f, "%llx\n", (unsigned long long)keep[i]); out++; }
    if (f) { fclose(f); MoveFileExA(tmp, g_cov_path, MOVEFILE_REPLACE_EXISTING); }
    static size_t last;
    if (out != last) { printf("coverage: %zu of %d lifted functions used so far (%ld pages touched) -> %s\n", out, n, (long)g_cov_hits, g_cov_path); fflush(stdout); last = out; }
    free(v); free(keep);
    ReleaseSRWLockExclusive(&lock);
}
static DWORD WINAPI cov_loop(LPVOID arg) { (void)arg; for (;;) { Sleep(10000); cov_write(); } return 0; }
static void cov_atexit(void) { cov_write(); }

__attribute__((constructor)) static void cov_start(void) {
    const char *e = getenv("SSBU_COVERAGE");
    if (!e || !e[0]) return;
    snprintf(g_cov_path, sizeof g_cov_path, "%s", e);
    HMODULE m = NULL;
    if (!GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCSTR)(void *)game_bind, &m) || !m) return;
    g_cov_base = (uint8_t *)m;
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(g_cov_base + ((IMAGE_DOS_HEADER *)g_cov_base)->e_lfanew);
    g_cov_size = nt->OptionalHeader.SizeOfImage;
    g_cov_page = calloc((g_cov_size >> 12) + 1, 1);
    if (!g_cov_page) return;
    AddVectoredExceptionHandler(1, cov_veh);
    IMAGE_SECTION_HEADER *sec = IMAGE_FIRST_SECTION(nt);
    size_t guarded = 0;
    for (int i = 0; i < nt->FileHeader.NumberOfSections; i++) {
        if (!(sec[i].Characteristics & IMAGE_SCN_MEM_EXECUTE)) continue;
        DWORD old;
        if (VirtualProtect(g_cov_base + sec[i].VirtualAddress, sec[i].Misc.VirtualSize, PAGE_EXECUTE_READ | PAGE_GUARD, &old)) guarded += sec[i].Misc.VirtualSize;
    }
    atexit(cov_atexit);
    HANDLE h = CreateThread(NULL, 0, cov_loop, NULL, 0, NULL);
    if (h) CloseHandle(h);
    printf("coverage: TEST ONLY: %.0f MB of game code are guard pages; used functions go to %s\n", guarded / 1048576.0, g_cov_path);
}
