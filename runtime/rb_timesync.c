/* Rollback netcode: keeping the two frame clocks together (rb.h). Every input message gives a sample of how far this
 * side runs ahead of the peer; every 30 frames the mean of the middle third of the last 30 samples decides:
 *   ahead by 8 ms or more: run 0.5 % slower (and, in the first 120 frames only, skip one frame when a whole frame ahead);
 *   behind by 8 ms or more: run 1 % faster, and when a whole frame behind run up to 3 extra frames (the caller spreads
 *   them, one per 5 frames). The thresholds follow Slippi's netplay (study N1b section 6). SPDX-License-Identifier: GPL-3.0-or-later */
#include <stdlib.h>
#include <string.h>
#include "rb.h"

#define TS_N 30
static int32_t g_s[TS_N];
static int g_n, g_i, g_frame_us = 16683;
static int32_t g_est;

void rb_ts_reset(int frame_us) { memset(g_s, 0, sizeof g_s); g_n = g_i = 0; g_est = 0; g_frame_us = frame_us > 0 ? frame_us : 16683; }
void rb_ts_sample(int32_t offset_us) { g_s[g_i] = offset_us; g_i = (g_i + 1) % TS_N; if (g_n < TS_N) g_n++; }
int32_t rb_ts_offset(void) { return g_est; }

static int cmp32(const void *a, const void *b) { int32_t x = *(const int32_t *)a, y = *(const int32_t *)b; return (x > y) - (x < y); }

RbSyncAction rb_ts_decide(int frame) {
    RbSyncAction a = {0, 0, 1.0};
    if (frame % 30 || g_n < 3) return a;
    int32_t v[TS_N];
    memcpy(v, g_s, sizeof(int32_t) * (size_t)g_n);
    qsort(v, (size_t)g_n, sizeof v[0], cmp32);
    int lo = g_n / 3, hi = g_n - g_n / 3;
    int64_t sum = 0;
    for (int i = lo; i < hi; i++) sum += v[i];
    g_est = (int32_t)(sum / (hi - lo));
    if (g_est >= 8000) {
        a.speed = 0.995;
        if (frame <= 120 && g_est >= g_frame_us) a.skip = 1;
    } else if (g_est <= -8000) {
        a.speed = 1.01;
        if (g_est <= -g_frame_us) { a.advance = (int)(-g_est / g_frame_us); if (a.advance > 3) a.advance = 3; }
    }
    return a;
}
