/* Unit test of the rollback netcode's game-free parts (rb.h): a scripted peer sends its pads over a lossy, late,
 * reordering link with a fixed seed (each message repeats every pad not yet confirmed); this side predicts them, finds
 * its mispredictions and "rolls back" (recomputes a toy simulation from the mismatch frame). The toy state must end
 * equal to a run with every pad known at once. Also: the wire round trip, malformed messages, the stick clamp, time sync numbers.
 *   clang -O1 -I<runtime> tests/rb_test.c <runtime>/rb_input.c <runtime>/rb_wire.c <runtime>/rb_timesync.c -o rb_test.exe
 *   (<runtime> = the folder with rb.h: runtime in the public tree; exit 0 = all passed)
 * SPDX-License-Identifier: GPL-3.0-or-later */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rb.h"

static int fails;
#define CHECK(c, ...) do { if (!(c)) { fails++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static uint32_t rng = 12345;
static uint32_t rnd(void) { rng = rng * 1103515245u + 12345u; return rng >> 8; }

/* the "game": a state that depends on every pad of every frame, in order */
static uint64_t step(uint64_t s, const RbPad *a, const RbPad *b) {
    s = s * 6364136223846793005ull + a->buttons * 31 + (uint64_t)(a->lx + 40000) * 7 + b->buttons * 131 + (uint64_t)(b->ly + 40000) * 3;
    return s ^ (s >> 29);
}
static RbPad human(int player, int frame) {      /* a pad that changes now and then, like a real player */
    RbPad p = {0, 0, 0, 0, 0};
    int phase = (frame / (7 + player * 5)) % 4;
    p.buttons = phase == 1 ? 1 : phase == 3 ? 2 | 8 : 0;
    p.lx = (int16_t)(phase == 2 ? 30000 : phase == 3 ? -20000 : 900);      /* 900: noise at rest, clamped to 0 */
    return p;
}

/* a link: packets with a delivery time, some dropped */
typedef struct { uint8_t b[2048]; size_t n; int at; } Pkt;
#define LQ 4096
typedef struct { Pkt q[LQ]; int n; } Link;
static void link_send(Link *l, const uint8_t *b, size_t n, int now) {
    if (rnd() % 100 < 15) return;                 /* 15 % lost */
    if (l->n >= LQ) return;
    Pkt *p = &l->q[l->n++];
    memcpy(p->b, b, n); p->n = n; p->at = now + 2 + (int)(rnd() % 6);      /* 2..7 frames late, so also reordered */
}
static int link_recv(Link *l, int now, uint8_t *b, size_t *n) {
    for (int i = 0; i < l->n; i++) if (l->q[i].at <= now) { memcpy(b, l->q[i].b, l->q[i].n); *n = l->q[i].n; l->q[i] = l->q[--l->n]; return 1; }
    return 0;
}

static void wire_tests(void) {
    RbMsg m, r;
    uint8_t buf[2048];
    memset(&m, 0, sizeof m);
    m.type = RB_MSG_PADS; m.player = 1; m.count = 3; m.newest = 100; m.ack = 97; m.check_frame = 90; m.check = 0xdeadbeef;
    for (int i = 0; i < 3; i++) { m.pads[i].buttons = 0x123456789abcull + (uint64_t)i; m.pads[i].lx = (int16_t)(-32767 + i); m.pads[i].ry = (int16_t)(32767 - i); }
    size_t n = rb_msg_build(buf, sizeof buf, &m);
    CHECK(n == RB_PADS_HEAD + 3 * RB_PAD_WIRE, "pads size %zu", n);
    CHECK(rb_msg_parse(buf, n, &r) == 1, "pads parse");
    CHECK(r.player == 1 && r.count == 3 && r.newest == 100 && r.ack == 97 && r.check_frame == 90 && r.check == 0xdeadbeef, "pads header");
    for (int i = 0; i < 3; i++) CHECK(rb_pad_equal(&m.pads[i], &r.pads[i]), "pad %d round trip", i);
    CHECK(rb_msg_parse(buf, n - 1, &r) == 0, "short pads refused");
    CHECK(rb_msg_parse(buf, n + 1, &r) == 0, "long pads refused");
    buf[1] = 200; CHECK(rb_msg_parse(buf, n, &r) == 0, "bad player refused");
    memset(&m, 0, sizeof m); m.type = RB_MSG_PONG; m.frame = 7; m.time_us = 111; m.echo_us = 222;
    n = rb_msg_build(buf, sizeof buf, &m);
    CHECK(rb_msg_parse(buf, n, &r) == 1 && r.frame == 7 && r.time_us == 111 && r.echo_us == 222, "pong round trip");
    CHECK(rb_msg_parse((const uint8_t *)"\x09", 1, &r) == 0, "unknown type refused");
    RbPad p = {5, 1600, -1600, 1601, -1601};
    p = rb_pad_rest(p);
    CHECK(p.lx == 0 && p.ly == 0 && p.rx == 1601 && p.ry == -1601, "stick clamp");
}

