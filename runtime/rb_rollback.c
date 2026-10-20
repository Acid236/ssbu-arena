/* R3 (TEST ONLY, default OFF): the GAME SIDE of online rollback (plan\phases\R3_online_rollback.md). Included by
 * r1_state.c after r1_ring.c: it drives R2's snapshot ring (r1_ring_capture / r1_ring_load) and its re-run passes
 * (g_ra_phase 2, the input sequence held, nothing presented) from rb_net.c's input queues instead of the SSBU_RB_SIM
 * schedule. Cut point: both games run the match as a LOCAL versus match (same start: same match settings and seeds), the
 * game's own Local Wireless netcode is not used in the match; only the pads of ports 1 and 2 are exchanged:
 *  - nnhid.c fill_pad, ports 1 / 2, while the match is on: the local player's pad of a real pass is handed to the input
 *    queue (kept for frame + delay, sent); the game gets rb_net's pad of each player for the frame of the pass (a remote
 *    pad not received yet = the last one received, repeated);
 *  - the safe point after each pass (the kick after the submission 0x7103749b24, the same as run-ahead / SSBU_RB_SIM):
 *    received messages are applied; a wrong guess at frame m -> the ring state of frame m - 1 is loaded and the passes
 *    m .. now are run again with the corrected pads (re-run passes but the last skip presentation work: SSBU_RB_SIM_SKIP /
 *    SSBU_RB_SIM_LITE, default 49 / 127 here); then the next real pass waits for its 60 Hz tick (SSBU_RB_NET_PACE=0: no
 *    wait), and for the other player when it is more than SSBU_RB_NET_AHEAD frames behind.
 * Frames: the ring's base capture (the first safe point of the fight) is frame 0; real pass n is frame n.
 * No game content in this file. SPDX-License-Identifier: GPL-3.0-or-later */
#include "rb.h"
int rbn_on(void); void rbn_init(void); void rbn_start(long long f0); int rbn_started(void); int rbn_local_player(void); int rbn_ahead(void);
void rbn_local_pad(long long f, RbPad now); RbPad rbn_pad(int player, long long f);
void rbn_drain(long long cur); int rbn_take_mismatch(void); long long rbn_confirmed(void); int rbn_peer_gone(void);
void rbn_pass_hash(long long f); void rbn_finalize(long long cur); double rbn_pace_extra(long long f); void rbn_report(FILE *o, long long frames);
int rbn_delay(void); int rbn_rtt_ms(void); double rbn_offset_ms(void); void rbn_resend(void); void rbn_status(char *out, size_t n); void rbn_hello(void); int rbn_peer_started(void); void rbn_choose_delay(void);

static int g_rbg = -1;
static int rbg_on(void) { if (g_rbg < 0) g_rbg = rbn_on() > 0; return g_rbg; }
static long long g_rbg_rb, g_rbg_k[RG_MAXSLOT + 2], g_rbg_rerun, g_rbg_miss, g_rbg_stalls, g_rbg_capfail, g_rbg_capskip, g_rbg_lastlocal, g_rbg_real, g_rbg_gone;
static double g_rbg_stall_ms, g_rbg_load_ms, g_rbg_tick0, g_rbg_next, g_rbg_last_go;
static volatile LONG g_rbg_last_k, g_rbg_max_k;
#define RBG_NT 200000
static float *g_rbg_work, *g_rbg_gap; static unsigned char *g_rbg_wk; static int g_rbg_nw, g_rbg_ng, g_rbg_pace = -1, g_rbg_tick_k;
static HANDLE g_rbg_timer;
/* (hs10) the task workers at the safe point H2: r1_state.c holds them from the kick H1 to H2, so at H2 the kick's jobs are
 * queued and their (host-side) wake-up event is signaled and not consumed; a ring load relies on that, since the nn::os
 * objects are not part of the ring. The 200 ms watchdog of that hold let them go while this file waited at H2 (a stall for
 * the other player, the start barrier): they consumed the event and ran the jobs, and a rollback loaded right after left the
 * game's job counters waiting for jobs no worker would ever be woken for: the main thread spun in the job wait f_710354a120
 * forever (rnh2 / rnh3 / hs7). Now the watchdog is paused while this file runs at H2 (SSBU_RB_NET_WDFIX=0: the old way). */
