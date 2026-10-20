/* net_minilobby.c: a lobby inside the game, so LAN mode and direct-over-internet mode need no server of ours.
 * C port of tools_net/ssbu_lobby.py (same wire protocol "SU" version 1, see the top of net_relay.c); design adapted
 * from SNO2207/WindowSmash, used with the author's permission.
 * #included by net_relay.c: only static functions and data (every name starts with ml_ / ML_ / minilobby_).
 *   minilobby_start / minilobby_stop / minilobby_counts / minilobby_socket / minilobby_open_to (see below).
 * Standalone test: clang -DMINILOBBY_MAIN -x c net_minilobby.c -o minilobby.exe -lws2_32
 *                  minilobby.exe <port> [1 = no PEERS]  */
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#include <mstcpip.h>
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#ifndef SIO_UDP_CONNRESET
#define SIO_UDP_CONNRESET _WSAIOW(IOC_VENDOR, 12)
#endif

enum { ML_PROTO = 1, ML_JOIN = 1, ML_WELCOME, ML_REJECT, ML_PING, ML_PONG, ML_DATA, ML_LEAVE, ML_LIST, ML_LISTING,
       ML_LIST_END, ML_PEERS, ML_PUNCH, ML_DIRECT, ML_BCAST };
enum { ML_M_ADVERTISE = 1, ML_M_JOIN, ML_M_ACCEPT, ML_M_REJECT, ML_M_KEEP, ML_M_LEAVE, ML_M_GONE, ML_M_KICK };
#define ML_NAME_LEN 32
#define ML_BUILD_LEN 40
#define ML_JOIN_LEN (4 + 8 + 2 * ML_NAME_LEN + ML_BUILD_LEN + 4 + 2 + 1)
#define ML_SUBNET 0x0A0D0000u
#define ML_BCAST0 0x0A0DFFFFu
#define ML_BCAST1 0xFFFFFFFFu
#define ML_LDN_PORT 65511
#define ML_NI_SIZE 0x480
#define ML_NI_SESSION 0x10
#define ML_NI_POLICY 0x62
#define ML_NI_NODE_MAX 0x66
#define ML_NI_NODE_COUNT 0x67
#define ML_NI_NODES 0x68
#define ML_NODE_LEN 0x40
#define ML_LIST_MAX 24
#define ML_CLIENT_TIMEOUT 10000
#define ML_ROOM_TIMEOUT 10000
#define ML_LISTED_FOR 4000
#define ML_MAX_DATA 1500
#define ML_MAX_CLIENTS 256
#define ML_MAX_ROOMS 256
#define ML_PEER_LEN 56   /* ip4 name32 pubip4 port2 lanip4 lanport2 secret8 */
#define ML_OPEN_MAX 8

typedef struct ml_room ml_room;
typedef struct ml_client {
    int used;
    struct sockaddr_in at;
    uint8_t nonce[8];
    uint32_t ip;
    char name[ML_NAME_LEN + 1], build[ML_BUILD_LEN + 1], code[ML_NAME_LEN + 1];
    uint32_t lan_ip;
    uint16_t lan_port;
    int direct;
    uint64_t cookie;
    ULONGLONG seen;
    ml_room *room;            /* the room this player hosts */
    int has_claim;
    uint8_t claim[16];        /* session id of the room it asked to join */
    uint32_t peers_version;
    int peers_valid, peers_len;
    uint8_t peers_sent[7 * ML_PEER_LEN];
} ml_client;

struct ml_room {
    int used;
    ml_client *owner;
    uint8_t session[16];
    uint8_t info[ML_NI_SIZE];
    uint32_t nodes[7];        /* station addresses (node 0 is the owner) */
    int nnodes;
    ULONGLONG created, updated;
    struct { uint32_t a, b; uint64_t s; } pairs[64];
    int npairs, pnext;
};

static ml_client ml_clients[ML_MAX_CLIENTS];
static ml_room ml_rooms[ML_MAX_ROOMS];
static uint32_t ml_next_ip = ML_SUBNET + 2;
static unsigned long long ml_relayed, ml_ldn_msgs, ml_dropped;
static CRITICAL_SECTION ml_lock;
static int ml_lock_ready;
static SOCKET ml_sock = INVALID_SOCKET;
static volatile LONG ml_running;
static HANDLE ml_thread;
static int ml_no_peers;
static struct { struct sockaddr_in at; int used; } ml_open[ML_OPEN_MAX];
static uint64_t ml_rng_state;

