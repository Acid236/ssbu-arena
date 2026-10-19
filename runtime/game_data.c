/* Linked into the game DLL (ssbu_game*.dll) with the lifted game code: the exe's view of the dump-derived tables and of
 * the lifted SDK code, which are compiled into this DLL beside it (build.py GAME_DATA_SOURCES: sdkdata.c, nro_registry.c,
 * sdklift_gen.c; eh_tests.h below). See game_data.h for why they are here and not in the exe.
 *
 * Compiled with -DSDKLIFT_GEN (sdklift.h then declares only what the lifted SDK code uses) and, in a build without the
 * MSVC / Windows SDK headers, -DGAME_NOCRT with the headers of nocrt\ (build.py RECOMP_NOCRT). */
#include "runtime.h"
#include "sdklift.h"
#include "game_data.h"
#include "eh_tests.h"                            /* static const EhVec eh_vecs[], EhFnVec eh_fn_vecs[] (gen_eh_tests.py) */

extern const SdkData sdk_data[];                 /* sdkdata.c */
extern const int sdk_data_count;
extern const NroInfo nro_registry[];             /* nro_registry.c (its own copy of the NroInfo layout) */
extern const int nro_registry_count;

static GameDataHost host;

/* the host functions the lifted SDK code calls (sdklift_rt.c), forwarded: the DLL cannot import from the exe */
void sdk_host_call(Ctx *c, int index) { host.sdk_host_call(c, index); }
void sdk_trap_call(Ctx *c, const char *name) { host.sdk_trap_call(c, name); }
void sdk_dispatch(Ctx *c, uint64_t addr) { host.sdk_dispatch(c, addr); }
SdkJmpRec *sdk_jmp_record(Ctx *c) { return (SdkJmpRec *)host.sdk_jmp_record(c); }
void sdk_jmp_restore(Ctx *c, SdkJmpRec *r) { host.sdk_jmp_restore(c, r); }
/* SDK_SETJMP (sdklift.h) runs setjmp in the lifted function, in this DLL: the matching longjmp is made here too, with the
 * same C library (the exe's static one and this DLL's may differ) */
void sdk_longjmp(Ctx *c) {
    SdkJmpRec *r = (SdkJmpRec *)host.sdk_longjmp_target(c);
    longjmp(r->host, 1);
}

#ifdef GAME_NOCRT
/* without the C runtime: the one symbol the compiler expects it to define when floating point is used (MSVC ABI) */
int _fltused = 0x9875;
#endif

__declspec(dllexport) void game_data_bind(const GameDataHost *h, GameData *d) {
    host = *h;
    memset(d, 0, sizeof *d);
    d->version = GAME_DATA_VERSION;
    d->size = (int)sizeof *d;
    if (h->version != GAME_DATA_VERSION)
        return;                                  /* the exe reports the mismatch (gamedll.c) */
    d->sdk_data_tab = sdk_data;
    d->sdk_data_n = sdk_data_count;
    d->nro_tab = nro_registry;
    d->nro_n = nro_registry_count;
    d->sdk_fn_tab = sdk_fns;
    d->sdk_fn_n = sdk_fn_count;
    d->sdk_host_name_tab = sdk_host_names;
    d->sdk_host_name_n = sdk_host_name_count;
    d->eh_vec_tab = eh_vecs;
    d->eh_vec_n = (int)(sizeof eh_vecs / sizeof eh_vecs[0]);
    d->eh_fn_vec_tab = eh_fn_vecs;
    d->eh_fn_vec_n = (int)(sizeof eh_fn_vecs / sizeof eh_fn_vecs[0]);
}