static int g_rbg_wdfix = -1; static long long g_rbg_wd_before, g_rbg_rb_unheld;
static int g_rbg_detail = -1;
static long long g_rbg_test_f = -2; static int g_rbg_test_ms, g_rbg_test_k;    /* SSBU_RB_NET_TEST=<frame>,<ms>[,<k>]: a stall of ms at frame's H2, then a rollback of k */

void rbn_stats(int *delay, int *last, int *maxk) { *delay = rbn_delay(); *last = (int)g_rbg_last_k; *maxk = (int)g_rbg_max_k; }   /* net_relay.c net_stats_get (F2) */

static void rbg_wait_until(double t) {                  /* a high-resolution timer for the long part, a spin for the last 0.3 ms */
    for (;;) {
        double now = now_ms(), left = t - now;
        if (left <= 0) return;
        if (left > 1.3 && g_rbg_timer) { LARGE_INTEGER due; due.QuadPart = -(LONGLONG)((left - 1.0) * 10000.0); SetWaitableTimer(g_rbg_timer, &due, 0, NULL, NULL, FALSE); WaitForSingleObject(g_rbg_timer, 100); }
        else if (left > 0.3) Sleep(0);
        else YieldProcessor();
    }
}
static int rbg_rollback(Ctx *c, long long i, int m) {
    long long target = m - 1, best = -1;
    for (int s = 0; s < g_rg_count; s++) { long long f = rg_slot(s)->frame; if (f <= target && f > best) best = f; }
    if (best < 0) {
        g_rbg_miss++;
        if (g_rbg_miss <= 10) LOG("r1: RB NET: wrong guess at frame %lld but no state at or before frame %lld in the ring (oldest %lld): NOT rolled back (desync)\n", (long long)m, target, r1_ring_oldest());
        return 0;
    }
    double t0 = now_ms();
    if (!g_ra_wh_on) { g_rbg_rb_unheld++; if (g_rbg_rb_unheld <= 10) LOG("r1: RB NET: rollback at frame %lld while the task workers are NOT held (watchdog releases so far %lld): the load may leave the job system waiting\n", i, g_ra_wd_fired); }
    if (!r1_ring_load(best, c)) { g_rbg_miss++; return 0; }
    g_rbg_load_ms += now_ms() - t0;
    int k = (int)(i - best);
    g_rgs_left = k; g_rgs_next = best + 1; g_ra_phase = 2;
    g_rbg_rb++; g_rbg_k[k < RG_MAXSLOT + 1 ? k : RG_MAXSLOT + 1]++; g_rbg_rerun += k; g_rbg_tick_k += k;
    InterlockedExchange(&g_rbg_last_k, k); if (k > g_rbg_max_k) InterlockedExchange(&g_rbg_max_k, k);
    if (g_rbg_rb <= 20 || g_rbg_rb % 200 == 0 || g_rbg_detail > 0) LOG("r1: RB NET: rollback %lld at frame %lld: wrong guess at %d, state of frame %lld loaded in %.3f ms, %d frames again\n", g_rbg_rb, i, m, best, now_ms() - t0, k);
    return 1;
}
/* at the safe point (H2) of every pass while the fight runs (r1_ring.c rgs_step) */
static void rbg_step(Ctx *c) {
    long long i = g_rgs_next;
    if (g_rbg_wdfix < 0) { const char *e = getenv("SSBU_RB_NET_WDFIX"); g_rbg_wdfix = !e || atoi(e) != 0; e = getenv("SSBU_RB_NET_DETAIL"); g_rbg_detail = e && atoi(e) > 0; }
    if (g_rbg_wdfix) g_ra_wd_pause = 1;                 /* (until H2 lets the workers go: r1_state.c ra_kick2) */
    if (g_rbg_wd_before != g_ra_wd_fired) { if (g_rg_ready) LOG("r1: RB NET: the task-worker watchdog let them go before the safe point of frame %lld (%lld times so far)\n", i, g_ra_wd_fired); g_rbg_wd_before = g_ra_wd_fired; }
    if (!g_rg_ready) {                                  /* the base state: r1's full save (one hitch) */
        r1_ring_capture(i, c);
        if (g_rbg_wdfix) g_ra_wd_pause = 1;             /* (the full save sets it back to 0) */
        if (!g_rg_ready) return;
        rbn_start(i);
        if (g_rbg_wdfix) g_ra_wd_base = 2;              /* from now on the hold watchdog has the long limit (H2 sets it back to this) */
        g_rbg_wd_before = g_ra_wd_fired;                /* (releases before the match, e.g. at its slow first passes, are harmless: no state in the ring yet) */
        g_rgs_next = i + 1;
        if (g_rbg_pace < 0) { const char *e = getenv("SSBU_RB_NET_PACE"); g_rbg_pace = !e || atoi(e) != 0; }
        { const char *e = getenv("SSBU_RB_NET_LASTLITE"); g_rgs_lastlite = !e || atoi(e) != 0; }      /* default on here: proven exact (rl4L, rl4K); =0 runs the last re-run pass fully */
        if (!g_rbg_timer) g_rbg_timer = CreateWaitableTimerExW(NULL, NULL, 0x2 /* CREATE_WAITABLE_TIMER_HIGH_RESOLUTION */, TIMER_ALL_ACCESS);
        if (!g_rbg_timer) g_rbg_timer = CreateWaitableTimerExW(NULL, NULL, 0, TIMER_ALL_ACCESS);
        if (!g_rbg_work) { g_rbg_work = calloc(RBG_NT, sizeof *g_rbg_work); g_rbg_gap = calloc(RBG_NT, sizeof *g_rbg_gap); g_rbg_wk = calloc(RBG_NT, 1); }
        LOG("r1: RB NET: match start, base state = frame %lld (fight frame %lld); pacing %s; re-run skip mask %d, lite mask %d%s\n", i, g_ff, g_rbg_pace ? "60 Hz" : "off", g_rgs_skip, g_rgs_lite, g_rgs_lastlite ? " (the last re-run pass too)" : "");
        {   /* start barrier: both games begin frame 1 together (the one that finished loading first waits here, at frame 0,
             * instead of stalling seconds at frame 8 with states it might have to roll back to: rnh2 / rnh3 hung after that) */
            double tb = now_ms(), lastx = 0;
            while (!rbn_peer_started() && now_ms() - tb < 120000) {
                if (now_ms() - lastx >= 50) { lastx = now_ms(); rbn_hello(); }
                rbn_drain(i);
                rbg_wait_until(now_ms() + 1.0);
            }
            rbn_hello(); rbn_choose_delay();
            LOG("r1: RB NET: start barrier: the other game %s after %.0f ms\n", rbn_peer_started() ? "is in the match" : "DID NOT ANSWER (going on)", now_ms() - tb);
        }
        g_rbg_tick0 = now_ms(); g_rbg_next = 0;
        return;
    }
    rbn_pass_hash(i);
    { static int tr = -1; if (tr < 0) tr = getenv("SSBU_RB_NET_TRACE") ? atoi(getenv("SSBU_RB_NET_TRACE")) : 0;
      if (tr > 0 && i <= tr) LOG("r1: RB NET trace: safe point after pass %lld, phase %d, left %d, remote pads up to %lld, %.3f ms\n", i, g_ra_phase, g_rgs_left, rbn_confirmed(), now_ms()); }
    if (g_ra_phase == 2) {                              /* a re-run pass ended: its state is needed only from the newest frame with every pad known on */
        if (g_rgs_left <= 1 || i >= rbn_confirmed()) { if (!r1_ring_capture(i, c)) g_rbg_capfail++; } else g_rbg_capskip++;
        g_rgs_next = i + 1;
        if (--g_rgs_left > 0) return;
        g_ra_phase = 0; g_ra_after_quiet = 1; g_rgs_left = 0;
    } else {                                            /* a real pass ended */
        g_rgs_next = i + 1; g_rbg_real++;
        rbn_drain(i);
        int m = rbn_take_mismatch();
        if (m > 0 && m <= i) {
            /* captured anyway, with the threads kept held for the load that follows (R2 round 2: load hold 3.5 -> 0.2 ms);
             * SSBU_RB_NET_KEEP=0: no capture, the load holds the threads itself */
            static int keep = -1; if (keep < 0) { const char *e = getenv("SSBU_RB_NET_KEEP"); keep = !e || atoi(e) != 0; }
            if (keep) { g_rg_keep = 1; if (!r1_ring_capture(i, c)) g_rbg_capfail++; g_rg_keep = 0; }
            if (rbg_rollback(c, i, m)) return;
            if (keep) r1_ring_let_go(); else if (!r1_ring_capture(i, c)) g_rbg_capfail++;
        } else if (!r1_ring_capture(i, c)) g_rbg_capfail++;
        if (g_rbg_test_f == -2) { const char *e = getenv("SSBU_RB_NET_TEST"); g_rbg_test_f = -1; if (e && *e) { long long tf = -1; int ms = 0, k = 0; sscanf(e, "%lld,%d,%d", &tf, &ms, &k); g_rbg_test_f = tf; g_rbg_test_ms = ms; g_rbg_test_k = k; } }
        if (g_rbg_test_f > 0 && i >= g_rbg_test_f) {    /* (the first real pass from that frame on without a rollback of its own) */
            g_rbg_test_f = -1;                        /* test: a long stall at this safe point, then a rollback (same pads: the timeline must not change) */
            double ts = now_ms(); rbg_wait_until(ts + g_rbg_test_ms);
            LOG("r1: RB NET TEST: stalled %.0f ms at frame %lld (watchdog releases so far %lld, workers held %d); rollback of %d frames\n", now_ms() - ts, i, g_ra_wd_fired, (int)g_ra_wh_on, g_rbg_test_k);
            if (g_rbg_test_k > 0 && rbg_rollback(c, i, (int)(i - g_rbg_test_k + 1))) return;
        }
    }
    /* the next pass is a real one (frame i + 1): pending wrong guesses first, then the other player, then the tick */
    double tw = now_ms();
    if (g_rbg_tick0 > 0 && g_rbg_nw < RBG_NT) { g_rbg_work[g_rbg_nw] = (float)(tw - g_rbg_tick0); g_rbg_wk[g_rbg_nw] = (unsigned char)(g_rbg_tick_k > 255 ? 255 : g_rbg_tick_k); g_rbg_nw++; }
    g_rbg_tick0 = 0;
    int stalled = 0; double ts = 0;
    for (;;) {
        rbn_drain(i);
        int m = rbn_take_mismatch();
        if (m > 0 && m <= i) { if (stalled) { g_rbg_stall_ms += now_ms() - ts; } if (rbg_rollback(c, i, m)) return; }
        if (g_rgs_next - rbn_confirmed() <= rbn_ahead()) break;
        if (rbn_peer_gone()) { if (!g_rbg_gone++) LOG("r1: RB NET: no message from the other player for 5 s at frame %lld: going on alone (guesses)\n", i); break; }
        if (!stalled) { stalled = 1; ts = now_ms(); g_rbg_stalls++; r1_ring_let_go(); }
        {   /* while waiting: our newest pads again every 50 ms (a lost datagram must not leave both games waiting), a line every 2 s */
            static double last_tx, last_log; double now = now_ms();
            if (now - last_tx >= 50) { last_tx = now; rbn_resend(); }
            if (now - ts >= 2000 && now - last_log >= 2000) { last_log = now; char st[200]; rbn_status(st, sizeof st);
                LOG("r1: RB NET: waiting for the other player at frame %lld for %.0f ms: %s\n", i, now - ts, st); }
        }
        rbg_wait_until(now_ms() + 0.5);
    }
    if (stalled) g_rbg_stall_ms += now_ms() - ts;
    r1_ring_let_go();
    rbn_finalize(i);
    if (g_rbg_pace) {
        double period = 1000.0 / 60.0 + rbn_pace_extra(g_rgs_next), now = now_ms();
        if (g_rbg_next <= 0 || now - g_rbg_next > 3 * period) g_rbg_next = now;      /* (far behind: no catching up in a burst) */
        rbg_wait_until(g_rbg_next);
        g_rbg_next += period;
    }
    double go = now_ms();
    if (g_rbg_last_go > 0 && g_rbg_ng < RBG_NT) g_rbg_gap[g_rbg_ng++] = (float)(go - g_rbg_last_go);
    g_rbg_last_go = go; g_rbg_tick0 = go; g_rbg_tick_k = 0;
    if (g_rbg_real % 600 == 0) LOG("r1: RB NET: frame %lld: %lld rollbacks (%lld frames again), %lld stalls (%.0f ms), round trip %d ms, delay %d, remote pads up to %lld, clock ahead of the other game by %.1f ms\n",
                                   i, g_rbg_rb, g_rbg_rerun, g_rbg_stalls, g_rbg_stall_ms, rbn_rtt_ms(), rbn_delay(), rbn_confirmed(), rbn_offset_ms());
}
/* nnhid.c (through r1_pad / r1_pad_id): the pad of port id (0 / 1) in the pass now running */
static void rbg_pad(int id, uint64_t *b, int *lx, int *ly, int *rx, int *ry) {
    if (!g_rg_ready || g_ra_off || !rbn_started() || id < 0 || id > 1) return;
    long long f = g_rgs_next;
    if (f < 1) return;
    if (id == 0 && g_ra_phase != 2 && f > g_rbg_lastlocal) {          /* a real pass: this game's own pad (port 1's devices / input sequence) */
        RbPad now; now.buttons = *b & 0xffffull; now.lx = (int16_t)*lx; now.ly = (int16_t)*ly; now.rx = (int16_t)*rx; now.ry = (int16_t)*ry;
        rbn_local_pad(f, now); g_rbg_lastlocal = f;
    }
    RbPad p = rbn_pad(id, f);
    *b = p.buttons; *lx = p.lx; *ly = p.ly; *rx = p.rx; *ry = p.ry;
}
static int cmp_f(const void *a, const void *b) { float x = *(const float *)a, y = *(const float *)b; return x < y ? -1 : x > y; }
static void rbg_dist(const char *what, const float *v, int n, const unsigned char *kk, int want) {
    float *w = malloc((size_t)(n ? n : 1) * sizeof *w); int m = 0; double s = 0, over = 0;
    for (int j = 0; j < n; j++) if (!kk || want < 0 || (want == 0 ? kk[j] == 0 : kk[j] > 0)) { w[m++] = v[j]; s += v[j]; over += v[j] > 1000.0 / 60.0; }
    if (m) { qsort(w, (size_t)m, sizeof *w, cmp_f);
        LOG("r1: RB NET TIMING %s: %d, mean %.2f median %.2f p90 %.2f p99 %.2f max %.2f ms; over 16.67 ms: %.0f (%.2f%%)\n", what, m, s / m, w[m / 2], w[m * 9 / 10], w[m * 99 / 100], w[m - 1], over, 100.0 * over / m); }
    free(w);
}
static void rbg_report(void) {
    if (g_rbg <= 0 || !g_rg_ready) return;
    LOG("r1: RB NET report: %lld real frames, %lld rollbacks, %lld frames run again (k: 1 %lld, 2 %lld, 3 %lld, 4 %lld, 5 %lld, 6 %lld, 7 %lld, more %lld); rollbacks impossible (state not in the ring) %lld\n",
        g_rbg_real, g_rbg_rb, g_rbg_rerun, g_rbg_k[1], g_rbg_k[2], g_rbg_k[3], g_rbg_k[4], g_rbg_k[5], g_rbg_k[6], g_rbg_k[7], g_rbg_k[RG_MAXSLOT + 1] + g_rbg_k[8], g_rbg_miss);
    LOG("r1: RB NET report: stalls for the other player %lld (%.1f ms in all); captures failed %lld, re-run captures not needed %lld; load mean %.3f ms; peer silent %lld\n",
        g_rbg_stalls, g_rbg_stall_ms, g_rbg_capfail, g_rbg_capskip, g_rbg_rb ? g_rbg_load_ms / g_rbg_rb : 0.0, g_rbg_gone);
    LOG("r1: RB NET report: task-worker watchdog releases %lld (since the process start), rollbacks with the workers not held %lld (watchdog paused at H2: %s)\n", g_ra_wd_fired, g_rbg_rb_unheld, g_rbg_wdfix ? "yes" : "NO");
    rbg_dist("work per tick (real pass + its rollback, without waits)", g_rbg_work, g_rbg_nw, g_rbg_wk, -1);
    rbg_dist("work per tick without rollback", g_rbg_work, g_rbg_nw, g_rbg_wk, 0);
    rbg_dist("work per tick with rollback", g_rbg_work, g_rbg_nw, g_rbg_wk, 1);
    rbg_dist("time between real passes (tick to tick)", g_rbg_gap, g_rbg_ng, NULL, -1);
    rbn_report(g_log, g_rbg_real);
}
