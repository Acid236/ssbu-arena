// SPDX-License-Identifier: GPL-3.0-or-later
/* ldn_relay.c - the room server of ldn_room_server.py, in C for Linux (epoll, one thread). Same protocol, same rules,
 * same refusals and log lines; the Python file stays the description of the protocol and the reference.
 *
 *     cc -O2 -o ldn_relay ldn_relay.c
 *     ./ldn_relay [--port 39010] [--bind 0.0.0.0] [--per-ip 32]
 *
 * The game's datagrams are the whole load (one per frame and player): they are read and sent in batches (recvmmsg /
 * sendmmsg) and relayed in place, since the server header has the length of the client header. Every member's
 * datagram costs a token lookup (hash table) and a room slot lookup (the low byte of the virtual address), nothing else.
 * Only the relay sees the players' addresses: each member is sent the virtual 169.254.1.N of the others, never their IP.
 *
 * On top of the Python server: at most MAX_CONNS connections and MAX_PER_IP from one address, a connection that has not
 * joined in 10 s is closed, a member that does not read its TCP messages (over 1 MB queued) is closed, TCP keep-alive
 * closes a member whose computer vanished, and a token is never given twice. */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/random.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/uio.h>
#include <time.h>
#include <unistd.h>

#define VERSION      2
#define NET          0xA9FE0100u            /* 169.254.1.0/24 */
#define MASK         0xFFFFFF00u
#define BROADCAST    (NET | 0xFF)
#define MAX_MEMBERS  8
#define MAX_FRAME    (64 * 1024)
#define MAX_LDN      0x500                  /* the largest LDN message is a NetworkInfo (0x480) */
#define MAX_DATAGRAM (0xFFFF - 13)
#define MAX_CONNS    4000
#define MAX_PER_IP   32                     /* --per-ip N changes it (a load test from one address) */
#define HELLO_SECS   10.0
#define OUT_LIMIT    (1 << 20)
#define BATCH        64                     /* datagrams per recvmmsg */
#define OUTQ         (BATCH * MAX_MEMBERS)  /* datagrams per sendmmsg: a batch that is all broadcasts */
#define TOK_BITS     13
#define TOK_N        (1u << TOK_BITS)       /* > 2 * MAX_CONNS */
#define ROOM_N       4096

/* ---------------------------------------------------------------- SHA-256 (the room key, as the Python server's) */
static const uint32_t K256[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01,
    0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
    0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08,
    0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};
