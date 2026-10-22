/* U3 (plan\phases\U3_loading_anim.md): the loading animation in the black window, Windows. Included by display.c.
 *
 * From the moment the window exists until the game's first present, nothing draws into it: the boot (main.elf, the game
 * DLL, the Vulkan device and its pipeline cache, the container store, the game's own boot) left it black for seconds, and
 * on a first start for minutes. The window thread paints Kirby's Inhale hitbox animation with GDI+, small in the
 * bottom-right corner on black, beside the current boot step. tools/ui/loading_inhale.py prepares its transparent
 * atlas from Ultimate Frame Data's original loop, with subtle breathing and cyan suction particles.
 *
 * It stops for good at the first present (display_present_plan / display_before_present / display_pace, game's thread),
 * under a lock the painter holds while it paints: once the first present has begun, no GDI pixel is drawn into the window
 * again, so the animation never covers a Vulkan (or OpenGL) frame. gdiplus.dll is loaded at run time (no link change);
 * no PNG, no gdiplus.dll, a test window off-screen or SSBU_LOADING_ANIM=0: the window stays black as before. Host only:
 * nothing the game reads changes. */

/* Atlas dimensions match media/loading_kirby.json. All frame selection uses wall time, independent of boot work. */
#define LA_FRAME_W 384
#define LA_FRAME_H 256
#define LA_COLS 10
#define LA_FRAMES 60
#define LA_FPS 30
#define LA_SIZE 0.17f                      /* whole animation box, of the client height */
#define LA_MARGIN 0.025f                   /* from the bottom-right corner, of the client height */

typedef struct { UINT32 version; void *debug_cb; BOOL no_bg_thread, no_codecs; } LaGdipInput;
typedef int (WINAPI *la_startup_t)(ULONG_PTR *, const LaGdipInput *, void *);
typedef int (WINAPI *la_load_t)(const WCHAR *, void **);
typedef int (WINAPI *la_from_hdc_t)(HDC, void **);
typedef int (WINAPI *la_set_t)(void *, int);
typedef int (WINAPI *la_draw_t)(void *, void *, float, float, float, float, float, float, float, float, int, void *, void *, void *);
typedef int (WINAPI *la_size_t)(void *, UINT *);
typedef int (WINAPI *la_del_t)(void *);
static struct {
    la_from_hdc_t from_hdc; la_set_t smoothing, interp, pixoff; la_draw_t draw; la_del_t del;
    void *kirby;
    int on;                                /* window thread: painting (timer running) */
    volatile int ready;                    /* gdiplus and the atlas are loaded */
    RECT last;                             /* the client part painted last (bottom-right; the timer repaints it) */
    HFONT font, title; int font_h;         /* title: Barlow Condensed ExtraBold Italic (arena_fonts\ beside the exe), else bold Segoe UI */
    LARGE_INTEGER t0;
} LA;
static SRWLOCK g_la_lock = SRWLOCK_INIT;
static volatile LONG g_la_off;             /* 1: the first present has begun (or no animation): never paint again */
static volatile LONG g_la_first;           /* 1: the first present has begun (la_stop ran) */
static SRWLOCK g_la_note_lock = SRWLOCK_INIT;
static char g_la_note[200];                /* display_title_note's text, up to its " (" */
static LONG64 g_la_t_window;               /* QPC when the window was made, for the black-time line */
#define LA_TIMER 0x5a1

static double la_since_process_start(void) {      /* seconds since the process was created */
    FILETIME c, e, k, u, now;
    if (!GetProcessTimes(GetCurrentProcess(), &c, &e, &k, &u)) return 0;
    GetSystemTimeAsFileTime(&now);
    ULARGE_INTEGER a, b; a.LowPart = c.dwLowDateTime; a.HighPart = c.dwHighDateTime; b.LowPart = now.dwLowDateTime; b.HighPart = now.dwHighDateTime;
    return b.QuadPart > a.QuadPart ? (double)(b.QuadPart - a.QuadPart) / 1e7 : 0;
}

/* display_title_note: the step, for the line beside the animation */
static void la_note(const char *note) {
    AcquireSRWLockExclusive(&g_la_note_lock);
    g_la_note[0] = 0;
    if (note) {
        size_t n = strcspn(note, "(");
        while (n && note[n - 1] == ' ') n--;
        if (n >= sizeof g_la_note) n = sizeof g_la_note - 1;
        memcpy(g_la_note, note, n); g_la_note[n] = 0;
        if (g_la_note[0] >= 'a' && g_la_note[0] <= 'z') g_la_note[0] -= 32;
    }
    ReleaseSRWLockExclusive(&g_la_note_lock);
}