#define ml_log(...) do { printf("[online] lobby: " __VA_ARGS__); printf("\n"); fflush(stdout); } while (0)

/* ---- small helpers */
static uint32_t ml_get32(const uint8_t *p) { return (uint32_t)p[0] << 24 | p[1] << 16 | p[2] << 8 | p[3]; }
static uint16_t ml_get16(const uint8_t *p) { return (uint16_t)(p[0] << 8 | p[1]); }
static uint64_t ml_get64(const uint8_t *p) { return (uint64_t)ml_get32(p) << 32 | ml_get32(p + 4); }
static uint8_t *ml_put32(uint8_t *p, uint32_t v) { p[0] = v >> 24; p[1] = v >> 16; p[2] = v >> 8; p[3] = (uint8_t)v; return p + 4; }
static uint8_t *ml_put16(uint8_t *p, unsigned v) { p[0] = v >> 8; p[1] = (uint8_t)v; return p + 2; }
static uint8_t *ml_put64(uint8_t *p, uint64_t v) { return ml_put32(ml_put32(p, (uint32_t)(v >> 32)), (uint32_t)v); }
static uint8_t *ml_hdr(uint8_t *p, int kind) { p[0] = 'S'; p[1] = 'U'; p[2] = ML_PROTO; p[3] = (uint8_t)kind; return p + 4; }

static void ml_text(char *dst, size_t cap, const uint8_t *raw, size_t n) {   /* NUL-terminated string field */
    size_t i = 0;
    while (i < n && i + 1 < cap && raw[i]) { dst[i] = (char)raw[i]; i++; }
    dst[i] = 0;
}

static uint64_t ml_random64(void) {
    static BOOLEAN (WINAPI *rtlgen)(PVOID, ULONG);
    static int tried;
    uint64_t v = 0;
    if (!tried) {
        HMODULE m = LoadLibraryA("advapi32.dll");
        rtlgen = m ? (BOOLEAN (WINAPI *)(PVOID, ULONG))GetProcAddress(m, "SystemFunction036") : NULL;
        ml_rng_state = GetTickCount64() * 0x9E3779B97F4A7C15ull ^ GetCurrentProcessId();
        tried = 1;
    }
    if (rtlgen && rtlgen(&v, sizeof v)) return v;
    ml_rng_state ^= ml_rng_state << 13; ml_rng_state ^= ml_rng_state >> 7; ml_rng_state ^= ml_rng_state << 17;
    return ml_rng_state;
}

static const char *ml_vip(uint32_t ip) {
    static char b[4][24];
    static int i;
    char *s = b[i++ & 3];
    snprintf(s, 24, "10.13.%u.%u", ip >> 8 & 255, ip & 255);
    return s;
}

static int ml_same_at(const struct sockaddr_in *a, const struct sockaddr_in *b) {
    return a->sin_addr.s_addr == b->sin_addr.s_addr && a->sin_port == b->sin_port;
}
static int ml_is_bcast(uint32_t ip) { return ip == ML_BCAST0 || ip == ML_BCAST1; }
static int ml_same_part(const ml_client *a, const ml_client *b) { return !strcmp(a->build, b->build) && !strcmp(a->code, b->code); }

static void ml_send(const void *data, int len, const struct sockaddr_in *at) {
    if (ml_sock != INVALID_SOCKET) sendto(ml_sock, (const char *)data, len, 0, (const struct sockaddr *)at, sizeof *at);
}

/* ---- tables */
static ml_client *ml_by_at(const struct sockaddr_in *at) {
    for (int i = 0; i < ML_MAX_CLIENTS; i++) if (ml_clients[i].used && ml_same_at(&ml_clients[i].at, at)) return &ml_clients[i];
    return NULL;
}
static ml_client *ml_by_ip(uint32_t ip) {
    for (int i = 0; i < ML_MAX_CLIENTS; i++) if (ml_clients[i].used && ml_clients[i].ip == ip) return &ml_clients[i];
    return NULL;
}
static ml_room *ml_find_room(const uint8_t *session) {
    for (int i = 0; i < ML_MAX_ROOMS; i++) if (ml_rooms[i].used && !memcmp(ml_rooms[i].session, session, 16)) return &ml_rooms[i];
    return NULL;
}
static int ml_has_node(const ml_room *r, uint32_t ip) {
    for (int i = 0; i < r->nnodes; i++) if (r->nodes[i] == ip) return 1;
    return 0;
}
static int ml_members(const ml_room *r, ml_client **out) {   /* the owner, then the players that claimed this room */
    int n = 0;
    out[n++] = r->owner;
    for (int i = 0; i < r->nnodes; i++) {
        ml_client *c = ml_by_ip(r->nodes[i]);
        if (c && c->has_claim && !memcmp(c->claim, r->session, 16)) out[n++] = c;
    }
    return n;
}
static ml_room *ml_room_of(ml_client *c) {
    if (c->room) return c->room;
    ml_room *r = c->has_claim ? ml_find_room(c->claim) : NULL;
    return r && ml_has_node(r, c->ip) ? r : NULL;
}
static uint32_t ml_new_ip(void) {
    for (int i = 0; i < 0x10000; i++) {
        uint32_t ip = ml_next_ip;
        ml_next_ip = ip >= ML_SUBNET + 0xFFFE ? ML_SUBNET + 2 : ip + 1;
        if ((ip & 0xFF) != 0 && (ip & 0xFF) != 255 && !ml_by_ip(ip)) return ip;
    }
    return 0;
}

