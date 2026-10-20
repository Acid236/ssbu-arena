/* U1: the in-game settings menu, in the style of Ship of Harkinian (the Ocarina of Time PC port): Dear ImGui (MIT,
 * reference\upstream\imgui-1.91.9b) drawn over the game's picture. Design, keys, proofs: plan\phases\U1_settings_menu.md.
 *
 * Open / close: F1 on the keyboard; on a controller the Home / Guide button (like the Switch's HOME menu), or the
 * Capture / Share button; + or Esc also close it. Those two buttons never reach the game while the menu exists (nnpad_sdl.c).
 * While it is open the game gets nothing from the real pads and keyboard
 * (nnhid.c asks menu_input_blocked), and after it closes, nothing until every pad button is released.
 * The game is not paused: it keeps running under the menu (a fight goes on; the players' inputs are held).
 *
 * Threads: the window thread (display.c wndproc) queues mouse and key messages here; the render thread (nvn_vk_menu.c,
 * included by nvn_vk_draw.c) calls menu_frame once per presented frame: the ImGui frame is built and drawn there.
 * Settings are written to config\graphics.ini (gfx_ini_set), the keyboard bindings to controllers.ini (nnpad_sdl.c),
 * the add-on content list to config\dlc.txt. Each control says whether it acts at once [live] or at the next start [restart].
 *
 * Log page: the runtime's own output, read back from the file stdout is redirected to (gioca.bat, the test runners):
 * the last LOG_MAX lines in memory, a filter, auto-scroll, "Export log" (logs\ssbu_log_<time>.txt beside the exe, then the
 * folder is opened in Explorer: from that button only). Stats overlay (F2 or the menu; graphics.ini stats_overlay):
 * frames per second, frame time, the online state of net_stats.h, run-ahead.
 *
 * Off unless SSBU_MENU=1 or graphics.ini menu = on (SSBU_MENU=0 wins). SSBU_MENU_TEST=<presented frame>: the test hook
 * (opens the menu, changes frame_time_overlay through the same code as the control, pictures of the Graphics and Log
 * pages and of the stats overlay with the menu closed, read back from the swapchain image into BMPs; "menu: test:" lines). */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <shellapi.h>
#include <psapi.h>
#include "imgui.h"
#include "net_stats.h"
extern "C" {
#include "gfx_options.h"
#include "menu.h"
#include "nnpad.h"
uint64_t nnhid_preview(int id, int st[4]); void nnhid_kb_player_refresh(void); int nnhid_kb_player(void);      /* nnhid.c */
void nnhid_test_key(int vk); long nnhid_test_result(uint64_t *buttons); int nnpad_kb_default(int idx);
uint64_t nnhid_menu_buttons(void);                                   /* nnhid.c: every pad, Npad bit order, no effect on the game */
void display_set_window_mode(int mode); void display_set_client_size(int w, int h); int display_window_mode(void);      /* display.c */
int nnaudio_volume(void); void nnaudio_set_volume(int percent);     /* nnaudio.c */
int nnpad_kb_vk(int idx); void nnpad_kb_bind(int idx, int vk); void nnpad_kb_player_set(int p); int nnpad_kb_player_cfg(void);      /* nnpad_sdl.c */
const char *nnpad_kb_label(int idx); void nnpad_vk_name(int vk, char *o, int n); int nnpad_describe(char *out, int n); const char *nnpad_config_path(void);
int nnaoc_owned(const int **list);                                   /* nnmisc.c */
long long nvn_front_presents(void); void nvn_front_osk_redraw(void); /* nvn_gl.c */
const char *nvn_vk_device_name(void);                                /* nvn_vk_menu.c */
int osk_active(void);                                                /* osk.c */
int osk_run(const wchar_t *header, const wchar_t *guide, const wchar_t *initial, int max_len, int min_len, int password, wchar_t *out);      /* osk.c */
int net_online(void); int net_mode(void); const char *net_room_code(void); const char *net_lan_code(void); const char *net_upnp_result(void);      /* net_relay.c */
int r1_ra_phase(void);                                               /* r1_state.c (read only): 0 = run-ahead not running now */
}

enum { B_A = 0, B_B, B_X, B_Y, B_LS, B_RS, B_L, B_R, B_ZL, B_ZR, B_PLUS, B_MINUS, B_LEFT, B_UP, B_RIGHT, B_DOWN, B_HOME, B_CAPTURE };
#define BIT(b) (1ull << (b))
enum { NET_MODE_LOBBY, NET_MODE_LAN, NET_MODE_HOST, NET_MODE_JOIN };      /* net_relay.h */

/* ------------------------------------------------------------------ state shared between threads */
static volatile LONG g_open, g_guard, g_toggle_req;
static int g_enabled = -1;
extern "C" int menu_enabled(void) {
    if (g_enabled < 0) {
        const char *e = getenv("SSBU_MENU"), *t = getenv("SSBU_MENU_TEST");
        int on = e && e[0] ? atoi(e) != 0 : gfx_menu();
        if (t && t[0]) on = 1;
        g_enabled = on;
        if (on) { printf("menu: settings menu on (F1, or the Home / Guide or Capture / Share button of a controller; %s)\n", e && e[0] ? "SSBU_MENU" : t && t[0] ? "SSBU_MENU_TEST" : "graphics.ini menu = on"); fflush(stdout); }
    }
    return g_enabled;
}
extern "C" int menu_is_open(void) { return g_enabled > 0 && g_open; }
extern "C" int menu_input_blocked(void) { return g_enabled > 0 && (g_open || g_guard); }
extern "C" void menu_request_toggle(void) { InterlockedIncrement(&g_toggle_req); }
/* R3: the online match's message (any thread; copied under a lock, read by the render thread) */
static SRWLOCK g_notice_lock = SRWLOCK_INIT;
static char g_notice[512];
static volatile LONG g_notice_on, g_notice_drawn;
extern "C" void menu_notice(const char *text) {
    AcquireSRWLockExclusive(&g_notice_lock);
    snprintf(g_notice, sizeof g_notice, "%s", text ? text : "");
    InterlockedExchange(&g_notice_on, g_notice[0] != 0);
    if (!g_notice[0]) InterlockedExchange(&g_notice_drawn, 0);
    ReleaseSRWLockExclusive(&g_notice_lock);
}
/* net_stats.h: the default answer until the online code defines net_stats_get itself */
extern "C" void net_stats_get_default(NetStats *o) { memset(o, 0, sizeof *o); o->state = NET_OFFLINE; o->ping_ms = -1; }
#pragma comment(linker, "/alternatename:net_stats_get=net_stats_get_default")
static volatile LONG g_stats_req;                    /* F2 */
static int g_asserts;
extern "C" void menu_assert_fail(const char *what, const char *file, int line) {
    if (g_asserts++ < 10) { const char *f = strrchr(file, '\\'); printf("menu: ImGui check failed: %s (%s:%d)\n", what, f ? f + 1 : file, line); fflush(stdout); }
}

/* the window's messages, queued by the window thread, read by the render thread */
enum { EV_MOVE = 1, EV_BTN, EV_WHEEL, EV_KEY, EV_CHAR };
struct Ev { int type, a, b; };
static CRITICAL_SECTION g_qcs;
static INIT_ONCE g_qonce = INIT_ONCE_STATIC_INIT;
static Ev g_q[256];
static int g_qn;
static BOOL CALLBACK q_init(PINIT_ONCE, PVOID, PVOID *) { InitializeCriticalSection(&g_qcs); return TRUE; }
static void q_push(int type, int a, int b) {
    InitOnceExecuteOnce(&g_qonce, q_init, NULL, NULL);
    EnterCriticalSection(&g_qcs);
    if (g_qn < 256) { g_q[g_qn].type = type; g_q[g_qn].a = a; g_q[g_qn].b = b; g_qn++; }
    LeaveCriticalSection(&g_qcs);
}
static int q_take(Ev *out, int max) {
    InitOnceExecuteOnce(&g_qonce, q_init, NULL, NULL);
    EnterCriticalSection(&g_qcs);
    int n = g_qn < max ? g_qn : max;
    memcpy(out, g_q, sizeof(Ev) * (size_t)n);
    g_qn = 0;
    LeaveCriticalSection(&g_qcs);
    return n;
}

extern "C" int menu_wndproc(void *hwnd, unsigned m, uintptr_t w, intptr_t l) {
    (void)hwnd;
    if (!menu_enabled()) return 0;
    if (m == WM_KEYDOWN && w == VK_F1) { if (!(l & (1 << 30))) menu_request_toggle(); return 1; }
    if (m == WM_KEYDOWN && w == VK_F2) { if (!(l & (1 << 30))) InterlockedIncrement(&g_stats_req); return 1; }      /* the stats overlay */
    if (!g_open || osk_active()) return 0;
    switch (m) {
    case WM_MOUSEMOVE: q_push(EV_MOVE, (short)LOWORD(l), (short)HIWORD(l)); return 0;
    case WM_LBUTTONDOWN: case WM_LBUTTONUP: q_push(EV_BTN, 0, m == WM_LBUTTONDOWN); return 1;
    case WM_RBUTTONDOWN: case WM_RBUTTONUP: q_push(EV_BTN, 1, m == WM_RBUTTONDOWN); return 1;
    case WM_MBUTTONDOWN: case WM_MBUTTONUP: q_push(EV_BTN, 2, m == WM_MBUTTONDOWN); return 1;
    case WM_MOUSEWHEEL: q_push(EV_WHEEL, GET_WHEEL_DELTA_WPARAM(w), 0); return 1;
    case WM_KEYDOWN: case WM_KEYUP: q_push(EV_KEY, (int)w, m == WM_KEYDOWN); return 1;
    case WM_CHAR: {                                   /* the window is an ANSI one: a character of the system code page */
        char a = (char)w; wchar_t u = 0;
        if (w < 0x80 || MultiByteToWideChar(CP_ACP, 0, &a, 1, &u, 1) != 1) u = (wchar_t)w;
        q_push(EV_CHAR, (int)u, 0); return 1; }
    }
    return 0;
}

/* ------------------------------------------------------------------ the settings */
static const char *const k_window[] = {"windowed", "borderless", "fullscreen"};
static const char *const k_vsync[] = {"clock", "on", "off", "mailbox", "display", "auto"};      /* GfxOptions.present */
static const char *const k_latency[] = {"normal", "low", "lowest"};
static const char *const k_renderer[] = {"vulkan", "opengl"};
static const int k_aniso_v[] = {0, 2, 4, 8, 16};
static const char *const k_aniso[] = {"game", "2", "4", "8", "16"};
static const char *const k_profile[] = {"custom", "low"};
static const char *const k_wait[] = {"hold", "skip"};
static const char *const k_prepare[] = {"first_run", "background", "off"};
static const char *const k_load[] = {"start", "loading"};
static const char *const k_console[] = {"docked", "handheld"};
static const char *const k_onoff[] = {"off", "on"};
static const char *const k_lang[] = {"auto", "ja", "en-US", "en-GB", "fr", "fr-CA", "de", "it", "es", "es-419", "zh-Hans", "zh-Hant", "ko", "nl", "ru"};
static const char *const k_lang_name[] = {"auto (Windows display language)", "Japanese", "English (US)", "English (UK)", "French", "French (Canada)", "German", "Italian",
                                          "Spanish (Spain)", "Spanish (Latin America)", "Chinese (simplified)", "Chinese (traditional)", "Korean", "Dutch", "Russian"};
