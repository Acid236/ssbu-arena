/* arcpack.c - the light archive (included by nnfs.c; not a build unit of its own). Contains nothing of the game.
 *
 * (1) SSBU_ARC_LOG=<file>: every read the game makes of RomFS data.arc is appended to the file as "<offset hex> <size hex>"
 *     (the coverage of the archive; tools/competitive/pack_arc.py turns the logs of many runs into a light archive).
 * (2) data.arcp next to (in place of) data.arc: a packed copy that holds only some byte ranges of the original:
 *         "SSBUARCP" | u64 size of the original | u64 range count | ranges: {u64 original offset, u64 length, u64 offset
 *         in this file} sorted by original offset | the bytes of the ranges
 *     When data.arc is missing and data.arcp is there, the game's open of data.arc gets data.arcp, and every read is
 *     translated: bytes inside a kept range come from it, bytes outside are zero and logged ("arcpack: MISSING ..."), so a
 *     run that needs a removed part says where (offset of the original): add that run's SSBU_ARC_LOG and pack again.
 *     The file size the game sees is the original's.
 * (3) data.arcp.extra next to data.arcp (same format, optional): more ranges, read where data.arcp has none. A small
 *     patch for a light archive already copied elsewhere (tools/competitive/pack_regions.py: every language / region
 *     version of the region-dependent files whose one version data.arcp has). */
typedef struct { uint64_t off, len, at; } ArcpRange;
static struct { HANDLE h; uint64_t size; uint64_t n; ArcpRange *r; HANDLE xh; uint64_t xn; ArcpRange *xr; } g_arcp[16];
static HANDLE g_arc_handles[16];
static SRWLOCK g_arcp_lock = SRWLOCK_INIT;
static FILE *g_arc_log;
static volatile LONG64 g_arcp_missing;

static int ends_with_i(const char *s, const char *t) { size_t a = strlen(s), b = strlen(t); return a >= b && !_stricmp(s + a - b, t); }

/* the original data.arc was opened: remember the handle for SSBU_ARC_LOG */
static void arc_log_flush(void);
static void arc_opened(HANDLE h, const char *path) {
    static int on = -1;
    if (on < 0) {
        const char *e = getenv("SSBU_ARC_LOG");
        on = e && e[0];
        if (on) { g_arc_log = fopen(e, "a"); if (!g_arc_log) on = 0; else { atexit(arc_log_flush); printf("arcpack: reads of data.arc are logged to %s\n", e); } }
    }
    if (!on || !ends_with_i(path, "\\data.arc")) return;
    AcquireSRWLockExclusive(&g_arcp_lock);
    for (int i = 0; i < 16; i++) if (!g_arc_handles[i]) { g_arc_handles[i] = h; break; }
    ReleaseSRWLockExclusive(&g_arcp_lock);
}
static void arc_read_logged(HANDLE h, int64_t off, uint64_t size) {
    if (!g_arc_log) return;
    for (int i = 0; i < 16; i++) if (g_arc_handles[i] == h) {
        AcquireSRWLockExclusive(&g_arcp_lock);
        fprintf(g_arc_log, "%llx %llx\n", (unsigned long long)off, (unsigned long long)size);
        static int n; if (++n % 256 == 0) fflush(g_arc_log);
        ReleaseSRWLockExclusive(&g_arcp_lock);
        return;
    }
}
static void arc_log_flush(void) { if (g_arc_log) fflush(g_arc_log); }
static void arc_closed(HANDLE h) {                       /* a closed handle value can come back for another file */
    AcquireSRWLockExclusive(&g_arcp_lock);
    for (int i = 0; i < 16; i++) { if (g_arc_handles[i] == h) g_arc_handles[i] = NULL; if (g_arcp[i].h == h) { free(g_arcp[i].r); free(g_arcp[i].xr); if (g_arcp[i].xh) CloseHandle(g_arcp[i].xh); memset(&g_arcp[i], 0, sizeof g_arcp[i]); } }
    ReleaseSRWLockExclusive(&g_arcp_lock);
}

