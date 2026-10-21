// SPDX-License-Identifier: GPL-3.0-or-later
/* rb_lobby.c - the online lobby of ssbu_lobby.py (protocol "SU" 1, lobby 1.4) in C for Linux, RELAY ONLY.
 *
 *     cc -O2 -o rb_lobby rb_lobby.c
 *     ./rb_lobby [--port 39500] [--bind 0.0.0.0] [--per-ip 32] [--search-secs 120] [--match-secs 180] [--stats 10]
 *
 * Same messages, same rules and the same answers as ssbu_lobby.py (the Python file stays the description of the
 * protocol): players join and get a 10.13.x.y address, Local Wireless rooms are listed and their datagrams relayed,
 * matchmaking pairs two searching players (MATCH op 1: a room; op 2: an online rollback match), and the rollback
 * messages (RB, type 16) of a pair are relayed between them.
 *
 * What differs on purpose:
 *   - no direct paths: PEERS is never sent, so no game ever learns another player's internet address and every
 *     datagram goes through this server (the JOIN "direct" flag is ignored). A game then stays on the relay.
 *   - the log never holds internet addresses: players are named by their name and their 10.13 address only.
 *   - at most --per-ip players from one internet address (default 32), at most MAX_CLIENTS in all.
 * Datagrams are read in batches (recvmmsg). One thread, no allocation after start. */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/random.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#define PROTO 1
#define LOBBY_VERSION "1.4"
enum { JOIN = 1, WELCOME, REJECT, PING, PONG, DATA, LEAVE, LIST, LISTING, LIST_END, PEERS, PUNCH, DIRECT, BCAST };
enum { RB = 16, ROOMS = 17, ROOM_INFO = 18, ROOMS_END = 19, MATCH = 20, MATCH_STATE = 21 };
enum { MS_IDLE, MS_SEARCHING, MS_MATCHED, MS_TIMEOUT, MS_PEER_LEFT, MS_TOGETHER, MS_EXPIRED };
enum { ROLE_HOST = 1, ROLE_JOIN = 2 };
enum { KIND_ROOM = 1, KIND_ROLLBACK = 2 };
#define MODS_MAX 32
#define MOD_NAME 31
#define MODS_BYTES (1 + MODS_MAX * (5 + MOD_NAME))
#define ROOMS_MAX 32
#define NAME_LEN 32
#define BUILD_LEN 40
#define CODE_LEN 32
#define JOIN_LEN (4 + 8 + 2 * NAME_LEN + BUILD_LEN + 4 + 2 + 1)
#define SUBNET 0x0A0D0000u
#define BCAST_A 0x0A0DFFFFu
#define BCAST_B 0xFFFFFFFFu
#define LDN_PORT 65511
enum { M_ADVERTISE = 1, M_JOIN, M_ACCEPT, M_REJECT, M_KEEP, M_LEAVE, M_GONE, M_KICK };
#define NI_SIZE 0x480
#define NI_SESSION 0x10
#define NI_POLICY 0x62
#define NI_NODE_MAX 0x66
#define NI_NODE_COUNT 0x67
#define NI_NODES 0x68
#define NODE_LEN 0x40
#define LIST_MAX 24
#define CLIENT_TIMEOUT 10.0
#define ROOM_TIMEOUT 10.0
#define LISTED_FOR 4.0
#define MAX_DATA 1500
#define MAX_CLIENTS 8192
#define ADDR_BITS 14                        /* address hash: 16384 slots, open addressing */
#define BATCH 64
#define PKT_MAX 4096                        /* the largest datagram read (a DATA with a NetworkInfo is ~1.2 KB) */

typedef struct Client Client;
typedef struct { Client *host, *guest; double at; int room_said; int rb_seen; int used; } Match;
struct Client {
    int used;
    struct sockaddr_in at;
    uint8_t nonce[8];
    uint32_t ip;
    char name[NAME_LEN + 1];
    uint8_t build[BUILD_LEN]; int build_len;
    char code[CODE_LEN + 1];
    uint64_t cookie;
    double seen;
    /* the room it hosts (one at most) */
    int has_room; uint8_t session[16]; uint8_t info[NI_SIZE]; uint32_t nodes[7]; int nnodes; double created, updated;
    /* the room it asked to join: its session, and its owner when it was asked */
    int has_claim; uint8_t claim[16]; Client *claim_owner;
    uint8_t mods[MODS_BYTES]; int mods_len;     /* -1: an older game that sends none */
    /* O2 matchmaking */
    int has_search_id; uint32_t search_id; double search_since; int searching;
    Match *match;
    int has_final; uint32_t f_sid; int f_state, f_role; uint32_t f_peer; char f_name[NAME_LEN + 1];
    int kind; uint32_t rb_peer;
    int rtt;                                    /* its round trip to this lobby (from its PING), ms; -1 unknown */
};

static Client g_c[MAX_CLIENTS];
static Match g_m[MAX_CLIENTS];
static int g_addr[1 << ADDR_BITS];          /* client index + 1, 0 = empty, -1 = deleted */
static int g_by_ip[65536];                  /* client index + 1 by the low 16 bits of its 10.13 address */
static int g_sock, g_per_ip = 32, g_nclients, g_hi;     /* g_hi: one past the highest client slot ever used */
static uint32_t g_next_ip = SUBNET + 2;
static double g_search_for = 120.0, g_match_for = 180.0;
static unsigned long long g_relayed, g_ldn, g_dropped;
static double g_now;

