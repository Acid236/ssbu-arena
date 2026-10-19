/* Host side of the exe / ssbu_game.dll split (see game_shim.c).
 *
 * build.py compiles every host file with
 *     -Dfn_table=(*game_fn_table_p) -Dfn_table_count=(*game_fn_table_count_p)
 *     -Ddyn_syms=(*game_dyn_syms_p) -Ddyn_sym_count=(*game_dyn_sym_count_p)
 * so the tables declared in runtime.h become pointers into the DLL, filled in here before main(). */
#include <stdio.h>
#include <stdlib.h>
#include "runtime.h"
#include "game_data.h"

typedef struct {
    void (*call_indirect)(Ctx *, uint64_t);
    void (*host_import)(Ctx *, int);
    void (*guest_trap)(const char *, uint64_t);
    void (*guest_unimpl)(uint64_t, uint32_t, const char *);
    void (*guest_svc)(Ctx *, uint32_t);
    void (*stx_diag)(Ctx *, uint64_t, uint64_t, uint64_t, uint64_t, int);
    void (*site_inline)(Ctx *, uint64_t);      /* appended (game_shim.c): an older DLL copies only the fields it knows */
    int (*site_midhook)(Ctx *, uint64_t);
} GameHost;

typedef struct {
    const FnEntry *table;
    const int *table_count;
    const DynSym *syms;
    const int *sym_count;
} GameTables;

__declspec(dllimport) void game_bind(const GameHost *h, GameTables *t);
/* game_data.h: the dump-derived tables and the lifted SDK code, in the DLL too (game_data.c) */
__declspec(dllimport) void game_data_bind(const GameDataHost *h, GameData *d);
GameData game_data;
void sdk_host_call(Ctx *c, int index);                   /* sdklift_rt.c */
void sdk_trap_call(Ctx *c, const char *name);
void sdk_dispatch(Ctx *c, uint64_t addr);
void *sdk_jmp_record(Ctx *c);
void sdk_jmp_restore(Ctx *c, void *r);
void *sdk_longjmp_target(Ctx *c);

/* The site callouts of a DLL re-lifted from a site list (tools/lifter/relift_sites.py) go to the Skyline layer
 * (skyline.c, included by nnro.c). */
void sky_site_inline(Ctx *c, uint64_t addr);
int sky_site_midhook(Ctx *c, uint64_t addr);

#undef fn_table
#undef fn_table_count
#undef dyn_syms
#undef dyn_sym_count
const FnEntry (*game_fn_table_p)[];
const int *game_fn_table_count_p;
const DynSym (*game_dyn_syms_p)[];
const int *game_dyn_sym_count_p;

__attribute__((constructor)) static void bind_game(void) {
    GameHost h = {call_indirect, host_import, guest_trap, guest_unimpl, guest_svc, stx_diag, sky_site_inline, sky_site_midhook};
    GameTables t;
    game_bind(&h, &t);
    game_fn_table_p = (const FnEntry (*)[])t.table;
    game_fn_table_count_p = t.table_count;
    game_dyn_syms_p = (const DynSym (*)[])t.syms;
    game_dyn_sym_count_p = t.sym_count;
    GameDataHost dh = {GAME_DATA_VERSION, sdk_host_call, sdk_trap_call, sdk_dispatch, sdk_jmp_record, sdk_jmp_restore, sdk_longjmp_target};
    game_data_bind(&dh, &game_data);
    if (game_data.version != GAME_DATA_VERSION || game_data.size != (int)sizeof game_data) {
        fprintf(stderr, "the game DLL was built for another version of this exe (game data interface %d, this exe %d): build both "
                        "from the same tree (scripts/setup.py)\n", game_data.version, GAME_DATA_VERSION);
        exit(9);
    }
}
