/* R3 (TEST ONLY, default OFF): the ONLINE ROLLBACK SESSION, the parts that do not touch the game's state
 * (plan\phases\R3_online_rollback.md). The game side (snapshot ring, re-run passes, the pads given to the game) is
 * rb_rollback.c, included by r1_state.c; the transport is net_relay.c (packet type 16, through the lobby / the host's
 * game). This file: the input queues (rb_input.c), the wire format (rb_wire.c), the time sync (rb_timesync.c), the
 * receive queue, the RTT / clock-offset measurement, the per-frame state checksums, a test bot and the session report.
 * Design after Slippi's netplay (project-slippi/Ishiiruka, GPL-2.0-or-later) and melee-unlocked's mu_net
 * (GPL-2.0-or-later), N1 / N1b studies; no code copied. No game content in this file.
 *
 *   SSBU_RB_NET=net        two games over net_relay (SSBU_ONLINE host / join / lobby with a private code)
 *   SSBU_RB_NET=loop[,<f>] one game: the other player is a bot whose pads "arrive" <f> frames late (default 4):
 *                          rollback without a network, for the determinism proof (f = 0: never late = reference)
 *   SSBU_RB_NET_PLAYER=0|1 this game's player (default: 0, 1 in SSBU_ONLINE=join mode)
 *   SSBU_RB_NET_DELAY=<n>  input delay in frames (default: from the measured round trip, 1..4)
 *   SSBU_RB_NET_BOT=<seed> the local player's pads come from a test bot instead of the controller / input sequence
 *   SSBU_RB_NET_LOG=<file> one line per finalized frame: "f <frame> h <checksum>" (compare two games' files)
 *   SSBU_RB_NET_AHEAD=<n>  most frames this game runs ahead of the newest remote pad (default 7 = the ring depth)
 * SPDX-License-Identifier: GPL-3.0-or-later */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "rb.h"
#include "rb_input.c"
#include "rb_wire.c"
#include "rb_timesync.c"
#undef M

int net_rb_send(const void *p, int n);                 /* net_relay.c: 1 = sent (or queued by the latency simulation) */
int net_rb_ready(void);                                /* net_relay.c: joined a lobby (the host's game or a server) */
int net_mode(void);
int net_online(void);

static int g_on = -1, g_loop, g_loop_lat = 4, g_local, g_delay_cfg = -1, g_ahead = 7, g_started, g_peer_started;
static unsigned g_bot_seed; static int g_bot;
static FILE *g_hlog;
static volatile LONG64 g_cur;                          /* the frame this game is on (read by the receive thread for PONGs) */
static LARGE_INTEGER g_qpf;
static uint64_t now_us(void) { LARGE_INTEGER t; QueryPerformanceCounter(&t); if (!g_qpf.QuadPart) QueryPerformanceFrequency(&g_qpf); return (uint64_t)(t.QuadPart / (double)g_qpf.QuadPart * 1e6); }

int rbn_on(void) {
    if (g_on >= 0) return g_on;
    const char *e = getenv("SSBU_RB_NET");
    g_on = e && e[0] && e[0] != '0';
    if (!g_on) return 0;
    if (!_strnicmp(e, "loop", 4)) { g_loop = 1; if (e[4] == ',') g_loop_lat = atoi(e + 5); }
    g_local = 0;
    if (!g_loop && net_online() && net_mode() == 3) g_local = 1;      /* NET_MODE_JOIN */
    if ((e = getenv("SSBU_RB_NET_PLAYER"))) g_local = atoi(e) ? 1 : 0;
    if ((e = getenv("SSBU_RB_NET_DELAY"))) g_delay_cfg = atoi(e);
    if ((e = getenv("SSBU_RB_NET_BOT")) && *e) { g_bot = 1; g_bot_seed = (unsigned)strtoul(e, NULL, 0); }
    if ((e = getenv("SSBU_RB_NET_AHEAD")) && atoi(e) > 0) g_ahead = atoi(e);
    if ((e = getenv("SSBU_RB_NET_LOG")) && *e) g_hlog = fopen(e, "w");
    printf("[rbnet] on: %s, local player %d, delay %s, ahead at most %d, bot %s\n", g_loop ? "loop test (no network)" : "over net_relay", g_local + 1, g_delay_cfg >= 0 ? "fixed" : "from the round trip", g_ahead, g_bot ? "on" : "off");
    if (g_loop) printf("[rbnet] loop: remote pads arrive %d frames after the frame that would send them\n", g_loop_lat);
    fflush(stdout);
    return g_on;
}
int rbn_local_player(void) { return g_local; }
int rbn_ahead(void) { return g_ahead; }