static double mono(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec / 1e9; }
static void say(const char *fmt, ...) {
    time_t t = time(NULL); struct tm tm; localtime_r(&t, &tm);
    printf("%02d:%02d:%02d ", tm.tm_hour, tm.tm_min, tm.tm_sec);
    va_list a; va_start(a, fmt); vprintf(fmt, a); va_end(a); putchar('\n'); fflush(stdout);
}
static const char *vip(uint32_t ip) { static char b[4][20]; static int i; i = (i + 1) & 3; snprintf(b[i], 20, "10.13.%u.%u", ip >> 8 & 255, ip & 255); return b[i]; }
static uint32_t rd32(const uint8_t *p) { return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3]; }
static uint64_t rd64(const uint8_t *p) { return (uint64_t)rd32(p) << 32 | rd32(p + 4); }
static uint32_t rd32le(const uint8_t *p) { return (uint32_t)p[3] << 24 | (uint32_t)p[2] << 16 | (uint32_t)p[1] << 8 | p[0]; }
static uint8_t *w8(uint8_t *p, unsigned v) { *p = (uint8_t)v; return p + 1; }
static uint8_t *w16(uint8_t *p, unsigned v) { p[0] = (uint8_t)(v >> 8); p[1] = (uint8_t)v; return p + 2; }
static uint8_t *w32(uint8_t *p, uint32_t v) { p[0] = v >> 24; p[1] = v >> 16; p[2] = v >> 8; p[3] = (uint8_t)v; return p + 4; }
static uint8_t *w64(uint8_t *p, uint64_t v) { return w32(w32(p, (uint32_t)(v >> 32)), (uint32_t)v); }
static uint8_t *wbytes(uint8_t *p, const void *s, size_t n) { memcpy(p, s, n); return p + n; }
static uint8_t *wpad(uint8_t *p, const void *s, size_t n, size_t width) { size_t k = n < width ? n : width; memcpy(p, s, k); memset(p + k, 0, width - k); return p + width; }
static uint8_t *hdr(uint8_t *p, int kind) { p[0] = 'S'; p[1] = 'U'; p[2] = PROTO; p[3] = (uint8_t)kind; return p + 4; }
static void tsend(const void *d, size_t n, const struct sockaddr_in *to) { sendto(g_sock, d, n, 0, (const struct sockaddr *)to, sizeof *to); }
static void csend(const void *d, size_t n, const Client *c) { tsend(d, n, &c->at); }
static void text(char *out, const uint8_t *raw, size_t n, const char *dflt) {
    size_t k = 0; while (k < n && raw[k]) k++;
    memcpy(out, raw, k); out[k] = 0;
    if (!k && dflt) strcpy(out, dflt);
}
static int same_part(const Client *a, const Client *b) { return a->build_len == b->build_len && !memcmp(a->build, b->build, (size_t)a->build_len) && !strcmp(a->code, b->code); }
static int same_code(const Client *a, const Client *b) { return !strcmp(a->code, b->code); }
static uint64_t rnd64(void) { uint64_t v = 0; if (getrandom(&v, sizeof v, 0) != sizeof v) v = (uint64_t)time(NULL) * 6364136223846793005ull; return v; }

/* ---- the address table */
static unsigned ahash(const struct sockaddr_in *a) { uint64_t k = (uint64_t)a->sin_addr.s_addr << 16 | a->sin_port; k *= 0x9E3779B97F4A7C15ull; return (unsigned)(k >> (64 - ADDR_BITS)); }
static int same_at(const struct sockaddr_in *a, const struct sockaddr_in *b) { return a->sin_addr.s_addr == b->sin_addr.s_addr && a->sin_port == b->sin_port; }
static Client *by_at(const struct sockaddr_in *a) {
    for (unsigned h = ahash(a), n = 0; n < (1u << ADDR_BITS); n++, h = (h + 1) & ((1u << ADDR_BITS) - 1)) {
        int v = g_addr[h];
        if (!v) return NULL;
        if (v > 0 && same_at(&g_c[v - 1].at, a)) return &g_c[v - 1];
    }
    return NULL;
}
static void at_put(Client *c) {
    for (unsigned h = ahash(&c->at); ; h = (h + 1) & ((1u << ADDR_BITS) - 1)) if (g_addr[h] <= 0) { g_addr[h] = (int)(c - g_c) + 1; return; }
}
static void at_del(Client *c) {
    for (unsigned h = ahash(&c->at), n = 0; n < (1u << ADDR_BITS); n++, h = (h + 1) & ((1u << ADDR_BITS) - 1)) {
        if (!g_addr[h]) return;
        if (g_addr[h] == (int)(c - g_c) + 1) { g_addr[h] = -1; return; }
    }
}
static Client *by_ip(uint32_t ip) { if ((ip & 0xFFFF0000u) != SUBNET) return NULL; int v = g_by_ip[ip & 0xFFFF]; return v ? &g_c[v - 1] : NULL; }

