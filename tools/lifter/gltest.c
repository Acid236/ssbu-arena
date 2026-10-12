/* Study tool: does this PC's OpenGL driver accept the game's shader programs as they are?
 *
 * The control section the game passes to nvnProgramSetShaders holds the shader as NV_gpu_program5
 * assembly text (offset at +0x14, length at +0x18). This program creates an OpenGL context and gives
 * every dumped shader (shader_dump\*_control.bin, written by nvn_stub.c) to glProgramStringARB.
 *
 *     gltest.exe            prints the driver, then one line per shader
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include <GL/gl.h>

/* ask laptop drivers for the discrete GPU */
__declspec(dllexport) DWORD NvOptimusEnablement = 1;
__declspec(dllexport) int AmdPowerXpressRequestHighPerformance = 1;

#define GL_VERTEX_PROGRAM_ARB 0x8620
#define GL_FRAGMENT_PROGRAM_ARB 0x8804
#define GL_GEOMETRY_PROGRAM_NV 0x8C26
#define GL_PROGRAM_FORMAT_ASCII_ARB 0x8875
#define GL_PROGRAM_ERROR_POSITION_ARB 0x864B
#define GL_PROGRAM_ERROR_STRING_ARB 0x8874

typedef void (WINAPI *GenProgramsFn)(int, unsigned *);
typedef void (WINAPI *BindProgramFn)(unsigned, unsigned);
typedef void (WINAPI *ProgramStringFn)(unsigned, unsigned, int, const void *);

int main(void) {
    WNDCLASSA wc;
    memset(&wc, 0, sizeof wc);
    wc.lpfnWndProc = DefWindowProcA;
    wc.hInstance = GetModuleHandleA(NULL);
    wc.lpszClassName = "gltest";
    wc.style = CS_OWNDC;
    RegisterClassA(&wc);
    HWND w = CreateWindowA("gltest", "gltest", WS_OVERLAPPEDWINDOW, 0, 0, 64, 64, NULL, NULL, wc.hInstance, NULL);
    HDC dc = GetDC(w);
    PIXELFORMATDESCRIPTOR pfd;
    memset(&pfd, 0, sizeof pfd);
    pfd.nSize = sizeof pfd;
    pfd.nVersion = 1;
    pfd.dwFlags = PFD_DRAW_TO_WINDOW | PFD_SUPPORT_OPENGL | PFD_DOUBLEBUFFER;
    pfd.iPixelType = PFD_TYPE_RGBA;
    pfd.cColorBits = 32;
    pfd.cDepthBits = 24;
    SetPixelFormat(dc, ChoosePixelFormat(dc, &pfd), &pfd);
    HGLRC rc = wglCreateContext(dc);
    if (!rc || !wglMakeCurrent(dc, rc)) { printf("no OpenGL context\n"); return 1; }
    printf("vendor  : %s\nrenderer: %s\nversion : %s\n", glGetString(GL_VENDOR), glGetString(GL_RENDERER), glGetString(GL_VERSION));
    const char *ext = (const char *)glGetString(GL_EXTENSIONS);
    static const char *const wanted[] = {"GL_NV_gpu_program5", "GL_NV_bindless_texture", "GL_NV_parameter_buffer_object2", "GL_NV_shader_storage_buffer_object",
                                         "GL_NV_gpu_program_fp64", "GL_ARB_bindless_texture"};
    for (int i = 0; i < 6; i++) printf("  %-36s %s\n", wanted[i], ext && strstr(ext, wanted[i]) ? "yes" : "NO");
    GenProgramsFn gen = (GenProgramsFn)wglGetProcAddress("glGenProgramsARB");
    BindProgramFn bind = (BindProgramFn)wglGetProcAddress("glBindProgramARB");
    ProgramStringFn string = (ProgramStringFn)wglGetProcAddress("glProgramStringARB");
    if (!gen || !bind || !string) { printf("the driver has no assembly program support\n"); return 1; }

    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA("shader_dump\\*_control.bin", &fd);
    int total = 0, accepted = 0, truncated = 0;
    if (h != INVALID_HANDLE_VALUE) do {
        char path[MAX_PATH];
        static uint8_t buf[1 << 20];
        snprintf(path, sizeof path, "shader_dump\\%s", fd.cFileName);
        FILE *f = fopen(path, "rb");
        size_t n = fread(buf, 1, sizeof buf, f);
        fclose(f);
        uint32_t off = *(uint32_t *)(buf + 0x14), len = *(uint32_t *)(buf + 0x18);
        if (*(uint32_t *)buf != 0x98761234u || off + len > n) { truncated++; continue; }
        const char *text = (const char *)buf + off;
        unsigned target = !memcmp(text, "!!NVvp", 6) ? GL_VERTEX_PROGRAM_ARB : !memcmp(text, "!!NVfp", 6) ? GL_FRAGMENT_PROGRAM_ARB
                        : !memcmp(text, "!!NVgp", 6) ? GL_GEOMETRY_PROGRAM_NV : 0;
        if (!target) { printf("%-24s unknown kind %.9s\n", fd.cFileName, text); continue; }
        unsigned id = 0;
        int pos = -1;
        gen(1, &id);
        bind(target, id);
        while (glGetError() != GL_NO_ERROR) {}
        string(target, GL_PROGRAM_FORMAT_ASCII_ARB, (int)strlen(text), text);
        glGetIntegerv(GL_PROGRAM_ERROR_POSITION_ARB, &pos);
        total++;
        if (pos == -1 && glGetError() == GL_NO_ERROR) { accepted++; printf("%-24s %.9s  %5u bytes  accepted\n", fd.cFileName, text, len); }
        else printf("%-24s %.9s  %5u bytes  REJECTED at %d: %s\n", fd.cFileName, text, len, pos, glGetString(GL_PROGRAM_ERROR_STRING_ARB));
    } while (FindNextFileA(h, &fd));
    printf("\n%d shaders tried, %d accepted by the driver, %d skipped (dump too short)\n", total, accepted, truncated);
    return 0;
}
