/* Track R1 round 3: the shim of ssbu_game_p15r1.dll (built with -DR1_MARK): game_shim_eh.c plus the dirty-page maps every
 * guest store of the lifted code marks (runtime.h R1M). The exe finds them with GetProcAddress and sets them; until then
 * both windows are empty and nothing is marked. No game content. */
#include "game_shim_eh.c"
__declspec(dllexport) uint8_t *r1_m1, *r1_m2;
__declspec(dllexport) uint64_t r1_lo1, r1_n1, r1_n2;