/* ---- rooms (a client hosts one at most; the session identifies it) */
static Client *room_by_session(const uint8_t *s) {
    for (int i = 0; i < g_hi; i++) if (g_c[i].used && g_c[i].has_room && !memcmp(g_c[i].session, s, 16)) return &g_c[i];
    return NULL;
}
static int in_nodes(const Client *o, uint32_t ip) { for (int i = 0; i < o->nnodes; i++) if (o->nodes[i] == ip) return 1; return 0; }
static int room_open(const Client *o) { return o->info[NI_POLICY] != 1 && o->info[NI_NODE_COUNT] < o->info[NI_NODE_MAX]; }
static int members(const Client *o, Client **out) {        /* the owner first */
    int n = 0; out[n++] = (Client *)o;
    for (int i = 0; i < o->nnodes; i++) { Client *c = by_ip(o->nodes[i]); if (c && c->has_claim && !memcmp(c->claim, o->session, 16)) out[n++] = c; }
    return n;
}
static Client *room_of(Client *c) {                         /* the owner of the room c is in, or NULL */
    if (c->has_room) return c;
    if (!c->has_claim) return NULL;
    Client *o = c->claim_owner;                             /* (hot path: every relayed datagram) the owner when it was asked */
    if (!o || !o->used || !o->has_room || memcmp(o->session, c->claim, 16)) o = c->claim_owner = room_by_session(c->claim);
    return o && in_nodes(o, c->ip) ? o : NULL;
}
static int room_nodes(const uint8_t *info, uint32_t owner, uint32_t *ips) {   /* -1: not a NetworkInfo a game makes */
    int count = info[NI_NODE_COUNT], most = info[NI_NODE_MAX], n = 0; uint32_t all[8];
    if (!(1 <= count && count <= most && most <= 8)) return -1;
    for (int i = 0; i < 8; i++) {
        const uint8_t *o = info + NI_NODES + NODE_LEN * i;
        if (!o[0xB]) { if (!i) return -1; continue; }
        uint32_t ip = rd32le(o);
        if ((ip & 0xFFFF0000u) != SUBNET || (!i && ip != owner)) return -1;
        for (int k = 0; k < n; k++) if (all[k] == ip) return -1;
        all[n++] = ip;
    }
    for (int k = 1; k < n; k++) ips[k - 1] = all[k];
    return n - 1;
}
static void node_names(const uint8_t *info, char *out, size_t cap) {
    size_t o = 0; out[0] = 0;
    for (int i = 0; i < 8; i++) {
        const uint8_t *nd = info + NI_NODES + NODE_LEN * i;
        if (!nd[0xB]) continue;
        char nm[NAME_LEN + 1]; text(nm, nd + 0xC, NAME_LEN, "?");
        o += (size_t)snprintf(out + o, cap - o, "%s%s", o ? ", " : "", nm);
        if (o >= cap) break;
    }
}
static void ldn_msg(uint8_t *b, uint32_t src, uint32_t dst, int kind, const uint8_t *session) {    /* 36 bytes */
    uint8_t *p = hdr(b, DATA); p = w32(p, src); p = w32(p, dst); p = w16(p, LDN_PORT); p = w16(p, LDN_PORT);
    *p++ = 'L'; *p++ = (uint8_t)kind; *p++ = 0; *p++ = 0; memcpy(p, session, 16);
}
static void close_room(Client *o, const char *why) {
    uint8_t gone[36]; ldn_msg(gone, o->ip, BCAST_A, M_GONE, o->session);
    Client *m[8]; int n = members(o, m);
    for (int i = 1; i < n; i++) { csend(gone, sizeof gone, m[i]); m[i]->has_claim = 0; }
    o->has_room = 0; o->nnodes = 0;
    say("room of %s closed (%s)", o->name, why);
}

/* ---- O2 matchmaking */
static void match_send(Client *c, int state) {               /* state -1: how it stands */
    Match *m = c->match; int role = 0, flags = 0; uint32_t peer = 0, sid = c->has_search_id ? c->search_id : 0; const char *name = "";
    if (state < 0 && !m && !c->searching && c->has_final) { sid = c->f_sid; state = c->f_state; role = c->f_role; peer = c->f_peer; name = c->f_name; }
    else if (state < 0) state = m ? MS_MATCHED : c->searching ? MS_SEARCHING : MS_IDLE;
    if (m) {
        Client *o = m->host == c ? m->guest : m->host;
        role = m->host == c ? ROLE_HOST : ROLE_JOIN; peer = o->ip; name = o->name;
        if (m->host->has_room && room_open(m->host) && g_now - m->host->updated <= LISTED_FOR) flags |= 1;
    }
    double since = m ? m->at : c->searching ? c->search_since : -1;
    int same = 0, searching = 0;
    for (int i = 0; i < g_hi; i++) if (g_c[i].used && same_part(&g_c[i], c)) { same++; searching += g_c[i].searching; }
    uint8_t b[80], *p = hdr(b, MATCH_STATE);
    p = w32(p, sid); p = w8(p, (unsigned)state); p = w8(p, (unsigned)role); p = w8(p, (unsigned)flags); p = w32(p, peer);
    p = wpad(p, name, strlen(name), NAME_LEN);
    p = w16(p, (unsigned)searching); p = w16(p, (unsigned)same);
    double w = since >= 0 ? g_now - since : 0; p = w16(p, w > 65535 ? 65535u : (unsigned)w);
    csend(b, (size_t)(p - b), c);
}
static void match_end(Client *c, int state, const char *fmt, ...) {
    Match *m = c->match; int role = 0; uint32_t peer = 0; const char *name = "";
    if (m) { Client *o = m->host == c ? m->guest : m->host; role = m->host == c ? ROLE_HOST : ROLE_JOIN; peer = o->ip; name = o->name; }
    c->has_final = 1; c->f_sid = c->has_search_id ? c->search_id : 0; c->f_state = state; c->f_role = role; c->f_peer = peer;
    snprintf(c->f_name, sizeof c->f_name, "%s", name);
    c->match = NULL; c->searching = 0;
    if (m && m->host->match != m && m->guest->match != m) m->used = 0;      /* neither side in it any more */
    match_send(c, -1);
    char why[160]; va_list a; va_start(a, fmt); vsnprintf(why, sizeof why, fmt, a); va_end(a);
    say("match: %s: %s", c->name, why);
}
static Match *match_new(void) { for (int i = 0; i < MAX_CLIENTS; i++) if (!g_m[i].used) { memset(&g_m[i], 0, sizeof g_m[i]); g_m[i].used = 1; return &g_m[i]; } return NULL; }
static Client *other_of(Match *m, Client *c) { return m->host == c ? m->guest : m->host; }
static void match_room(Match *m) {
    Client *h = m->host, *g = m->guest;
    if (in_nodes(h, g->ip) && g->has_claim && !memcmp(g->claim, h->session, 16)) {
        match_end(h, MS_TOGETHER, "in a room with %s", g->name);
        match_end(g, MS_TOGETHER, "in %s's room", h->name);
        return;
    }
    if (room_open(h) && !m->room_said) { m->room_said = 1; match_send(g, -1); match_send(h, -1); }
}