/* the ranges of an arcp-format file: 1 when it is one (its handle stays open) */
static int arcp_load(const char *p, HANDLE *ph, uint64_t *psize, uint64_t *pn, ArcpRange **pr) {
    HANDLE h = CreateFileA(p, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return 0;
    uint8_t hd[24]; DWORD got = 0;
    if (!ReadFile(h, hd, 24, &got, NULL) || got != 24 || memcmp(hd, "SSBUARCP", 8)) { CloseHandle(h); return 0; }
    uint64_t size, n; memcpy(&size, hd + 8, 8); memcpy(&n, hd + 16, 8);
    ArcpRange *r = malloc((size_t)n * sizeof *r + 1);
    if (!r || !ReadFile(h, r, (DWORD)(n * sizeof *r), &got, NULL) || got != n * sizeof *r) { free(r); CloseHandle(h); return 0; }
    *ph = h; *psize = size; *pn = n; *pr = r;
    return 1;
}
/* open data.arcp for a path that ends in data.arc and does not exist; INVALID_HANDLE_VALUE if there is none */
static HANDLE arcp_open(const char *arc_path) {
    char p[MAX_PATH + 4];
    if (!ends_with_i(arc_path, "data.arc")) return INVALID_HANDLE_VALUE;
    snprintf(p, sizeof p, "%sp", arc_path);
    HANDLE h; uint64_t size, n; ArcpRange *r;
    if (!arcp_load(p, &h, &size, &n, &r)) return INVALID_HANDLE_VALUE;
    char px[MAX_PATH + 16]; HANDLE xh = NULL; uint64_t xsize = 0, xn = 0; ArcpRange *xr = NULL;
    snprintf(px, sizeof px, "%s.extra", p);
    if (arcp_load(px, &xh, &xsize, &xn, &xr) && xsize != size) { printf("arcpack: %s is for another data.arc (size): not used\n", px); free(xr); CloseHandle(xh); xh = NULL; xn = 0; xr = NULL; }
    AcquireSRWLockExclusive(&g_arcp_lock);
    int k = 0;
    while (k < 16 && g_arcp[k].h) k++;
    if (k < 16) { g_arcp[k].h = h; g_arcp[k].size = size; g_arcp[k].n = n; g_arcp[k].r = r; g_arcp[k].xh = xh; g_arcp[k].xn = xn; g_arcp[k].xr = xr; }
    ReleaseSRWLockExclusive(&g_arcp_lock);
    static int said;
    if (!said++) {
        uint64_t kept = 0, xkept = 0; for (uint64_t i = 0; i < n; i++) kept += r[i].len; for (uint64_t i = 0; i < xn; i++) xkept += xr[i].len;
        printf("arcpack: %s: light archive, %llu ranges, %.2f of %.2f GB kept\n", p, (unsigned long long)n, kept / 1073741824.0, size / 1073741824.0);
        if (xh) printf("arcpack: %s: %llu more ranges, %.1f MB\n", px, (unsigned long long)xn, xkept / 1048576.0);
    }
    if (k >= 16) { if (xh) CloseHandle(xh); CloseHandle(h); return INVALID_HANDLE_VALUE; }
    return h;
}
static int arcp_find(HANDLE h) { for (int i = 0; i < 16; i++) if (g_arcp[i].h == h) return i; return -1; }
static int arcp_size(HANDLE h, int64_t *out) { int k = arcp_find(h); if (k < 0) return 0; *out = (int64_t)g_arcp[k].size; return 1; }

/* the bytes of [pos, end) that the ranges r (in file fh) hold, into buf (which starts at pos); returns how many */
static uint64_t arcp_fill(HANDLE fh, const ArcpRange *r, uint64_t n, uint64_t pos, uint64_t end, void *buf) {
    uint64_t lo = 0, hi = n, covered = 0;
    while (lo < hi) { uint64_t mid = (lo + hi) / 2; if (r[mid].off + r[mid].len <= pos) lo = mid + 1; else hi = mid; }
    for (uint64_t i = lo; i < n && r[i].off < end; i++) {
        uint64_t a = r[i].off > pos ? r[i].off : pos, b = r[i].off + r[i].len < end ? r[i].off + r[i].len : end;
        if (a >= b) continue;
        uint64_t done = 0;
        while (done < b - a) {
            OVERLAPPED ov = {0}; uint64_t p = r[i].at + (a - r[i].off) + done;
            ov.Offset = (DWORD)p; ov.OffsetHigh = (DWORD)(p >> 32);
            DWORD chunk = b - a - done > 0x40000000 ? 0x40000000 : (DWORD)(b - a - done), g = 0;
            if (!ReadFile(fh, (char *)buf + (a - pos) + done, chunk, &g, &ov) || !g) break;
            done += g;
        }
        covered += b - a;
    }
    return covered;
}
/* a read of the light archive: 1 when h is one (got = bytes delivered: zero-filled holes count) */
static int arcp_read(HANDLE h, int64_t off, void *buf, uint64_t size, uint64_t *got) {
    int k = arcp_find(h);
    if (k < 0) return 0;
    uint64_t pos = (uint64_t)off, end = pos + size, n = g_arcp[k].n;
    ArcpRange *r = g_arcp[k].r;
    if (end > g_arcp[k].size) end = g_arcp[k].size;
    if (pos >= end) { *got = 0; return 1; }
    memset(buf, 0, (size_t)(end - pos));
    uint64_t covered = arcp_fill(h, r, n, pos, end, buf);
    if (covered < end - pos && g_arcp[k].xh) covered += arcp_fill(g_arcp[k].xh, g_arcp[k].xr, g_arcp[k].xn, pos, end, buf);      /* data.arcp.extra: ranges data.arcp does not have */
    if (covered < end - pos && InterlockedIncrement64(&g_arcp_missing) <= 50)
        printf("arcpack: MISSING data.arc bytes %llx..%llx (%llu of %llu bytes not in data.arcp): the light archive lacks what this run needs\n",
               (unsigned long long)pos, (unsigned long long)end, (unsigned long long)(end - pos - covered), (unsigned long long)(end - pos));
    *got = end - pos;
    return 1;
}