/* ---- direct paths: each member of a room learns the others' addresses and a pair secret */
static void ml_send_peers(ml_client *c) {
    if (ml_no_peers) return;
    ml_room *room = ml_room_of(c);
    uint8_t body[7 * ML_PEER_LEN], pkt[9 + sizeof body];
    int n = 0;
    if (room && c->direct) {
        ml_client *mem[8];
        int cnt = ml_members(room, mem);
        for (int i = 0; i < cnt; i++) {
            ml_client *m = mem[i];
            if (m == c || !m->direct || n >= 7) continue;
            uint32_t a = c->ip < m->ip ? c->ip : m->ip, b = c->ip < m->ip ? m->ip : c->ip;
            uint64_t secret = 0;
            for (int k = 0; k < room->npairs; k++) if (room->pairs[k].a == a && room->pairs[k].b == b) secret = room->pairs[k].s;
            if (!secret) {
                int slot = room->npairs < 64 ? room->npairs++ : room->pnext++ & 63;
                room->pairs[slot].a = a; room->pairs[slot].b = b;
                secret = room->pairs[slot].s = ml_random64() | 1;
            }
            uint8_t *p = body + n * ML_PEER_LEN;
            memset(p, 0, ML_PEER_LEN);
            ml_put32(p, m->ip);
            memcpy(p + 4, m->name, strlen(m->name));
            ml_put32(p + 36, ntohl(m->at.sin_addr.s_addr));
            ml_put16(p + 40, ntohs(m->at.sin_port));
            ml_put32(p + 42, m->lan_ip);
            ml_put16(p + 46, m->lan_port);
            ml_put64(p + 48, secret);
            n++;
        }
    }
    int blen = n * ML_PEER_LEN;
    if (c->peers_valid && c->peers_len == blen && !memcmp(c->peers_sent, body, blen)) return;
    c->peers_valid = 1; c->peers_len = blen;
    memcpy(c->peers_sent, body, blen);
    uint8_t *p = ml_put32(ml_hdr(pkt, ML_PEERS), ++c->peers_version);
    *p++ = (uint8_t)n;
    memcpy(p, body, blen);
    ml_send(pkt, (int)(p + blen - pkt), &c->at);
}

static void ml_close_room(ml_room *room, const char *why) {
    uint8_t gone[4 + 12 + 4 + 16], *p;
    ml_client *mem[8];
    int cnt = ml_members(room, mem);
    p = ml_hdr(gone, ML_DATA);
    p = ml_put32(p, room->owner->ip); p = ml_put32(p, ML_BCAST0); p = ml_put16(p, ML_LDN_PORT); p = ml_put16(p, ML_LDN_PORT);
    *p++ = 'L'; *p++ = ML_M_GONE; *p++ = 0; *p++ = 0;
    memcpy(p, room->session, 16);
    for (int i = 1; i < cnt; i++) {
        ml_send(gone, sizeof gone, &mem[i]->at);
        mem[i]->has_claim = 0;
        ml_send_peers(mem[i]);
    }
    ml_client *owner = room->owner;
    if (owner->room == room) owner->room = NULL;
    room->used = 0;
    if (owner->used) ml_send_peers(owner);
    ml_log("room of %s closed (%s)", owner->name, why);
}