#define ROR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))
static void sha256_block(uint32_t h[8], const uint8_t *p) {
    uint32_t w[64], a, b, c, d, e, f, g, k;
    for (int i = 0; i < 16; i++) w[i] = (uint32_t)p[4 * i] << 24 | (uint32_t)p[4 * i + 1] << 16 | (uint32_t)p[4 * i + 2] << 8 | p[4 * i + 3];
    for (int i = 16; i < 64; i++) {
        uint32_t s0 = ROR(w[i - 15], 7) ^ ROR(w[i - 15], 18) ^ (w[i - 15] >> 3), s1 = ROR(w[i - 2], 17) ^ ROR(w[i - 2], 19) ^ (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    a = h[0]; b = h[1]; c = h[2]; d = h[3]; e = h[4]; f = h[5]; g = h[6]; k = h[7];
    for (int i = 0; i < 64; i++) {
        uint32_t t1 = k + (ROR(e, 6) ^ ROR(e, 11) ^ ROR(e, 25)) + ((e & f) ^ (~e & g)) + K256[i] + w[i];
        uint32_t t2 = (ROR(a, 2) ^ ROR(a, 13) ^ ROR(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
        k = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += k;
}
static void sha256(const uint8_t *m, size_t n, uint8_t out[32]) {
    uint32_t h[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    uint8_t blk[64];
    size_t i = 0;
    for (; i + 64 <= n; i += 64) sha256_block(h, m + i);
    size_t r = n - i;
    memset(blk, 0, 64); memcpy(blk, m + i, r); blk[r] = 0x80;
    if (r >= 56) { sha256_block(h, blk); memset(blk, 0, 64); }
    uint64_t bits = (uint64_t)n * 8;
    for (int j = 0; j < 8; j++) blk[63 - j] = (uint8_t)(bits >> (8 * j));
    sha256_block(h, blk);
    for (int j = 0; j < 8; j++) { out[4 * j] = h[j] >> 24; out[4 * j + 1] = h[j] >> 16; out[4 * j + 2] = h[j] >> 8; out[4 * j + 3] = h[j]; }
}

/* ---------------------------------------------------------------- state */
typedef struct Room Room;
typedef struct Conn {
    int fd, idx, dead, joined, refused, want_out;
    uint32_t peer_ip;                       /* network order; datagrams count only from the address of the TCP connection */
    char peer[48];
    double t_open;
    uint8_t *in; size_t in_n, in_cap;
    uint8_t *out; size_t out_off, out_n, out_cap;
    Room *room; uint32_t vip, token; char name[33];
    struct sockaddr_in udp; int has_udp; double last_udp;
} Conn;
struct Room { uint8_t key[32]; char hex[9]; uint8_t fp[8]; Conn *slot[256]; int n; Room *next; };

static int g_ep, g_udp, g_tcp;
static Conn *g_conns[MAX_CONNS]; static int g_nconns;
static Conn *g_dead[MAX_CONNS + 1]; static int g_ndead;
static Conn *g_tok[TOK_N];
static Room *g_rooms[ROOM_N]; static int g_nrooms, g_nmembers;
static unsigned long long st_udp_in, st_udp_out, st_ldn, st_dropped, st_bytes_in, st_bytes_out;
static int TAG_TCP, TAG_UDP;
static int g_per_ip = MAX_PER_IP;                /* their addresses tag the two listening sockets in epoll */

static double now_s(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec * 1e-9; }
static uint32_t rd32(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static uint16_t rd16(const uint8_t *p) { return (uint16_t)(p[0] | p[1] << 8); }
static void wr32(uint8_t *p, uint32_t v) { p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24; }
static void wr16(uint8_t *p, uint16_t v) { p[0] = v; p[1] = v >> 8; }
static const char *ip_str(uint32_t v, char *b) { sprintf(b, "%u.%u.%u.%u", v >> 24, (v >> 16) & 255, (v >> 8) & 255, v & 255); return b; }

static void say(const char *fmt, ...) {
    struct timespec ts; clock_gettime(CLOCK_REALTIME, &ts);
    struct tm tm; localtime_r(&ts.tv_sec, &tm);
    char b[32]; strftime(b, sizeof b, "%Y-%m-%d %H:%M:%S", &tm);
    printf("%s,%03ld ", b, ts.tv_nsec / 1000000);
    va_list ap; va_start(ap, fmt); vprintf(fmt, ap); va_end(ap);
    putchar('\n'); fflush(stdout);
}

/* tokens: open addressing, deletion by backward shift */
static uint32_t tok_h(uint32_t t) { return (t * 2654435761u) >> (32 - TOK_BITS); }
static Conn *tok_get(uint32_t t) {
    for (uint32_t i = tok_h(t);; i = (i + 1) & (TOK_N - 1)) { Conn *c = g_tok[i]; if (!c) return NULL; if (c->token == t) return c; }
}
static void tok_put(Conn *c) { uint32_t i = tok_h(c->token); while (g_tok[i]) i = (i + 1) & (TOK_N - 1); g_tok[i] = c; }
static void tok_del(uint32_t t) {
    uint32_t i = tok_h(t);
    while (g_tok[i] && g_tok[i]->token != t) i = (i + 1) & (TOK_N - 1);
    if (!g_tok[i]) return;
    g_tok[i] = NULL;
    for (uint32_t j = i;;) {
        j = (j + 1) & (TOK_N - 1);
        Conn *c = g_tok[j];
        if (!c) break;
        uint32_t k = tok_h(c->token);
        if (i <= j ? (i < k && k <= j) : (i < k || k <= j)) continue;     /* its home is between the hole and it: stays */
        g_tok[i] = c; g_tok[j] = NULL; i = j;
    }
}

static Room **room_link(const uint8_t key[32]) {
    Room **r = &g_rooms[(key[0] | key[1] << 8) & (ROOM_N - 1)];
    while (*r && memcmp((*r)->key, key, 32)) r = &(*r)->next;
    return r;
}

/* ---------------------------------------------------------------- TCP connections */
static void kill_conn(Conn *c) { if (!c->dead) { c->dead = 1; g_dead[g_ndead++] = c; } }

static void set_out(Conn *c, int on) {
    if (c->want_out == on) return;
    c->want_out = on;
    struct epoll_event ev = {.events = EPOLLIN | (on ? EPOLLOUT : 0), .data.ptr = c};
    epoll_ctl(g_ep, EPOLL_CTL_MOD, c->fd, &ev);
}

static void conn_send(Conn *c, uint8_t type, const uint8_t *p, size_t n) {
    if (c->dead) return;
    uint8_t h[5]; wr32(h, (uint32_t)n + 1); h[4] = type;
    size_t done = 0, total = n + 5;
    if (!c->out_n) {
        struct iovec iov[2] = {{h, 5}, {(void *)p, n}};
        struct msghdr m = {.msg_iov = iov, .msg_iovlen = n ? 2 : 1};
        ssize_t r = sendmsg(c->fd, &m, MSG_NOSIGNAL);
        if (r < 0) { if (errno != EAGAIN && errno != EWOULDBLOCK) { kill_conn(c); return; } r = 0; }
        done = (size_t)r;
        if (done == total) return;
    }
    if (c->out_n + total - done > OUT_LIMIT) { kill_conn(c); return; }      /* a member that does not read */
    if (c->out_off && c->out_off == c->out_n) c->out_off = c->out_n = 0;
    if (c->out_n + total > c->out_cap) {
        if (c->out_off) { memmove(c->out, c->out + c->out_off, c->out_n - c->out_off); c->out_n -= c->out_off; c->out_off = 0; }
        size_t cap = c->out_cap ? c->out_cap : 4096;
        while (cap < c->out_n + total) cap *= 2;
        uint8_t *nb = realloc(c->out, cap);
        if (!nb) { kill_conn(c); return; }
        c->out = nb; c->out_cap = cap;
    }
    for (size_t i = done; i < total; i++) c->out[c->out_n++] = i < 5 ? h[i] : p[i - 5];
    set_out(c, 1);
}

static void conn_flush(Conn *c) {
    while (c->out_off < c->out_n) {
        ssize_t r = send(c->fd, c->out + c->out_off, c->out_n - c->out_off, MSG_NOSIGNAL);
        if (r < 0) { if (errno == EAGAIN || errno == EWOULDBLOCK) return; kill_conn(c); return; }
        c->out_off += (size_t)r;
    }
    c->out_off = c->out_n = 0;
    set_out(c, 0);
    if (c->refused) kill_conn(c);
}

static void refuse(Conn *c, const char *reason) {
    uint8_t b[201]; size_t n = strlen(reason); if (n > 200) n = 200;
    b[0] = (uint8_t)n; memcpy(b + 1, reason, n);
    conn_send(c, 4, b, n + 1);
    say("refused %s: %s", c->peer, reason);
    c->refused = 1;
    if (!c->out_n) kill_conn(c);            /* sent: close now; queued: close once it is out (conn_flush) */
}

static int utf8_ok(const uint8_t *s, size_t n) {           /* strict, as Python's decoder: no overlongs, surrogates, > U+10FFFF */
    for (size_t i = 0; i < n;) {
        uint8_t c = s[i];
        if (c < 0x80) { i++; continue; }
        int k; uint32_t cp;
        if (c >= 0xC2 && c <= 0xDF) { k = 1; cp = c & 0x1F; }
        else if (c >= 0xE0 && c <= 0xEF) { k = 2; cp = c & 0x0F; }
        else if (c >= 0xF0 && c <= 0xF4) { k = 3; cp = c & 0x07; }
        else return 0;
        if (n - i <= (size_t)k) return 0;
        for (int j = 1; j <= k; j++) { uint8_t b = s[i + j]; if ((b & 0xC0) != 0x80) return 0; cp = cp << 6 | (b & 0x3F); }
        if (k == 2 && (cp < 0x800 || (cp >= 0xD800 && cp <= 0xDFFF))) return 0;
        if (k == 3 && (cp < 0x10000 || cp > 0x10FFFF)) return 0;
        i += k + 1;
    }
    return 1;
}

static void join(Conn *c, const uint8_t *p, size_t n) {
    char why[128];
    if (n < 1) { refuse(c, "empty hello"); return; }
    if (p[0] != VERSION) { snprintf(why, sizeof why, "server protocol %d, client protocol %d: update the game or the server", VERSION, p[0]); refuse(c, why); return; }
    size_t q = 1;
    if (q >= n) { refuse(c, "malformed hello"); return; }
    size_t rn = p[q++];
    if (rn < 1 || rn > 127 || q + rn > n) { refuse(c, "malformed hello (room password)"); return; }
    const uint8_t *room_pw = p + q; q += rn;
    if (q >= n) { refuse(c, "malformed hello"); return; }
    size_t mn = p[q++];
    if (mn < 1 || mn > 32 || q + mn + 8 != n) { refuse(c, "malformed hello (nickname 1 to 32 bytes, fingerprint 8 bytes)"); return; }
    const uint8_t *nick = p + q; q += mn;
    const uint8_t *fp = p + q;
    if (!utf8_ok(room_pw, rn) || !utf8_ok(nick, mn)) { refuse(c, "room password and nickname must be UTF-8"); return; }
    for (size_t i = 0; i < mn; i++) if (nick[i] < 32 || nick[i] == 127) { refuse(c, "nickname with control characters"); return; }

    uint8_t key[32]; sha256(room_pw, rn, key);
    Room **link = room_link(key), *room = *link;
    if (room && room->n && memcmp(room->fp, fp, 8)) {
        refuse(c, "your game build differs from the room's (game version, game DLL, mods, fighter source or new fighters): both sides must run the same game");
        return;
    }
    if (room && room->n >= MAX_MEMBERS) { refuse(c, "room full"); return; }
    if (!room) {
        room = calloc(1, sizeof *room);
        if (!room) { refuse(c, "room full"); return; }
        memcpy(room->key, key, 32);
        for (int i = 0; i < 4; i++) sprintf(room->hex + 2 * i, "%02x", key[i]);
        *link = room; g_nrooms++;
    }
    if (!room->n) memcpy(room->fp, fp, 8);
    int s = 1;
    while (room->slot[s]) s++;              /* n < 8: a free slot below 9 */
    uint32_t token;
    do { if (getrandom(&token, sizeof token, 0) != sizeof token) token = (uint32_t)rand() ^ (uint32_t)(now_s() * 1e6); } while (!token || tok_get(token));
    c->room = room; c->vip = NET | (uint32_t)s; c->token = token; c->joined = 1;
    memcpy(c->name, nick, mn); c->name[mn] = 0;
    room->slot[s] = c; room->n++; g_nmembers++;
    tok_put(c);
    uint8_t w[16]; wr32(w, c->vip); wr32(w + 4, token); wr32(w + 8, MASK); wr32(w + 12, (uint32_t)room->n);
    conn_send(c, 2, w, 16);
    char ib[16]; say("join  %s as %s (%s) room %s.. now %d member(s)", c->peer, ip_str(c->vip, ib), c->name, room->hex, room->n);
}

static void leave(Conn *c) {
    Room *room = c->room;
    room->slot[c->vip & 255] = NULL; room->n--; g_nmembers--;
    tok_del(c->token);
    char ib[16]; say("leave %s (%s) room %s.. now %d member(s)", ip_str(c->vip, ib), c->name, room->hex, room->n);
    if (!room->n) { *room_link(room->key) = room->next; free(room); g_nrooms--; return; }
    uint8_t m[5]; wr32(m, c->vip); m[4] = 0xFF;      /* tell the others, as a host that vanished would */
    for (int i = 1; i < 255; i++) if (room->slot[i]) conn_send(room->slot[i], 10, m, 5);
}

static void relay_ldn(Conn *c, uint8_t *p, size_t n) {
    if (n < 5 || n > 5 + MAX_LDN || p[4] == 0xFF) { st_dropped++; return; }
    uint32_t dst = rd32(p);
    wr32(p, c->vip);                        /* destination -> source, in place */
    st_ldn++;
    Room *room = c->room;
    if (dst == 0xFFFFFFFFu || dst == BROADCAST) {
        for (int i = 1; i < 255; i++) if (room->slot[i] && room->slot[i] != c) conn_send(room->slot[i], 10, p, n);
    } else if ((dst & MASK) == NET && room->slot[dst & 255] && dst != c->vip) {
        conn_send(room->slot[dst & 255], 10, p, n);
    }
}

static void frame(Conn *c, uint8_t type, uint8_t *p, size_t n) {
    if (c->refused) return;
    if (!c->joined) { if (type != 1) kill_conn(c); else join(c, p, n); return; }
    if (type == 10) relay_ldn(c, p, n);
    else if (type == 3) conn_send(c, 5, NULL, 0);
}

static void conn_read(Conn *c) {
    if (c->in_cap - c->in_n < 1024 && c->in_cap < 5 + MAX_FRAME) {
        size_t cap = c->in_cap ? c->in_cap * 2 : 2048;
        if (cap > 5 + MAX_FRAME) cap = 5 + MAX_FRAME;
        uint8_t *nb = realloc(c->in, cap);
        if (!nb) { kill_conn(c); return; }
        c->in = nb; c->in_cap = cap;
    }
    ssize_t r = recv(c->fd, c->in + c->in_n, c->in_cap - c->in_n, 0);
    if (r == 0 || (r < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)) { kill_conn(c); return; }
    if (r < 0) return;
    c->in_n += (size_t)r;
    size_t q = 0;
    while (!c->dead && c->in_n - q >= 5) {
        uint32_t len = rd32(c->in + q);
        if (len < 1 || len > MAX_FRAME) { kill_conn(c); break; }
        if (c->in_n - q < 4 + (size_t)len) break;
        uint8_t type = c->in[q + 4], *p = c->in + q + 5;
        q += 4 + (size_t)len;
        frame(c, type, p, len - 1);
    }
    if (q) { memmove(c->in, c->in + q, c->in_n - q); c->in_n -= q; }
    if (!c->dead && c->in_n >= 5) {                 /* a frame not complete yet: room for all of it */
        size_t need = 4 + (size_t)rd32(c->in);
        if (need > c->in_cap) {
            uint8_t *nb = realloc(c->in, need);
            if (!nb) { kill_conn(c); return; }
            c->in = nb; c->in_cap = need;
        }
    }
}

static void reap(void) {
    while (g_ndead) {
        Conn *c = g_dead[--g_ndead];
        if (c->joined) leave(c);                    /* may kill others (their send failed): the loop takes them too */
        epoll_ctl(g_ep, EPOLL_CTL_DEL, c->fd, NULL);
        close(c->fd);
        g_conns[c->idx] = g_conns[--g_nconns]; g_conns[c->idx]->idx = c->idx;
        free(c->in); free(c->out); free(c);
    }
}

static void accept_all(void) {
    for (;;) {
        struct sockaddr_in a; socklen_t al = sizeof a;
        int fd = accept4(g_tcp, (struct sockaddr *)&a, &al, SOCK_NONBLOCK | SOCK_CLOEXEC);
        if (fd < 0) return;
        int same = 0;
        for (int i = 0; i < g_nconns; i++) same += g_conns[i]->peer_ip == a.sin_addr.s_addr;
        Conn *c = g_nconns < MAX_CONNS && same < g_per_ip ? calloc(1, sizeof *c) : NULL;
        if (!c) { close(fd); continue; }
        int one = 1, idle = 60, intvl = 10, cnt = 6;
        setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
        setsockopt(fd, SOL_SOCKET, SO_KEEPALIVE, &one, sizeof one);
        setsockopt(fd, IPPROTO_TCP, TCP_KEEPIDLE, &idle, sizeof idle);
        setsockopt(fd, IPPROTO_TCP, TCP_KEEPINTVL, &intvl, sizeof intvl);
        setsockopt(fd, IPPROTO_TCP, TCP_KEEPCNT, &cnt, sizeof cnt);
        c->fd = fd; c->peer_ip = a.sin_addr.s_addr; c->t_open = now_s();
        char ib[16];
        snprintf(c->peer, sizeof c->peer, "('%s', %u)", inet_ntop(AF_INET, &a.sin_addr, ib, sizeof ib), ntohs(a.sin_port));
        c->idx = g_nconns; g_conns[g_nconns++] = c;
        struct epoll_event ev = {.events = EPOLLIN, .data.ptr = c};
        epoll_ctl(g_ep, EPOLL_CTL_ADD, fd, &ev);
    }
}

/* ---------------------------------------------------------------- UDP: the game's datagrams */
static struct mmsghdr g_rmsg[BATCH]; static struct iovec g_riov[BATCH]; static struct sockaddr_in g_raddr[BATCH];
static uint8_t g_rbuf[BATCH][65536];
static struct mmsghdr g_smsg[OUTQ]; static struct iovec g_siov[OUTQ]; static struct sockaddr_in g_saddr[OUTQ]; static int g_nsend;
static uint8_t REGOK = 3;

static void udp_flush(void) {
    int i = 0;
    while (i < g_nsend) {
        int r = sendmmsg(g_udp, g_smsg + i, (unsigned)(g_nsend - i), 0);
        if (r > 0) { i += r; continue; }
        if (r < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == ENOBUFS)) break;     /* full: dropped, as UDP is */
        i++;                                                                                    /* that one failed: skip it */
    }
    g_nsend = 0;
}
static void udp_queue(const void *p, size_t n, const struct sockaddr_in *to) {
    if (g_nsend == OUTQ) udp_flush();
    g_siov[g_nsend] = (struct iovec){(void *)p, n};
    g_saddr[g_nsend] = *to;
    g_smsg[g_nsend].msg_hdr = (struct msghdr){.msg_name = &g_saddr[g_nsend], .msg_namelen = sizeof *to, .msg_iov = &g_siov[g_nsend], .msg_iovlen = 1};
    g_nsend++;
}

static void datagram(uint8_t *d, size_t n, const struct sockaddr_in *from, double now) {
    if (n < 5) return;
    uint8_t kind = d[0];
    Conn *m = tok_get(rd32(d + 1));
    if (!m || m->dead || from->sin_addr.s_addr != m->peer_ip) return;
    m->udp = *from; m->has_udp = 1; m->last_udp = now;
    if (kind == 1) { udp_queue(&REGOK, 1, from); return; }
    if (kind == 4) { if (n == 13) { d[4] = 6; udp_queue(d + 4, 9, from); } return; }    /* ping: echo the client's 8 bytes */
    if (kind != 2 || n < 13 || n - 13 > MAX_DATAGRAM) { st_dropped++; return; }
    st_udp_in++; st_bytes_in += n;
    uint32_t dst = rd32(d + 5); uint16_t dport = rd16(d + 9), sport = rd16(d + 11);
    wr32(d + 1, m->vip); wr16(d + 5, sport); wr32(d + 7, dst); wr16(d + 11, dport);      /* the server header, in place */
    Room *room = m->room;
    if ((dst & 0xFF) == 0xFF) {
        for (int i = 1; i < 255; i++) {
            Conn *t = room->slot[i];
            if (t && t != m && t->has_udp && !t->dead) { udp_queue(d, n, &t->udp); st_udp_out++; st_bytes_out += n; }
        }
    } else if ((dst & MASK) == NET && dst != m->vip) {
        Conn *t = room->slot[dst & 255];
        if (t && t->has_udp && !t->dead) { udp_queue(d, n, &t->udp); st_udp_out++; st_bytes_out += n; }
    }
}

static void udp_read(void) {
    double now = now_s();
    for (int round = 0; round < 16; round++) {     /* then back to epoll: TCP gets its turn under a flood */
        for (int i = 0; i < BATCH; i++) {
            g_riov[i] = (struct iovec){g_rbuf[i], sizeof g_rbuf[i]};
            g_rmsg[i].msg_hdr = (struct msghdr){.msg_name = &g_raddr[i], .msg_namelen = sizeof g_raddr[i], .msg_iov = &g_riov[i], .msg_iovlen = 1};
        }
        int r = recvmmsg(g_udp, g_rmsg, BATCH, MSG_DONTWAIT, NULL);
        if (r <= 0) break;
        for (int i = 0; i < r; i++)
            if (g_rmsg[i].msg_hdr.msg_namelen == sizeof(struct sockaddr_in) && !(g_rmsg[i].msg_hdr.msg_flags & MSG_TRUNC))
                datagram(g_rbuf[i], g_rmsg[i].msg_len, &g_raddr[i], now);
        udp_flush();                                /* before the buffers are read into again */
        if (r < BATCH) break;
    }
}

/* ---------------------------------------------------------------- main */
int main(int argc, char **argv) {
    int port = 39010; const char *bind_ip = "0.0.0.0";
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--port") && i + 1 < argc) port = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--bind") && i + 1 < argc) bind_ip = argv[++i];
        else if (!strcmp(argv[i], "--per-ip") && i + 1 < argc) g_per_ip = atoi(argv[++i]);
        else { fprintf(stderr, "usage: %s [--port 39010] [--bind 0.0.0.0] [--per-ip 32]\n", argv[0]); return 2; }
    }
    signal(SIGPIPE, SIG_IGN);
    struct rlimit rl;
    if (!getrlimit(RLIMIT_NOFILE, &rl) && rl.rlim_cur < MAX_CONNS + 64) {
        rl.rlim_cur = rl.rlim_max < MAX_CONNS + 64 ? rl.rlim_max : MAX_CONNS + 64;
        setrlimit(RLIMIT_NOFILE, &rl);
    }
    struct sockaddr_in a = {.sin_family = AF_INET, .sin_port = htons((uint16_t)port)};
    if (inet_pton(AF_INET, bind_ip, &a.sin_addr) != 1) { fprintf(stderr, "bad --bind %s\n", bind_ip); return 2; }
    int one = 1, buf = 4 << 20;
    g_udp = socket(AF_INET, SOCK_DGRAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    setsockopt(g_udp, SOL_SOCKET, SO_RCVBUF, &buf, sizeof buf);
    setsockopt(g_udp, SOL_SOCKET, SO_SNDBUF, &buf, sizeof buf);
    if (bind(g_udp, (struct sockaddr *)&a, sizeof a)) { perror("udp bind"); return 1; }
    g_tcp = socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    setsockopt(g_tcp, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    if (bind(g_tcp, (struct sockaddr *)&a, sizeof a) || listen(g_tcp, 512)) { perror("tcp bind"); return 1; }
    g_ep = epoll_create1(EPOLL_CLOEXEC);
    struct epoll_event ev = {.events = EPOLLIN, .data.ptr = &TAG_TCP};
    epoll_ctl(g_ep, EPOLL_CTL_ADD, g_tcp, &ev);
    ev.data.ptr = &TAG_UDP;
    epoll_ctl(g_ep, EPOLL_CTL_ADD, g_udp, &ev);
    say("ldn room server on %s:%d (tcp + udp), protocol %d (C relay)", bind_ip, port, VERSION);

    double last_sweep = now_s(), last_report = last_sweep;
    struct epoll_event evs[256];
    for (;;) {
        int n = epoll_wait(g_ep, evs, 256, 1000);
        for (int i = 0; i < n; i++) {
            void *p = evs[i].data.ptr;
            if (p == &TAG_UDP) udp_read();
            else if (p == &TAG_TCP) accept_all();
            else {
                Conn *c = p;
                if (c->dead) continue;
                if (evs[i].events & (EPOLLERR | EPOLLHUP)) { kill_conn(c); continue; }
                if (evs[i].events & EPOLLOUT) conn_flush(c);
                if (!c->dead && (evs[i].events & EPOLLIN)) conn_read(c);
            }
        }
        reap();
        double now = now_s();
        if (now - last_sweep >= 1) {
            last_sweep = now;
            for (int i = 0; i < g_nconns; i++) if (!g_conns[i]->joined && now - g_conns[i]->t_open > HELLO_SECS) kill_conn(g_conns[i]);
            reap();
        }
        if (now - last_report >= 60) {
            last_report = now;
            if (g_nmembers)
                say("rooms %d, members %d, udp in %llu out %llu (%llu / %llu bytes), ldn %llu, dropped %llu", g_nrooms, g_nmembers, st_udp_in, st_udp_out,
                    st_bytes_in, st_bytes_out, st_ldn, st_dropped);
        }
    }
}