/* window thread, after the window is made */
static void la_start(HWND h, int visible) {
    QueryPerformanceCounter(&LA.t0);
    g_la_t_window = LA.t0.QuadPart;
    printf("display: window made %.2f s after the process started\n", la_since_process_start());
    const char *e = getenv("SSBU_LOADING_ANIM");
    if (!visible || (e && atoi(e) == 0) || getenv("SSBU_VK_SELFTEST")) { InterlockedExchange(&g_la_off, 1); return; }
    HMODULE g = LoadLibraryA("gdiplus.dll");
    la_startup_t startup = g ? (la_startup_t)(void *)GetProcAddress(g, "GdiplusStartup") : NULL;
    la_load_t load = g ? (la_load_t)(void *)GetProcAddress(g, "GdipLoadImageFromFile") : NULL;
    LA.from_hdc = g ? (la_from_hdc_t)(void *)GetProcAddress(g, "GdipCreateFromHDC") : NULL;
    LA.smoothing = g ? (la_set_t)(void *)GetProcAddress(g, "GdipSetSmoothingMode") : NULL;
    LA.interp = g ? (la_set_t)(void *)GetProcAddress(g, "GdipSetInterpolationMode") : NULL;
    LA.pixoff = g ? (la_set_t)(void *)GetProcAddress(g, "GdipSetPixelOffsetMode") : NULL;
    LA.draw = g ? (la_draw_t)(void *)GetProcAddress(g, "GdipDrawImageRectRect") : NULL;
    LA.del = g ? (la_del_t)(void *)GetProcAddress(g, "GdipDeleteGraphics") : NULL;
    la_size_t width = g ? (la_size_t)(void *)GetProcAddress(g, "GdipGetImageWidth") : NULL;
    la_size_t height = g ? (la_size_t)(void *)GetProcAddress(g, "GdipGetImageHeight") : NULL;
    if (!startup || !load || !LA.from_hdc || !LA.smoothing || !LA.interp || !LA.pixoff || !LA.draw || !LA.del || !width || !height) {
        printf("display: loading animation off: gdiplus.dll not usable\n"); InterlockedExchange(&g_la_off, 1); return;
    }
    ULONG_PTR token; LaGdipInput in = {1, NULL, FALSE, FALSE};
    WCHAR p[MAX_PATH + 32]; DWORD n = GetModuleFileNameW(NULL, p, MAX_PATH);
    while (n && p[n - 1] != L'\\' && p[n - 1] != L'/') n--;
    if (startup(&token, &in, NULL) == 0 && n) {
        wcscpy(p + n, L"loading_kirby.png"); if (load(p, &LA.kirby)) LA.kirby = NULL;
    }
    UINT aw = 0, ah = 0;
    if (!LA.kirby || width(LA.kirby, &aw) || height(LA.kirby, &ah) || aw != LA_FRAME_W * LA_COLS || ah != LA_FRAME_H * (LA_FRAMES / LA_COLS)) {
        printf("display: loading animation off: loading_kirby.png missing or atlas dimensions invalid\n"); InterlockedExchange(&g_la_off, 1); return;
    }
    LA.ready = 1;                          /* the atlas is loaded: la_hold may show it again during the shader hold */
    if (g_la_off) return;                  /* (a present already) */
    LA.on = 1;
    SetTimer(h, LA_TIMER, 16, NULL);       /* wall-time selects a 30 FPS atlas frame */
    printf("display: Kirby Inhale loading animation: %d frames at %d FPS\n", LA_FRAMES, LA_FPS); fflush(stdout);
    InvalidateRect(h, NULL, TRUE);
}