static void ml_drop(ml_client *c, const char *why) {
    if (c->room) ml_close_room(c->room, "host left");
    if (c->has_claim) {
        ml_room *r = ml_find_room(c->claim);
        if (r && ml_has_node(r, c->ip)) {   /* tell its host at once */
            uint8_t pkt[4 + 12 + 4 + 16], *p = ml_hdr(pkt, ML_DATA);
            p = ml_put32(p, c->ip); p = ml_put32(p, r->owner->ip); p = ml_put16(p, ML_LDN_PORT); p = ml_put16(p, ML_LDN_PORT);
            *p++ = 'L'; *p++ = ML_M_LEAVE; *p++ = 0; *p++ = 0;
            memcpy(p, r->session, 16);
            ml_send(pkt, sizeof pkt, &r->owner->at);
        }
    }
    c->used = 0;
    ml_log("%s (%s) left: %s", c->name, ml_vip(c->ip), why);
}

/* ---- packets */
static void ml_on_join(const uint8_t *p, int len, const struct sockaddr_in *at, ml_client *c, ULONGLONG now) {
    if (len < ML_JOIN_LEN) return;
    const uint8_t *nonce = p + 4;
    char code[ML_NAME_LEN + 1], name[ML_NAME_LEN + 1], build[ML_BUILD_LEN + 1];
    ml_text(code, sizeof code, p + 12, 32);
    ml_text(name, sizeof name, p + 44, 32);
    if (!name[0]) snprintf(name, sizeof name, "Player");
    ml_text(build, sizeof build, p + 76, 40);
    uint32_t lan_ip = ml_get32(p + 116);
    uint16_t lan_port = ml_get16(p + 120);
    int direct = p[122] & 1;
    if (c && memcmp(c->nonce, nonce, 8)) { ml_drop(c, "restarted"); c = NULL; }
    if (!c) {   /* the same game from a new port (its router remapped it)? */
        for (int i = 0; i < ML_MAX_CLIENTS; i++) {
            ml_client *o = &ml_clients[i];
            if (o->used && !memcmp(o->nonce, nonce, 8) && !strcmp(o->build, build) && !strcmp(o->code, code)) { o->at = *at; c = o; break; }
        }
    }
    if (!c) {
        uint32_t ip = ml_new_ip();
        for (int i = 0; ip && i < ML_MAX_CLIENTS && !c; i++) if (!ml_clients[i].used) c = &ml_clients[i];
        if (!c) {
            uint8_t rej[4 + 8 + 64], *r = ml_hdr(rej, ML_REJECT);
            memset(r, 0, 8 + 64);
            memcpy(r, nonce, 8);
            memcpy(r + 8, "the lobby is full", 17);
            ml_send(rej, sizeof rej, at);
            return;
        }
        memset(c, 0, sizeof *c);
        c->used = 1; c->at = *at; c->ip = ip; c->cookie = ml_random64();
        memcpy(c->nonce, nonce, 8);
        snprintf(c->name, sizeof c->name, "%s", name); snprintf(c->build, sizeof c->build, "%s", build); snprintf(c->code, sizeof c->code, "%s", code);
        ml_log("%s joined (code '%s', build %s) as %s from %u.%u.%u.%u:%d, LAN %u.%u.%u.%u:%u, direct %s", name, code, build, ml_vip(ip),
               at->sin_addr.S_un.S_un_b.s_b1, at->sin_addr.S_un.S_un_b.s_b2, at->sin_addr.S_un.S_un_b.s_b3, at->sin_addr.S_un.S_un_b.s_b4, ntohs(at->sin_port), lan_ip >> 24, lan_ip >> 16 & 255, lan_ip >> 8 & 255, lan_ip & 255,
               lan_port, direct ? "yes" : "no");
    }
    c->seen = now; c->lan_ip = lan_ip; c->lan_port = lan_port; c->direct = direct;
    uint8_t w[4 + 8 + 4 + 8], *q = ml_hdr(w, ML_WELCOME);
    memcpy(q, nonce, 8);
    q = ml_put64(ml_put32(q + 8, c->ip), c->cookie);
    ml_send(w, sizeof w, at);
}

static int ml_room_rank(const ml_room *r) {   /* open rooms first, then fuller ones */
    int open = r->info[ML_NI_POLICY] != 1 && r->info[ML_NI_NODE_COUNT] < r->info[ML_NI_NODE_MAX];
    return (open ? 0 : 1000) - r->info[ML_NI_NODE_COUNT];
}