static void drop(Client *c, const char *why) {
    if (c->match) { Match *m = c->match; Client *o = other_of(m, c); c->match = NULL; match_end(o, MS_PEER_LEFT, "%s left the lobby", c->name); }
    c->searching = 0;
    if (c->has_room) close_room(c, "host left");
    if (c->has_claim) {
        Client *o = room_by_session(c->claim);
        if (o && in_nodes(o, c->ip)) { uint8_t lv[36]; ldn_msg(lv, c->ip, o->ip, M_LEAVE, o->session); csend(lv, sizeof lv, o); }
    }
    at_del(c);
    if (g_by_ip[c->ip & 0xFFFF] == (int)(c - g_c) + 1) g_by_ip[c->ip & 0xFFFF] = 0;
    say("%s (%s) left: %s", c->name, vip(c->ip), why);
    c->used = 0; g_nclients--;
}

static uint32_t new_ip(void) {
    for (int k = 0; k < 0x10000; k++) {
        uint32_t ip = g_next_ip;
        g_next_ip = ip >= SUBNET + 0xFFFE ? SUBNET + 2 : ip + 1;
        if ((ip & 0xFF) != 0 && (ip & 0xFF) != 255 && !g_by_ip[ip & 0xFFFF]) return ip;
    }
    return 0;
}
static int mods_block(const uint8_t *raw, int n, uint8_t *out) {
    if (n < 1 || raw[0] > MODS_MAX) return -1;
    int o = 1;
    for (int i = 0; i < raw[0]; i++) {
        if (o + 5 > n || raw[o + 4] > MOD_NAME || o + 5 + raw[o + 4] > n) return -1;
        o += 5 + raw[o + 4];
    }
    memcpy(out, raw, (size_t)o);
    return o;
}

static void on_join(const uint8_t *p, int n, const struct sockaddr_in *at, Client *c) {
    if (n < JOIN_LEN) return;
    Client tmp; memset(&tmp, 0, sizeof tmp);
    text(tmp.code, p + 12, CODE_LEN, NULL);
    text(tmp.name, p + 44, NAME_LEN, "Player");
    int bl = BUILD_LEN; while (bl > 0 && !p[76 + bl - 1]) bl--;
    memcpy(tmp.build, p + 76, (size_t)bl); tmp.build_len = bl;
    if (c && memcmp(c->nonce, p + 4, 8)) { drop(c, "restarted"); c = NULL; }
    if (!c) {                                               /* the same game from a new port (its router remapped it)? */
        for (int i = 0; i < g_hi; i++) {
            Client *o = &g_c[i];
            if (o->used && !memcmp(o->nonce, p + 4, 8) && same_part(o, &tmp)) { at_del(o); o->at = *at; at_put(o); c = o; break; }
        }
    }
    if (!c) {
        int from_ip = 0, free_i = -1;
        for (int i = 0; i < g_hi; i++) { if (g_c[i].used) { if (g_c[i].at.sin_addr.s_addr == at->sin_addr.s_addr) from_ip++; } else if (free_i < 0) free_i = i; }
        if (free_i < 0 && g_hi < MAX_CLIENTS) free_i = g_hi;
        uint32_t ip = free_i >= 0 && from_ip < g_per_ip ? new_ip() : 0;
        if (!ip) {
            uint8_t b[4 + 8 + 64], *q = hdr(b, REJECT); q = wbytes(q, p + 4, 8);
            const char *why = from_ip >= g_per_ip ? "too many players from this address" : "the lobby is full";
            wpad(q, why, strlen(why), 64); tsend(b, sizeof b, at); return;
        }
        c = &g_c[free_i]; memset(c, 0, sizeof *c);
        c->used = 1; c->at = *at; memcpy(c->nonce, p + 4, 8); c->ip = ip;
        memcpy(c->name, tmp.name, sizeof c->name); memcpy(c->code, tmp.code, sizeof c->code);
        memcpy(c->build, tmp.build, BUILD_LEN); c->build_len = tmp.build_len;
        c->cookie = rnd64(); c->mods_len = -1; c->kind = KIND_ROOM; c->rtt = -1;
        at_put(c); g_by_ip[ip & 0xFFFF] = free_i + 1; g_nclients++; if (free_i + 1 > g_hi) g_hi = free_i + 1;
        say("%s joined (code '%s', build %.*s) as %s", c->name, c->code, c->build_len, (const char *)c->build, vip(ip));
    }
    c->seen = g_now;
    if (n > JOIN_LEN + 2 && p[JOIN_LEN] == 'M' && p[JOIN_LEN + 1] == 'S') c->mods_len = mods_block(p + JOIN_LEN + 2, n - JOIN_LEN - 2, c->mods);
    uint8_t b[4 + 8 + 12], *q = hdr(b, WELCOME); q = wbytes(q, c->nonce, 8); q = w32(q, c->ip); w64(q, c->cookie);
    csend(b, sizeof b, c);
}