/* ---------------------------------------------------------------- the test bot: a pure function of (seed, frame) */
static uint32_t mix32(uint32_t x) { x ^= x >> 16; x *= 0x7feb352du; x ^= x >> 15; x *= 0x846ca68bu; x ^= x >> 16; return x; }
static RbPad bot_pad(unsigned seed, long long f) {
    /* segments of 6..29 frames; each segment one action. Walking alternates sides around the middle of the stage. */
    RbPad p; memset(&p, 0, sizeof p);
    long long start = 1; uint32_t h = 0; int seg = 0;
    for (;; seg++) { h = mix32(seed * 0x9E3779B9u ^ (uint32_t)seg * 0x85EBCA6Bu); long long len = 6 + (h % 24); if (f < start + len) break; start += len; }
    int act = (int)((h >> 8) % 10);
    int dir = (seg & 1) ? 1 : -1;
    switch (act) {
    case 0: case 1: break;                                            /* nothing */
    case 2: case 3: p.lx = (int16_t)(dir * 32767); break;            /* walk / run */
    case 4: p.buttons = 1ull << 0; break;                            /* A (jab) */
    case 5: p.buttons = 1ull << 1; break;                            /* B (neutral special) */
    case 6: if (((f - start) & 15) < 3) p.buttons = 1ull << 2; break;        /* X (jump), tapped */
    case 7: p.lx = (int16_t)(dir * 32767); p.buttons = 1ull << 0; break;     /* forward A */
    case 8: p.ly = -32767; break;                                     /* crouch */
    case 9: p.buttons = (((f - start) & 7) < 4) ? 1ull << 0 : 0; break;       /* A mashed */
    }
    return p;
}
int rbn_bot_on(void) { return g_bot; }

