/* Linux build: forced into every host and game compile (-include). The MSVC keywords the sources use. */
#ifndef PLAT_PRE_H
#define PLAT_PRE_H
#define __declspec(x) PLAT_DECLSPEC_##x
#define PLAT_DECLSPEC_thread __thread
#define PLAT_DECLSPEC_dllexport __attribute__((visibility("default")))
#define PLAT_DECLSPEC_dllimport
#define PLAT_DECLSPEC_noinline __attribute__((noinline))
#define PLAT_DECLSPEC_noreturn __attribute__((noreturn))
#define PLAT_DECLSPEC_align(n) __attribute__((aligned(n)))
#define __forceinline inline __attribute__((always_inline))
#endif