/* window thread: one picture into the bottom-right corner (WM_PAINT) */
static void la_paint(HWND h, HDC dc) {
    RECT cr; GetClientRect(h, &cr);
    int cw = cr.right, ch = cr.bottom;
    if (cw < 64 || ch < 64) return;
    int margin = (int)((float)ch * LA_MARGIN), ih = (int)((float)ch * LA_SIZE), iw = ih * LA_FRAME_W / LA_FRAME_H;
    int fh = ch / 36 < 13 ? 13 : ch / 36;
    RECT r = {cw * 2 / 5, ch - margin - ih - fh * 3, cw, ch};      /* the text, the shader bar above the animation and the animation */
    if (r.top < 0) r.top = 0;
    int w = r.right - r.left, hh = r.bottom - r.top;
    if (w <= 0 || hh <= 0) return;
    LA.last = r;
    if (fh != LA.font_h) {
        static int barlow = -1;
        if (barlow < 0) {                  /* Arena's title font, private to this process (scripts/setup.py copies it to arena_fonts\) */
            char p[MAX_PATH + 64]; DWORD k = GetModuleFileNameA(NULL, p, MAX_PATH);
            while (k && p[k - 1] != '\\' && p[k - 1] != '/') k--;
            p[k] = 0; strcat(p, "arena_fonts\\BarlowCondensed-ExtraBoldItalic.ttf");
            barlow = AddFontResourceExA(p, FR_PRIVATE, NULL) > 0;
            if (!barlow) { p[k] = 0; strcat(p, "..\\..\\tools\\launcher\\arena\\Assets\\Fonts\\BarlowCondensed-ExtraBoldItalic.ttf"); barlow = AddFontResourceExA(p, FR_PRIVATE, NULL) > 0; }
        }
        if (LA.font) DeleteObject(LA.font);
        if (LA.title) DeleteObject(LA.title);
        LA.font = CreateFontA(-fh, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0, ANTIALIASED_QUALITY, 0, "Segoe UI");
        LA.title = barlow ? CreateFontA(-fh * 3 / 2, 0, 0, 0, FW_EXTRABOLD, TRUE, 0, 0, DEFAULT_CHARSET, 0, 0, ANTIALIASED_QUALITY, 0, "Barlow Condensed ExtraBold")
                          : CreateFontA(-fh * 5 / 4, 0, 0, 0, FW_BOLD, TRUE, 0, 0, DEFAULT_CHARSET, 0, 0, ANTIALIASED_QUALITY, 0, "Segoe UI");
        LA.font_h = fh;
    }
    HDC m = CreateCompatibleDC(dc);
    HBITMAP bm = CreateCompatibleBitmap(dc, w, hh), old = (HBITMAP)SelectObject(m, bm);
    RECT all = {0, 0, w, hh};
    FillRect(m, &all, (HBRUSH)GetStockObject(BLACK_BRUSH));
    LARGE_INTEGER now, fq; QueryPerformanceCounter(&now); QueryPerformanceFrequency(&fq);
    double ms = (double)(now.QuadPart - LA.t0.QuadPart) * 1000.0 / (double)fq.QuadPart;
    unsigned frame = (unsigned long long)(ms * LA_FPS / 1000.0) % LA_FRAMES;
    char note[sizeof g_la_note];
    AcquireSRWLockShared(&g_la_note_lock); memcpy(note, g_la_note, sizeof note); ReleaseSRWLockShared(&g_la_note_lock);
    int pct = g_splash_prep_pct, loading = g_splash_prep_load;
    if (pct < 0) {                         /* before the hold reports its own percent: the files read so far (the title note) */
        int a = 0, b = 0;                  /* "loading the shaders, a of b" or "first start: preparing the shaders, a of b" (any case) */
        const char *n = strstr(note, "shaders, ");
        if (n && sscanf(n + 9, "%d of %d", &a, &b) == 2 && b > 0) { pct = a * 100 / b; loading = strstr(note, "oading") != NULL; }
    }
    int below = pct >= 0 ? fh * 3 : 0;     /* the shader hold: room under the animation for its bar and line */
    float ox = (float)(cw - margin - iw - r.left), oy = (float)(ch - margin - ih - below - r.top);
    void *g = NULL;
    if (LA.from_hdc(m, &g) == 0 && g) {
        LA.smoothing(g, 4); LA.interp(g, 7); LA.pixoff(g, 4);     /* anti-alias, high-quality bicubic, half-pixel offset */
        LA.draw(g, LA.kirby, ox, oy, (float)iw, (float)ih,
                (float)((frame % LA_COLS) * LA_FRAME_W), (float)((frame / LA_COLS) * LA_FRAME_H),
                (float)LA_FRAME_W, (float)LA_FRAME_H, 2 /* UnitPixel */, NULL, NULL, NULL);
        LA.del(g);
    }
    if (pct >= 0) {                        /* SSBU Arena: the shaders (prep_first_hold): "LOADING SHADERS 37%" and a thin bar under Kirby */
        if (pct > 100) pct = 100;
        int bx0 = (int)ox + iw / 8, bx1 = (int)ox + iw - iw / 8, bh = fh / 5 < 3 ? 3 : fh / 5;
        int by = (int)oy + ih - ih / 16;  /* the bar, just under the animation */
        RECT track = {bx0, by, bx1, by + bh}, done = {bx0, by, bx0 + (bx1 - bx0) * pct / 100, by + bh};
        HBRUSH tb = CreateSolidBrush(RGB(0x1E, 0x2A, 0x38)), ab = CreateSolidBrush(RGB(0x65, 0xC7, 0xFF));
        FillRect(m, &track, tb); if (done.right > done.left) FillRect(m, &done, ab);
        DeleteObject(tb); DeleteObject(ab);
        HFONT of = (HFONT)SelectObject(m, LA.title ? LA.title : LA.font);
        SetBkMode(m, TRANSPARENT);
        char num[8]; snprintf(num, sizeof num, "%d%%", pct);
        const char *what = loading ? "LOADING SHADERS " : "PREPARING SHADERS ";
        SIZE sn, sw; GetTextExtentPoint32A(m, num, (int)strlen(num), &sn); GetTextExtentPoint32A(m, what, (int)strlen(what), &sw);
        int ty = by + bh + fh / 3, tx = bx1 - sn.cx;                                  /* under the bar, the % ending where the bar ends */
        SetTextColor(m, RGB(0x65, 0xC7, 0xFF)); TextOutA(m, tx, ty, num, (int)strlen(num));
        SetTextColor(m, RGB(0xEE, 0xF3, 0xF7)); TextOutA(m, tx - sw.cx, ty, what, (int)strlen(what));
        SelectObject(m, of);
    } else if (note[0]) {
        HFONT of = (HFONT)SelectObject(m, LA.font);
        SetBkMode(m, TRANSPARENT); SetTextColor(m, RGB(166, 193, 216));
        RECT tr = {0, 0, (int)ox - fh / 2, hh - margin - ih / 6};
        DrawTextA(m, note, -1, &tr, DT_RIGHT | DT_BOTTOM | DT_SINGLELINE | DT_END_ELLIPSIS | DT_NOPREFIX);
        SelectObject(m, of);
    }
    BitBlt(dc, r.left, r.top, w, hh, m, 0, 0, SRCCOPY);
    SelectObject(m, old); DeleteObject(bm); DeleteDC(m);
}

