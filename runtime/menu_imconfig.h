/* U1: Dear ImGui's compile-time configuration for the settings menu (build.py compiles imgui with
 * -DIMGUI_USER_CONFIG="menu_imconfig.h"). A failed ImGui check is logged (a few times), it does not stop the game. */
#pragma once
#ifdef __cplusplus
extern "C"
#endif
void menu_assert_fail(const char *what, const char *file, int line);
/* No __FILE__: it is the full path of the build folder (with the builder's user name), and a prebuilt exe must not carry it
 * (scripts/make_release.py audits that); the expression and the line say enough. */
#define IM_ASSERT(_EXPR) do { if (!(_EXPR)) menu_assert_fail(#_EXPR, "imgui", __LINE__); } while (0)
#define IMGUI_DISABLE_OBSOLETE_FUNCTIONS
#define IMGUI_DISABLE_WIN32_DEFAULT_IME_FUNCTIONS      /* no imm32.lib */