/* the Rooms List / room browser: candidates sorted as ssbu_lobby.py does */
static Client *g_sort_me, *g_sort_mhost;
static int cmp_list(const void *a, const void *b) {
    const Client *x = *(Client *const *)a, *y = *(Client *const *)b; int d;
    if ((d = (x != g_sort_mhost) - (y != g_sort_mhost))) return d;
    if ((d = !same_part(x, g_sort_me) - !same_part(y, g_sort_me))) return d;
    if ((d = !room_open(x) - !room_open(y))) return d;
    if ((d = (int)y->info[NI_NODE_COUNT] - (int)x->info[NI_NODE_COUNT])) return d;
    return x->created < y->created ? -1 : x->created > y->created;
}
static void on_list(Client *c, const uint8_t *seq, int other) {
    static Client *r[MAX_CLIENTS]; int n = 0;
    g_sort_me = c; g_sort_mhost = c->match && c->match->guest == c ? c->match->host : NULL;
    for (int i = 0; i < g_hi; i++) {
        Client *o = &g_c[i];
        if (!o->used || !o->has_room || o == c || g_now - o->updated > LISTED_FOR) continue;
        if (other ? !same_code(o, c) : !same_part(o, c)) continue;
        r[n++] = o;
    }
    qsort(r, (size_t)n, sizeof *r, cmp_list);
    if (n > LIST_MAX) n = LIST_MAX;
    static uint8_t b[4 + 4 + 4 + NI_SIZE + BUILD_LEN];
    for (int i = 0; i < n; i++) {
        uint8_t *p = hdr(b, LISTING); p = wbytes(p, seq, 4); p = w32(p, r[i]->ip); p = wbytes(p, r[i]->info, NI_SIZE);
        if (other) p = wpad(p, r[i]->build, (size_t)r[i]->build_len, BUILD_LEN);
        csend(b, (size_t)(p - b), c);
    }
    uint8_t e[9], *p = hdr(e, LIST_END); p = wbytes(p, seq, 4); *p = (uint8_t)n; csend(e, sizeof e, c);
}
static void on_rooms(Client *c, const uint8_t *seq) {
    static Client *r[MAX_CLIENTS]; int n = 0;
    g_sort_me = c; g_sort_mhost = NULL;
    for (int i = 0; i < g_hi; i++) {
        Client *o = &g_c[i];
        if (o->used && o->has_room && same_code(o, c) && g_now - o->updated <= LISTED_FOR) r[n++] = o;
    }
    qsort(r, (size_t)n, sizeof *r, cmp_list);         /* (its own room is listed too; the host-first key never applies) */
    if (n > ROOMS_MAX) n = ROOMS_MAX;
    static uint8_t b[4 + 4 + 7 + NAME_LEN + BUILD_LEN + MODS_BYTES];
    for (int i = 0; i < n; i++) {
        Client *o = r[i];
        int flags = (room_open(o) ? 1 : 0) | (o == c ? 2 : 0) | (o->mods_len >= 0 ? 4 : 0);
        uint8_t *p = hdr(b, ROOM_INFO); p = wbytes(p, seq, 4); p = w32(p, o->ip);
        p = w8(p, o->info[NI_NODE_COUNT]); p = w8(p, o->info[NI_NODE_MAX]); p = w8(p, (unsigned)flags);
        p = wpad(p, o->name, strlen(o->name), NAME_LEN); p = wpad(p, o->build, (size_t)o->build_len, BUILD_LEN);
        if (o->mods_len >= 0) p = wbytes(p, o->mods, (size_t)o->mods_len); else *p++ = 0;
        csend(b, (size_t)(p - b), c);
    }
    uint8_t e[9], *p = hdr(e, ROOMS_END); p = wbytes(p, seq, 4); *p = (uint8_t)n; csend(e, sizeof e, c);
}

