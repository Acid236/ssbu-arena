/* R3 (TEST ONLY, default OFF): the match handshake of an online rollback session (plan\phases\R3_online_rollback.md,
 * section 6). Shared by rb_net.c (the protocol) and debug_mode.c (reads the select screens' choice, writes the agreed
 * one through the debug-match route A hook). Plain values only; the game fields they come from are named in debug_mode.c.
 * No game content in this file. SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef RB_HS_H
#define RB_HS_H
#include <stdint.h>
#pragma pack(push, 1)
typedef struct {
    uint64_t chara[2];             /* ui_chara id of player 1 (the host's own choice) and player 2 (the joiner's own choice) */
    uint8_t colour[2];
    uint8_t has_layout[2];         /* 1: layout[i] = that player's control layout as its own game resolved it */
    uint16_t layout[2][11];        /* (panel state + 0x54 .. 0x69 / the name-tag profile + 0xc .. 0x21) */
    uint8_t stage[0x20];           /* the host's stage choice entry (ui_stage id, form, flag word, second id) */
    uint8_t hazards, rule_kind, stock, pad0;
    uint32_t items;                /* match block + 0x54 (item appear) */
    uint64_t seed;                 /* the agreed seed (never 0) */
    /* (hs12) the host's state that the game's stage set-up 0x710177a980 reads (run tw5: a stage whose variation, stage
     * block + 0x91 / + 0x92, the two games chose differently from their own history: desync from frame 7): the seed word
     * at 0x710530d380, the set-up's own history 0x71050c5ad0 .. + 0x60 (no-repeat bags), the match block's stage block
     * (+ 0x420 .. + 0x4d0) as it was before the set-up. Both games write the host's values before the set-up runs. */
    uint32_t ctx_seed;
    uint8_t ctx_hist[0x60];
    uint8_t ctx_stage[0xb0];
} RbhMatch;
#pragma pack(pop)
int rbn_handshake_wanted(void);                         /* SSBU_RB_NET=net (not loop) and SSBU_RB_NET_HANDSHAKE not 0: env only */
/* main thread, at the match set-up (player 1's record): `mine` = this game's own choice in chara[0] / colour[0] /
 * layout[0] (+ the stage / rule fields: used from the host only). Blocks until both games agree (or the wait limit);
 * 1 = *out is the agreed match, 0 = not agreed (each game plays its own choice: the match will differ) */
int rbn_handshake(const RbhMatch *mine, RbhMatch *out);
uint64_t rbn_match_seed(void);                          /* the agreed seed, 0 before / without a handshake */
#endif