static void ml_on_list(ml_client *c, const uint8_t *seq, ULONGLONG now) {
    ml_room *sel[ML_LIST_MAX + 1];
    int n = 0;
    for (int i = 0; i < ML_MAX_ROOMS; i++) {
        ml_room *r = &ml_rooms[i];
        if (!r->used || r->owner == c || !ml_same_part(r->owner, c) || now - r->updated > ML_LISTED_FOR) continue;
        int k = n < ML_LIST_MAX ? n++ : ML_LIST_MAX;   /* insertion sort keeping the best ML_LIST_MAX */
        sel[k] = r;
        while (k > 0 && (ml_room_rank(sel[k]) < ml_room_rank(sel[k - 1]) ||
                         (ml_room_rank(sel[k]) == ml_room_rank(sel[k - 1]) && sel[k]->created < sel[k - 1]->created))) {
            ml_room *t = sel[k]; sel[k] = sel[k - 1]; sel[k - 1] = t; k--;
        }
    }
    for (int i = 0; i < n; i++) {
        uint8_t pkt[4 + 4 + 4 + ML_NI_SIZE], *p = ml_hdr(pkt, ML_LISTING);
        memcpy(p, seq, 4);
        ml_put32(p + 4, sel[i]->owner->ip);
        memcpy(p + 8, sel[i]->info, ML_NI_SIZE);
        ml_send(pkt, sizeof pkt, &c->at);
    }
    uint8_t end[4 + 4 + 1], *p = ml_hdr(end, ML_LIST_END);
    memcpy(p, seq, 4);
    p[4] = (uint8_t)n;
    ml_send(end, sizeof end, &c->at);
    if (n) ml_log("%s scanned: %d room(s)", c->name, n);
}

/* NetworkInfo's station addresses (node 0 = owner) into out[]; -1 if it is not one a game makes */
static int ml_room_nodes(const uint8_t *info, uint32_t owner, uint32_t *out) {
    int count = info[ML_NI_NODE_COUNT], most = info[ML_NI_NODE_MAX], n = 0;
    uint32_t ips[8];
    if (!(1 <= count && count <= most && most <= 8)) return -1;
    for (int i = 0; i < 8; i++) {
        const uint8_t *o = info + ML_NI_NODES + ML_NODE_LEN * i;
        if (!o[0xB]) { if (i == 0) return -1; continue; }
        uint32_t ip = (uint32_t)o[0] | o[1] << 8 | o[2] << 16 | (uint32_t)o[3] << 24;   /* little-endian */
        if ((ip & 0xFFFF0000u) != ML_SUBNET || (i == 0 && ip != owner)) return -1;
        for (int k = 0; k < n; k++) if (ips[k] == ip) return -1;
        ips[n++] = ip;
    }
    for (int i = 1; i < n; i++) out[i - 1] = ips[i];
    return n - 1;
}

static void ml_on_advertise(ml_client *c, const uint8_t *p, int len, const uint8_t *info, ULONGLONG now) {
    uint32_t nodes[8];
    int nn = ml_room_nodes(info, c->ip, nodes);
    if (nn < 0) { ml_dropped++; return; }
    const uint8_t *session = info + ML_NI_SESSION;
    ml_room *room = ml_find_room(session);
    if (room && room->owner != c) { ml_dropped++; return; }
    if (!room) {
        if (c->room) ml_close_room(c->room, "replaced by a new room");
        c->has_claim = 0;
        for (int i = 0; i < ML_MAX_ROOMS && !room; i++) if (!ml_rooms[i].used) room = &ml_rooms[i];
        if (!room) { ml_dropped++; return; }
        memset(room, 0, sizeof *room);
        room->used = 1; room->owner = c; room->created = now;
        memcpy(room->session, session, 16);
        c->room = room;
        ml_log("%s opened a room (%d players at most)", c->name, info[ML_NI_NODE_MAX]);
    }
    ml_client *before[8], *after[8];
    int nb = ml_members(room, before);
    int changed = nn != room->nnodes;
    for (int i = 0; i < nn && !changed; i++) changed = !ml_has_node(room, nodes[i]);
    memcpy(room->info, info, ML_NI_SIZE);
    memcpy(room->nodes, nodes, nn * sizeof nodes[0]);
    room->nnodes = nn; room->updated = now;
    int na = ml_members(room, after);
    if (changed) {
        char names[8 * (ML_NAME_LEN + 3)] = "";
        for (int i = 0; i < 8; i++) {
            const uint8_t *o = info + ML_NI_NODES + ML_NODE_LEN * i;
            if (!o[0xB]) continue;
            char nm[ML_NAME_LEN + 1];
            ml_text(nm, sizeof nm, o + 0xC, ML_NAME_LEN);
            if (names[0]) strcat(names, ", ");
            strcat(names, nm[0] ? nm : "?");
        }
        ml_log("room of %s: %d player(s): %s", c->name, info[ML_NI_NODE_COUNT], names);
        for (int i = 0; i < na; i++) ml_send_peers(after[i]);
        for (int i = 0; i < nb; i++) {
            int stays = 0;
            for (int k = 0; k < na; k++) stays |= before[i] == after[k];
            if (!stays) ml_send_peers(before[i]);
        }
    }
    for (int i = 0; i < nb + na; i++) {   /* before and after, each once */
        ml_client *m = i < nb ? before[i] : after[i - nb];
        int dup = 0;
        for (int k = 0; k < i; k++) dup |= m == (k < nb ? before[k] : after[k - nb]);
        if (m != c && !dup) ml_send(p, len, &m->at);
    }
}