static void ts_tests(void) {
    rb_ts_reset(16683);
    for (int i = 0; i < 30; i++) rb_ts_sample(i < 5 ? 900000 : 12000);      /* 5 outliers must not count */
    RbSyncAction a = rb_ts_decide(60);
    CHECK(rb_ts_offset() == 12000 && a.speed < 1.0 && !a.skip, "ahead: offset %d speed %.3f", rb_ts_offset(), a.speed);
    rb_ts_reset(16683);
    for (int i = 0; i < 30; i++) rb_ts_sample(-40000);
    a = rb_ts_decide(300);
    CHECK(a.speed > 1.0 && a.advance == 2, "behind: speed %.3f advance %d", a.speed, a.advance);
    a = rb_ts_decide(301);
    CHECK(a.speed == 1.0 && !a.advance, "decides only every 30 frames");
}

#define SIDE_FRAMES 3000
typedef struct {
    int me;
    uint64_t state[SIDE_FRAMES + 2];               /* toy state after each frame (index = frame) */
    int frame;                                     /* last frame simulated */
    int rollbacks, rolled_frames, max_back;
} Side;

static void sim_from(Side *s, int from, int to) {  /* recompute frames from..to with the pads known or guessed now */
    for (int f = from; f <= to; f++) {
        int pr;
        RbPad a = rb_input_get(0, f, &pr), b = rb_input_get(1, f, &pr);
        s->state[f] = step(s->state[f - 1], &a, &b);
    }
}

int main(void) {
    wire_tests();
    ts_tests();
    /* a single process can hold one rb_input instance: run side 0 against a scripted remote that delivers player 1's
     * true pads late and lossy (with redundancy), then check the state equals the perfect-input state. */
    rb_input_reset(2, 0, 2);
    static Side s;
    memset(&s, 0, sizeof s);
    static Link to_me;
    memset(&to_me, 0, sizeof to_me);
    int peer_ack_of_theirs = 0;                    /* newest of THEIR pads we have confirmed (they resend everything after it) */
    for (int f = 1; f <= SIDE_FRAMES; f++) {
        /* the remote: sends its pads from (our ack + 1) to (f + delay), newest first, at most 64 */
        {
            RbMsg m; memset(&m, 0, sizeof m);
            m.type = RB_MSG_PADS; m.player = 1;
            int newest = f + 2, oldest = peer_ack_of_theirs + 1;
            if (newest - oldest + 1 > RB_MAX_PADS_PER_MSG) oldest = newest - RB_MAX_PADS_PER_MSG + 1;
            m.newest = newest; m.count = newest - oldest + 1;
            for (int i = 0; i < m.count; i++) m.pads[i] = rb_pad_rest(human(1, newest - i <= 2 ? 0 : newest - i - 2));
            uint8_t b[2048]; size_t n = rb_msg_build(b, sizeof b, &m);
            link_send(&to_me, b, n, f);
        }
        /* we receive what has arrived */
        uint8_t b[2048]; size_t n;
        while (link_recv(&to_me, f, b, &n)) {
            RbMsg m;
            if (!rb_msg_parse(b, n, &m) || m.type != RB_MSG_PADS) continue;
            for (int i = 0; i < m.count; i++) rb_input_remote_put(m.player, m.newest - i, m.pads[i]);
        }
        peer_ack_of_theirs = rb_input_remote_latest(1);
        /* our own pad for this frame */
        rb_input_local(f, human(0, f));
        /* a misprediction since the last frame: roll back to it and simulate again up to the frame before */
        int mis = rb_input_take_mismatch();
        if (mis && mis < f) {
            CHECK(f - mis <= 64, "rollback too deep: %d", f - mis);
            if (f - mis > s.max_back) s.max_back = f - mis;
            s.rollbacks++; s.rolled_frames += f - mis;
            sim_from(&s, mis, f - 1);
        }
        sim_from(&s, f, f);
    }
    /* let the late packets arrive, then roll back over the end */
    for (int f = SIDE_FRAMES + 1; f <= SIDE_FRAMES + 20; f++) {
        uint8_t b[2048]; size_t n;
        while (link_recv(&to_me, f, b, &n)) {
            RbMsg m;
            if (!rb_msg_parse(b, n, &m) || m.type != RB_MSG_PADS) continue;
            for (int i = 0; i < m.count; i++) rb_input_remote_put(m.player, m.newest - i, m.pads[i]);
        }
    }
    int mis = rb_input_take_mismatch();
    if (mis) sim_from(&s, mis, SIDE_FRAMES);
    /* the reference: every pad known at once (the remote's pad of frame f is human(1, f - 2), ours human(0, f - 2)) */
    uint64_t ref = 0;
    for (int f = 1; f <= SIDE_FRAMES; f++) {
        RbPad a = f <= 2 ? (RbPad){0} : rb_pad_rest(human(0, f - 2)), bb = f <= 2 ? (RbPad){0} : rb_pad_rest(human(1, f - 2));
        ref = step(ref, &a, &bb);
    }
    CHECK(rb_input_remote_latest(1) >= SIDE_FRAMES, "remote pads all received: %d", rb_input_remote_latest(1));
    CHECK(s.state[SIDE_FRAMES] == ref, "final state %016llx != perfect-input state %016llx", (unsigned long long)s.state[SIDE_FRAMES], (unsigned long long)ref);
    printf("rb_test: %d rollbacks, %d frames simulated again, deepest %d frames; %s\n", s.rollbacks, s.rolled_frames, s.max_back, fails ? "FAILED" : "all passed");
    return fails ? 1 : 0;
}
