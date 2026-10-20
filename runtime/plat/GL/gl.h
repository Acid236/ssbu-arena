/* Linux build: the system <GL/gl.h> declares some GL 1.2+ functions that the runtime loads itself as pointers of the
 * same name (the Windows gl.h stops at 1.1): those declarations are renamed out of the way. */
#ifndef PLAT_GL_GL_H
#define PLAT_GL_GL_H
#define glBlendColor plat_sys_glBlendColor
#define glCompressedTexSubImage2D plat_sys_glCompressedTexSubImage2D
#define glCompressedTexSubImage3D plat_sys_glCompressedTexSubImage3D
#define glTexSubImage3D plat_sys_glTexSubImage3D
#define glTexImage3D plat_sys_glTexImage3D
#define glCopyTexSubImage3D plat_sys_glCopyTexSubImage3D
#define glDrawRangeElements plat_sys_glDrawRangeElements
#define glActiveTexture plat_sys_glActiveTexture
#define glBlendEquation plat_sys_glBlendEquation
#define glCompressedTexImage2D plat_sys_glCompressedTexImage2D
#define glCompressedTexImage3D plat_sys_glCompressedTexImage3D
#define glSampleCoverage plat_sys_glSampleCoverage
#define GL_GLEXT_LEGACY
#ifdef __APPLE__                 /* macOS: the OpenGL framework's header (GL 2.1 legacy profile); its GL 1.2+ functions as
                                    pointer types only, the runtime loads them itself under the same names */
#define GL_SILENCE_DEPRECATION
#define GL_GLEXT_FUNCTION_POINTERS 1
#include <OpenGL/gl.h>
#else
#include_next <GL/gl.h>
#endif
#undef glBlendColor
#undef glCompressedTexSubImage2D
#undef glCompressedTexSubImage3D
#undef glTexSubImage3D
#undef glTexImage3D
#undef glCopyTexSubImage3D
#undef glDrawRangeElements
#undef glActiveTexture
#undef glBlendEquation
#undef glCompressedTexImage2D
#undef glCompressedTexImage3D
#undef glSampleCoverage
#endif
