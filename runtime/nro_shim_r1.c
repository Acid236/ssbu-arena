/* Track R1 round 3: shim of a run-time module DLL built with -DR1_MARK (tests\r1_nro_build.py, folder nro_bin_r1): nro_shim.c
 * plus the dirty-page maps its lifted stores mark (runtime.h R1M); the exe sets them (r1_state.c). No game content. */
#include "nro_shim.c"
__declspec(dllexport) uint8_t *r1_m1, *r1_m2;
__declspec(dllexport) uint64_t r1_lo1, r1_n1, r1_n2;