/* ---------------------------------------------------------------- receive queue (net thread -> main) */
#define RQ_N 1024
#define RQ_MAX 1100
static struct { uint64_t at_us; long long at_frame; int n; uint8_t b[RQ_MAX]; } *g_rq;
static volatile LONG g_rq_head, g_rq_tail; static SRWLOCK g_rq_lock = SRWLOCK_INIT;
static volatile LONG64 g_rx_pkts, g_rx_bad, g_rx_drop, g_tx_pkts, g_tx_fail, g_rx_last_ms;
static volatile LONG g_rtt_us = -1, g_rtt_min_us = -1;
static long long g_rtt_n; static double g_rtt_sum;      /* (under g_rq_lock) */
#define TSQ 64
static int32_t g_tsq[TSQ]; static int g_tsq_n;          /* clock-offset samples waiting for the main thread (under g_rq_lock) */
static void send_msg(const RbMsg *m) {
    uint8_t b[RB_PADS_HEAD + RB_MAX_PADS_PER_MSG * RB_PAD_WIRE];
    size_t n = rb_msg_build(b, sizeof b, m);
    if (!n || g_loop) return;
    if (net_rb_send(b, (int)n)) InterlockedIncrement64(&g_tx_pkts); else InterlockedIncrement64(&g_tx_fail);
}
/* net_relay.c's receive thread: one rollback message from the other player */
void rbn_rx(const uint8_t *p, int n) {
    if (rbn_on() <= 0 || n <= 0 || n > RQ_MAX) { InterlockedIncrement64(&g_rx_bad); return; }
    InterlockedIncrement64(&g_rx_pkts); InterlockedExchange64(&g_rx_last_ms, (LONG64)GetTickCount64());
    if (p[0] == RB_MSG_PING) {                          /* answered at once on this thread (the round trip excludes the frame wait) */
        RbMsg m, r; if (!rb_msg_parse(p, (size_t)n, &m)) { InterlockedIncrement64(&g_rx_bad); return; }
        memset(&r, 0, sizeof r); r.type = RB_MSG_PONG; r.frame = (int32_t)g_cur; r.time_us = now_us(); r.echo_us = m.time_us;
        send_msg(&r); return;
    }
    if (p[0] == RB_MSG_PONG) {                          /* the round trip at once (also before the match: the delay is chosen from it) */
        RbMsg m; if (!rb_msg_parse(p, (size_t)n, &m)) { InterlockedIncrement64(&g_rx_bad); return; }
        long rtt = (long)(now_us() - m.echo_us);
        if (rtt <= 0 || rtt >= 5000000) return;
        InterlockedExchange(&g_rtt_us, rtt); if (g_rtt_min_us < 0 || rtt < g_rtt_min_us) InterlockedExchange(&g_rtt_min_us, rtt);
        AcquireSRWLockExclusive(&g_rq_lock);
        g_rtt_sum += rtt; g_rtt_n++;
        if (g_started && m.frame > 0 && g_cur > 0 && g_tsq_n < TSQ) g_tsq[g_tsq_n++] = (int32_t)((g_cur - m.frame) * 16683 - rtt / 2);   /* > 0: this game runs ahead */
        ReleaseSRWLockExclusive(&g_rq_lock);
        return;
    }
    AcquireSRWLockExclusive(&g_rq_lock);
    if (!g_rq) g_rq = calloc(RQ_N, sizeof *g_rq);
    LONG next = (g_rq_head + 1) % RQ_N;
    if (g_rq && next != g_rq_tail) { g_rq[g_rq_head].at_us = now_us(); g_rq[g_rq_head].at_frame = g_cur; g_rq[g_rq_head].n = n; memcpy(g_rq[g_rq_head].b, p, (size_t)n); g_rq_head = next; }
    else InterlockedIncrement64(&g_rx_drop);
    ReleaseSRWLockExclusive(&g_rq_lock);
}
/* a thread that pings the other player every 100 ms from the start (the delay is chosen from it when the match begins) */
static DWORD WINAPI ping_thread(void *u) {
    (void)u;
    for (;;) {
        Sleep(100);
        if (!net_rb_ready()) continue;
        RbMsg m; memset(&m, 0, sizeof m); m.type = RB_MSG_PING; m.frame = (int32_t)g_cur; m.time_us = now_us();
        send_msg(&m);
    }
    return 0;
}
void rbn_init(void) {                                   /* r1_state.c ra_init: before the match */
    static int done; if (done++ || rbn_on() <= 0) return;
    if (!g_loop) CloseHandle(CreateThread(NULL, 0, ping_thread, NULL, 0, NULL));
}

/* ---------------------------------------------------------------- the session */
static long long g_f0;                                  /* the base frame (the ring's first capture) */
static int g_delay, g_remote = 1;
static long long g_peer_ack, g_sent_newest;
static long long g_stat_pred, g_stat_padget, g_stat_mis;
static long long g_ts_n; static double g_ts_extra;     /* time sync: extra ms per frame for the next frames */
static int g_ts_left;
static uint64_t g_hacc = 0xcbf29ce484222325ull; static int g_hlines;
#define HR 512
static uint64_t g_hash[HR]; static long long g_hframe[HR], g_hfinal_upto; static long long g_desync, g_check_ok, g_desync_first = -1;
static long long g_peer_check_f; static uint32_t g_peer_check;