static void on_advertise(Client *c, const uint8_t *p, int n, const uint8_t *info) {
    uint32_t nodes[7]; int nn = room_nodes(info, c->ip, nodes);
    if (nn < 0) { g_dropped++; return; }
    const uint8_t *session = info + NI_SESSION;
    Client *owner = room_by_session(session);
    if (owner && owner != c) { g_dropped++; return; }
    Client *before[8]; int nb = 0;
    if (!owner) {
        if (c->has_room) close_room(c, "replaced by a new room");
        c->has_claim = 0;
        c->has_room = 1; memcpy(c->session, session, 16); c->created = g_now; c->nnodes = 0; memcpy(c->info, info, NI_SIZE);
        say("%s opened a room (%d players at most)", c->name, info[NI_NODE_MAX]);
    } else nb = members(c, before);
    int changed = nn != c->nnodes || memcmp(nodes, c->nodes, sizeof(uint32_t) * (size_t)nn);
    memcpy(c->info, info, NI_SIZE); memcpy(c->nodes, nodes, sizeof nodes); c->nnodes = nn; c->updated = g_now;
    Client *after[8]; int na = members(c, after);
    if (changed) { char names[400]; node_names(info, names, sizeof names); say("room of %s: %d player(s): %s", c->name, info[NI_NODE_COUNT], names); }
    for (int i = 1; i < na; i++) csend(p, (size_t)n, after[i]);                       /* the members now */
    for (int i = 1; i < nb; i++) {                                                     /* and those that just left it */
        int still = 0; for (int k = 1; k < na; k++) if (after[k] == before[i]) still = 1;
        if (!still) csend(p, (size_t)n, before[i]);
    }
    if (c->match && c->match->host == c && c->kind == KIND_ROOM) match_room(c->match);
}
static void on_ldn(Client *c, const uint8_t *p, int n, uint32_t dst, unsigned sport, unsigned dport) {
    if (sport != LDN_PORT || dport != LDN_PORT || n < 20 || p[16] != 'L') { g_dropped++; return; }
    g_ldn++;
    int kind = p[17]; const uint8_t *body = p + 20; int blen = n - 20;
    if (dst == BCAST_A || dst == BCAST_B) {
        if (kind == M_ADVERTISE && blen >= NI_SIZE) on_advertise(c, p, n, body);
        else if (kind == M_GONE && c->has_room && blen >= 16 && !memcmp(body, c->session, 16)) close_room(c, "closed by its host");
        return;
    }
    Client *b = by_ip(dst);
    if (!b || b == c || !same_part(b, c)) { g_dropped++; return; }
    if (kind == M_JOIN) {
        if (!b->has_room || blen < 16 || memcmp(body, b->session, 16)) { g_dropped++; return; }
        if (c->has_room) close_room(c, "its host joins another room");
        c->has_claim = 1; memcpy(c->claim, b->session, 16); c->claim_owner = b;
        say("%s asks to join %s's room", c->name, b->name);
    } else if (kind == M_LEAVE) {
        if (c->has_claim && b->has_room && !memcmp(b->session, c->claim, 16)) c->has_claim = 0;
    }
    csend(p, (size_t)n, b);
}
static void on_data(Client *c, const uint8_t *p, int n, const uint32_t *skip, int nskip) {   /* p: a DATA packet */
    if (n - 4 - 12 > MAX_DATA + NI_SIZE) { g_dropped++; return; }
    uint32_t src = rd32(p + 4), dst = rd32(p + 8); unsigned sport = (unsigned)p[12] << 8 | p[13], dport = (unsigned)p[14] << 8 | p[15];
    if (src != c->ip) { g_dropped++; return; }
    if (sport == LDN_PORT || dport == LDN_PORT) { on_ldn(c, p, n, dst, sport, dport); return; }
    Client *o = room_of(c);
    if (!o) { g_dropped++; return; }
    Client *m[8]; int nm = members(o, m), sent = 0;
    for (int i = 0; i < nm; i++) {
        if (m[i] == c) continue;
        int sk = 0; for (int k = 0; k < nskip; k++) if (skip[k] == m[i]->ip) sk = 1;
        if (sk) continue;
        if (dst == BCAST_A || dst == BCAST_B || m[i]->ip == dst) { csend(p, (size_t)n, m[i]); sent++; }
    }
    g_relayed += (unsigned long long)sent;
    if (!sent && dst != BCAST_A && dst != BCAST_B) g_dropped++;
}
static void on_match(Client *c, int op, uint32_t sid) {
    if (op == 0) {
        if (c->match) { Client *o = other_of(c->match, c); c->match = NULL; match_end(o, MS_PEER_LEFT, "%s cancelled the match", c->name); }
        if (c->searching) say("match: %s stopped searching", c->name);
        c->searching = 0; c->has_search_id = 1; c->search_id = sid;
        c->has_final = 1; c->f_sid = sid; c->f_state = MS_IDLE; c->f_role = 0; c->f_peer = 0; c->f_name[0] = 0;
        match_send(c, -1); return;
    }
    if (op != KIND_ROOM && op != KIND_ROLLBACK) return;
    if (c->has_search_id && c->search_id == sid && (c->match || c->searching || c->has_final)) { match_send(c, -1); return; }
    if (c->match) { Client *o = other_of(c->match, c); c->match = NULL; match_end(o, MS_PEER_LEFT, "%s searches again", c->name); }
    c->has_search_id = 1; c->search_id = sid; c->search_since = g_now; c->searching = 1; c->has_final = 0; c->kind = op;
    say("match: %s searches an opponent%s (build %.*s)", c->name, op == KIND_ROLLBACK ? " for a rollback match" : "", c->build_len, (const char *)c->build);
    Client *o = NULL;
    for (int i = 0; i < g_hi; i++) {
        Client *x = &g_c[i];
        if (x->used && x != c && same_part(x, c) && x->searching && !x->match && x->kind == op && (!o || x->search_since < o->search_since)) o = x;
    }
    if (!o) { match_send(c, -1); return; }
    Match *m = match_new(); if (!m) { match_send(c, -1); return; }
    int c_open = op == KIND_ROOM && c->has_room && room_open(c), o_open = op == KIND_ROOM && o->has_room && room_open(o);
    m->host = c_open && !o_open ? c : o; m->guest = m->host == c ? o : c; m->at = g_now;
    c->match = o->match = m; c->searching = o->searching = 0;
    if (op == KIND_ROLLBACK) { c->rb_peer = o->ip; o->rb_peer = c->ip; }
    say("match: %s hosts, %s joins%s", m->host->name, m->guest->name, op == KIND_ROLLBACK ? " (rollback match)" : "");
    match_send(m->host, -1); match_send(m->guest, -1);
    if (m->host->has_room && op == KIND_ROOM) match_room(m);
}
static void on_rb(Client *c, const uint8_t *p, int n) {
    uint32_t dst = rd32(p + 12); int pub = !strcmp(c->code, "public");
    if (!dst && pub) return;
    if (dst && pub && dst != c->rb_peer) {
        Client *o = room_of(c), *m[8]; int nm = o ? members(o, m) : 0, in = 0;
        for (int i = 0; i < nm; i++) if (m[i]->ip == dst) in = 1;
        if (!in) { g_dropped++; return; }
    }
    static uint8_t out[1504]; uint8_t *q = hdr(out, RB); q = w32(q, c->ip); memcpy(q, p + 16, (size_t)(n - 16)); size_t len = 8 + (size_t)(n - 16);
    if (dst) { Client *x = by_ip(dst); if (x && x != c && same_part(x, c)) csend(out, len, x); }
    else for (int i = 0; i < g_hi; i++) { Client *x = &g_c[i]; if (x->used && x != c && same_part(x, c)) csend(out, len, x); }
    Match *m = c->match;
    if (dst && m && c->kind == KIND_ROLLBACK && other_of(m, c)->ip == dst) {
        m->rb_seen |= m->host == c ? 1 : 2;
        if (m->rb_seen == 3) {
            Client *h = m->host, *g = m->guest;
            match_end(h, MS_TOGETHER, "playing a rollback match with %s", g->name);
            match_end(g, MS_TOGETHER, "playing a rollback match with %s", h->name);
        }
    }
}