static void ml_on_ldn(ml_client *c, const uint8_t *p, int len, uint32_t dst, unsigned sport, unsigned dport, ULONGLONG now) {
    if (sport != ML_LDN_PORT || dport != ML_LDN_PORT || len < 20 || p[16] != 'L') { ml_dropped++; return; }
    ml_ldn_msgs++;
    int kind = p[17], blen = len - 20;
    const uint8_t *body = p + 20;
    if (ml_is_bcast(dst)) {
        if (kind == ML_M_ADVERTISE && blen >= ML_NI_SIZE) ml_on_advertise(c, p, len, body, now);
        else if (kind == ML_M_GONE && c->room && blen >= 16 && !memcmp(body, c->room->session, 16)) ml_close_room(c->room, "closed by its host");
        return;
    }
    ml_client *b = ml_by_ip(dst);
    if (!b || b == c || !ml_same_part(b, c)) { ml_dropped++; return; }
    if (kind == ML_M_JOIN) {
        if (!b->room || blen < 16 || memcmp(body, b->room->session, 16)) { ml_dropped++; return; }
        if (c->room) ml_close_room(c->room, "its host joins another room");
        c->has_claim = 1;
        memcpy(c->claim, b->room->session, 16);
        ml_log("%s asks to join %s's room", c->name, b->name);
    } else if (kind == ML_M_LEAVE) {
        if (c->has_claim && b->room && !memcmp(b->room->session, c->claim, 16)) {
            c->has_claim = 0;
            ml_send(p, len, &b->at);
            ml_send_peers(c);
            return;
        }
    }
    ml_send(p, len, &b->at);
}

static void ml_on_data(ml_client *c, const uint8_t *p, int len, const uint32_t *skip, int nskip, ULONGLONG now) {
    if (len - 16 > ML_MAX_DATA + ML_NI_SIZE) { ml_dropped++; return; }
    uint32_t src = ml_get32(p + 4), dst = ml_get32(p + 8);
    unsigned sport = ml_get16(p + 12), dport = ml_get16(p + 14);
    if (src != c->ip) { ml_dropped++; return; }
    if (sport == ML_LDN_PORT || dport == ML_LDN_PORT) { ml_on_ldn(c, p, len, dst, sport, dport, now); return; }
    ml_room *room = ml_room_of(c);
    if (!room) { ml_dropped++; return; }
    ml_client *mem[8];
    int cnt = ml_members(room, mem), sent = 0;
    for (int i = 0; i < cnt; i++) {
        int skipped = 0;
        for (int k = 0; k < nskip; k++) skipped |= skip[k] == mem[i]->ip;
        if (mem[i] == c || skipped) continue;
        if (ml_is_bcast(dst) || mem[i]->ip == dst) { ml_send(p, len, &mem[i]->at); sent++; }
    }
    ml_relayed += sent;
    if (!sent && !ml_is_bcast(dst)) ml_dropped++;
}

