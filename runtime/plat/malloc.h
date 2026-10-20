/* POSIX builds: glibc's <malloc.h>; macOS has its malloc extensions in <malloc/malloc.h> and no <malloc.h>. */
#ifdef __APPLE__
#include <stdlib.h>
#include <malloc/malloc.h>
#else
#include_next <malloc.h>
#endif