static const int k_sizes[][2] = {{1280, 720}, {1600, 900}, {1920, 1080}, {2560, 1440}, {3840, 2160}};
static const char *const k_size_name[] = {"1280 x 720", "1600 x 900", "1920 x 1080", "2560 x 1440", "3840 x 2160"};
#define N(a) ((int)(sizeof(a) / sizeof((a)[0])))

struct Settings {
    int window, size, vsync, latency, renderer, aniso, profile, wait, prepare, load, console, overlay, volume, runahead, lang, kb_player, stats;
    float scale;
    char gpu[64];
};
static Settings S, S0;               /* S0 = what this run started with (restart marks) */
static char g_lang_start[16];
static int g_sections_inited;

static int idx_of(const char *const *names, int n, const char *v) { for (int i = 0; i < n; i++) if (!_stricmp(names[i], v)) return i; return 0; }
static void settings_init(int cw, int ch) {
    const GfxOptions *o = gfx_options();
    memset(&S, 0, sizeof S);
    S.window = o->window_mode; S.vsync = o->present >= 0 && o->present < N(k_vsync) ? o->present : 5; S.latency = gfx_latency(); S.renderer = o->renderer;
    S.aniso = 0; for (int i = 0; i < N(k_aniso_v); i++) if (k_aniso_v[i] == o->aniso) S.aniso = i;
    S.profile = o->profile; S.wait = o->shader_skip; S.prepare = o->shader_prepare; S.load = o->shader_load; S.console = o->handheld; S.overlay = o->overlay;
    S.volume = gfx_volume(); S.runahead = gfx_runahead(); S.scale = o->scale;
    snprintf(S.gpu, sizeof S.gpu, "%s", o->gpu[0] ? o->gpu : "auto");
    S.lang = idx_of(k_lang, N(k_lang), gfx_language()[0] ? gfx_language() : "auto");
    snprintf(g_lang_start, sizeof g_lang_start, "%s", k_lang[S.lang]);
    S.size = -1; for (int i = 0; i < N(k_sizes); i++) if (k_sizes[i][0] == o->width && k_sizes[i][1] == o->height) S.size = i;
    S.kb_player = nnpad_kb_player_cfg();
    S.stats = gfx_stats_overlay();
    S0 = S;
    (void)cw; (void)ch;
}
static void ini(const char *key, const char *value) { gfx_ini_set(key, value); }
static int restart_pending(void) {
    return S.vsync != S0.vsync || S.latency != S0.latency || S.renderer != S0.renderer || S.aniso != S0.aniso || S.profile != S0.profile || S.wait != S0.wait ||
           S.prepare != S0.prepare || S.load != S0.load || S.console != S0.console || S.runahead != S0.runahead || S.lang != S0.lang ||
           fabsf(S.scale - S0.scale) > 0.001f || strcmp(S.gpu, S0.gpu);
}
static void apply_stats(int on) {            /* live: the stats box (F2) */
    S.stats = on;
    ini("stats_overlay", k_onoff[on]);
}
static void apply_overlay(int on) {          /* live: title bar + log line (display.c reads it every second) + the picture (below) */
    S.overlay = on;
    gfx_set_overlay(on);
    ini("frame_time_overlay", k_onoff[on]);
}

/* ------------------------------------------------------------------ add-on content list (config\dlc.txt) */
struct DlcLine { char text[160]; int index, entry, on; };
static DlcLine *g_dlc;
static int g_dlc_n, g_dlc_loaded, g_dlc_dirty;
static char g_dlc_path[MAX_PATH];
static int dlc_entry(const char *p) {        /* the index of an entry line (nnmisc.c aoc_parse, simplified: 0x.., decimal or the 16-digit id), 0 = none */
    while (*p == ' ' || *p == '\t') p++;
    char *e = NULL;
    unsigned long long v;
    if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) v = strtoull(p + 2, &e, 16);
    else { size_t nd = strspn(p, "0123456789abcdefABCDEF"); v = nd == 16 ? strtoull(p, &e, 16) : strtoull(p, &e, 10); }
    if (!e || e == p) return 0;
    if (v > 0xfff) v = v > 0x01006A800016E000ULL + 0x1000 && v < 0x01006A800016E000ULL + 0x2000 ? v - 0x01006A800016E000ULL - 0x1000 : 0;
    return v > 0 && v < 0x1000 ? (int)v : 0;
}
static void dlc_load(void) {
    const char *e = getenv("SSBU_DLC_LIST");
    if (e && e[0]) snprintf(g_dlc_path, sizeof g_dlc_path, "%s", e);
    else { char exe[MAX_PATH], tmp[MAX_PATH + 32]; GetModuleFileNameA(NULL, exe, MAX_PATH); char *s = strrchr(exe, '\\'); if (s) *s = 0; snprintf(tmp, sizeof tmp, "%s\\..\\config\\dlc.txt", exe); if (!_fullpath(g_dlc_path, tmp, MAX_PATH)) snprintf(g_dlc_path, sizeof g_dlc_path, "%s", tmp); }
    free(g_dlc); g_dlc = NULL; g_dlc_n = 0;
    FILE *f = fopen(g_dlc_path, "r");
    char ln[256];
    int cap = 0;
    while (f && fgets(ln, sizeof ln, f)) {
        ln[strcspn(ln, "\r\n")] = 0;
        if (g_dlc_n == cap) { cap = cap ? cap * 2 : 64; g_dlc = (DlcLine *)realloc(g_dlc, sizeof(DlcLine) * (size_t)cap); }
        DlcLine *d = &g_dlc[g_dlc_n++];
        memset(d, 0, sizeof *d);
        snprintf(d->text, sizeof d->text, "%s", ln);
        const char *p = ln;
        while (*p == ' ' || *p == '\t') p++;
        if (!strncmp(p, "#off ", 5) && dlc_entry(p + 5)) { d->entry = 1; d->on = 0; d->index = dlc_entry(p + 5); }
        else if (*p != '#' && dlc_entry(p)) { d->entry = 1; d->on = 1; d->index = dlc_entry(p); }
    }
    if (f) fclose(f);
    g_dlc_loaded = 1; g_dlc_dirty = 0;
}
static void dlc_save(void) {
    char bak[MAX_PATH + 8];
    snprintf(bak, sizeof bak, "%s.bak", g_dlc_path);
    CopyFileA(g_dlc_path, bak, FALSE);
    FILE *f = fopen(g_dlc_path, "w");
    if (!f) { printf("menu: %s could NOT be written\n", g_dlc_path); return; }
    for (int i = 0; i < g_dlc_n; i++) {
        DlcLine *d = &g_dlc[i];
        const char *p = d->text;
        while (*p == ' ' || *p == '\t') p++;
        if (!d->entry) fprintf(f, "%s\n", d->text);
        else if (!strncmp(p, "#off ", 5)) fprintf(f, d->on ? "%s\n" : "#off %s\n", p + 5);
        else fprintf(f, d->on ? "%s\n" : "#off %s\n", p);
    }
    fclose(f);
    printf("menu: %s written (old copy: %s); the game reads it at the next start\n", g_dlc_path, bak);
    fflush(stdout);
    dlc_load();
}

/* ------------------------------------------------------------------ the ImGui side */
static int g_im_ready, g_section, g_section_req = -1, g_capture = -1;
static float g_base_h;
static unsigned char *g_font_px;
static int g_font_w, g_font_h;
static ImVector<ImDrawVert> g_vtx;
static ImVector<ImDrawIdx> g_idx;
static ImVector<MenuCmd> g_cmd;
static LARGE_INTEGER g_qpf, g_last_t;
static float g_ft[120];
static int g_ft_pos;
static uint64_t g_pad_prev;
static long long g_closed_at, g_frame;
static char g_pads[1024];
static ULONGLONG g_pads_at;
enum { SEC_DISPLAY, SEC_GRAPHICS, SEC_AUDIO, SEC_CONTROLS, SEC_EXPERIMENTAL, SEC_DLC, SEC_LANG, SEC_LOG, SEC_ABOUT, SEC_N };
static const char *const k_sections[SEC_N] = {"Display", "Graphics", "Audio", "Controls", "Experimental", "Add-on content", "Language", "Log", "About"};

static ImGuiKey vk_key(int vk) {
    if (vk >= 'A' && vk <= 'Z') return (ImGuiKey)(ImGuiKey_A + (vk - 'A'));
    if (vk >= '0' && vk <= '9') return (ImGuiKey)(ImGuiKey_0 + (vk - '0'));
    if (vk >= VK_F1 && vk <= VK_F12) return (ImGuiKey)(ImGuiKey_F1 + (vk - VK_F1));
    switch (vk) {
    case VK_TAB: return ImGuiKey_Tab; case VK_LEFT: return ImGuiKey_LeftArrow; case VK_RIGHT: return ImGuiKey_RightArrow; case VK_UP: return ImGuiKey_UpArrow;
    case VK_DOWN: return ImGuiKey_DownArrow; case VK_PRIOR: return ImGuiKey_PageUp; case VK_NEXT: return ImGuiKey_PageDown; case VK_HOME: return ImGuiKey_Home;
    case VK_END: return ImGuiKey_End; case VK_INSERT: return ImGuiKey_Insert; case VK_DELETE: return ImGuiKey_Delete; case VK_BACK: return ImGuiKey_Backspace;
    case VK_SPACE: return ImGuiKey_Space; case VK_RETURN: return ImGuiKey_Enter; case VK_ESCAPE: return ImGuiKey_Escape;
    case VK_SHIFT: return ImGuiKey_LeftShift; case VK_CONTROL: return ImGuiKey_LeftCtrl; case VK_MENU: return ImGuiKey_LeftAlt;
    }
    return ImGuiKey_None;
}

static void im_init(int h) {
    ImGui::CreateContext();
    ImGuiIO &io = ImGui::GetIO();
    io.IniFilename = NULL; io.LogFilename = NULL;
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard | ImGuiConfigFlags_NavEnableGamepad;
    io.BackendFlags |= ImGuiBackendFlags_HasGamepad;
    io.BackendPlatformName = "ssbu_menu (display.c window messages)";
    io.BackendRendererName = "nvn_vk_menu (Vulkan, dynamic rendering)";
    ImGui::StyleColorsDark();
    ImGuiStyle &st = ImGui::GetStyle();
    st.WindowRounding = 6.0f; st.FrameRounding = 4.0f; st.GrabRounding = 4.0f; st.WindowBorderSize = 1.0f;
    st.Colors[ImGuiCol_WindowBg].w = 0.92f;
    float px = (float)h / 40.0f;
    if (px < 15.0f) px = 15.0f;
    if (px > 40.0f) px = 40.0f;
    g_base_h = (float)h;
    char font[MAX_PATH];
    UINT n = GetWindowsDirectoryA(font, MAX_PATH);
    snprintf(font + n, sizeof font - n, "\\Fonts\\segoeui.ttf");
    ImFont *f = GetFileAttributesA(font) != INVALID_FILE_ATTRIBUTES ? io.Fonts->AddFontFromFileTTF(font, px) : NULL;
    if (!f) { ImFontConfig c; c.SizePixels = px; io.Fonts->AddFontDefault(&c); }
    st.ScaleAllSizes(px / 15.0f);
    int bpp = 0;
    io.Fonts->GetTexDataAsRGBA32(&g_font_px, &g_font_w, &g_font_h, &bpp);
    io.Fonts->SetTexID((ImTextureID)1);
    QueryPerformanceFrequency(&g_qpf);
    g_im_ready = 1;
    printf("menu: Dear ImGui %s ready: font %s %.0f px, atlas %dx%d\n", ImGui::GetVersion(), f ? font : "(built-in)", px, g_font_w, g_font_h);
    fflush(stdout);
}
extern "C" const unsigned char *menu_font_rgba(int *w, int *h) { *w = g_font_w; *h = g_font_h; return g_font_px; }

