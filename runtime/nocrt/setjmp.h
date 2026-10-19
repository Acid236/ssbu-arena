/* Minimal <setjmp.h> for the game libraries built without the MSVC headers (RECOMP_NOCRT=1): the x64 jmp_buf of the
 * Microsoft C runtime (16 aligned 16-byte slots, 256 bytes) and its two functions, which ntdll.dll exports
 * (nocrt/ntdll_min.def). The lifted SDK code's SDK_SETJMP (sdklift.h) uses it. */
#ifndef SSBU_NOCRT_SETJMP_H
#define SSBU_NOCRT_SETJMP_H
typedef struct __declspec(align(16)) _SETJMP_FLOAT128 { unsigned __int64 Part[2]; } SETJMP_FLOAT128;
#define _JBLEN 16
typedef SETJMP_FLOAT128 _JBTYPE;
typedef _JBTYPE jmp_buf[_JBLEN];
#define setjmp _setjmp
int __cdecl setjmp(jmp_buf _Buf);
__declspec(noreturn) void __cdecl longjmp(jmp_buf _Buf, int _Value);
#endif