static void packet(const uint8_t *p, int n, const struct sockaddr_in *at) {
    if (n < 4 || p[0] != 'S' || p[1] != 'U' || p[2] != PROTO) return;
    int kind = p[3];
    Client *c = by_at(at);
    if (kind == JOIN) { on_join(p, n, at, c); return; }
    if (!c) return;
    c->seen = g_now;
    int ck = n >= 12 && rd64(p + 4) == c->cookie;
    if (kind == PING && n >= 21 && ck) {
        int same = 0, rooms = 0, searching = 0, code = 0;
        for (int i = 0; i < g_hi; i++) {
            Client *x = &g_c[i]; if (!x->used) continue;
            if (same_part(x, c)) { same++; searching += x->searching; if (x->has_room) rooms++; }
            if (same_code(x, c)) code++;
        }
        if (n >= 23) { unsigned r = (unsigned)p[21] << 8 | p[22]; c->rtt = r == 0xFFFF ? -1 : (int)r; }     /* (our games) its round trip */
        /* + "PR", count, (vip u32, ms u16) x count: the round trips of the players of its room and of its rollback opponent,
         * for their ping overlay (an older game reads the first 20 bytes only) */
        uint8_t b[4 + 8 + 8 + 3 + 8 * 6], *q = hdr(b, PONG); q = wbytes(q, p + 12, 8);
        q = w16(q, (unsigned)same); q = w16(q, (unsigned)rooms); q = w16(q, (unsigned)searching); q = w16(q, (unsigned)code);
        Client *o = room_of(c), *m[9]; int nm = o ? members(o, m) : 0, k = 0;
        Client *rb = c->rb_peer ? by_ip(c->rb_peer) : NULL;
        if (rb && rb != c && same_part(rb, c)) { int dup = 0; for (int i = 0; i < nm; i++) dup |= m[i] == rb; if (!dup) m[nm++] = rb; }
        uint8_t *cnt = q + 2; q[0] = 'P'; q[1] = 'R'; q += 3;
        for (int i = 0; i < nm && k < 8; i++) if (m[i] != c) { q = w32(q, m[i]->ip); q = w16(q, m[i]->rtt < 0 ? 0xFFFFu : (unsigned)m[i]->rtt); k++; }
        *cnt = (uint8_t)k;
        csend(b, (size_t)(q - b), c);
    } else if (kind == LEAVE && ck) drop(c, "left");
    else if (kind == LIST && n >= 16 && ck) on_list(c, p + 12, n >= 17 && (p[16] & 1));
    else if (kind == ROOMS && n >= 16 && ck) on_rooms(c, p + 12);
    else if (kind == MATCH && n >= 17 && ck) on_match(c, p[12], rd32(p + 13));
    else if (kind == RB && n > 16 && n <= 1500 && ck) on_rb(c, p, n);
    else if (kind == DATA && n >= 16) on_data(c, p, n, NULL, 0);
    else if (kind == BCAST && n >= 5) {
        int k = p[4], body = 5 + 4 * k; uint32_t skip[255];
        if (n >= body) for (int i = 0; i < k; i++) skip[i] = rd32(p + 5 + 4 * i); else k = 0;
        if (n >= body + 12) {
            static uint8_t d[PKT_MAX + 8]; uint8_t *q = hdr(d, DATA); memcpy(q, p + body, (size_t)(n - body));
            on_data(c, d, 4 + n - body, skip, k);
        }
    }
    /* PEERS / PUNCH / DIRECT: no direct paths on this lobby (relay only); anything else: ignored */
}