static void ml_packet(const uint8_t *p, int len, const struct sockaddr_in *at, ULONGLONG now) {
    if (len < 4 || p[0] != 'S' || p[1] != 'U' || p[2] != ML_PROTO) return;
    int kind = p[3];
    ml_client *c = ml_by_at(at);
    if (kind == ML_JOIN) {
        for (int i = 0; i < ML_OPEN_MAX; i++) if (ml_open[i].used && ml_same_at(&ml_open[i].at, at)) ml_open[i].used = 0;   /* NAT is open */
        ml_on_join(p, len, at, c, now);
        return;
    }
    if (!c) return;
    c->seen = now;
    int cookie_ok = len >= 12 && ml_get64(p + 4) == c->cookie;
    if (kind == ML_PING && len >= 21 && cookie_ok) {
        int players = 0, rooms = 0;
        for (int i = 0; i < ML_MAX_CLIENTS; i++) players += ml_clients[i].used && ml_same_part(&ml_clients[i], c);
        for (int i = 0; i < ML_MAX_ROOMS; i++) rooms += ml_rooms[i].used && ml_same_part(ml_rooms[i].owner, c);
        uint8_t pong[4 + 8 + 4], *q = ml_hdr(pong, ML_PONG);
        memcpy(q, p + 12, 8);
        ml_put16(ml_put16(q + 8, players), rooms);
        ml_send(pong, sizeof pong, at);
    } else if (kind == ML_LEAVE && len >= 12 && cookie_ok) {
        ml_drop(c, "left");
    } else if (kind == ML_LIST && len >= 16 && cookie_ok) {
        ml_on_list(c, p + 12, now);
    } else if (kind == 16 && len > 16 && len <= 1500 && cookie_ok) {      /* R3: a rollback message (net_relay.c T_RB) to the other players of its lobby code */
        uint32_t dst = ml_get32(p + 12);
        static uint8_t out[1600];   /* (only used under ml_lock) */
        int on = len - 16 + 8, sent = 0;
        memcpy(out, "SU\1\x10", 4); ml_put32(out + 4, c->ip); memcpy(out + 8, p + 16, len - 16);
        for (int i = 0; i < ML_MAX_CLIENTS; i++) {
            ml_client *o = &ml_clients[i];
            if (!o->used || o == c || !ml_same_part(o, c) || (dst && o->ip != dst)) continue;
            ml_send(out, on, &o->at); sent++;
        }
        ml_relayed += sent;
        if (!sent) ml_dropped++;
    } else if (kind == ML_DATA && len >= 16) {
        ml_on_data(c, p, len, NULL, 0, now);
    } else if (kind == ML_BCAST && len >= 5) {
        int n = p[4], body = 5 + 4 * n;
        uint32_t skip[255];
        if (len < body) n = 0, body = 5 + 4 * p[4];   /* (no usable skip list) */
        for (int i = 0; i < n; i++) skip[i] = ml_get32(p + 5 + 4 * i);
        if (len >= body + 12) {
            static uint8_t buf[65536];   /* (only used under ml_lock) */
            memcpy(buf, "SU\1\x06", 4);
            memcpy(buf + 4, p + body, len - body);
            ml_on_data(c, buf, 4 + len - body, skip, n, now);
        }
    }
}

static void ml_sweep(ULONGLONG now) {
    for (int i = 0; i < ML_MAX_CLIENTS; i++)
        if (ml_clients[i].used && now - ml_clients[i].seen > ML_CLIENT_TIMEOUT) ml_drop(&ml_clients[i], "silent for 10 s");
    for (int i = 0; i < ML_MAX_ROOMS; i++)
        if (ml_rooms[i].used && now - ml_rooms[i].updated > ML_ROOM_TIMEOUT) ml_close_room(&ml_rooms[i], "no advertisement for 10 s");
}

static DWORD WINAPI ml_thread_main(LPVOID arg) {
    static uint8_t buf[65536];
    ULONGLONG last_sweep, last_stats, last_open = 0;
    (void)arg;
    last_sweep = last_stats = GetTickCount64();
    while (ml_running) {
        struct sockaddr_in from;
        int fl = sizeof from;
        int n = recvfrom(ml_sock, (char *)buf, sizeof buf, 0, (struct sockaddr *)&from, &fl);
        ULONGLONG now = GetTickCount64();
        EnterCriticalSection(&ml_lock);
        if (n > 0 && ml_running) ml_packet(buf, n, &from, now);
        if (now - last_sweep >= 1000) { last_sweep = now; ml_sweep(now); }
        if (now - last_stats >= 60000) {
            int players = 0, rooms = 0;
            last_stats = now;
            for (int i = 0; i < ML_MAX_CLIENTS; i++) players += ml_clients[i].used;
            for (int i = 0; i < ML_MAX_ROOMS; i++) rooms += ml_rooms[i].used;
            if (players) ml_log("stats: %d player(s), %d room(s), relayed game datagrams %llu, ldn messages %llu, dropped %llu",
                                players, rooms, ml_relayed, ml_ldn_msgs, ml_dropped);
        }
        if (now - last_open >= 500) {   /* keep opening the host's NAT for joiners who gave their code */
            last_open = now;
            for (int i = 0; i < ML_OPEN_MAX; i++) if (ml_open[i].used) ml_send("SUo", 4, &ml_open[i].at);
        }
        LeaveCriticalSection(&ml_lock);
        if (n < 0 && WSAGetLastError() != WSAETIMEDOUT && WSAGetLastError() != WSAECONNRESET && ml_running) Sleep(10);
    }
    return 0;
}