static int auto_delay(void) {
    if (g_delay_cfg >= 0) return g_delay_cfg;
    if (g_loop) return 2;
    int rtt = g_rtt_min_us > 0 ? g_rtt_min_us : g_rtt_us;
    if (rtt <= 0) return 2;
    double one_way = rtt / 2000.0 / (1000.0 / 60.0);     /* frames */
    int d = (int)(one_way - 2.0 + 0.5);                   /* up to 2 frames of lateness covered by rollback */
    return d < 1 ? 1 : d > 4 ? 4 : d;
}
void rbn_start(long long f0) {
    g_f0 = f0; g_started = 1;
    g_remote = 1 - g_local;
    g_delay = auto_delay();
    if (g_delay < 1) g_delay = 1;                        /* (frames 1..delay are empty on both sides: no rollback can reach the base state, made before the start barrier) */
    rb_input_reset(2, g_local, g_delay);
    rb_ts_reset(16683);
    printf("[rbnet] match start at frame %lld: local player %d, input delay %d frames (round trip %.1f ms, best %.1f ms)\n", f0, g_local + 1, g_delay,
           g_rtt_us > 0 ? g_rtt_us / 1000.0 : -1.0, g_rtt_min_us > 0 ? g_rtt_min_us / 1000.0 : -1.0);
    fflush(stdout);
}
/* after the start barrier: the delay again from the round trip measured meanwhile (no frame has run: the queues start over;
 * pads of the other game already queued are sent again by it, from our acknowledgement on) */
