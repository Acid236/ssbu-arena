/* U1: the settings menu when the build has no Dear ImGui (build.py compiles this file instead of menu.cpp and the ImGui
 * sources when IMGUI_ROOT / the default folder holds no imgui.h). Everything answers "no menu": F1 and the controller's
 * Home button do nothing, the game's input is never held, nothing is drawn. One log line says why, when the menu was
 * asked for (SSBU_MENU=1, graphics.ini menu = on) or F1 is pressed. */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "gfx_options.h"
#include "menu.h"
#include "net_stats.h"

static int g_said;
static void say_why(const char *what) {
    if (g_said++) return;
    printf("menu: %s, but this build has no settings menu (Dear ImGui was not found when it was built: scripts/setup.py --imgui <folder> or IMGUI_ROOT)\n", what);
    fflush(stdout);
}
int menu_enabled(void) {
    static int checked;
    if (!checked) {
        const char *e = getenv("SSBU_MENU");
        checked = 1;
        /* graphics.ini menu = on is the default: only an explicit request (or the test hook) is worth a line at the start */
        if ((e && e[0] && atoi(e) != 0) || (getenv("SSBU_MENU_TEST") && getenv("SSBU_MENU_TEST")[0])) say_why("the settings menu is asked for");
    }
    return 0;
}
int menu_is_open(void) { return 0; }
int menu_input_blocked(void) { return 0; }
void menu_request_toggle(void) {}
void menu_notice(const char *text) { (void)text; }      /* (the message is in the log only) */
void menu_popup(const char *title, const char *text) { printf("menu: popup (no menu in this build): %s: %s\n", title ? title : "", text ? text : ""); fflush(stdout); }
int menu_wndproc(void *hwnd, unsigned msg, uintptr_t w, intptr_t l) {
    (void)hwnd; (void)l;
    if (msg == WM_KEYDOWN && w == VK_F1) say_why("F1 was pressed");
    return 0;
}
int menu_frame(int width, int height, MenuDraw *out) { (void)width; (void)height; (void)out; return 0; }
const unsigned char *menu_font_rgba(int *w, int *h) { *w = *h = 0; return NULL; }
int menu_shot_wanted(char *path, int n) { (void)path; (void)n; return 0; }
void menu_shot_done(const char *path, int w, int h, int ok) { (void)path; (void)w; (void)h; (void)ok; }
void menu_assert_fail(const char *what, const char *file, int line) { (void)what; (void)file; (void)line; }

/* net_stats.h: the default answer until the online code defines net_stats_get itself (as in menu.cpp) */
void net_stats_get_default(NetStats *o) { memset(o, 0, sizeof *o); o->state = NET_OFFLINE; o->ping_ms = -1; }
#pragma comment(linker, "/alternatename:net_stats_get=net_stats_get_default")
#ifndef _WIN32
/* Linux / macOS (display.c's SDL window thread): nothing to take from the window without the menu */
void menu_sdl_attach(void *window) { (void)window; }
void menu_sdl_service(void) {}
#endif