/* the pad, read every frame (also while the menu is closed: the combination that opens it) */
static void pad_feed(ImGuiIO &io, uint64_t b) {
    struct { int bit; ImGuiKey k; } m[] = {
        {B_A, ImGuiKey_GamepadFaceDown}, {B_B, ImGuiKey_GamepadFaceRight}, {B_Y, ImGuiKey_GamepadFaceLeft}, {B_X, ImGuiKey_GamepadFaceUp},
        {B_ZL, ImGuiKey_GamepadL2}, {B_ZR, ImGuiKey_GamepadR2}, {B_LEFT, ImGuiKey_GamepadDpadLeft}, {B_RIGHT, ImGuiKey_GamepadDpadRight},
        {B_UP, ImGuiKey_GamepadDpadUp}, {B_DOWN, ImGuiKey_GamepadDpadDown}};
    for (size_t i = 0; i < sizeof m / sizeof m[0]; i++) io.AddKeyEvent(m[i].k, (b & BIT(m[i].bit)) != 0);
}

static void tag(int restart, int changed) {
    ImGui::SameLine();
    if (!restart) ImGui::TextColored(ImVec4(0.45f, 0.85f, 0.45f, 1.0f), "[live]");
    else ImGui::TextColored(changed ? ImVec4(1.0f, 0.75f, 0.2f, 1.0f) : ImVec4(0.6f, 0.6f, 0.6f, 1.0f), changed ? "[restart: changed]" : "[restart]");
}
static bool combo(const char *label, int *v, const char *const *names, int n) { return ImGui::Combo(label, v, names, n); }
static void help(const char *s) { ImGui::PushTextWrapPos(0.0f); ImGui::TextDisabled("%s", s); ImGui::PopTextWrapPos(); }

static void sec_display(int cw, int ch) {
    int wm = display_window_mode();
    S.window = wm;
    if (combo("Window", &S.window, k_window, N(k_window))) { display_set_window_mode(S.window); ini("window", k_window[S.window]); }
    tag(0, 0);
    help("F11 also switches between the window and borderless at any time. Fullscreen = borderless and always on top (no display mode change).");
    int sz = S.size < 0 ? 0 : S.size;
    if (combo("Window size", &sz, k_size_name, N(k_size_name))) {
        S.size = sz;
        char v[16];
        display_set_client_size(k_sizes[sz][0], k_sizes[sz][1]);
        snprintf(v, sizeof v, "%d", k_sizes[sz][0]); ini("width", v);
        snprintf(v, sizeof v, "%d", k_sizes[sz][1]); ini("height", v);
    }
    tag(0, 0);
    ImGui::TextDisabled("now %d x %d (the windowed size is kept for later when borderless)", cw, ch);
    ImGui::Separator();
    if (combo("Vsync / pacing", &S.vsync, k_vsync, N(k_vsync))) ini("vsync", k_vsync[S.vsync]);
    tag(1, S.vsync != S0.vsync);
    help("auto: 'display' on a 60/120/240 Hz monitor, else 'clock'. display: the game's clock is the monitor's refresh. clock: our own 60 Hz clock. off: no wait, tearing. on: FIFO (two clocks). mailbox: as clock, mailbox only.");
    if (combo("Input latency", &S.latency, k_latency, N(k_latency))) ini("latency", k_latency[S.latency]);
    tag(1, S.latency != S0.latency);
    if (combo("Renderer", &S.renderer, k_renderer, N(k_renderer))) ini("renderer", k_renderer[S.renderer]);
    tag(1, S.renderer != S0.renderer);
    ImGui::InputText("GPU", S.gpu, sizeof S.gpu);
    if (ImGui::IsItemDeactivatedAfterEdit()) ini("gpu", S.gpu[0] ? S.gpu : "auto");
    tag(1, strcmp(S.gpu, S0.gpu) != 0);
    ImGui::TextDisabled("in use: %s   (auto, a number of the list in the log, or a part of the name)", nvn_vk_device_name());
}
static void sec_graphics(void) {
    if (ImGui::SliderFloat("Resolution scale", &S.scale, 0.25f, 2.0f, "%.2f")) S.scale = floorf(S.scale * 20.0f + 0.5f) / 20.0f;
    if (ImGui::IsItemDeactivatedAfterEdit()) { char v[16]; snprintf(v, sizeof v, "%.2f", S.scale); ini("resolution_scale", v); }
    tag(1, fabsf(S.scale - S0.scale) > 0.001f);
    ImGui::TextDisabled("1.00 = 1920 x 1080 inside; 0.50 = 960 x 540 (weak GPU); above 1 = supersampling (strong GPU)");
    if (combo("Anisotropic filtering", &S.aniso, k_aniso, N(k_aniso))) ini("anisotropic_filtering", k_aniso[S.aniso]);
    tag(1, S.aniso != S0.aniso);
    if (combo("Profile", &S.profile, k_profile, N(k_profile))) ini("profile", k_profile[S.profile]);
    tag(1, S.profile != S0.profile);
    ImGui::TextDisabled("low = scale 0.50, filtering game, vsync clock (those three keys are then not used)");
    if (combo("Shader wait", &S.wait, k_wait, N(k_wait))) ini("shader_wait", k_wait[S.wait]);
    tag(1, S.wait != S0.wait);
    if (combo("Shader preparation", &S.prepare, k_prepare, N(k_prepare))) ini("shader_prepare", k_prepare[S.prepare]);
    tag(1, S.prepare != S0.prepare);
    if (combo("Shader loading", &S.load, k_load, N(k_load))) ini("shader_load", k_load[S.load]);
    tag(1, S.load != S0.load);
    if (combo("Console mode", &S.console, k_console, N(k_console))) ini("console_mode", k_console[S.console]);
    tag(1, S.console != S0.console);
    bool ov = S.overlay != 0;
    if (ImGui::Checkbox("Frame time overlay", &ov)) apply_overlay(ov);
    tag(0, 0);
    ImGui::TextDisabled("in the picture (top left), in the window title and as a 'frame-time:' log line every second");
    bool so = S.stats != 0;
    if (ImGui::Checkbox("Stats overlay (F2)", &so)) apply_stats(so);
    tag(0, 0);
    ImGui::TextDisabled("top right: fps, frame time, online state, ping, input delay, rollback, run-ahead");
}
static void sec_audio(void) {
    int cur = nnaudio_volume();
    int v = S.volume < 0 ? (cur >= 0 ? cur : 100) : S.volume;
    if (cur < 0) ImGui::BeginDisabled();
    if (ImGui::SliderInt("Volume", &v, 0, 100, "%d %%")) { S.volume = v; nnaudio_set_volume(v); }
    if (ImGui::IsItemDeactivatedAfterEdit()) { char t[8]; snprintf(t, sizeof t, "%d", S.volume); ini("volume", t); }
    if (cur < 0) ImGui::EndDisabled();
    tag(0, 0);
    if (cur < 0) help("No sound device in this copy (test copies, SSBU_AUDIO_MUTE): the volume is saved for the copies a person plays.");
    if (ImGui::Button("Volume: auto (100 %)")) { S.volume = -1; nnaudio_set_volume(100); ini("volume", "auto"); }
    ImGui::Separator();
    help("Music and sound effects apart: the game's own Options > Sound (it mixes them itself; the PC gets the finished mix, and this volume scales all of it).");
}
/* ------------------------------------------------------------------ the Controls page: remapping of the keyboard and of every
 * controller (nnpad_sdl.c writes controllers.ini; all of it is used at once). The game's own actions next to each control are
 * the game's DEFAULT controls (its Options > Controls can change them per player name). */
static const char *const k_target_label[24] = {"A", "B", "X", "Y", "L-stick click", "R-stick click", "L", "R", "ZL", "ZR", "+ (Plus)", "- (Minus)",
    "D-pad left", "D-pad up", "D-pad right", "D-pad down", "Left stick left", "Left stick up", "Left stick right", "Left stick down",
    "Right stick left", "Right stick up", "Right stick right", "Right stick down"};
static const char *const k_action[24] = {"attack", "special", "jump", "jump", "-", "-", "grab", "grab", "shield", "shield", "pause", "pause",
    "taunt", "taunt", "taunt", "taunt", "move", "move / jump", "move", "move / crouch", "smash attack", "smash attack", "smash attack", "smash attack"};
