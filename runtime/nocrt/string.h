/* Minimal <string.h> for the game libraries built without the MSVC / Windows SDK headers (RECOMP_NOCRT=1, see
 * tools/lifter/build.py): the declarations the lifted code and the shims use, written as the C library declares them,
 * nothing else. The functions themselves come from ucrtbase.dll, part of Windows 10 and 11 (nocrt/ucrtbase_min.def). */
#ifndef SSBU_NOCRT_STRING_H
#define SSBU_NOCRT_STRING_H
#include <stddef.h>
void *__cdecl memcpy(void *_Dst, const void *_Src, size_t _Size);
void *__cdecl memmove(void *_Dst, const void *_Src, size_t _Size);
void *__cdecl memset(void *_Dst, int _Val, size_t _Size);
int __cdecl memcmp(const void *_Buf1, const void *_Buf2, size_t _Size);
size_t __cdecl strlen(const char *_Str);
int __cdecl strcmp(const char *_Str1, const char *_Str2);
int __cdecl strncmp(const char *_Str1, const char *_Str2, size_t _MaxCount);
#endif