static void sweep(void) {
    for (int i = 0; i < g_hi; i++) if (g_c[i].used && g_now - g_c[i].seen > CLIENT_TIMEOUT) drop(&g_c[i], "silent for 10 s");
    for (int i = 0; i < g_hi; i++) {
        Client *c = &g_c[i]; if (!c->used) continue;
        if (c->searching && !c->match && g_now - c->search_since > g_search_for) match_end(c, MS_TIMEOUT, "no opponent in %.0f s", g_search_for);
        Match *m = c->match;
        if (m && m->host == c && g_now - m->at > g_match_for) {
            Client *g = m->guest;
            match_end(c, MS_EXPIRED, "the match with %s expired", g->name);
            match_end(g, MS_EXPIRED, "the match with %s expired", c->name);
        }
    }
    for (int i = 0; i < g_hi; i++) if (g_c[i].used && g_c[i].has_room && g_now - g_c[i].updated > ROOM_TIMEOUT) close_room(&g_c[i], "no advertisement for 10 s");
}

int main(int argc, char **argv) {
    const char *bind_to = "0.0.0.0"; int port = 39500; double stats = 10.0;
    const char *e;                                          /* (test_ssbu_lobby.py LOBBY_EXE=: "<exe> <port>" and these two) */
    if ((e = getenv("SSBU_LOBBY_SEARCH_SECS"))) g_search_for = atof(e);
    if ((e = getenv("SSBU_LOBBY_MATCH_SECS"))) g_match_for = atof(e);
    if (argc == 2 && atoi(argv[1]) > 0) { port = atoi(argv[1]); bind_to = "127.0.0.1"; argc = 1; }
    for (int i = 1; i + 1 < argc; i += 2) {
        if (!strcmp(argv[i], "--port")) port = atoi(argv[i + 1]);
        else if (!strcmp(argv[i], "--bind")) bind_to = argv[i + 1];
        else if (!strcmp(argv[i], "--per-ip")) g_per_ip = atoi(argv[i + 1]);
        else if (!strcmp(argv[i], "--search-secs")) g_search_for = atof(argv[i + 1]);
        else if (!strcmp(argv[i], "--match-secs")) g_match_for = atof(argv[i + 1]);
        else if (!strcmp(argv[i], "--stats")) stats = atof(argv[i + 1]);
        else { fprintf(stderr, "unknown option %s\n", argv[i]); return 2; }
    }
    signal(SIGPIPE, SIG_IGN);
    g_sock = socket(AF_INET, SOCK_DGRAM, 0);
    int big = 4 << 20; setsockopt(g_sock, SOL_SOCKET, SO_RCVBUF, &big, sizeof big); setsockopt(g_sock, SOL_SOCKET, SO_SNDBUF, &big, sizeof big);
    struct sockaddr_in sa = {0}; sa.sin_family = AF_INET; sa.sin_port = htons((uint16_t)port);
    if (inet_pton(AF_INET, bind_to, &sa.sin_addr) != 1 || bind(g_sock, (struct sockaddr *)&sa, sizeof sa) < 0) { perror("bind"); return 1; }
    say("lobby on UDP %s:%d (protocol SU %d, lobby %s, relay only)", bind_to, port, PROTO, LOBBY_VERSION);
    static uint8_t buf[BATCH][PKT_MAX]; static struct sockaddr_in from[BATCH]; static struct iovec iov[BATCH]; static struct mmsghdr msg[BATCH];
    for (int i = 0; i < BATCH; i++) {
        iov[i].iov_base = buf[i]; iov[i].iov_len = PKT_MAX;
        msg[i].msg_hdr.msg_iov = &iov[i]; msg[i].msg_hdr.msg_iovlen = 1; msg[i].msg_hdr.msg_name = &from[i];
    }
    double last_sweep = mono(), last_stats = last_sweep;
    for (;;) {
        struct pollfd pf = {g_sock, POLLIN, 0};
        int r = poll(&pf, 1, 500);
        g_now = mono();
        if (r > 0) {
            for (int i = 0; i < BATCH; i++) msg[i].msg_hdr.msg_namelen = sizeof from[i];
            int got = recvmmsg(g_sock, msg, BATCH, MSG_DONTWAIT, NULL);
            for (int i = 0; i < got; i++) if (!(msg[i].msg_hdr.msg_flags & MSG_TRUNC)) packet(buf[i], (int)msg[i].msg_len, &from[i]);
        }
        if (g_now - last_sweep >= 1.0) { last_sweep = g_now; sweep(); }
        if (stats > 0 && g_now - last_stats >= stats) {
            last_stats = g_now;
            if (g_nclients) {
                int rooms = 0; for (int i = 0; i < g_hi; i++) rooms += g_c[i].used && g_c[i].has_room;
                say("stats: %d player(s), %d room(s), relayed game datagrams %llu, ldn messages %llu, dropped %llu", g_nclients, rooms, g_relayed, g_ldn, g_dropped);
            }
        }
    }
}