/* ---- API */
static uint16_t minilobby_start(uint32_t bind_ip_host_order, uint16_t port, int no_peers) {
    WSADATA wsa;
    struct sockaddr_in a;
    int al = sizeof a;
    DWORD timeout = 50;
    BOOL off = FALSE;
    DWORD bytes = 0;
    if (ml_running) return 0;
    if (!ml_lock_ready) { InitializeCriticalSection(&ml_lock); ml_lock_ready = 1; }
    WSAStartup(MAKEWORD(2, 2), &wsa);
    SOCKET s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (s == INVALID_SOCKET) return 0;
    WSAIoctl(s, SIO_UDP_CONNRESET, &off, sizeof off, NULL, 0, &bytes, NULL, NULL);   /* (no ICMP errors on receive) */
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (const char *)&timeout, sizeof timeout);
    memset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(bind_ip_host_order);
    a.sin_port = htons(port);
    if (bind(s, (struct sockaddr *)&a, sizeof a) || getsockname(s, (struct sockaddr *)&a, &al)) { closesocket(s); return 0; }
    EnterCriticalSection(&ml_lock);
    memset(ml_clients, 0, sizeof ml_clients);
    memset(ml_rooms, 0, sizeof ml_rooms);
    memset(ml_open, 0, sizeof ml_open);
    ml_next_ip = ML_SUBNET + 2;
    ml_relayed = ml_ldn_msgs = ml_dropped = 0;
    ml_no_peers = no_peers;
    ml_sock = s;
    ml_running = 1;
    LeaveCriticalSection(&ml_lock);
    ml_thread = CreateThread(NULL, 0, ml_thread_main, NULL, 0, NULL);
    if (!ml_thread) { ml_running = 0; ml_sock = INVALID_SOCKET; closesocket(s); return 0; }
    ml_log("lobby on UDP port %u (protocol SU %d%s)", ntohs(a.sin_port), ML_PROTO, no_peers ? ", everyone relayed" : "");
    return ntohs(a.sin_port);
}

static void minilobby_stop(void) {
    if (!ml_running) return;
    ml_running = 0;
    WaitForSingleObject(ml_thread, 2000);
    CloseHandle(ml_thread);
    ml_thread = NULL;
    EnterCriticalSection(&ml_lock);
    closesocket(ml_sock);
    ml_sock = INVALID_SOCKET;
    LeaveCriticalSection(&ml_lock);
}

static void minilobby_counts(int *players, int *rooms) {
    int p = 0, r = 0;
    if (ml_lock_ready) {
        EnterCriticalSection(&ml_lock);
        for (int i = 0; i < ML_MAX_CLIENTS; i++) p += ml_clients[i].used;
        for (int i = 0; i < ML_MAX_ROOMS; i++) r += ml_rooms[i].used;
        LeaveCriticalSection(&ml_lock);
    }
    if (players) *players = p;
    if (rooms) *rooms = r;
}

static SOCKET minilobby_socket(void) { return ml_running ? ml_sock : INVALID_SOCKET; }

static void minilobby_open_to(const struct sockaddr_in *at) {
    int slot = -1;
    if (!at || !ml_lock_ready) return;
    EnterCriticalSection(&ml_lock);
    for (int i = 0; i < ML_OPEN_MAX; i++) {
        if (ml_open[i].used && ml_same_at(&ml_open[i].at, at)) { slot = -2; break; }
        if (!ml_open[i].used && slot < 0) slot = i;
    }
    if (slot >= 0) { ml_open[slot].at = *at; ml_open[slot].used = 1; }
    LeaveCriticalSection(&ml_lock);
}

#ifdef MINILOBBY_MAIN
int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: minilobby <port> [1 = no PEERS]\n"); return 2; }
    if (!minilobby_start(0x7F000001u, (uint16_t)atoi(argv[1]), argc > 2 && argv[2][0] == '1')) { fprintf(stderr, "cannot start\n"); return 1; }
    for (;;) Sleep(1000);
}
#endif
