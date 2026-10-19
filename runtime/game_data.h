/* What the host runtime gets from the game DLL besides the lifted game code: every table and every piece of code that
 * is derived from the dump (the SDK data symbols gen_sdkdata.py reads out of sdk.elf, the module list build_nro.py writes
 * from data.arc, the SDK functions sdklift.py lifts, the exception-table vectors gen_eh_tests.py decodes from main.elf).
 *
 * They used to be compiled into the exe. Living in ssbu_game*.dll (game_data.c), which is built on the player's PC from
 * the player's own dump, they leave the exe free of anything of the game: the exe can be built once and published as a
 * prebuilt runtime (scripts/make_release.py), and the player's PC builds only the DLLs.
 *
 * The exe calls game_data_bind() once before main() (gamedll.c). GAME_DATA_VERSION changes whenever this interface does:
 * an exe and a DLL of different versions refuse to run together instead of misreading each other's tables. */
#ifndef GAME_DATA_H
#define GAME_DATA_H

#include "runtime.h"

#define GAME_DATA_VERSION 1

typedef struct { const char *name; const unsigned char *bytes; unsigned size; } SdkData;      /* sdkdata.c (gen_sdkdata.py) */

typedef struct {                                 /* nro_registry.c (build_nro.py), one per script module of the game */
    const char *name;
    uint64_t base;
    uint32_t image_size, file_size;              /* file_size = text + rodata + data as stored in data.arc */
    uint8_t build_id[20];
} NroInfo;

typedef struct {
    int version;                                 /* GAME_DATA_VERSION of the DLL */
    int size;                                    /* sizeof(GameData) of the DLL */
    const SdkData *sdk_data_tab;                 /* the exe's names for them (hostrt.h, nnro.c, sdklift.h) are macros over these */
    int sdk_data_n;
    const NroInfo *nro_tab;
    int nro_n;
    const void *sdk_fn_tab;                      /* const SdkFn[] (sdklift.h), sorted by address */
    int sdk_fn_n;
    const char *const *sdk_host_name_tab;
    int sdk_host_name_n;
    const void *eh_vec_tab;                      /* const EhVec[] (cxxrt_selftest.h): self-test vectors of eh_tests.h */
    int eh_vec_n;
    const void *eh_fn_vec_tab;                   /* const EhFnVec[] */
    int eh_fn_vec_n;
} GameData;

/* the host functions the lifted SDK code calls (sdklift_rt.c); the DLL forwards its calls through these */
typedef struct {
    int version;                                 /* GAME_DATA_VERSION of the exe */
    void (*sdk_host_call)(Ctx *c, int index);
    void (*sdk_trap_call)(Ctx *c, const char *name);
    void (*sdk_dispatch)(Ctx *c, uint64_t addr);
    void *(*sdk_jmp_record)(Ctx *c);             /* SdkJmpRec * */
    void (*sdk_jmp_restore)(Ctx *c, void *rec);
    void *(*sdk_longjmp_target)(Ctx *c);         /* SdkJmpRec * the guest longjmp goes to (its value set); does not return if none */
} GameDataHost;

#endif
