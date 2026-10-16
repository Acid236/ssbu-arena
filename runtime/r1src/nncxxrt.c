/* Track R1 round 5: the C++ runtime (static-local guards __cxa_guard_*: host wr8 into guest memory) with dirty-page marks
 * (runtime.h R1M). Nothing else differs from the tree file. */
#define R1_MARK 1
#include "../nncxxrt.c"