/* SSBU Arena: the shaders are loaded (or prepared) INSIDE the first present, before its picture reaches the window
 * (nvn_vk_draw.c prep_first_hold), so the animation had stopped and the window showed one still frame for the whole
 * wait. During that hold it runs again with "LOADING SHADERS n%" and its bar; it stops again (under the paint lock)
 * when the hold ends, before the first picture. Any thread; the window thread restarts the timer (WM_APP + 0x53). */
#define LA_RESUME (WM_APP + 0x53)
static void la_hold(int on) {
    if (!LA.ready) return;
    if (on) { if (InterlockedExchange(&g_la_off, 0)) PostMessageA(g_hwnd, LA_RESUME, 0, 0); return; }
    AcquireSRWLockExclusive(&g_la_lock);
    InterlockedExchange(&g_la_off, 1);
    ReleaseSRWLockExclusive(&g_la_lock);
}

/* wndproc: WM_PAINT and the timer while the animation runs; returns 1 when it handled the message */
static int la_wndproc(HWND h, UINT msg, WPARAM w) {
    if (msg == LA_RESUME) {
        if (!g_la_off && LA.ready && !LA.on) { LA.on = 1; SetTimer(h, LA_TIMER, 16, NULL); InvalidateRect(h, NULL, FALSE); }
        return 1;
    }
    if (!LA.on) return 0;
    if (msg == WM_TIMER && w == LA_TIMER) {
        if (g_la_off) { KillTimer(h, LA_TIMER); LA.on = 0; return 1; }
        InvalidateRect(h, LA.last.right ? &LA.last : NULL, FALSE);      /* the bottom-right part painted last (a resize repaints it all) */
        return 1;
    }
    if (msg == WM_PAINT) {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(h, &ps);
        AcquireSRWLockExclusive(&g_la_lock);
        if (!g_la_off) la_paint(h, dc);
        ReleaseSRWLockExclusive(&g_la_lock);
        EndPaint(h, &ps);
        return 1;
    }
    return 0;
}

/* game's thread, at the first present (before any picture reaches the window): no GDI painting from here on. Callers
 * test g_la_first first, so this runs once (and the timing line is printed for hidden test windows too). */
static void la_stop(void) {
    AcquireSRWLockExclusive(&g_la_lock);   /* waits for a picture being painted */
    LONG was = InterlockedExchange(&g_la_off, 1);
    ReleaseSRWLockExclusive(&g_la_lock);
    if (!InterlockedExchange(&g_la_first, 1)) {
        LARGE_INTEGER now, fq; QueryPerformanceCounter(&now); QueryPerformanceFrequency(&fq);
        printf("display: the game's first present %.2f s after the process started, %.2f s after the window was made (the loading animation %s)\n", la_since_process_start(),
               g_la_t_window ? (double)(now.QuadPart - g_la_t_window) / (double)fq.QuadPart : 0.0, was ? "was not shown" : "stops here");
        fflush(stdout);
    }
}