void rbn_choose_delay(void) {
    int d = auto_delay(); if (d < 1) d = 1;
    if (d == g_delay) return;
    printf("[rbnet] after the start barrier: input delay %d -> %d frames (round trip %.1f ms, best %.1f ms)\n", g_delay, d, g_rtt_us > 0 ? g_rtt_us / 1000.0 : -1.0, g_rtt_min_us > 0 ? g_rtt_min_us / 1000.0 : -1.0);
    fflush(stdout);
    g_delay = d; rb_input_reset(2, g_local, g_delay);
}
int rbn_started(void) { return g_started; }
int rbn_delay(void) { return g_started ? g_delay : 0; }
static void send_pads(void) {
    long long newest = rb_input_local_latest();
    if (newest < 1 || g_loop) return;
    RbMsg m; memset(&m, 0, sizeof m);
    m.type = RB_MSG_PADS; m.player = g_local; m.newest = (int32_t)newest; m.ack = rb_input_remote_latest(g_remote);
    long long from = g_peer_ack + 1; if (newest - from + 1 > RB_MAX_PADS_PER_MSG) from = newest - RB_MAX_PADS_PER_MSG + 1; if (from < 1) from = 1;
    for (long long f = newest; f >= from; f--) { RbPad p; if (!rb_input_local_get((int)f, &p)) break; m.pads[m.count++] = p; }
    long long cf = g_hfinal_upto;
    if (cf > 0 && g_hframe[cf % HR] == cf) { m.check_frame = (int32_t)cf; m.check = (uint32_t)(g_hash[cf % HR] ^ (g_hash[cf % HR] >> 32)); }
    send_msg(&m); g_sent_newest = newest;
}
/* the local player's pad of a real pass (frame f): kept for f + delay and sent */
void rbn_local_pad(long long f, RbPad now) {
    if (g_bot) now = bot_pad(g_bot_seed, f);
    rb_input_local((int)f, now);
    send_pads();
}
RbPad rbn_pad(int player, long long f) {
    int pred = 0; RbPad p = rb_input_get(player, (int)f, &pred);
    g_stat_padget++; g_stat_pred += pred;
    return p;
}
static void on_check(long long cf, uint32_t ck) {
    if (cf <= 0 || cf > g_hfinal_upto || g_hframe[cf % HR] != cf) { g_peer_check_f = cf; g_peer_check = ck; return; }      /* not final here yet: kept for later */
    uint32_t mine = (uint32_t)(g_hash[cf % HR] ^ (g_hash[cf % HR] >> 32));
    if (mine == ck) g_check_ok++;
    else { g_desync++; if (g_desync_first < 0) { g_desync_first = cf; printf("[rbnet] DESYNC: frame %lld checksum here %08x, the other game %08x\n", cf, mine, ck); fflush(stdout); } }
}
/* main thread, at the safe point: the messages received since the last call */
void rbn_drain(long long cur) {
    InterlockedExchange64(&g_cur, cur);
    if (g_loop && g_started) {                          /* loop test: the bot's pad of frame f arrives at frame f + delay - lat */
        long long upto = cur + g_delay - g_loop_lat;
        for (long long f = rb_input_remote_latest(g_remote) + 1; f <= upto; f++) rb_input_remote_put(g_remote, (int)f, bot_pad(g_bot_seed ^ 0x5bd1e995u, f));
        return;
    }
    {   int32_t ts[TSQ]; int nts;
        AcquireSRWLockExclusive(&g_rq_lock); nts = g_tsq_n; memcpy(ts, g_tsq, sizeof(int32_t) * (size_t)nts); g_tsq_n = 0; ReleaseSRWLockExclusive(&g_rq_lock);
        for (int k = 0; k < nts; k++) rb_ts_sample(ts[k]);
    }
    for (;;) {
        static uint8_t b[RQ_MAX]; int n = 0; uint64_t at = 0; long long atf = 0;
        AcquireSRWLockExclusive(&g_rq_lock);
        if (g_rq && g_rq_tail != g_rq_head) { n = g_rq[g_rq_tail].n; at = g_rq[g_rq_tail].at_us; atf = g_rq[g_rq_tail].at_frame; memcpy(b, g_rq[g_rq_tail].b, (size_t)n); g_rq_tail = (g_rq_tail + 1) % RQ_N; }
        ReleaseSRWLockExclusive(&g_rq_lock);
        if (!n) break;
        RbMsg m;
        if (!rb_msg_parse(b, (size_t)n, &m)) { g_rx_bad++; continue; }
        if (m.type != RB_MSG_PADS || !g_started || m.player != g_remote) continue;
        g_peer_started = 1;
        for (int k = 0; k < m.count; k++) rb_input_remote_put(g_remote, m.newest - k, m.pads[k]);
        if (m.ack > g_peer_ack) g_peer_ack = m.ack;
        if (m.check_frame > 0) on_check(m.check_frame, m.check);
    }
}
int rbn_take_mismatch(void) { int m = rb_input_take_mismatch(); if (m) g_stat_mis++; return m; }
long long rbn_confirmed(void) { return rb_input_remote_latest(g_remote); }
int rbn_peer_gone(void) {
    if (g_loop || !g_started) return 0;
    LONG64 last = g_rx_last_ms;
    return last && GetTickCount64() - (ULONGLONG)last > 5000;
}

/* ---------------------------------------------------------------- checksums: fighter_host.c gives each fighter's frame line */
void rbn_hash_add(const void *p, size_t n) {
    if (g_on <= 0) return;
    const uint8_t *b = p; while (n--) { g_hacc ^= *b++; g_hacc *= 0x100000001b3ull; }
    g_hlines++;
}
/* the safe point after pass f: the lines since the last call belong to frame f (a re-run pass overwrites the value) */
void rbn_pass_hash(long long f) {
    if (g_hlines && f > 0) { g_hash[f % HR] = g_hacc; g_hframe[f % HR] = f; }
    g_hacc = 0xcbf29ce484222325ull; g_hlines = 0;
}
/* no rollback pending: every frame up to min(cur, newest remote pad) is final */
void rbn_finalize(long long cur) {
    long long upto = rb_input_remote_latest(g_remote);
    if (upto > cur) upto = cur;
    for (long long f = g_hfinal_upto + 1; f <= upto; f++) {
        if (g_hlog && g_hframe[f % HR] == f) fprintf(g_hlog, "f %lld h %016llx\n", f, (unsigned long long)g_hash[f % HR]);
        g_hfinal_upto = f;
    }
    if (g_hlog && (upto & 63) == 0) fflush(g_hlog);
    if (g_peer_check_f > 0 && g_peer_check_f <= g_hfinal_upto) { long long cf = g_peer_check_f; g_peer_check_f = 0; on_check(cf, g_peer_check); }
}