static const char *const k_display_order_note = "Order: the Switch Pro Controller's buttons, then the d-pad, then the two sticks.";
static int g_ctl_dev = -1;          /* -1 = the keyboard, else the index of a controller (nnpad_list) */
static int g_ctl_scope = 1;         /* 1 = every controller of this kind, 0 = this controller only */
static int g_pcap = -1;             /* a controller target waiting for "press the button / stick direction" */
static ULONGLONG g_cap_t0;          /* when the waiting (keyboard or controller) began */
#define CAPTURE_MS 6000
static NnPadDev g_devs[16];
static int g_ndev;
static ULONGLONG g_devs_at;
static void capture_cancel(const char *why) {
    if (g_capture >= 0 || g_pcap >= 0) { printf("menu: rebinding of %s cancelled (%s)\n", nnpad_target_name(g_capture >= 0 ? g_capture : g_pcap), why); fflush(stdout); }
    g_capture = -1;
    if (g_pcap >= 0) nnpad_capture_end();
    g_pcap = -1;
}
static int capturing(void) { return g_capture >= 0 || g_pcap >= 0; }
static const NnPadDev *ctl_dev(void) { for (int i = 0; i < g_ndev; i++) if (g_devs[i].index == g_ctl_dev) return &g_devs[i]; return NULL; }
/* once per frame (render thread): the controller capture and the time-outs */
static void capture_tick(uint64_t down) {
    if (!capturing()) return;
    ULONGLONG now = GetTickCount64();
    if (now - g_cap_t0 > CAPTURE_MS) { capture_cancel("time-out"); return; }
    if (g_capture >= 0 && (down & BIT(B_B))) { capture_cancel("B on a controller"); return; }      /* a keyboard key is wanted: B of a pad cancels */
    if (g_pcap >= 0) {
        char src[32];
        int r = nnpad_capture_poll(src, sizeof src);
        if (r == 1) {
            nnpad_target_set(g_ctl_dev, g_ctl_scope, g_pcap, src);
            printf("menu: %s of controller %d bound to %s (%s)\n", nnpad_target_name(g_pcap), g_ctl_dev, src, g_ctl_scope ? "its type profile" : "this controller only"); fflush(stdout);
            nnpad_capture_end(); g_pcap = -1;
        } else if (r == 2) capture_cancel("Home / Capture");
        else if (r < 0) capture_cancel("the controller is gone");
    }
}
static void test_area(int player) {
    int st[4];
    uint64_t b = player >= 0 ? nnhid_preview(player, st) : 0;
    if (player < 0) { ImGui::TextDisabled("Test: this device is not a player now."); return; }
    ImGui::Text("Test (player %d, what the game would get):", player + 1);
    static const char *const sh[16] = {"A", "B", "X", "Y", "LS", "RS", "L", "R", "ZL", "ZR", "+", "-", "<", "^", ">", "v"};
    for (int i = 0; i < 16; i++) {
        bool on = (b >> i & 1) != 0;
        if (i) ImGui::SameLine();
        ImGui::PushStyleColor(ImGuiCol_Button, on ? ImVec4(0.95f, 0.55f, 0.15f, 1) : ImVec4(0.25f, 0.25f, 0.28f, 1));
        ImGui::PushStyleColor(ImGuiCol_ButtonHovered, on ? ImVec4(0.95f, 0.55f, 0.15f, 1) : ImVec4(0.25f, 0.25f, 0.28f, 1));
        ImGui::PushStyleColor(ImGuiCol_ButtonActive, on ? ImVec4(0.95f, 0.55f, 0.15f, 1) : ImVec4(0.25f, 0.25f, 0.28f, 1));
        ImGui::PushID(1000 + i);
        ImGui::SmallButton(sh[i]);
        ImGui::PopID();
        ImGui::PopStyleColor(3);
    }
    ImDrawList *dl = ImGui::GetWindowDrawList();
    float r = ImGui::GetFontSize() * 1.6f;
    ImVec2 p = ImGui::GetCursorScreenPos();
    for (int s = 0; s < 2; s++) {
        ImVec2 c(p.x + r + s * (r * 2.6f), p.y + r);
        dl->AddCircle(c, r, IM_COL32(160, 160, 170, 255), 32, 1.5f);
        dl->AddCircleFilled(ImVec2(c.x + r * st[s * 2] / 32767.0f, c.y - r * st[s * 2 + 1] / 32767.0f), r * 0.18f, IM_COL32(240, 140, 40, 255));
    }
    ImGui::Dummy(ImVec2(r * 4.6f, r * 2.0f));
    ImGui::SameLine();
    ImGui::Text("left (%6d, %6d)\nright (%6d, %6d)", st[0], st[1], st[2], st[3]);
}
static void sec_controls(void) {
    if (GetTickCount64() - g_devs_at > 500) { g_devs_at = GetTickCount64(); g_ndev = nnpad_list(g_devs, 16); }
    const NnPadDev *dv = ctl_dev();
    if (g_ctl_dev >= 0 && !dv) { capture_cancel("the controller is gone"); g_ctl_dev = -1; }
    char cur[160];
    if (dv) snprintf(cur, sizeof cur, "%s (%s)%s", dv->name, nnpad_type_label(dv->type), dv->player >= 0 ? "" : " - no player");
    else snprintf(cur, sizeof cur, "Keyboard");
    if (capturing()) ImGui::BeginDisabled();
    if (ImGui::BeginCombo("Device", cur)) {
        if (ImGui::Selectable("Keyboard", g_ctl_dev < 0)) g_ctl_dev = -1;
        for (int i = 0; i < g_ndev; i++) {
            char l[200];
            if (g_devs[i].player >= 0) snprintf(l, sizeof l, "Player %d: %s (%s)##%d", g_devs[i].player + 1, g_devs[i].name, nnpad_type_label(g_devs[i].type), g_devs[i].index);
            else snprintf(l, sizeof l, "No player: %s (%s)##%d", g_devs[i].name, nnpad_type_label(g_devs[i].type), g_devs[i].index);
            if (ImGui::Selectable(l, g_ctl_dev == g_devs[i].index)) g_ctl_dev = g_devs[i].index;
        }
        ImGui::EndCombo();
    }
    if (capturing()) ImGui::EndDisabled();
    tag(0, 0);
    if (!g_ndev) { ImGui::SameLine(); ImGui::TextDisabled("(no controller connected)"); }
    dv = ctl_dev();
    static const char *const kp[] = {"auto", "nobody", "1", "2", "3", "4", "5", "6", "7", "8"};
    static const char *const pp[] = {"auto", "1", "2", "3", "4", "5", "6", "7", "8"};
    if (!dv) {
        int p = S.kb_player + 2;
        if (combo("Keyboard plays as player", &p, kp, N(kp))) { S.kb_player = p - 2; S0.kb_player = S.kb_player; nnpad_kb_player_set(S.kb_player); nnhid_kb_player_refresh(); }
        tag(0, 0);
        ImGui::SameLine(); ImGui::TextDisabled("now: %s", nnhid_kb_player() >= 0 ? kp[nnhid_kb_player() + 2] : "nobody");
    } else {
        int p = nnpad_player_cfg(dv->index) + 1;
        if (combo("Player", &p, pp, N(pp))) nnpad_player_assign(dv->index, p - 1);
        tag(0, 0);
        ImGui::SameLine(); ImGui::TextDisabled("now: %s", dv->player >= 0 ? pp[dv->player + 1] : "none");
        char every[64];
        snprintf(every, sizeof every, "Every %s controller", nnpad_type_label(dv->type));
        if (ImGui::RadioButton(every, g_ctl_scope == 1)) g_ctl_scope = 1;
        ImGui::SameLine();
        if (ImGui::RadioButton("This controller only", g_ctl_scope == 0)) g_ctl_scope = 0;
        ImGui::SameLine();
        ImGui::TextDisabled("changes are saved for: %s", g_ctl_scope ? "its kind (a profile used whenever one is connected)" : "this controller (its GUID)");
    }
    ImGui::TextDisabled("%s   %s", nnpad_config_path(), k_display_order_note);
    if (g_capture >= 0) ImGui::TextColored(ImVec4(1, 0.8f, 0.2f, 1), "Press the KEY for %s ... %d s (Esc or B on a controller = cancel)", k_target_label[g_capture], (int)((CAPTURE_MS - (GetTickCount64() - g_cap_t0)) / 1000) + 1);
    if (g_pcap >= 0) ImGui::TextColored(ImVec4(1, 0.8f, 0.2f, 1), "Press the BUTTON or push the STICK / TRIGGER for %s ... %d s (Esc or Home = cancel)", k_target_label[g_pcap], (int)((CAPTURE_MS - (GetTickCount64() - g_cap_t0)) / 1000) + 1);
    float tbl_h = ImGui::GetContentRegionAvail().y - ImGui::GetFrameHeightWithSpacing() * (dv ? 7.4f : 4.6f);
    if (tbl_h < ImGui::GetFrameHeight() * 4) tbl_h = ImGui::GetFrameHeight() * 4;
    if (ImGui::BeginTable("map", 4, ImGuiTableFlags_RowBg | ImGuiTableFlags_ScrollY | ImGuiTableFlags_SizingStretchProp, ImVec2(0, tbl_h))) {
        ImGui::TableSetupScrollFreeze(0, 1);
        ImGui::TableSetupColumn("Switch control", ImGuiTableColumnFlags_WidthStretch, 1.0f);
        ImGui::TableSetupColumn("In the game (default)", ImGuiTableColumnFlags_WidthStretch, 1.0f);
        ImGui::TableSetupColumn(dv ? "Bound to" : "Key", ImGuiTableColumnFlags_WidthStretch, 1.6f);
        ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthStretch, 1.4f);
        ImGui::TableHeadersRow();
        for (int i = 0; i < 24; i++) {
            char name[96];
            int from = 0;
            if (dv) from = nnpad_target_text(dv->index, i, name, sizeof name); else nnpad_vk_name(nnpad_kb_vk(i), name, sizeof name);
            ImGui::PushID(i);
            ImGui::TableNextRow();
            ImGui::TableSetColumnIndex(0); ImGui::TextUnformatted(k_target_label[i]);
            ImGui::TableSetColumnIndex(1); ImGui::TextDisabled("%s", k_action[i]);
            ImGui::TableSetColumnIndex(2);
            if ((!dv && g_capture == i) || (dv && g_pcap == i)) ImGui::TextColored(ImVec4(1, 0.8f, 0.2f, 1), "... waiting");
            else if (dv) { ImGui::TextUnformatted(name); ImGui::SameLine(); ImGui::TextDisabled(from == 2 ? "(this controller)" : from == 1 ? "(profile)" : "(default)"); }
            else ImGui::TextUnformatted(name);
            ImGui::TableSetColumnIndex(3);
            if (capturing()) ImGui::BeginDisabled();
            if (ImGui::SmallButton("Change")) {
                g_cap_t0 = GetTickCount64();
                if (dv) { g_pcap = i; nnpad_capture_begin(dv->index); } else g_capture = i;
            }
            ImGui::SameLine();
            if (ImGui::SmallButton("Clear")) { if (dv) nnpad_target_set(dv->index, g_ctl_scope, i, "none"); else nnpad_kb_bind(i, 0); }
            ImGui::SameLine();
            if (ImGui::SmallButton("Default")) { if (dv) nnpad_target_set(dv->index, g_ctl_scope, i, NULL); else nnpad_kb_bind(i, nnpad_kb_default(i)); }
            if (capturing()) ImGui::EndDisabled();
            ImGui::PopID();
        }
        ImGui::EndTable();
    }
    if (capturing()) ImGui::BeginDisabled();
    if (dv) {
        char rl[96];
        snprintf(rl, sizeof rl, "Reset %s to the default", g_ctl_scope ? "the profile" : "this controller");
        if (ImGui::Button(rl)) nnpad_profile_reset(dv->index, g_ctl_scope);
        float tv[3];
        nnpad_tune_get(dv->index, tv);
        static const char *const tn[3] = {"Stick dead zone", "Stick outer zone (lower = more sensitive)", "Trigger threshold (ZL / ZR)"};
        static const float lo[3] = {0.0f, 0.5f, 0.05f}, hi[3] = {0.5f, 1.0f, 0.95f};
        static float edit[3];
        static int editing = -1;
        for (int k = 0; k < 3; k++) {
            float v = editing == k ? edit[k] : tv[k];
            if (ImGui::SliderFloat(tn[k], &v, lo[k], hi[k], "%.2f")) { edit[k] = v; editing = k; }
            if (ImGui::IsItemDeactivatedAfterEdit()) { nnpad_tune_set(dv->index, g_ctl_scope, k, v); editing = -1; }
        }
    } else {
        if (ImGui::Button("All keys back to the default")) for (int i = 0; i < 24; i++) nnpad_kb_bind(i, nnpad_kb_default(i));
    }
    if (capturing()) ImGui::EndDisabled();
    ImGui::Separator();
    test_area(dv ? dv->player : nnhid_kb_player());
}
/* ------------------------------------------------------------------ the Online page (net_relay.c / nnldn.c, docs/ONLINE.md)
 * The online code reads its graphics.ini keys once at the start (nnldn_register replaces the game's nn::ldn imports at boot
 * only when online play is on), so every control here is [restart]; "Restart the game now" starts this exe again with the
 * same command line and ends this copy (net_start of the new copy waits for the old one to be gone). */
