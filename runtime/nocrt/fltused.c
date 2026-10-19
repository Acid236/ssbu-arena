/* For the RECOMP_NOCRT module DLLs (tools/lifter/build.py link_dll): clang, like MSVC, references _fltused from every
 * object that uses floating point, and the C runtime that normally defines it is not linked. The value is the one the
 * Universal CRT uses; nothing reads it. The game DLL defines it in game_data.c. */
int _fltused = 0x9875;