/* ---------------------------------------------------------------- time sync: extra wait per frame (ms) */
double rbn_pace_extra(long long f) {
    if (!g_started || g_loop) return 0;
    if (f % 30 == 0) {
        rb_ts_decide((int)f);
        double est_ms = rb_ts_offset() / 1000.0;
        /* ahead: half of the lead given back over the next 30 frames (the other game, behind, does nothing; both halves meet) */
        if (est_ms > 2.0) { g_ts_extra = est_ms / 2.0 / 30.0; if (g_ts_extra > 4.0) g_ts_extra = 4.0; g_ts_left = 30; g_ts_n++; }
        else g_ts_left = 0;
    }
    if (g_ts_left > 0) { g_ts_left--; return g_ts_extra; }
    return 0;
}
int rbn_rtt_ms(void) { return g_rtt_us > 0 ? (int)(g_rtt_us / 1000) : -1; }
void rbn_resend(void) { if (g_started) send_pads(); }
/* the match-start barrier: an empty PADS message says "in the match" (count 0, newest 0) */
void rbn_hello(void) {
    if (!g_started || g_loop) return;
    if (rb_input_local_latest() >= 1) { send_pads(); return; }
    RbMsg m; memset(&m, 0, sizeof m); m.type = RB_MSG_PADS; m.player = g_local; m.newest = 0; m.count = 0; send_msg(&m);
}
int rbn_peer_started(void) { return g_loop || g_peer_started; }
void rbn_status(char *out, size_t n) {
    LONG q = (g_rq_head - g_rq_tail + RQ_N) % RQ_N;
    snprintf(out, n, "remote pads up to %d, local up to %d, the other game has ours up to %lld; packets sent %lld received %lld (bad %lld, queue %ld, full %lld)",
             rb_input_remote_latest(g_remote), rb_input_local_latest(), g_peer_ack, (long long)g_tx_pkts, (long long)g_rx_pkts, (long long)g_rx_bad, (long)q, (long long)g_rx_drop);
}
double rbn_offset_ms(void) { return rb_ts_offset() / 1000.0; }

void rbn_report(FILE *o, long long frames) {
    if (g_on <= 0) return;
    if (g_hlog) fflush(g_hlog);
    fprintf(o, "[rbnet] report: %lld frames; delay %d; round trip mean %.1f ms (best %.1f, %lld samples); clock offset estimate %.1f ms, time-sync corrections %lld\n",
            frames, g_delay, g_rtt_n ? g_rtt_sum / g_rtt_n / 1000.0 : -1.0, g_rtt_min_us > 0 ? g_rtt_min_us / 1000.0 : -1.0, g_rtt_n, rb_ts_offset() / 1000.0, g_ts_n);
    fprintf(o, "[rbnet] report: pads given %lld, predicted %lld (%.1f%%), mispredictions %lld; finalized frames %lld; checksums compared %lld, DESYNCS %lld (first %lld)\n",
            g_stat_padget, g_stat_pred, g_stat_padget ? 100.0 * g_stat_pred / g_stat_padget : 0.0, g_stat_mis, g_hfinal_upto, g_check_ok + g_desync, g_desync, g_desync_first);
    fprintf(o, "[rbnet] report: packets sent %lld (failed %lld), received %lld (bad %lld, queue full %lld); remote pads up to %d, local up to %d\n",
            (long long)g_tx_pkts, (long long)g_tx_fail, (long long)g_rx_pkts, (long long)g_rx_bad, (long long)g_rx_drop, rb_input_remote_latest(g_remote), rb_input_local_latest());
    fflush(o);
}