#define ONLINE_DEFAULT_LOBBY "opensmash-lobby.duckdns.org:39500"      /* the project's public lobby server (host:port); a domain name can replace it */
static const char *const k_online_mode[] = {"off", "lan", "host", "join", "lobby"};
static const char *const k_online_name[] = {"Off", "Same network (LAN)", "Host a room (room code)", "Join with a code", "Lobby server (recommended)"};
static struct { int mode, last_mode; bool upnp, relay_only; char join[64], server[128]; } O, O0;
static void sec_online(void);
static int g_online_inited;
static volatile LONG g_osk_busy;
static char g_osk_text[64];
static volatile LONG g_osk_done;
static int ini_read(const char *key, char *out, int n) {       /* "key = value" of graphics.ini (the online code's own reading rule) */
    FILE *f = fopen(gfx_options()->path, "r");
    char ln[512];
    int found = 0;
    out[0] = 0;
    while (f && !found && fgets(ln, sizeof ln, f)) {
        char *s = ln;
        while (*s == ' ' || *s == '\t') s++;
        size_t kl = strlen(key);
        if (_strnicmp(s, key, kl) || (s[kl] != ' ' && s[kl] != '\t' && s[kl] != '=')) continue;
        s += kl;
        while (*s == ' ' || *s == '\t') s++;
        if (*s++ != '=') continue;
        while (*s == ' ' || *s == '\t') s++;
        char *e = s + strcspn(s, ";#\r\n");
        while (e > s && (e[-1] == ' ' || e[-1] == '\t')) e--;
        *e = 0;
        snprintf(out, (size_t)n, "%s", s);
        found = 1;
    }
    if (f) fclose(f);
    return found;
}
static int off_word(const char *v) { return !*v || !strcmp(v, "0") || !_stricmp(v, "off") || !_stricmp(v, "no") || !_stricmp(v, "false"); }
static void online_init(void) {
    char v[128];
    memset(&O, 0, sizeof O);
    O.upnp = 1;
    if (ini_read("online_mode", v, sizeof v)) {
        if (off_word(v)) O.mode = 0;
        else if (!_stricmp(v, "lan")) O.mode = 1;
        else if (!_strnicmp(v, "host", 4)) O.mode = 2;
        else if (!_strnicmp(v, "join", 4)) { O.mode = 3; if (v[4] == ':') snprintf(O.join, sizeof O.join, "%s", v + 5); }
        else if (!_stricmp(v, "1") || !_stricmp(v, "on") || !_stricmp(v, "auto")) O.mode = ini_read("online_server", v, sizeof v) && !off_word(v) ? 4 : 1;
        else O.mode = 4;
    } else if (ini_read("online_server", v, sizeof v) && !off_word(v)) O.mode = 4;
    if (!O.join[0]) ini_read("online_join", O.join, sizeof O.join);
    if (!ini_read("online_server", O.server, sizeof O.server) || off_word(O.server)) snprintf(O.server, sizeof O.server, "%s", ONLINE_DEFAULT_LOBBY);
    if (ini_read("online_upnp", v, sizeof v)) O.upnp = !off_word(v);
    if (ini_read("online_direct", v, sizeof v)) O.relay_only = off_word(v);
    /* what this run started with: the online code's own answer (SSBU_ONLINE wins over the file) */
    O.last_mode = O.mode;
    O0 = O;
    O0.mode = !net_online() ? 0 : net_mode() == NET_MODE_LAN ? 1 : net_mode() == NET_MODE_HOST ? 2 : net_mode() == NET_MODE_JOIN ? 3 : 4;
    g_online_inited = 1;
}
static void online_save(void) {
    ini("online_mode", k_online_mode[O.mode]);
    if (O.mode == 3) ini("online_join", O.join[0] ? O.join : "");
    if (O.mode == 4) ini("online_server", O.server[0] ? O.server : "off");
    ini("online_upnp", O.upnp ? "on" : "off");
    ini("online_direct", O.relay_only ? "off" : "on");
    printf("menu: online settings written: online_mode = %s%s%s (used at the next start)\n", k_online_mode[O.mode], O.mode == 3 ? ", online_join = " : O.mode == 4 ? ", online_server = " : "",
           O.mode == 3 ? O.join : O.mode == 4 ? O.server : "");
    fflush(stdout);
}
static DWORD WINAPI osk_code_thread(LPVOID) {             /* the on-screen keyboard for the room code (it blocks: not on the render thread) */
    wchar_t init[64], out[64] = L"";
    MultiByteToWideChar(CP_UTF8, 0, O.join, -1, init, 64);
    int r = osk_run(L"Room code", L"The code the host's game shows (like 1A2B3-C4D5E)", init, 32, 0, 0, out);
    if (r == 1) WideCharToMultiByte(CP_UTF8, 0, out, -1, g_osk_text, sizeof g_osk_text, NULL, NULL);
    InterlockedExchange(&g_osk_done, r == 1 ? 1 : 2);
    InterlockedExchange(&g_osk_busy, 0);
    return 0;
}
static DWORD WINAPI restart_thread(LPVOID) { Sleep(100); exit(0); return 0; }      /* the exit handlers (UPnP, lobby) run */
static void restart_game(void) {
    wchar_t dir[MAX_PATH], pid[16];
    GetCurrentDirectoryW(MAX_PATH, dir);
    swprintf(pid, 16, L"%lu", GetCurrentProcessId());
    SetEnvironmentVariableW(L"SSBU_RESTART_WAIT_PID", pid);
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    memset(&si, 0, sizeof si); si.cb = sizeof si;
    HANDLE h[3] = {GetStdHandle(STD_INPUT_HANDLE), GetStdHandle(STD_OUTPUT_HANDLE), GetStdHandle(STD_ERROR_HANDLE)};
    for (int i = 0; i < 3; i++) if (h[i] && h[i] != INVALID_HANDLE_VALUE) SetHandleInformation(h[i], HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
    si.dwFlags = STARTF_USESTDHANDLES; si.hStdInput = h[0]; si.hStdOutput = h[1]; si.hStdError = h[2];
    wchar_t *cmd = _wcsdup(GetCommandLineW());
    printf("menu: restarting the game: %ls\n", cmd);
    fflush(stdout);
    if (CreateProcessW(NULL, cmd, NULL, NULL, TRUE, 0, NULL, dir, &si, &pi)) {
        CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
        CreateThread(NULL, 0, restart_thread, NULL, 0, NULL);
        CreateThread(NULL, 0, [](LPVOID) -> DWORD { Sleep(5000); ExitProcess(0); return 0; }, NULL, 0, NULL);      /* if an exit handler hangs */
    } else { printf("menu: the restart FAILED (error %lu): start the game again by hand\n", GetLastError()); fflush(stdout); }
    free(cmd);
}
static int g_ra_build = -1;               /* the run-ahead pieces are there: a loaded game DLL with the r1_m1 marks (r1_state.c mark_bind) */
static int ra_build(void) {
    if (g_ra_build < 0) {
        HMODULE mods[512];
        DWORD need = 0;
        g_ra_build = 0;
        if (K32EnumProcessModules(GetCurrentProcess(), mods, sizeof mods, &need))
            for (DWORD i = 0; i < need / sizeof(HMODULE) && i < 512; i++) if (mods[i] != GetModuleHandleA(NULL) && GetProcAddress(mods[i], "r1_m1")) g_ra_build = 1;      /* (the exe has its own r1_m1: not a sign) */
    }
    return g_ra_build;
}
static bool onoff(const char *id, bool on, bool enabled) {     /* a big ON / OFF switch; true when clicked */
    char l[64];
    snprintf(l, sizeof l, "%s##%s", on ? "ON" : "OFF", id);
    if (!enabled) ImGui::BeginDisabled();
    ImGui::PushStyleColor(ImGuiCol_Button, on ? ImVec4(0.20f, 0.60f, 0.25f, 1) : ImVec4(0.35f, 0.35f, 0.38f, 1));
    ImGui::PushStyleColor(ImGuiCol_ButtonHovered, on ? ImVec4(0.25f, 0.70f, 0.30f, 1) : ImVec4(0.45f, 0.45f, 0.48f, 1));
    bool c = ImGui::Button(l, ImVec2(ImGui::GetFontSize() * 4.0f, 0));
    ImGui::PopStyleColor(2);
    if (!enabled) ImGui::EndDisabled();
    return c && enabled;
}
static int online_differs(void);
static void sec_experimental(void) {
    if (!g_online_inited) online_init();
    help("Features still being tested. Each is saved to config\\graphics.ini and used from the next start.");
    ImGui::Separator();
    /* (1) run-ahead (r1_state.c: graphics.ini runahead = on | off; SSBU_RUNAHEAD wins) */
    if (onoff("ra", S.runahead != 0, ra_build() || S.runahead)) { S.runahead = !S.runahead; ini("runahead", k_onoff[S.runahead]); }
    ImGui::SameLine(); ImGui::Text("Run-ahead");
    tag(1, S.runahead != S0.runahead);
    ImGui::SameLine();
    if (ra_build()) ImGui::TextDisabled("one frame less input delay in fights; costs a second pass of each frame on the CPU");
    else ImGui::TextDisabled("needs the run-ahead build (the game DLL with write marks); this build cannot run it");
    ImGui::Separator();
    /* (2) online play (net_relay.c / nnldn.c) */
    bool on = O.mode != 0;
    if (onoff("net", on, true)) { O.mode = on ? 0 : (O.last_mode ? O.last_mode : 4); online_save(); }
    ImGui::SameLine(); ImGui::Text("Online play");
    tag(1, (O.mode != 0) != (O0.mode != 0));
    ImGui::SameLine(); ImGui::TextDisabled("play with others through the game's Local Wireless menu");
    if (O.mode) sec_online();
    if (online_differs() || S.runahead != S0.runahead) {
        ImGui::Separator();
        ImGui::TextColored(ImVec4(1.0f, 0.75f, 0.2f, 1.0f), "Saved. These changes are used when the game starts again.");
        if (ImGui::Button("Restart the game now")) restart_game();
        ImGui::SameLine(); ImGui::TextDisabled("(progress not saved by the game is lost)");
    }
}
static void sec_online(void) {
    if (InterlockedExchange(&g_osk_done, 0) == 1) { snprintf(O.join, sizeof O.join, "%s", g_osk_text); online_save(); }
    NetStats ns;
    net_stats_get(&ns);
    static const char *const st[] = {"Offline", "Connecting...", "Connected", "Disconnected"};
    ImVec4 col = ns.state == NET_CONNECTED ? ImVec4(0.45f, 0.9f, 0.45f, 1) : ns.state == NET_CONNECTING ? ImVec4(1, 0.8f, 0.2f, 1) : ns.state == NET_DISCONNECTED ? ImVec4(1, 0.4f, 0.4f, 1) : ImVec4(0.7f, 0.7f, 0.7f, 1);
    ImGui::Text("Now:"); ImGui::SameLine();
    if (ns.state == NET_CONNECTED) ImGui::TextColored(col, "%s - %s, %d player%s%s", st[2], k_online_name[O0.mode], ns.players, ns.players == 1 ? "" : "s", "");
    else ImGui::TextColored(col, "%s%s%s", ns.state >= 0 && ns.state <= 3 ? st[ns.state] : "?", O0.mode ? " - " : "", O0.mode ? k_online_name[O0.mode] : "");
    if (ns.state == NET_CONNECTED && ns.ping_ms >= 0) { ImGui::SameLine(); ImGui::Text("  ping %d ms", ns.ping_ms); }
    ImGui::Indent();
    ImGui::SetWindowFontScale(1.2f);
    int changed = 0;
    static const int order[4] = {4, 1, 2, 3};      /* the lobby first: it needs nothing from the router */
    for (int k = 0; k < 4; k++) { int i = order[k]; if (ImGui::RadioButton(k_online_name[i], O.mode == i)) { O.mode = O.last_mode = i; changed = 1; } }
    ImGui::SetWindowFontScale(1.0f);
    tag(1, O.mode != O0.mode);
    if (O.mode == 1) help("Every player on the same home network chooses Same network. One game hosts the room list by itself; nothing to type.");
    if (O.mode == 2) {
        const char *code = O0.mode == 2 ? net_room_code() : "";
        if (code && code[0]) {
            ImGui::Text("ROOM CODE (give it to the other player):");
            ImGui::SetWindowFontScale(2.6f);
            ImGui::TextColored(ImVec4(1.0f, 0.75f, 0.25f, 1), "%s", code);
            ImGui::SetWindowFontScale(1.0f);
            ImGui::SameLine();
            if (ImGui::Button("Copy")) { ImGui::SetClipboardText(code); printf("menu: room code copied\n"); fflush(stdout); }
            if (net_lan_code()[0] && strcmp(net_lan_code(), code)) ImGui::TextDisabled("On the same network: %s", net_lan_code());
            if (net_upnp_result()[0]) ImGui::TextDisabled("%s", net_upnp_result());
        } else help(O0.mode == 2 ? "The room code appears here in a few seconds (it needs the public address: STUN / UPnP)."
                                 : "The room code appears here after the restart.");
        if (ImGui::Checkbox("Open the router's port by itself (UPnP)", &O.upnp)) changed = 1;
        tag(1, O.upnp != O0.upnp);
    }
    if (O.mode == 3) {
        ImGui::InputTextWithHint("Room code", "1A2B3-C4D5E", O.join, sizeof O.join, ImGuiInputTextFlags_CharsUppercase);
        if (ImGui::IsItemDeactivatedAfterEdit()) changed = 1;
        tag(1, strcmp(O.join, O0.join) != 0);
        ImGui::SameLine();
        if (g_osk_busy) ImGui::BeginDisabled();
        if (ImGui::Button("Type with the controller")) { InterlockedExchange(&g_osk_busy, 1); CreateThread(NULL, 0, osk_code_thread, NULL, 0, NULL); }
        if (g_osk_busy) ImGui::EndDisabled();
        if (O0.mode == 3 && net_room_code()[0]) ImGui::TextDisabled("Your own code (only if the host's router blocks you; the host sets it as online_peer): %s", net_room_code());
    }
    if (O.mode == 4) {
        ImGui::InputTextWithHint("Lobby server", "host:port", O.server, sizeof O.server);
        if (ImGui::IsItemDeactivatedAfterEdit()) changed = 1;
        tag(1, strcmp(O.server, O0.server) != 0);
        if (strcmp(O.server, ONLINE_DEFAULT_LOBBY) && ImGui::SmallButton("Use the public lobby")) { snprintf(O.server, sizeof O.server, "%s", ONLINE_DEFAULT_LOBBY); changed = 1; }
        help("Everyone using the same lobby sees each other's rooms. Your own lobby: tools/net/ssbu_lobby.py.");
        if (ImGui::Checkbox("Relay only (everything through the lobby, no direct connection)", &O.relay_only)) changed = 1;
        tag(1, O.relay_only != O0.relay_only);
    }
    if (changed) online_save();
    help("Then, in the game: Smash > Local Wireless (the game's own menu): one player Create Room, the others Rooms List.");
    if (getenv("SSBU_ONLINE")) ImGui::TextColored(ImVec4(1, 0.6f, 0.3f, 1), "SSBU_ONLINE=%s is set for this run: it wins over these settings.", getenv("SSBU_ONLINE"));
    ImGui::Unindent();
}
static int online_differs(void) {
    return O.mode != O0.mode || (O.mode == 3 && strcmp(O.join, O0.join)) || (O.mode == 4 && (strcmp(O.server, O0.server) || O.relay_only != O0.relay_only)) || (O.mode == 2 && O.upnp != O0.upnp);
}


static void sec_dlc(void) {
    const int *own = NULL;
    int n = nnaoc_owned(&own);
    if (!g_dlc_loaded) dlc_load();
    if (n >= 0) ImGui::Text("The game was told of %d owned add-on content(s).", n); else ImGui::Text("The game has not asked for its add-on contents yet.");
    ImGui::TextDisabled("%s  (tools_audit\\dlc_list.py writes it from your own DLC dumps)", g_dlc_path);
    int entries = 0;
    for (int i = 0; i < g_dlc_n; i++) entries += g_dlc[i].entry;
    if (!entries) help("No entry in the list: no add-on content is owned (DLC fighters, stages and costumes stay locked).");
    ImGui::BeginChild("dlc", ImVec2(0, ImGui::GetContentRegionAvail().y - ImGui::GetFrameHeightWithSpacing() * 1.5f), ImGuiChildFlags_None);
    for (int i = 0; i < g_dlc_n; i++) {
        DlcLine *d = &g_dlc[i];
        if (!d->entry) continue;
        const char *c = strchr(d->text, '#');
        if (c == d->text) c = strchr(c + 1, '#');
        char label[200];
        snprintf(label, sizeof label, "0x%03x  %s##%d", d->index, c ? c + 1 : "", i);
        bool on = d->on != 0;
        if (ImGui::Checkbox(label, &on)) { d->on = on; g_dlc_dirty = 1; }
    }
    ImGui::EndChild();
    if (!g_dlc_dirty) ImGui::BeginDisabled();
    if (ImGui::Button("Save the list")) dlc_save();
    if (!g_dlc_dirty) ImGui::EndDisabled();
    ImGui::SameLine();
    if (ImGui::Button("Read it again")) dlc_load();
    tag(1, g_dlc_dirty);
}
static void sec_lang(void) {
    if (combo("Language", &S.lang, k_lang_name, N(k_lang_name))) ini("language", k_lang[S.lang]);
    tag(1, S.lang != S0.lang);
    help("The language the game is told (nn::oe::GetDesiredLanguage). SSBU_LANGUAGE=<code> wins over this setting.");
}
/* ------------------------------------------------------------------ the Log page: the file stdout goes to, read back */
#define LOG_MAX 5000
static char *g_log[LOG_MAX];
static int g_log_head, g_log_n, g_log_state, g_log_auto = 1;      /* state: 0 not tried, 1 reading, -1 stdout is not a file */
static HANDLE g_log_h = INVALID_HANDLE_VALUE;
static char g_log_path[MAX_PATH + 8], g_log_part[1024], g_export_msg[MAX_PATH + 64];
static int g_log_partn;
static ImGuiTextFilter g_log_filter;
static void log_add(const char *s, int n) {
    char *l = (char *)malloc((size_t)n + 1);
    if (!l) return;
    memcpy(l, s, (size_t)n); l[n] = 0;
    int at = (g_log_head + g_log_n) % LOG_MAX;
    if (g_log_n == LOG_MAX) { free(g_log[g_log_head]); g_log_head = (g_log_head + 1) % LOG_MAX; at = (g_log_head + LOG_MAX - 1) % LOG_MAX; } else g_log_n++;
    g_log[at] = l;
}
static const char *log_line(int i) { return g_log[(g_log_head + i) % LOG_MAX]; }
static void log_poll(void) {
    if (g_log_state == 0) {
        HANDLE so = GetStdHandle(STD_OUTPUT_HANDLE);
        g_log_state = -1;
        if (so && so != INVALID_HANDLE_VALUE && GetFileType(so) == FILE_TYPE_DISK && GetFinalPathNameByHandleA(so, g_log_path, MAX_PATH, FILE_NAME_NORMALIZED)) {
            g_log_h = CreateFileA(g_log_path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, OPEN_EXISTING, 0, NULL);
            if (g_log_h != INVALID_HANDLE_VALUE) {
                LARGE_INTEGER sz, at;
                GetFileSizeEx(g_log_h, &sz);
                at.QuadPart = sz.QuadPart > (2 << 20) ? sz.QuadPart - (2 << 20) : 0;      /* the last 2 MB at most */
                SetFilePointerEx(g_log_h, at, NULL, FILE_BEGIN);
                g_log_state = 1;
                if (at.QuadPart) g_log_partn = -1;                                      /* the first (cut) line is dropped */
            }
        }
    }
    if (g_log_state != 1) return;
    fflush(stdout);
    static char buf[256 * 1024];
    DWORD got = 0;
    for (int k = 0; k < 4 && ReadFile(g_log_h, buf, sizeof buf, &got, NULL) && got; k++) {
        for (DWORD i = 0; i < got; i++) {
            char ch = buf[i];
            if (ch == '\n') { if (g_log_partn >= 0) { while (g_log_partn && g_log_part[g_log_partn - 1] == '\r') g_log_partn--; log_add(g_log_part, g_log_partn); } g_log_partn = 0; }
            else if (g_log_partn >= 0 && g_log_partn < (int)sizeof g_log_part - 1) g_log_part[g_log_partn++] = ch;
        }
    }
}
static int log_export(char *out, int n) {             /* logs\ssbu_log_<date>_<time>.txt beside the exe; 1 = written */
    char dir[MAX_PATH];
    GetModuleFileNameA(NULL, dir, MAX_PATH);
    char *s = strrchr(dir, '\\');
    if (s) *s = 0;
    strncat(dir, "\\logs", sizeof dir - strlen(dir) - 1);
    CreateDirectoryA(dir, NULL);
    SYSTEMTIME t;
    GetLocalTime(&t);
    snprintf(out, (size_t)n, "%s\\ssbu_log_%04d%02d%02d_%02d%02d%02d.txt", dir, t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond);
    FILE *f = fopen(out, "wb");
    if (!f) return 0;
    for (int i = 0; i < g_log_n; i++) { fputs(log_line(i), f); fputs("\r\n", f); }
    int ok = !fclose(f);
    printf("menu: log exported: %s (%d lines)\n", out, g_log_n);
    fflush(stdout);
    return ok;
}
static void sec_log(void) {
    log_poll();
    if (g_log_state != 1) { help("The output of this run does not go to a file (started from a console without '> file'): nothing to show. gioca.bat writes it to logs_gioco\\gioca.log."); return; }
    g_log_filter.Draw("Filter (a,b = either; -x = without)", ImGui::GetFontSize() * 16);
    ImGui::SameLine();
    bool au = g_log_auto != 0;
    if (ImGui::Checkbox("Auto-scroll", &au)) g_log_auto = au;
    ImGui::SameLine();
    if (ImGui::Button("Export log")) {
        char path[MAX_PATH + 64];
        if (log_export(path, sizeof path)) {
            snprintf(g_export_msg, sizeof g_export_msg, "written: %s", path);
            char *s = strrchr(path, '\\');
            if (s) *s = 0;
            ShellExecuteA(NULL, "open", path, NULL, NULL, SW_SHOWNORMAL);      /* the folder, in Explorer: this button only */
        } else snprintf(g_export_msg, sizeof g_export_msg, "could NOT be written: %s", path);
    }
    ImGui::TextDisabled("%s - %d lines kept (the last %d)%s%s", g_log_path + (strncmp(g_log_path, "\\\\?\\", 4) ? 0 : 4), g_log_n, LOG_MAX, g_export_msg[0] ? " - " : "", g_export_msg);
    ImGui::BeginChild("log", ImVec2(0, 0), ImGuiChildFlags_Borders, ImGuiWindowFlags_HorizontalScrollbar);
    static ImVector<int> idx;
    idx.resize(0);
    for (int i = 0; i < g_log_n; i++) if (!g_log_filter.IsActive() || g_log_filter.PassFilter(log_line(i))) idx.push_back(i);
    ImGuiListClipper clip;
    clip.Begin(idx.Size);
    while (clip.Step()) for (int i = clip.DisplayStart; i < clip.DisplayEnd; i++) ImGui::TextUnformatted(log_line(idx[i]));
    clip.End();
    if (g_log_auto) ImGui::SetScrollHereY(1.0f);
    ImGui::EndChild();
}

/* ------------------------------------------------------------------ the stats overlay (F2), top right */
static void draw_stats(void) {
    float sum = 0;
    int n = 0;
    for (int i = 0; i < 120; i++) if (g_ft[i] > 0) { sum += g_ft[i]; n++; }
    float avg = n ? sum / (float)n : 0;
    NetStats ns;
    memset(&ns, 0, sizeof ns);
    net_stats_get(&ns);
    static int ra_cfg = -1;
    if (ra_cfg < 0) { const char *e = getenv("SSBU_RUNAHEAD"); ra_cfg = e ? (e[0] && e[0] != '0') : gfx_runahead(); }
    ImGuiIO &io = ImGui::GetIO();
    ImGui::SetNextWindowPos(ImVec2(io.DisplaySize.x - 8, g_open ? ImGui::GetFrameHeight() + 8 : 8), ImGuiCond_Always, ImVec2(1.0f, 0.0f));
    ImGui::SetNextWindowBgAlpha(0.6f);
    ImGui::Begin("##stats", NULL, ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_AlwaysAutoResize | ImGuiWindowFlags_NoInputs | ImGuiWindowFlags_NoNav |
                 ImGuiWindowFlags_NoFocusOnAppearing | ImGuiWindowFlags_NoSavedSettings);
    ImGui::Text("%.0f fps  %.2f ms", avg > 0 ? 1000.0f / avg : 0.0f, avg);
    static const char *const st[] = {"Offline", "Connecting...", "Online - connected", "Disconnected"};
    ImVec4 col = ns.state == NET_CONNECTED ? ImVec4(0.45f, 0.9f, 0.45f, 1) : ns.state == NET_CONNECTING ? ImVec4(1, 0.8f, 0.2f, 1) : ns.state == NET_DISCONNECTED ? ImVec4(1, 0.4f, 0.4f, 1) : ImVec4(0.7f, 0.7f, 0.7f, 1);
    if (ns.state == NET_CONNECTED) ImGui::TextColored(col, "%s (%d players)", st[2], ns.players);
    else ImGui::TextColored(col, "%s", ns.state >= 0 && ns.state <= 3 ? st[ns.state] : "?");
    if (ns.state == NET_CONNECTED || ns.state == NET_CONNECTING) {
        if (ns.ping_ms >= 0) ImGui::Text("ping %d ms  delay %d f", ns.ping_ms, ns.delay); else ImGui::Text("ping -  delay %d f", ns.delay);
        ImGui::Text("rollback %d / %d f", ns.rollback_last, ns.rollback_max);
    }
    ImGui::Text("run-ahead %s", !ra_cfg ? "off" : r1_ra_phase() ? "on (running)" : "on");
    ImGui::End();
}

static void sec_about(void) {
    ImGui::Text("SSBU native: Super Smash Bros. Ultimate, statically recompiled for Windows");
    ImGui::Text("Runtime built %s %s (study tree)", __DATE__, __TIME__);
    ImGui::Text("Renderer: Vulkan on %s", nvn_vk_device_name());
    ImGui::Text("Settings menu: Dear ImGui %s (MIT licence, Omar Cornut and contributors)", ImGui::GetVersion());
    ImGui::Text("graphics.ini: %s", gfx_options()->path);
    ImGui::Text("controllers.ini: %s", nnpad_config_path());
    ImGui::Separator();
    help("No game content is part of this program: it runs the game files you dumped from your own console.");
}

static void draw_overlay(void) {
    float sum = 0;
    int n = 0;
    for (int i = 0; i < 120; i++) if (g_ft[i] > 0) { sum += g_ft[i]; n++; }
    float avg = n ? sum / (float)n : 0;
    ImGui::SetNextWindowPos(ImVec2(8, g_open ? ImGui::GetFrameHeight() + 8 : 8), ImGuiCond_Always);      /* below the menu bar while the menu is open */
    ImGui::SetNextWindowBgAlpha(0.55f);
    ImGui::Begin("##frametime", NULL, ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_AlwaysAutoResize | ImGuiWindowFlags_NoInputs | ImGuiWindowFlags_NoNav |
                 ImGuiWindowFlags_NoFocusOnAppearing | ImGuiWindowFlags_NoSavedSettings);
    ImGui::Text("%.2f ms  %.0f fps", avg, avg > 0 ? 1000.0f / avg : 0.0f);
    ImGui::PlotLines("##ft", g_ft, 120, g_ft_pos, NULL, 0.0f, 33.4f, ImVec2(ImGui::GetFontSize() * 9, ImGui::GetFontSize() * 2.5f));
    ImGui::End();
}

static void draw_menu(int cw, int ch) {
    if (ImGui::BeginMainMenuBar()) {
        ImGui::TextColored(ImVec4(1.0f, 0.55f, 0.2f, 1.0f), "SSBU native");
        for (int i = 0; i < SEC_N; i++) if (ImGui::MenuItem(k_sections[i], NULL, g_section == i)) g_section = i;
        ImGui::TextDisabled("   F1 / Home: close   L / R: section");
        ImGui::EndMainMenuBar();
    }
    ImGuiIO &io = ImGui::GetIO();
    ImVec2 size(io.DisplaySize.x * 0.62f, io.DisplaySize.y * 0.78f);
    ImGui::SetNextWindowPos(ImVec2(io.DisplaySize.x * 0.5f, io.DisplaySize.y * 0.53f), ImGuiCond_Always, ImVec2(0.5f, 0.5f));
    ImGui::SetNextWindowSize(size, ImGuiCond_Always);
    char title[64];
    snprintf(title, sizeof title, "%s###settings", k_sections[g_section]);
    if (g_section_req >= 0) ImGui::SetNextWindowFocus();
    ImGui::Begin(title, NULL, ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoCollapse | ImGuiWindowFlags_NoSavedSettings);
    g_section_req = -1;
    ImGui::BeginChild("body", ImVec2(0, -ImGui::GetFrameHeightWithSpacing() * (restart_pending() ? 2.2f : 1.2f)), ImGuiChildFlags_NavFlattened);
    ImGui::PushItemWidth(ImGui::GetFontSize() * 14);
    switch (g_section) {
    case SEC_DISPLAY: sec_display(cw, ch); break;
    case SEC_GRAPHICS: sec_graphics(); break;
    case SEC_AUDIO: sec_audio(); break;
    case SEC_CONTROLS: sec_controls(); break;
    case SEC_EXPERIMENTAL: sec_experimental(); break;
    case SEC_DLC: sec_dlc(); break;
    case SEC_LANG: sec_lang(); break;
    case SEC_LOG: sec_log(); break;
    default: sec_about(); break;
    }
    ImGui::PopItemWidth();
    ImGui::EndChild();
    if (restart_pending()) ImGui::TextColored(ImVec4(1.0f, 0.75f, 0.2f, 1.0f), "Saved. The settings marked [restart: changed] take effect at the next start.");
    if (ImGui::Button("Close")) menu_request_toggle();
    ImGui::SameLine();
    ImGui::TextDisabled("Settings are saved at once (config\\graphics.ini)");
    ImGui::End();
}

static void set_open(int on) {
    if (on == (g_open != 0)) return;
    if (on) {
        InterlockedExchange(&g_open, 1);
        InterlockedExchange(&g_guard, 1);
        g_section_req = g_section;
        capture_cancel("menu opened");
        g_dlc_loaded = 0;
        printf("menu: opened at presented frame %lld\n", g_frame);
    } else {
        InterlockedExchange(&g_open, 0);
        g_closed_at = g_frame;
        capture_cancel("menu closed");
        printf("menu: closed at presented frame %lld\n", g_frame);
    }
    fflush(stdout);
}

/* while the menu is open and the game shows nothing new (a loading wait), the last frame is shown again with the menu over it */
static DWORD WINAPI redraw_thread(LPVOID) {
    long long seen = -1;
    ULONGLONG at = 0;
    for (;;) {
        Sleep(50);
        if (!g_open || osk_active()) { seen = -1; continue; }
        long long p = nvn_front_presents();
        ULONGLONG now = GetTickCount64();
        if (p != seen) { seen = p; at = now; continue; }
        if (now - at > 100) nvn_front_osk_redraw();
    }
}

/* ------------------------------------------------------------------ SSBU_MENU_TEST */
static long long g_test_at = -2;
static int g_test_step, g_test_kb_old;
static char g_shot_path[MAX_PATH];
static int g_shot_req;
static void test_shot(const char *what) {
    const char *dir = getenv("SSBU_SHOT_DIR");
    snprintf(g_shot_path, sizeof g_shot_path, "%s%smenu_test_%s.bmp", dir ? dir : "", dir ? "/" : "", what);
    g_shot_req = 1;
}
static void test_tick(void) {
    if (g_test_at == -2) { const char *e = getenv("SSBU_MENU_TEST"); g_test_at = e && e[0] ? atoll(e) : -1; }
    if (g_test_at < 0 || g_frame < g_test_at) return;
    long long t = g_frame - g_test_at;
    static long long step_at;
    switch (g_test_step) {
    case 0: set_open(1); printf("menu: test: opened; input to the game blocked = %d\n", menu_input_blocked()); g_test_step = 1; step_at = t; break;
    case 1: if (t - step_at < 5) break;
        g_section = SEC_GRAPHICS; g_section_req = g_section; printf("menu: test: section Graphics\n");
        {   int was = S.overlay;
            apply_overlay(!was);
            FILE *f = fopen(gfx_options()->path, "rb");
            char ln[256], got[256] = "(not found)";
            while (f && fgets(ln, sizeof ln, f)) if (!strncmp(ln, "frame_time_overlay", 18)) { ln[strcspn(ln, "\r\n")] = 0; snprintf(got, sizeof got, "%s", ln); }
            if (f) fclose(f);
            printf("menu: test: frame_time_overlay changed to %s; the file now says \"%s\"; live value %d\n", k_onoff[S.overlay], got, gfx_options()->overlay); }
        g_test_step = 2; step_at = t; break;
    case 2: if (t - step_at >= 10) { test_shot("graphics"); g_test_step = 3; } break;
    case 4: g_section = SEC_LOG; g_section_req = g_section; printf("menu: test: section Log\n"); g_test_step = 5; step_at = t; break;
    case 5: if (t - step_at >= 10) {
            char path[MAX_PATH + 64];
            printf("menu: test: log page: %d lines read from %s; export %s\n", g_log_n, g_log_state == 1 ? g_log_path : "(stdout is not a file)", log_export(path, sizeof path) ? path : "FAILED");
            test_shot("log"); g_test_step = 6; } break;
    case 7: apply_stats(1); set_open(0); printf("menu: test: stats overlay on, menu closed\n"); g_test_step = 8; step_at = t; break;
    case 8: if (t - step_at >= 10) { test_shot("stats"); g_test_step = 9; } break;
    case 10: apply_stats(0); apply_overlay(!S.overlay); printf("menu: test: stats overlay and frame time overlay back as they were\n"); g_test_step = 11; break;
    case 11: if (!g_guard) { printf("menu: test: closed; input to the game blocked = %d (released) at frame %lld\n", menu_input_blocked(), g_frame); g_test_step = 12; } break;
    /* the Controls page: a key rebound through the same code as the page (capture + window key message), and the game's
     * own read of the keyboard player's pad before and after (nnhid_test_key holds the key P whatever the focus) */
    case 12: g_test_kb_old = nnpad_kb_vk(0); nnhid_test_key('P'); g_test_step = 13; step_at = t;
        printf("menu: test: controls: key P held for the keyboard's player %d (A is bound to key 0x%02x now)\n", nnhid_kb_player() + 1, g_test_kb_old); break;
    case 13: if (t - step_at >= 15) {
            uint64_t seen; long polls = nnhid_test_result(&seen); nnhid_test_key(0);
            printf("menu: test: controls: BEFORE: %ld polls of player %d with key P held: the game read buttons 0x%llx (A %s)\n", polls, nnhid_kb_player() + 1, (unsigned long long)seen, seen & 1 ? "PRESSED" : "not pressed");
            set_open(1); g_section = SEC_CONTROLS; g_section_req = g_section; g_ctl_dev = -1; g_test_step = 14; step_at = t; } break;
    case 14: if (t - step_at >= 10) { test_shot("controls"); g_test_step = 15; } break;
    case 16: g_cap_t0 = GetTickCount64(); g_capture = 0;                          /* the Change button of row A */
        q_push(EV_KEY, 'P', 1); q_push(EV_KEY, 'P', 0);                          /* what the window thread queues for a press of P */
        printf("menu: test: controls: Change on A, then the key P (window messages)\n"); g_test_step = 17; step_at = t; break;
    case 17: if (t - step_at >= 3) {
            char nm[16], got[128] = "(not found)", ln[256];
            int in_kb = 0;
            nnpad_vk_name(nnpad_kb_vk(0), nm, sizeof nm);
            FILE *f = fopen(nnpad_config_path(), "rb");
            while (f && fgets(ln, sizeof ln, f)) { if (ln[0] == '[') in_kb = !_strnicmp(ln, "[keyboard]", 10); else if (in_kb && !strncmp(ln, "A = ", 4)) { ln[strcspn(ln, "\r\n")] = 0; snprintf(got, sizeof got, "%s", ln); } }
            if (f) fclose(f);
            printf("menu: test: controls: A is now bound to %s; %s [keyboard] says \"%s\"\n", nm, nnpad_config_path(), got);
            set_open(0); g_test_step = 18; } break;
    case 18: if (!g_guard) { nnhid_test_key('P'); g_test_step = 19; step_at = t; } break;
    case 19: if (t - step_at >= 15) {
            uint64_t seen; long polls = nnhid_test_result(&seen); nnhid_test_key(0);
            printf("menu: test: controls: AFTER: %ld polls of player %d with key P held: the game read buttons 0x%llx (A %s)\n", polls, nnhid_kb_player() + 1, (unsigned long long)seen, seen & 1 ? "PRESSED" : "not pressed");
            nnpad_kb_bind(0, g_test_kb_old);
            printf("menu: test: controls: A bound back to its old key 0x%02x\n", g_test_kb_old);
            set_open(1); g_section = SEC_EXPERIMENTAL; g_section_req = g_section; g_test_step = 20; step_at = t; } break;
    case 20: if (t - step_at >= 10) {
            NetStats ns; net_stats_get(&ns);
            printf("menu: test: online page: saved mode %s, this run %s, state %d\n", k_online_mode[O.mode], k_online_mode[O0.mode], ns.state);
            test_shot("online"); g_test_step = 21; } break;
    case 22: set_open(0); printf("menu: test: over\n"); g_test_step = 23; break;
    }
    fflush(stdout);
}
extern "C" int menu_shot_wanted(char *path, int n) {
    if (!g_shot_req) return 0;
    g_shot_req = 0;
    snprintf(path, (size_t)n, "%s", g_shot_path);
    return 1;
}
extern "C" void menu_shot_done(const char *path, int w, int h, int ok) {
    printf("menu: test: picture %s %dx%d %s; draw data of that frame: %d vertices, %d indices, %d commands\n", path, w, h, ok ? "written" : "NOT written", g_vtx.Size, g_idx.Size, g_cmd.Size);
    fflush(stdout);
    if (g_test_step == 3 || g_test_step == 6 || g_test_step == 9 || g_test_step == 15 || g_test_step == 21) g_test_step++;
}

/* ------------------------------------------------------------------ once per presented frame (render thread) */
extern "C" int menu_frame(int width, int height, MenuDraw *out) {
    if (!menu_enabled() || width <= 0 || height <= 0) return 0;
    long long fr = nvn_front_presents();
    int fresh = fr != g_frame;
    g_frame = fr;
    {   LARGE_INTEGER now; QueryPerformanceCounter(&now);
        if (!g_qpf.QuadPart) QueryPerformanceFrequency(&g_qpf);
        if (fresh && g_last_t.QuadPart) { g_ft[g_ft_pos] = (float)((double)(now.QuadPart - g_last_t.QuadPart) * 1000.0 / (double)g_qpf.QuadPart); g_ft_pos = (g_ft_pos + 1) % 120; }
        if (fresh) g_last_t = now; }
    if (!g_sections_inited) { settings_init(width, height); g_sections_inited = 1; CreateThread(NULL, 0, redraw_thread, NULL, 0, NULL); }
    test_tick();
    uint64_t b = nnhid_menu_buttons(), down = b & ~g_pad_prev;
    g_pad_prev = b;
    if (g_open && capturing()) { if (g_pcap < 0 && (down & (BIT(B_HOME) | BIT(B_CAPTURE)))) capture_cancel("Home / Capture"); }      /* Home cancels a rebinding instead of closing */
    else {
        if (down & (BIT(B_HOME) | BIT(B_CAPTURE))) menu_request_toggle();      /* nnhid_menu_buttons bits 16 / 17: never seen by the game */
        if (g_open && (down & BIT(B_PLUS))) menu_request_toggle();
    }
    if (g_open) capture_tick(down);
    for (LONG t = InterlockedExchange(&g_toggle_req, 0); t > 0; t--) set_open(!g_open);
    if (!g_open && g_guard && b == 0 && g_frame - g_closed_at >= 6) InterlockedExchange(&g_guard, 0);      /* closed and every pad button released */
    for (LONG t = InterlockedExchange(&g_stats_req, 0); t > 0; t--) apply_stats(!S.stats);
    if (!g_open && !S.overlay && !S.stats && !g_notice_on) { Ev drop[8]; while (q_take(drop, 8) == 8) continue; return 0; }
    if (!g_im_ready) im_init(height);
    ImGuiIO &io = ImGui::GetIO();
    io.DisplaySize = ImVec2((float)width, (float)height);
    io.FontGlobalScale = g_base_h > 0 ? (float)height / g_base_h : 1.0f;
    {   static LARGE_INTEGER prev; LARGE_INTEGER now; QueryPerformanceCounter(&now);
        float dt = prev.QuadPart ? (float)((double)(now.QuadPart - prev.QuadPart) / (double)g_qpf.QuadPart) : 1.0f / 60.0f;
        io.DeltaTime = dt > 0.0f && dt < 1.0f ? dt : 1.0f / 60.0f; prev = now; }
    Ev ev[256];
    int n = q_take(ev, 256);
    for (int i = 0; i < n && g_open; i++) {
        Ev &e = ev[i];
        if (e.type == EV_KEY && g_capture >= 0 && e.b) {                      /* a new keyboard binding */
            if (e.a != VK_ESCAPE) { nnpad_kb_bind(g_capture, e.a); char nm[16]; nnpad_vk_name(e.a, nm, sizeof nm); printf("menu: keyboard %s bound to %s\n", nnpad_target_name(g_capture), nm); fflush(stdout); g_capture = -1; }
            else capture_cancel("Esc");
            continue;
        }
        if (e.type == EV_KEY && g_pcap >= 0) { if (e.b && e.a == VK_ESCAPE) capture_cancel("Esc"); continue; }      /* the keyboard does not drive the menu meanwhile */
        switch (e.type) {
        case EV_MOVE: io.AddMousePosEvent((float)e.a, (float)e.b); break;
        case EV_BTN: io.AddMouseButtonEvent(e.a, e.b != 0); break;
        case EV_WHEEL: io.AddMouseWheelEvent(0.0f, (float)e.a / (float)WHEEL_DELTA); break;
        case EV_CHAR: io.AddInputCharacterUTF16((ImWchar16)e.a); break;
        case EV_KEY:
            if (e.a == VK_ESCAPE && e.b && !ImGui::IsAnyItemActive() && !ImGui::IsPopupOpen(NULL, ImGuiPopupFlags_AnyPopupId)) { menu_request_toggle(); break; }
            if (e.a == VK_CONTROL) io.AddKeyEvent(ImGuiMod_Ctrl, e.b != 0);
            if (e.a == VK_SHIFT) io.AddKeyEvent(ImGuiMod_Shift, e.b != 0);
            if (e.a == VK_MENU) io.AddKeyEvent(ImGuiMod_Alt, e.b != 0);
            if (vk_key(e.a) != ImGuiKey_None) io.AddKeyEvent(vk_key(e.a), e.b != 0);
            break;
        }
    }
    pad_feed(io, g_open && !capturing() && !osk_active() ? b : 0);
    if (g_open && !capturing() && (down & BIT(B_L))) { g_section = (g_section + SEC_N - 1) % SEC_N; g_section_req = g_section; }
    if (g_open && !capturing() && (down & BIT(B_R))) { g_section = (g_section + 1) % SEC_N; g_section_req = g_section; }
    io.MouseDrawCursor = false;
    ImGui::NewFrame();
    if (S.overlay) draw_overlay();
    if (S.stats) draw_stats();
    if (g_notice_on) {                                   /* R3: the online match's message, in the middle */
        char text[512];
        AcquireSRWLockShared(&g_notice_lock); snprintf(text, sizeof text, "%s", g_notice); ReleaseSRWLockShared(&g_notice_lock);
        ImGui::SetNextWindowPos(ImVec2(io.DisplaySize.x * 0.5f, io.DisplaySize.y * 0.5f), ImGuiCond_Always, ImVec2(0.5f, 0.5f));
        ImGui::SetNextWindowBgAlpha(0.8f);
        ImGui::Begin("##notice", NULL, ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_AlwaysAutoResize | ImGuiWindowFlags_NoInputs | ImGuiWindowFlags_NoNav |
                     ImGuiWindowFlags_NoFocusOnAppearing | ImGuiWindowFlags_NoSavedSettings);
        ImGui::TextColored(ImVec4(1.0f, 0.75f, 0.2f, 1.0f), "Online match");
        ImGui::Separator();
        ImGui::TextUnformatted(text);
        ImGui::End();
        if (!InterlockedExchange(&g_notice_drawn, 1)) { printf("menu: online notice drawn (presented frame %lld): %s\n", g_frame, text); fflush(stdout); }
    }
    if (g_open && !osk_active()) draw_menu(width, height);
    ImGui::Render();
    ImDrawData *dd = ImGui::GetDrawData();
    g_vtx.resize(0); g_idx.resize(0); g_cmd.resize(0);
    for (int i = 0; i < dd->CmdListsCount; i++) {
        const ImDrawList *dl = dd->CmdLists[i];
        uint32_t vbase = (uint32_t)g_vtx.Size, ibase = (uint32_t)g_idx.Size;
        for (int k = 0; k < dl->VtxBuffer.Size; k++) g_vtx.push_back(dl->VtxBuffer[k]);
        for (int k = 0; k < dl->IdxBuffer.Size; k++) g_idx.push_back(dl->IdxBuffer[k]);
        for (int k = 0; k < dl->CmdBuffer.Size; k++) {
            const ImDrawCmd &c = dl->CmdBuffer[k];
            if (c.UserCallback || !c.ElemCount) continue;
            MenuCmd m;
            m.clip[0] = c.ClipRect.x - dd->DisplayPos.x; m.clip[1] = c.ClipRect.y - dd->DisplayPos.y;
            m.clip[2] = c.ClipRect.z - dd->DisplayPos.x; m.clip[3] = c.ClipRect.w - dd->DisplayPos.y;
            m.idx_off = ibase + c.IdxOffset; m.vtx_off = vbase + c.VtxOffset; m.count = c.ElemCount;
            g_cmd.push_back(m);
        }
    }
    if (!g_cmd.Size) return 0;
    out->vtx = g_vtx.Data; out->idx = g_idx.Data; out->cmd = g_cmd.Data;
    out->nvtx = g_vtx.Size; out->nidx = g_idx.Size; out->ncmd = g_cmd.Size;
    out->disp_w = dd->DisplaySize.x; out->disp_h = dd->DisplaySize.y;
    return 1;
}
