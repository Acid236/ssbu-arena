/* Online play: the client side of the lobby protocol, and direct player-to-player paths (see net_relay.h).
 * Adapted from SNO2207/WindowSmash (runtime/net_relay.c: lobby client, UDP hole punching, relay fallback), used with
 * the author's permission. Our own code and our own wire protocol; no UPnP and no in-game relay (yet).
 *
 * Wire protocol "SU" version 1, UDP, every field big-endian; each packet starts 'S' 'U' 1 <type>:
 *   1 JOIN     client: nonce u64, code[32], name[32], build[40], lan address u32, lan port u16, flags u8 (1: direct ok)
 *   2 WELCOME  lobby:  nonce u64, virtual address u32, cookie u64
 *   3 REJECT   lobby:  nonce u64, text[64]
 *   4 PING     client: cookie u64, time u64, direct paths u8                   (every second: also keeps NAT mappings open)
 *   5 PONG     lobby:  time u64, players u16, rooms u16
 *   6 DATA     both:   source u32, destination u32, source port u16, destination port u16, payload
 *   7 LEAVE    client: cookie u64
 *   8 LIST     client: cookie u64, seq u32                                      (nn::ldn::Scan: the lobby's rooms)
 *   9 LISTING  lobby:  seq u32, host address u32, NetworkInfo[0x480]            (up to 24, best first)
 *  10 LIST_END lobby:  seq u32, count u8
 *  11 PEERS    lobby:  version u32, count u8, count x (address u32, name[32], public ip u32, port u16, lan ip u32,
 *                      port u16, secret u64)           (the other players of this player's room that allow direct paths)
 *  12 PUNCH    player: secret u64, from u32, to u32, ack u8, nonce u64          (straight to another player)
 *  13 DIRECT   player: secret u64, then a DATA body                             (the same)
 *  14 BCAST    client: count u8, count x address u32, then a DATA body          (a broadcast; the lobby leaves out the
 *                      players listed: this player reached them directly)
 * The lobby gives every player its own virtual address and relays a Local Wireless room's datagrams between that room's
 * players only. nnldn.c's own messages (port 65511) always go through the lobby: it is the judge of who is in which room.
 *
 * Configuration (environment first, then graphics.ini keys; nothing is written):
 *   SSBU_ONLINE=1 | <host:port>      online_server = <host:port>      the lobby (default 127.0.0.1:39500); 0/off = off
 *   SSBU_ONLINE_NAME                 online_name                      name in the lobby's log (default Player-xxxx)
 *   SSBU_ONLINE_CODE                 online_code                      lobby code: only players with the same code meet
 *   SSBU_ONLINE_DIRECT=0             online_direct = off              no direct paths: everything through the lobby
 *   SSBU_ONLINE_PORT=<n>             local UDP port (default: any)
 *   SSBU_ONLINE_LOG=0..3             log level (default 1)
 *   SSBU_ONLINE_BUILD                build id override (players of different builds never meet) */
#include <winsock2.h>
#include <ws2tcpip.h>
#include <mstcpip.h>
#include <windows.h>
#include <wincrypt.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include "net_relay.h"
#include "net_stats.h"
#include "gfx_options.h"

#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "advapi32.lib")
#ifndef SIO_UDP_CONNRESET
#define SIO_UDP_CONNRESET _WSAIOW(IOC_VENDOR, 12)
#endif

enum { T_JOIN = 1, T_WELCOME, T_REJECT, T_PING, T_PONG, T_DATA, T_LEAVE, T_LIST, T_LISTING, T_LIST_END,
       T_PEERS, T_PUNCH, T_DIRECT, T_BCAST };
#define PROTO 1
#define NAME_LEN 32
#define BUILD_LEN 40
#define NI_SIZE 0x480
#define MAX_PEERS 7
#define PEER_LEN (4 + NAME_LEN + 4 + 2 + 4 + 2 + 8)
#define LOBBY_TIMEOUT_MS 10000
#define GONE_AFTER_MS 5000
#define PUNCH_FOR_MS 5000          /* hellos every 200 ms this long; no answer -> relayed (hello every 5 s in case it opens) */
#define FRESH_MS 1200              /* a direct path is used while its last answer is younger than this */
#define NET_BUILD_DEFAULT "ssbu-recomp-ldn1"

static uint16_t g16(const uint8_t *p) { return (uint16_t)(p[0] << 8 | p[1]); }
static uint32_t g32(const uint8_t *p) { return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3]; }
static uint64_t g64(const uint8_t *p) { return (uint64_t)g32(p) << 32 | g32(p + 4); }
static void s16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)(v >> 8); p[1] = (uint8_t)v; }
static void s32(uint8_t *p, uint32_t v) { p[0] = (uint8_t)(v >> 24); p[1] = (uint8_t)(v >> 16); p[2] = (uint8_t)(v >> 8); p[3] = (uint8_t)v; }
static void s64(uint8_t *p, uint64_t v) { s32(p, (uint32_t)(v >> 32)); s32(p + 4, (uint32_t)v); }
static void hdr(uint8_t *p, int type) { p[0] = 'S'; p[1] = 'U'; p[2] = PROTO; p[3] = (uint8_t)type; }
static uint64_t ms_now(void) { return GetTickCount64(); }
static uint64_t rnd64(void) {
    uint64_t v = 0;
    HCRYPTPROV h;
    if (CryptAcquireContextA(&h, NULL, NULL, PROV_RSA_FULL, CRYPT_VERIFYCONTEXT)) { CryptGenRandom(h, sizeof v, (BYTE *)&v); CryptReleaseContext(h, 0); }
    if (!v) v = ((uint64_t)GetTickCount64() << 32) ^ GetCurrentProcessId() ^ (uint64_t)(uintptr_t)&v;
    return v;
}

/* ---------------------------------------------------------------- configuration */
static int g_cfg = -1, g_log = 1, g_direct = 1;
static char g_server[256], g_name[NAME_LEN + 1], g_code[NAME_LEN + 1] = "public", g_build[BUILD_LEN + 1] = NET_BUILD_DEFAULT;
static uint16_t g_local_port;

static int ini_value(const char *key, char *out, size_t n) {     /* "key = value" in graphics.ini (read only) */
    const GfxOptions *o = gfx_options();
    FILE *f = o && o->path[0] ? fopen(o->path, "r") : NULL;
    char line[512];
    int found = 0;
    if (!f) return 0;
    while (!found && fgets(line, sizeof line, f)) {
        char *s = line;
        while (*s == ' ' || *s == '\t') s++;
        size_t kl = strlen(key);
        if (_strnicmp(s, key, kl) || (s[kl] != ' ' && s[kl] != '\t' && s[kl] != '=')) continue;
        s += kl;
        while (*s == ' ' || *s == '\t') s++;
        if (*s++ != '=') continue;
        while (*s == ' ' || *s == '\t') s++;
        char *e = s + strcspn(s, ";#\r\n");
        while (e > s && (e[-1] == ' ' || e[-1] == '\t')) e--;
        *e = 0;
        snprintf(out, n, "%s", s);
        found = 1;
    }
    fclose(f);
    return found;
}
static int is_off(const char *v) { return !*v || !strcmp(v, "0") || !_stricmp(v, "off") || !_stricmp(v, "no") || !_stricmp(v, "false"); }

/* Modes (net_relay.h): LOBBY = our lobby server; LAN = no server: one game of the local network runs the lobby inside
 * itself and announces it with a beacon (multicast 239.255.13.13 + broadcast, UDP port 39501), the others find it;
 * HOST = no server, over the internet: this game runs the lobby inside itself and shows a room code (its public
 * address, learnt by STUN and/or a UPnP port mapping); JOIN = no server: the lobby is the host's game named by the code.
 *   SSBU_ONLINE = 0|off  1|on|auto  lan  host[:<port>]  join:<code or ip:port>  <host:port> (= lobby)
 *   graphics.ini: online_mode = off|auto|lobby|lan|host|join, online_server, online_join, online_peer, online_upnp,
 *   online_stun, online_port. auto: online_server given -> LOBBY (no answer for 5 s -> LAN), otherwise LAN. */
static int g_mode, g_auto, g_upnp = 1;
static uint16_t g_host_port;                    /* HOST mode: the in-game lobby's UDP port (default 39500) */
static char g_join[64], g_peer[256], g_stun[128] = "stun.l.google.com:19302";

static void configure(void) {
    if (g_cfg >= 0) return;
    char v[256] = "", mode[64] = "";
    const char *e = getenv("SSBU_ONLINE");
    g_cfg = 0;
    if (e) {
        if (is_off(e)) return;
        snprintf(mode, sizeof mode, "%s", e);
    } else if (ini_value("online_mode", v, sizeof v)) {
        if (is_off(v)) return;
        snprintf(mode, sizeof mode, "%s", v);
    } else {                                        /* (older key alone: a lobby address turns online play on) */
        if (!ini_value("online_server", v, sizeof v) || is_off(v)) return;
        snprintf(mode, sizeof mode, "lobby");
    }
    if (!_stricmp(mode, "1") || !_stricmp(mode, "on") || !_stricmp(mode, "auto")) g_auto = 1;
    else if (!_stricmp(mode, "lan")) g_mode = NET_MODE_LAN;
    else if (!_strnicmp(mode, "host", 4)) { g_mode = NET_MODE_HOST; if (mode[4] == ':') g_host_port = (uint16_t)atoi(mode + 5); }
    else if (!_strnicmp(mode, "join", 4)) { g_mode = NET_MODE_JOIN; if (mode[4] == ':') snprintf(g_join, sizeof g_join, "%s", mode + 5); }
    else if (!_stricmp(mode, "lobby")) g_mode = NET_MODE_LOBBY;
    else { g_mode = NET_MODE_LOBBY; snprintf(g_server, sizeof g_server, "%s", mode); }
    if (!g_server[0]) {
        if ((e = getenv("SSBU_ONLINE_SERVER")) && *e) snprintf(g_server, sizeof g_server, "%s", e);
        else if (ini_value("online_server", v, sizeof v) && !is_off(v)) snprintf(g_server, sizeof g_server, "%s", v);
    }
    if (g_auto) g_mode = g_server[0] ? NET_MODE_LOBBY : NET_MODE_LAN;
    if (g_mode == NET_MODE_LOBBY && !g_server[0]) snprintf(g_server, sizeof g_server, "127.0.0.1:%d", VNET_DEFAULT_PORT);
    if (!g_join[0]) { if ((e = getenv("SSBU_ONLINE_JOIN")) && *e) snprintf(g_join, sizeof g_join, "%s", e); else ini_value("online_join", g_join, sizeof g_join); }
    if ((e = getenv("SSBU_ONLINE_PEER")) && *e) snprintf(g_peer, sizeof g_peer, "%s", e); else ini_value("online_peer", g_peer, sizeof g_peer);
    if ((e = getenv("SSBU_ONLINE_UPNP"))) g_upnp = !is_off(e); else if (ini_value("online_upnp", v, sizeof v)) g_upnp = !is_off(v);
    if ((e = getenv("SSBU_ONLINE_STUN"))) snprintf(g_stun, sizeof g_stun, "%s", is_off(e) ? "" : e);
    else if (ini_value("online_stun", v, sizeof v)) snprintf(g_stun, sizeof g_stun, "%s", is_off(v) ? "" : v);
    if (!g_host_port && ini_value("online_port", v, sizeof v) && atoi(v) > 0 && atoi(v) < 65536) g_host_port = (uint16_t)atoi(v);
    if (!g_host_port) g_host_port = VNET_DEFAULT_PORT;
    if (g_mode == NET_MODE_JOIN && !g_join[0]) { printf("[online] join mode without a room code (SSBU_ONLINE=join:<code> or online_join): online play off\n"); fflush(stdout); return; }
    if ((e = getenv("SSBU_ONLINE_NAME")) && *e) snprintf(g_name, sizeof g_name, "%s", e);
    else if (ini_value("online_name", v, sizeof v) && *v) snprintf(g_name, sizeof g_name, "%s", v);
    else snprintf(g_name, sizeof g_name, "Player-%04x", (unsigned)(rnd64() & 0xffff));
    if ((e = getenv("SSBU_ONLINE_CODE")) && *e) snprintf(g_code, sizeof g_code, "%s", e);
    else if (ini_value("online_code", v, sizeof v) && *v) snprintf(g_code, sizeof g_code, "%s", v);
    if ((e = getenv("SSBU_ONLINE_DIRECT"))) g_direct = !is_off(e);
    else if (ini_value("online_direct", v, sizeof v)) g_direct = !is_off(v);
    if ((e = getenv("SSBU_ONLINE_PORT")) && atoi(e) > 0 && atoi(e) < 65536) g_local_port = (uint16_t)atoi(e);
    if ((e = getenv("SSBU_ONLINE_LOG"))) g_log = atoi(e);
    if ((e = getenv("SSBU_ONLINE_BUILD")) && *e) snprintf(g_build, sizeof g_build, "%s", e);
    g_cfg = 1;
    static const char *mode_names[] = {"lobby", "lan (no server)", "host (no server)", "join (no server)"};
    printf("[online] on: mode %s%s, lobby %s, code %s, name %s, direct paths %s, build %s\n", mode_names[g_mode], g_auto ? " (auto)" : "",
           g_mode == NET_MODE_LOBBY ? g_server : g_mode == NET_MODE_JOIN ? g_join : "inside this game", g_code, g_name, g_direct ? "allowed" : "off", g_build);
    fflush(stdout);
}
int net_online(void) { configure(); return g_cfg; }
int net_log_level(void) { configure(); return g_cfg ? g_log : 0; }

static void say(const char *fmt, ...) {
    char buf[512];
    va_list a;
    va_start(a, fmt);
    vsnprintf(buf, sizeof buf, fmt, a);
    va_end(a);
    printf("[online] %s\n", buf);
    fflush(stdout);
}

/* ---------------------------------------------------------------- state */
static SOCKET g_sock = INVALID_SOCKET;
static struct sockaddr_in g_lobby;
static volatile LONG g_joined, g_players, g_rooms, g_ping = -1;
static volatile uint32_t g_ip;
static uint64_t g_nonce, g_cookie, g_last_pong, g_unjoined_since;
static uint32_t g_lan_ip;
static uint16_t g_lan_port;
static int g_loopback;
static char g_reject[80];
static volatile LONG64 g_out_relay, g_out_direct, g_in_relay, g_in_direct;

enum { PS_PUNCHING, PS_DIRECT, PS_RELAYED };
typedef struct {
    struct sockaddr_in at;
    uint64_t hello, hello_at, prev, prev_at;          /* our last two hellos there */
} Cand;
typedef struct {
    uint32_t ip;
    char name[NAME_LEN + 1];
    uint64_t secret, since, last_ack, next_hello, acks_window;
    int state, via, ncand, acks, rtt;
    Cand cand[2];                                     /* through its router (as the lobby sees it), then on its own LAN */
} Peer;
static SRWLOCK g_peers_lock = SRWLOCK_INIT;
static Peer g_peers[MAX_PEERS];
static int g_npeers;
static uint32_t g_peers_version;

static int same_at(const struct sockaddr_in *a, const struct sockaddr_in *b) { return a->sin_addr.s_addr == b->sin_addr.s_addr && a->sin_port == b->sin_port; }
static const char *at_text(const struct sockaddr_in *a, char *buf) {          /* buf: 24 bytes */
    char ip[16];
    inet_ntop(AF_INET, (void *)&a->sin_addr, ip, sizeof ip);
    snprintf(buf, 24, "%s:%u", ip, ntohs(a->sin_port));
    return buf;
}
static int fresh(const Peer *q, uint64_t t) { return q->state == PS_DIRECT && t - q->last_ack < FRESH_MS; }

uint32_t net_my_ip(void) { return g_joined ? g_ip : 0; }
int net_lobby_gone(void) { return g_cfg > 0 && !g_joined && ms_now() - g_unjoined_since > GONE_AFTER_MS; }

static void tx(const void *p, int n, const struct sockaddr_in *to) { sendto(g_sock, (const char *)p, n, 0, (const struct sockaddr *)to, sizeof *to); }

/* ---------------------------------------------------------------- direct paths */
static void punch(Peer *q, int c, int ack, uint64_t word) {     /* (peers lock held) */
    uint8_t p[4 + 8 + 4 + 4 + 1 + 8];
    hdr(p, T_PUNCH);
    s64(p + 4, q->secret);
    s32(p + 12, g_ip);
    s32(p + 16, q->ip);
    p[20] = (uint8_t)ack;
    s64(p + 21, word);
    tx(p, sizeof p, &q->cand[c].at);
}
static void hello(Peer *q, int c, uint64_t t) {
    Cand *k = &q->cand[c];
    k->prev = k->hello; k->prev_at = k->hello_at;
    k->hello = rnd64() | 1; k->hello_at = t;
    punch(q, c, 0, k->hello);
}

static void read_peers(const uint8_t *p, int n) {               /* PEERS body */
    if (n < 5) return;
    uint32_t version = g32(p);
    int count = p[4];
    if ((int32_t)(version - g_peers_version) <= 0 || count > MAX_PEERS || 5 + count * PEER_LEN > n) return;
    uint64_t t = ms_now();
    Peer next[MAX_PEERS];
    char lines[MAX_PEERS][120];
    int nl = 0;
    memset(next, 0, sizeof next);
    AcquireSRWLockExclusive(&g_peers_lock);
    for (int i = 0; i < count; i++) {
        const uint8_t *e = p + 5 + i * PEER_LEN, *a = e + 4 + NAME_LEN;
        Peer *q = &next[i];
        q->ip = g32(e);
        for (int k = 0; k < NAME_LEN; k++) q->name[k] = e[4 + k] && e[4 + k] < 0x20 ? '?' : (char)e[4 + k];
        q->secret = g64(a + 12);
        q->ncand = 1;
        q->cand[0].at.sin_family = AF_INET;
        q->cand[0].at.sin_addr.s_addr = htonl(g32(a));
        q->cand[0].at.sin_port = htons(g16(a + 4));
        if (g32(a + 6) && g16(a + 10) && (g32(a + 6) != g32(a) || g16(a + 10) != g16(a + 4))) {
            q->cand[1].at.sin_family = AF_INET;
            q->cand[1].at.sin_addr.s_addr = htonl(g32(a + 6));
            q->cand[1].at.sin_port = htons(g16(a + 10));
            q->ncand = 2;
        }
        const Peer *old = NULL;
        for (int j = 0; j < g_npeers && !old; j++) if (g_peers[j].ip == q->ip && g_peers[j].secret == q->secret) old = &g_peers[j];
        int same = old && old->ncand == q->ncand;
        for (int c = 0; same && c < q->ncand; c++) same = same_at(&old->cand[c].at, &q->cand[c].at);
        if (same) {
            q->state = old->state; q->via = old->via; q->since = old->since; q->last_ack = old->last_ack; q->rtt = old->rtt;
            q->next_hello = old->next_hello; q->acks = old->acks; q->acks_window = old->acks_window;
            memcpy(q->cand, old->cand, sizeof q->cand);
        } else {
            char at[24];
            q->state = PS_PUNCHING;
            q->since = q->next_hello = t;
            if (nl < MAX_PEERS) snprintf(lines[nl++], sizeof lines[0], "%s (10.13.%u.%u) introduced at %s%s: punching", q->name,
                                         q->ip >> 8 & 255, q->ip & 255, at_text(&q->cand[0].at, at), q->ncand > 1 ? " (or its LAN address)" : "");
        }
    }
    memcpy(g_peers, next, sizeof next);
    g_npeers = count;
    g_peers_version = version;
    ReleaseSRWLockExclusive(&g_peers_lock);
    for (int i = 0; i < nl; i++) say("%s", lines[i]);
}

static void peers_tick(uint64_t t) {
    static uint64_t last_report;
    char lines[2 * MAX_PEERS][160];
    int nl = 0;
    AcquireSRWLockExclusive(&g_peers_lock);
    for (int i = 0; i < g_npeers; i++) {
        Peer *q = &g_peers[i];
        if (q->state == PS_DIRECT && t - q->last_ack >= FRESH_MS) {
            q->state = PS_RELAYED; q->since = t;
            snprintf(lines[nl++], sizeof lines[0], "direct path to %s went quiet: through the lobby", q->name);
        } else if (q->state == PS_PUNCHING && t - q->since >= PUNCH_FOR_MS) {
            q->state = PS_RELAYED;
            snprintf(lines[nl++], sizeof lines[0], "no direct path to %s (router or firewall): through the lobby", q->name);
        }
        if (t >= q->next_hello) {
            q->next_hello = t + (q->state == PS_PUNCHING ? 200 : q->state == PS_DIRECT || t - q->since < PUNCH_FOR_MS ? 400 : 5000);
            if (q->state == PS_DIRECT) hello(q, q->via, t);
            else for (int c = 0; c < q->ncand; c++) hello(q, c, t);
        }
    }
    if (g_log >= 1 && t - last_report >= 10000 && (g_out_relay || g_out_direct || g_in_relay || g_in_direct)) {
        last_report = t;
        snprintf(lines[nl++], sizeof lines[0], "traffic: out %lld relayed + %lld direct, in %lld relayed + %lld direct; %d peer(s)%s",
                 (long long)g_out_relay, (long long)g_out_direct, (long long)g_in_relay, (long long)g_in_direct, g_npeers,
                 g_npeers ? (fresh(&g_peers[0], t) ? ", first direct" : ", first relayed") : "");
    }
    ReleaseSRWLockExclusive(&g_peers_lock);
    for (int i = 0; i < nl; i++) say("%s", lines[i]);
}

/* (peers lock held) the introduced player whose secret this is, if it came from one of its addresses */
static Peer *peer_at(uint64_t secret, const struct sockaddr_in *from, int *cand) {
    for (int i = 0; i < g_npeers; i++) {
        if (g_peers[i].secret != secret) continue;
        for (int c = 0; c < g_peers[i].ncand; c++) if (same_at(&g_peers[i].cand[c].at, from)) { *cand = c; return &g_peers[i]; }
        return NULL;
    }
    return NULL;
}

static void from_player(const uint8_t *p, int n, const struct sockaddr_in *from) {
    uint64_t t = ms_now();
    int c = 0;
    if (n < 12) return;
    uint64_t secret = g64(p + 4);
    if (p[3] == T_DIRECT && n >= 12 + 12) {
        const uint8_t *b = p + 12;
        uint32_t src = g32(b), dst = g32(b + 4);
        uint16_t sport = g16(b + 8), dport = g16(b + 10);
        int ok;
        AcquireSRWLockShared(&g_peers_lock);
        Peer *q = peer_at(secret, from, &c);
        ok = q && q->ip == src && (dst == g_ip || dst == VNET_BROADCAST || dst == 0xFFFFFFFFu) && sport != VNET_LDN_PORT && dport != VNET_LDN_PORT;
        ReleaseSRWLockShared(&g_peers_lock);
        if (ok && nnldn_has_node(src)) {
            InterlockedIncrement64(&g_in_direct);
            nnldn_deliver(src, sport, dst, dport, b + 12, (uint32_t)(n - 24));
        }
        return;
    }
    if (p[3] != T_PUNCH || n < 29) return;
    uint32_t from_ip = g32(p + 12), to_ip = g32(p + 16);
    int ack = p[20];
    uint64_t word = g64(p + 21);
    char line[160] = "";
    AcquireSRWLockExclusive(&g_peers_lock);
    Peer *q = peer_at(secret, from, &c);
    if (q && q->ip == from_ip && to_ip == g_ip) {
        Cand *k = &q->cand[c];
        if (ack) {
            uint64_t asked = word == k->hello ? k->hello_at : word == k->prev ? k->prev_at : 0;
            if (word && asked && t - asked < 2000) {
                if (word == k->hello) k->hello = 0; else k->prev = 0;
                q->rtt = (int)(t - asked);
                q->last_ack = t;
                if (q->state != PS_DIRECT || (c == 1 && q->via == 0)) {
                    char at[24];
                    q->state = PS_DIRECT;
                    q->via = c;
                    snprintf(line, sizeof line, "%s: direct path via %s %s (%d ms)", q->name, c ? "LAN" : "public", at_text(&k->at, at), q->rtt);
                }
            }
        } else {
            if (t - q->acks_window >= 1000) { q->acks_window = t; q->acks = 0; }
            if (q->acks++ < 10) {
                punch(q, c, 1, word);
                if (q->state != PS_DIRECT) hello(q, c, t);
            }
        }
    }
    ReleaseSRWLockExclusive(&g_peers_lock);
    if (line[0]) say("%s", line);
}

/* ---------------------------------------------------------------- sending */
void net_send(uint32_t src, uint16_t sport, uint32_t dst, uint16_t dport, const void *data, uint32_t len) {
    if (!g_joined || g_sock == INVALID_SOCKET || len > 65000) return;
    enum { HEAD_ROOM = 4 + 1 + 4 * MAX_PEERS };
    uint8_t stack[2048], *buf = HEAD_ROOM + 12 + len <= sizeof stack ? stack : malloc(HEAD_ROOM + 12 + len);
    if (!buf) return;
    uint8_t *body = buf + HEAD_ROOM, *h;
    s32(body, src); s32(body + 4, dst); s16(body + 8, sport); s16(body + 10, dport);
    memcpy(body + 12, data, len);
    int n = 12 + (int)len, bcast = dst == VNET_BROADCAST || dst == 0xFFFFFFFFu, nd = 0;
    struct { struct sockaddr_in at; uint64_t secret; uint32_t ip; } direct[MAX_PEERS];
    if (sport != VNET_LDN_PORT && dport != VNET_LDN_PORT) {
        uint64_t t = ms_now();
        AcquireSRWLockShared(&g_peers_lock);
        for (int i = 0; i < g_npeers; i++) {
            Peer *q = &g_peers[i];
            if (!bcast && q->ip != dst) continue;
            if (fresh(q, t)) { direct[nd].at = q->cand[q->via].at; direct[nd].secret = q->secret; direct[nd++].ip = q->ip; }
        }
        ReleaseSRWLockShared(&g_peers_lock);
    }
    for (int i = 0; i < nd; i++) {
        h = body - 12;
        hdr(h, T_DIRECT);
        s64(h + 4, direct[i].secret);
        tx(h, n + 12, &direct[i].at);
        InterlockedIncrement64(&g_out_direct);
    }
    if (!nd || bcast) {                         /* a broadcast also reaches the room's players not reached directly: the lobby sends it on */
        if (nd) {
            h = body - (5 + 4 * nd);
            hdr(h, T_BCAST);
            h[4] = (uint8_t)nd;
            for (int i = 0; i < nd; i++) s32(h + 5 + 4 * i, direct[i].ip);
        } else {
            h = body - 4;
            hdr(h, T_DATA);
        }
        tx(h, (int)(body - h) + n, &g_lobby);
        InterlockedIncrement64(&g_out_relay);
    }
    if (g_log >= 3) printf("[online] send %u bytes 10.13.%u.%u:%u -> %u.%u.%u.%u:%u (%d direct)\n", len, src >> 8 & 255, src & 255, sport,
                           dst >> 24, dst >> 16 & 255, dst >> 8 & 255, dst & 255, dport, nd);
    if (buf != stack) free(buf);
}

void net_list_rooms(uint32_t seq) {
    if (!g_joined) return;
    uint8_t p[16];
    hdr(p, T_LIST);
    s64(p + 4, g_cookie);
    s32(p + 12, seq);
    tx(p, sizeof p, &g_lobby);
}

/* ---------------------------------------------------------------- the client thread */
static uint32_t outbound_ip(void) {                 /* the address this PC goes out on (no packet is sent) */
    SOCKET s = socket(AF_INET, SOCK_DGRAM, 0);
    struct sockaddr_in a = {0};
    int len = sizeof a;
    uint32_t ip = 0;
    a.sin_family = AF_INET;
    a.sin_port = htons(53);
    inet_pton(AF_INET, "192.0.2.1", &a.sin_addr);  /* (TEST-NET-1: only the route is looked up) */
    if (s != INVALID_SOCKET && !connect(s, (struct sockaddr *)&a, sizeof a) && !getsockname(s, (struct sockaddr *)&a, &len)) ip = ntohl(a.sin_addr.s_addr);
    if (s != INVALID_SOCKET) closesocket(s);
    return ip;
}

static int lookup(const char *text, uint16_t default_port, struct sockaddr_in *out) {     /* "host[:port]" */
    char host[256];
    snprintf(host, sizeof host, "%s", text);
    uint16_t port = default_port;
    char *colon = strrchr(host, ':');
    if (colon) { *colon = 0; if (atoi(colon + 1) > 0) port = (uint16_t)atoi(colon + 1); }
    struct addrinfo hints = {0}, *res = NULL;
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_DGRAM;
    if (getaddrinfo(host, NULL, &hints, &res) || !res) return 0;
    *out = *(struct sockaddr_in *)res->ai_addr;
    out->sin_port = htons(port);
    freeaddrinfo(res);
    return 1;
}
static void bind_client(int loopback_only) {    /* (client thread) binds g_sock; loopback_only: the lobby is on this PC */
    g_loopback = loopback_only;
    struct sockaddr_in a = {0};
    a.sin_family = AF_INET;
    a.sin_port = htons(g_local_port);
    a.sin_addr.s_addr = loopback_only ? htonl(INADDR_LOOPBACK) : INADDR_ANY;
    if (bind(g_sock, (struct sockaddr *)&a, sizeof a)) say("cannot bind UDP port %u (error %d)", g_local_port, WSAGetLastError());
    int len = sizeof a;
    if (!getsockname(g_sock, (struct sockaddr *)&a, &len)) g_lan_port = ntohs(a.sin_port);
    g_lan_ip = loopback_only ? INADDR_LOOPBACK : outbound_ip();
}
static int resolve(void) {
    if (!lookup(g_server, VNET_DEFAULT_PORT, &g_lobby)) return 0;
    bind_client((ntohl(g_lobby.sin_addr.s_addr) >> 24) == 127);      /* (lobby on this PC: loopback only) */
    return 1;
}

/* ---------------------------------------------------------------- no server: room codes, STUN, the in-game lobby */
#include "net_minilobby.c"                      /* the lobby of tools_net/ssbu_lobby.py in C: runs inside the host's game */
#include "net_upnp.c"                           /* UPnP-IGD port mapping (HOST mode, online_upnp) */

/* A room code is an IPv4 address and a UDP port (6 bytes) in Crockford base32: 10 characters, shown as XXXXX-XXXXX.
 * Reading it ignores '-', spaces and case; O reads as 0, I and L as 1. "a.b.c.d:port" is accepted as well. */
static const char B32[] = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
static void code_of(uint32_t ip, uint16_t port, char *out) {   /* out: 12 bytes */
    uint64_t v = (uint64_t)ip << 16 | port;
    char t[10];
    for (int i = 9; i >= 0; i--) { t[i] = B32[v & 31]; v >>= 5; }
    memcpy(out, t, 5); out[5] = '-'; memcpy(out + 6, t + 5, 5); out[11] = 0;
}
static int code_read(const char *s, struct sockaddr_in *out) {
    if (strchr(s, '.')) return lookup(s, VNET_DEFAULT_PORT, out);
    uint64_t v = 0;
    int n = 0;
    for (; *s; s++) {
        int c = toupper((unsigned char)*s), d;
        if (c == '-' || c == ' ') continue;
        if (c == 'O') c = '0'; else if (c == 'I' || c == 'L') c = '1';
        const char *k = strchr(B32, c);
        if (!k || !c) return 0;
        d = (int)(k - B32);
        v = v << 5 | (uint64_t)d;
        n++;
    }
    if (n != 10 || !(v & 0xffff)) return 0;
    memset(out, 0, sizeof *out);
    out->sin_family = AF_INET;
    out->sin_addr.s_addr = htonl((uint32_t)(v >> 16));
    out->sin_port = htons((uint16_t)v);
    return 1;
}
static char g_room_code[64];
const char *net_room_code(void) { return g_room_code; }
int net_mode(void) { configure(); return g_mode; }

/* STUN (RFC 5389) Binding request from socket s: the public address the router gives that socket's port. 0 = no answer. */
static int stun_query(SOCKET s, uint32_t *ip, uint16_t *port) {
    struct sockaddr_in srv;
    if (!g_stun[0] || !lookup(g_stun, 3478, &srv)) return 0;
    uint8_t q[20] = {0, 1, 0, 0, 0x21, 0x12, 0xa4, 0x42}, r[512];
    for (int i = 8; i < 20; i++) q[i] = (uint8_t)rnd64();
    for (int tries = 0; tries < 3; tries++) {
        sendto(s, (const char *)q, sizeof q, 0, (struct sockaddr *)&srv, sizeof srv);
        uint64_t until = ms_now() + 700;
        while (ms_now() < until) {
            struct sockaddr_in from; int fl = sizeof from;
            int n = recvfrom(s, (char *)r, sizeof r, 0, (struct sockaddr *)&from, &fl);
            if (n < 20 || r[0] != 1 || r[1] != 1 || memcmp(r + 4, q + 4, 16)) continue;
            for (int o = 20; o + 4 <= n;) {                 /* attributes: 0x20 XOR-MAPPED-ADDRESS, 0x01 MAPPED-ADDRESS */
                int type = g16(r + o), len = g16(r + o + 2);
                if (o + 4 + len > n) break;
                if ((type == 0x20 || type == 0x01) && len >= 8 && r[o + 5] == 1) {
                    *port = g16(r + o + 6); *ip = g32(r + o + 8);
                    if (type == 0x20) { *port ^= 0x2112; *ip ^= 0x2112a442u; }
                    return 1;
                }
                o += 4 + ((len + 3) & ~3);
            }
        }
    }
    return 0;
}
static SOCKET udp_socket(uint32_t ip, uint16_t port, int timeout_ms) {
    SOCKET s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (s == INVALID_SOCKET) return s;
    struct sockaddr_in a = {0};
    a.sin_family = AF_INET; a.sin_addr.s_addr = htonl(ip); a.sin_port = htons(port);
    DWORD to = (DWORD)timeout_ms, bytes = 0; BOOL off = FALSE;
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (const char *)&to, sizeof to);
    WSAIoctl(s, SIO_UDP_CONNRESET, &off, sizeof off, NULL, 0, &bytes, NULL, NULL);
    if (bind(s, (struct sockaddr *)&a, sizeof a)) { closesocket(s); return INVALID_SOCKET; }
    return s;
}
static const char *ip_text(uint32_t ip, char *b) { snprintf(b, 16, "%u.%u.%u.%u", ip >> 24, ip >> 16 & 255, ip >> 8 & 255, ip & 255); return b; }

static uint16_t g_upnp_mapped;
static void upnp_cleanup(void) { if (g_upnp_mapped) upnp_unmap_udp(g_upnp_mapped); }
static int start_host(void) {                   /* HOST mode: the lobby in this game, its code, the NAT opened if we can */
    uint16_t port = g_host_port;
    uint32_t lan = outbound_ip(), pub = 0;
    uint16_t pub_port = 0;
    char a[16], b[16], why[128] = "", ext[32] = "";
    SOCKET probe = udp_socket(0, port, 300);                  /* STUN from the lobby's own port, before the lobby takes it */
    if (probe == INVALID_SOCKET) { say("host: UDP port %u is in use: set another with online_port", port); return 0; }
    int stun_ok = stun_query(probe, &pub, &pub_port);
    closesocket(probe);
    if (!minilobby_start(0, port, 1)) { say("host: cannot start the lobby on UDP port %u", port); return 0; }
    int mapped = 0;
    if (g_upnp && lan) {
        mapped = upnp_map_udp(port, lan, "SSBU online room", ext, sizeof ext, why, sizeof why);
        if (mapped) { g_upnp_mapped = port; atexit(upnp_cleanup); say("host: UPnP: the router forwards UDP port %u to this PC%s%s", port, ext[0] ? ", public address " : "", ext); }
        else say("host: UPnP: %s", why);
        if (mapped && !pub && ext[0] && strcmp(ext, "0.0.0.0")) { struct in_addr x; if (inet_pton(AF_INET, ext, &x) == 1) { pub = ntohl(x.s_addr); pub_port = port; } }
    }
    if (stun_ok) say("host: STUN %s: public address %s:%u", g_stun, ip_text(pub, a), pub_port);
    else if (g_stun[0]) say("host: STUN %s: no answer", g_stun);
    char code[16], lan_code[16];
    code_of(lan ? lan : 0x7f000001u, port, lan_code);
    if (pub) {
        code_of(pub, mapped ? port : pub_port, code);
        snprintf(g_room_code, sizeof g_room_code, "%s", code);
        say("host: ROOM CODE %s (internet, %s:%u); on the same network: %s (%s:%u)", code, ip_text(pub, a), mapped ? port : pub_port, lan_code, ip_text(lan, b), port);
        if (!mapped && pub != lan)
            say("host: no port mapping: if the other player cannot join, forward UDP port %u to %s on the router, or set online_peer = <the joiner's code>, or use lobby mode", port, ip_text(lan, b));
    } else {
        snprintf(g_room_code, sizeof g_room_code, "%s", lan_code);
        say("host: ROOM CODE %s (this network only, %s:%u: the public address is not known)", lan_code, ip_text(lan ? lan : 0x7f000001u, b), port);
    }
    for (char *s = g_peer; *s;) {                             /* online_peer = code[,code...]: open our NAT towards them */
        char one[64]; size_t k = strcspn(s, ", ;");
        snprintf(one, sizeof one, "%.*s", (int)k, s);
        struct sockaddr_in at;
        if (one[0] && code_read(one, &at)) { minilobby_open_to(&at); say("host: sending NAT-opening datagrams to the joiner %s", one); }
        s += k; while (*s == ',' || *s == ' ' || *s == ';') s++;
    }
    g_lobby.sin_family = AF_INET; g_lobby.sin_addr.s_addr = htonl(INADDR_LOOPBACK); g_lobby.sin_port = htons(port);
    bind_client(1);
    return 1;
}

/* LAN mode: beacon "SU" 1 15: lobby id u64, lobby port u16, code[32], build[40] (multicast + broadcast, every second). */
#define T_BEACON 15
#define BEACON_GROUP "239.255.13.13"
static volatile LONG64 g_lan_lobby_id;          /* our own in-game lobby (0: none) */
static uint16_t g_lan_lobby_port;
static struct { SRWLOCK lock; struct sockaddr_in at; uint64_t id; int pending; } g_switch = {SRWLOCK_INIT};
static SOCKET g_beacon = INVALID_SOCKET;
static SOCKET beacon_socket(void) {
    SOCKET s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (s == INVALID_SOCKET) return s;
    BOOL yes = TRUE; DWORD to = 200, bytes = 0, off = FALSE; int ttl = 1;
    setsockopt(s, SOL_SOCKET, SO_REUSEADDR, (const char *)&yes, sizeof yes);
    setsockopt(s, SOL_SOCKET, SO_BROADCAST, (const char *)&yes, sizeof yes);
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (const char *)&to, sizeof to);
    WSAIoctl(s, SIO_UDP_CONNRESET, &off, sizeof off, NULL, 0, &bytes, NULL, NULL);
    struct sockaddr_in a = {0};
    a.sin_family = AF_INET; a.sin_port = htons(VNET_BEACON_PORT); a.sin_addr.s_addr = INADDR_ANY;
    if (bind(s, (struct sockaddr *)&a, sizeof a)) { closesocket(s); return INVALID_SOCKET; }
    struct ip_mreq m = {0};
    inet_pton(AF_INET, BEACON_GROUP, &m.imr_multiaddr);
    m.imr_interface.s_addr = INADDR_ANY;
    setsockopt(s, IPPROTO_IP, IP_ADD_MEMBERSHIP, (const char *)&m, sizeof m);
    setsockopt(s, IPPROTO_IP, IP_MULTICAST_TTL, (const char *)&ttl, sizeof ttl);
    yes = TRUE; setsockopt(s, IPPROTO_IP, IP_MULTICAST_LOOP, (const char *)&yes, sizeof yes);
    return s;
}
static int beacon_read(const uint8_t *p, int n, uint64_t *id, uint16_t *port) {   /* 1: a lobby of our code and build */
    if (n < 4 + 8 + 2 + NAME_LEN + BUILD_LEN || p[0] != 'S' || p[1] != 'U' || p[2] != PROTO || p[3] != T_BEACON) return 0;
    char code[NAME_LEN + 1] = "", build[BUILD_LEN + 1] = "";
    memcpy(code, p + 14, NAME_LEN); memcpy(build, p + 14 + NAME_LEN, BUILD_LEN);
    if (strcmp(code, g_code) || strcmp(build, g_build)) return 0;
    *id = g64(p + 4); *port = g16(p + 12);
    return *id != 0 && *port != 0;
}
static DWORD WINAPI beacon_thread(LPVOID unused) {    /* sends our lobby's beacon; hears the others' (one lobby per network) */
    (void)unused;
    uint8_t p[4 + 8 + 2 + NAME_LEN + BUILD_LEN] = {0}, r[256];
    struct sockaddr_in grp = {0}, bc = {0};
    grp.sin_family = bc.sin_family = AF_INET;
    grp.sin_port = bc.sin_port = htons(VNET_BEACON_PORT);
    inet_pton(AF_INET, BEACON_GROUP, &grp.sin_addr);
    bc.sin_addr.s_addr = INADDR_BROADCAST;
    uint64_t last = 0;
    for (;;) {
        uint64_t t = ms_now(), mine = (uint64_t)g_lan_lobby_id;
        if (mine && t - last >= 1000) {
            hdr(p, T_BEACON); s64(p + 4, mine); s16(p + 12, g_lan_lobby_port);
            memcpy(p + 14, g_code, strlen(g_code)); memcpy(p + 14 + NAME_LEN, g_build, strlen(g_build));
            sendto(g_beacon, (const char *)p, sizeof p, 0, (struct sockaddr *)&grp, sizeof grp);
            sendto(g_beacon, (const char *)p, sizeof p, 0, (struct sockaddr *)&bc, sizeof bc);
            last = t;
        }
        struct sockaddr_in from; int fl = sizeof from; uint64_t id; uint16_t port;
        int n = recvfrom(g_beacon, (char *)r, sizeof r, 0, (struct sockaddr *)&from, &fl);
        if (n <= 0 || !beacon_read(r, n, &id, &port) || id == mine) continue;
        /* another lobby on this network: the one with the smaller id stays; ours goes if nobody but us is in it and we are
         * in no Local Wireless room (otherwise both stay: their rooms are listed by each lobby to its own players) */
        int players = 0, rooms = 0;
        if (mine) minilobby_counts(&players, &rooms);
        if (mine && (id > mine || players > 1 || nnldn_players())) continue;
        AcquireSRWLockExclusive(&g_switch.lock);
        if (g_switch.id != id) { g_switch.at = from; g_switch.at.sin_port = htons(port); g_switch.id = id; g_switch.pending = 1; }
        ReleaseSRWLockExclusive(&g_switch.lock);
    }
}
static int lan_become_lobby(void) {             /* (client thread) this game runs the network's lobby and announces it */
    uint16_t port = minilobby_start(0, 0, 1);
    if (!port) { say("lan: cannot start a lobby"); return 0; }
    g_lan_lobby_port = port;
    InterlockedExchange64(&g_lan_lobby_id, (LONG64)(rnd64() >> 1 | 1));
    g_lobby.sin_family = AF_INET; g_lobby.sin_addr.s_addr = htonl(INADDR_LOOPBACK); g_lobby.sin_port = htons(port);
    say("lan: no lobby on this network: this game is the lobby (UDP port %u, beacon on port %u)", port, VNET_BEACON_PORT);
    return 1;
}
static int start_lan(void) {                    /* LAN mode: find the network's lobby for 1.5 s; none -> run it here */
    char a[16];
    g_beacon = beacon_socket();
    if (g_beacon == INVALID_SOCKET) { say("lan: cannot open the beacon port %u", VNET_BEACON_PORT); return 0; }
    HANDLE th = CreateThread(NULL, 0, beacon_thread, NULL, 0, NULL);
    if (th) { SetThreadDescription(th, L"online lan beacon"); CloseHandle(th); }
    Sleep(1500 + (DWORD)(rnd64() % 500));
    AcquireSRWLockExclusive(&g_switch.lock);
    int found = g_switch.pending;
    if (found) { g_lobby = g_switch.at; g_switch.pending = 0; }
    ReleaseSRWLockExclusive(&g_switch.lock);
    if (found) { bind_client(0); say("lan: found the lobby of this network at %s:%u", ip_text(ntohl(g_lobby.sin_addr.s_addr), a), ntohs(g_lobby.sin_port)); return 1; }
    bind_client(0);
    return lan_become_lobby();
}
static void lan_switch_if_asked(void) {         /* (client thread) another network lobby won: join it */
    if (g_mode != NET_MODE_LAN) return;
    AcquireSRWLockExclusive(&g_switch.lock);
    int go = g_switch.pending;
    struct sockaddr_in at = g_switch.at;
    g_switch.pending = 0;
    ReleaseSRWLockExclusive(&g_switch.lock);
    if (!go || same_at(&at, &g_lobby)) return;
    char a[16];
    if (g_lan_lobby_id) { InterlockedExchange64(&g_lan_lobby_id, 0); minilobby_stop(); }
    InterlockedExchange(&g_joined, 0);
    g_lobby = at;
    g_unjoined_since = ms_now();
    say("lan: another lobby on this network (%s:%u): joining it", ip_text(ntohl(at.sin_addr.s_addr), a), ntohs(at.sin_port));
}
static void lobby_fallback_to_lan(void) {       /* (client thread) auto mode, the lobby server does not answer */
    say("no answer from the lobby %s: looking for players on this network instead (LAN mode)", g_server);
    SOCKET s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (s == INVALID_SOCKET) return;
    DWORD timeout = 50, bytes = 0; BOOL off = FALSE;
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (const char *)&timeout, sizeof timeout);
    WSAIoctl(s, SIO_UDP_CONNRESET, &off, sizeof off, NULL, 0, &bytes, NULL, NULL);
    SOCKET old = g_sock;
    g_sock = s;                                 /* (net_send sends nothing until joined) */
    closesocket(old);
    g_mode = NET_MODE_LAN;
    if (!start_lan()) say("lan: online play unavailable");
    g_unjoined_since = ms_now();
}
static int setup(void) {                        /* (client thread) where the lobby is, for this mode */
    char a[16];
    switch (g_mode) {
    case NET_MODE_HOST: return start_host();
    case NET_MODE_LAN: return start_lan();
    case NET_MODE_JOIN:
        if (!code_read(g_join, &g_lobby)) { snprintf(g_reject, sizeof g_reject, "not a room code: %s", g_join); say("%s", g_reject); return 0; }
        bind_client((ntohl(g_lobby.sin_addr.s_addr) >> 24) == 127);
        say("join: the host's game at %s:%u (room code %s)", ip_text(ntohl(g_lobby.sin_addr.s_addr), a), ntohs(g_lobby.sin_port), g_join);
        if (!g_loopback) {                       /* our own code: the host can open its NAT towards it (online_peer) */
            uint32_t pub; uint16_t pp;
            if (stun_query(g_sock, &pub, &pp)) { code_of(pub, pp, g_room_code); say("join: your code (only needed if the host's router blocks you: the host sets online_peer = %s)", g_room_code); }
        }
        return 1;
    default:
        if (resolve()) return 1;
        snprintf(g_reject, sizeof g_reject, "cannot find the lobby %s", g_server);
        return 0;
    }
}

static void send_join(void) {
    uint8_t p[4 + 8 + 2 * NAME_LEN + BUILD_LEN + 4 + 2 + 1] = {0};
    hdr(p, T_JOIN);
    s64(p + 4, g_nonce);
    memcpy(p + 12, g_code, strlen(g_code));
    memcpy(p + 12 + NAME_LEN, g_name, strlen(g_name));
    memcpy(p + 12 + 2 * NAME_LEN, g_build, strlen(g_build));
    s32(p + 12 + 2 * NAME_LEN + BUILD_LEN, g_lan_ip);
    s16(p + 16 + 2 * NAME_LEN + BUILD_LEN, g_lan_port);
    p[18 + 2 * NAME_LEN + BUILD_LEN] = (uint8_t)g_direct;
    tx(p, sizeof p, &g_lobby);
}

static DWORD WINAPI client_thread(LPVOID unused) {
    (void)unused;
    static uint8_t buf[65536];
    while (!setup()) {
        if (g_mode == NET_MODE_LOBBY && g_auto && ms_now() - g_unjoined_since > GONE_AFTER_MS) { lobby_fallback_to_lan(); break; }
        Sleep(3000);
    }
    g_reject[0] = 0;
    { char a[16]; say("UDP port %u, lobby %s:%u", g_lan_port, ip_text(ntohl(g_lobby.sin_addr.s_addr), a), ntohs(g_lobby.sin_port)); }
    uint64_t last_join = 0, last_ping = 0, last_tick = 0, said_blocked = 0;
    for (;;) {
        uint64_t t = ms_now();
        lan_switch_if_asked();
        if (!g_joined && g_auto && g_mode == NET_MODE_LOBBY && t - g_unjoined_since > GONE_AFTER_MS) lobby_fallback_to_lan();
        if (!g_joined && g_mode == NET_MODE_JOIN && !said_blocked && t - g_unjoined_since > LOBBY_TIMEOUT_MS) {
            said_blocked = 1;
            say("join: no answer from the host's game: its router or firewall blocks it. The host can forward its UDP port, turn on online_upnp, "
                "or set online_peer = %s; otherwise use lobby mode", g_room_code[0] ? g_room_code : "<your code>");
            snprintf(g_reject, sizeof g_reject, "no answer from the host (router?)");
        }
        if (!g_joined && t - last_join >= 500) { send_join(); last_join = t; }
        if (g_joined && t - last_ping >= 1000) {
            uint8_t p[4 + 8 + 8 + 1];
            int nd = 0;
            hdr(p, T_PING);
            s64(p + 4, g_cookie);
            s64(p + 12, t);
            AcquireSRWLockShared(&g_peers_lock);
            for (int i = 0; i < g_npeers; i++) nd += fresh(&g_peers[i], t);
            ReleaseSRWLockShared(&g_peers_lock);
            p[20] = (uint8_t)nd;
            tx(p, sizeof p, &g_lobby);
            last_ping = t;
        }
        if (g_joined && t - g_last_pong > LOBBY_TIMEOUT_MS) {
            g_unjoined_since = t;
            InterlockedExchange(&g_joined, 0);
            InterlockedExchange(&g_ping, -1);
            AcquireSRWLockExclusive(&g_peers_lock); g_npeers = 0; g_peers_version = 0; ReleaseSRWLockExclusive(&g_peers_lock);
            if (g_mode == NET_MODE_LAN && !g_lan_lobby_id) lan_become_lobby();          /* the network's lobby went away: be it */
            else say("lost the lobby %s: joining again", g_server);
        }
        if (g_joined && t - last_tick >= 50) { peers_tick(t); last_tick = t; }
        struct sockaddr_in from;
        int flen = sizeof from;
        int n = recvfrom(g_sock, (char *)buf, sizeof buf, 0, (struct sockaddr *)&from, &flen);
        if (n < 4 || buf[0] != 'S' || buf[1] != 'U' || buf[2] != PROTO) continue;
        if (!same_at(&from, &g_lobby)) { if (g_joined && g_direct) from_player(buf, n, &from); continue; }
        switch (buf[3]) {
        case T_DATA:
            if (n >= 16 && g_joined) {
                InterlockedIncrement64(&g_in_relay);
                nnldn_deliver(g32(buf + 4), g16(buf + 12), g32(buf + 8), g16(buf + 14), buf + 16, (uint32_t)(n - 16));
            }
            break;
        case T_WELCOME:
            if (n < 24 || g64(buf + 4) != g_nonce) break;
            g_ip = g32(buf + 12);
            g_cookie = g64(buf + 16);
            g_last_pong = ms_now();
            last_ping = 0;
            if (!g_joined) { char a[16]; say("joined the lobby %s:%u as 10.13.%u.%u (code %s)", ip_text(ntohl(g_lobby.sin_addr.s_addr), a), ntohs(g_lobby.sin_port), g_ip >> 8 & 255, g_ip & 255, g_code); }
            InterlockedExchange(&g_joined, 1);
            break;
        case T_REJECT:
            if (n >= 12 && g64(buf + 4) == g_nonce) {
                snprintf(g_reject, sizeof g_reject, "%.64s", (const char *)buf + 12);
                say("the lobby refused: %s", g_reject);
                Sleep(2000);
            }
            break;
        case T_PONG:
            if (n >= 16) {
                g_last_pong = ms_now();
                InterlockedExchange(&g_ping, (LONG)(g_last_pong - g64(buf + 4)));
                InterlockedExchange(&g_players, g16(buf + 12));
                InterlockedExchange(&g_rooms, g16(buf + 14));
            }
            break;
        case T_LISTING:
            if (n >= 12 + NI_SIZE && g_joined) nnldn_listing(g32(buf + 4), g32(buf + 8), buf + 12);
            break;
        case T_LIST_END:
            if (n >= 9 && g_joined) nnldn_list_end(g32(buf + 4));
            break;
        case T_PEERS:
            if (g_joined && g_direct) read_peers(buf + 4, n - 4);
            break;
        }
    }
}

static void leave(void) {
    if (!g_joined) return;
    uint8_t p[12];
    hdr(p, T_LEAVE);
    s64(p + 4, g_cookie);
    tx(p, sizeof p, &g_lobby);
}

void net_start(void) {
    static INIT_ONCE once = INIT_ONCE_STATIC_INIT;
    BOOL pending;
    InitOnceBeginInitialize(&once, 0, &pending, NULL);
    if (!pending) return;
    if (net_online()) {
        WSADATA wsa;
        WSAStartup(MAKEWORD(2, 2), &wsa);
        g_nonce = rnd64();
        g_unjoined_since = ms_now();
        g_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        if (g_sock != INVALID_SOCKET) {
            DWORD timeout = 50, bytes = 0;
            BOOL off = FALSE;
            int big = 1 << 20;
            setsockopt(g_sock, SOL_SOCKET, SO_RCVTIMEO, (const char *)&timeout, sizeof timeout);
            setsockopt(g_sock, SOL_SOCKET, SO_RCVBUF, (const char *)&big, sizeof big);
            WSAIoctl(g_sock, SIO_UDP_CONNRESET, &off, sizeof off, NULL, 0, &bytes, NULL, NULL);   /* (no ICMP errors on receive) */
            HANDLE th = CreateThread(NULL, 0, client_thread, NULL, 0, NULL);
            if (th) { SetThreadDescription(th, L"online lobby client"); CloseHandle(th); }
            atexit(leave);
        } else say("no UDP socket (error %d): online play unavailable", WSAGetLastError());
    }
    InitOnceComplete(&once, 0, NULL);
}

/* net_stats.h: the F2 overlay's online fields, read once per drawn frame on the render thread; never blocks.
 *   state    NET_OFFLINE (online play off), NET_CONNECTING (asked for, no lobby answer yet), NET_CONNECTED (joined the
 *            lobby), NET_DISCONNECTED (no answer from the lobby for GONE_AFTER_MS, or refused)
 *   players  in this player's Local Wireless room (this PC included); 1 while in the lobby but in no room
 *   ping_ms  round trip to the other player of the room: the direct path's last hello answer when the path is direct,
 *            otherwise the round trip to the lobby (relayed: the lobby is in between); -1 = unknown
 *   delay, rollback_*  0: the game's own Local Wireless netcode is delay based and is not ours to measure (rollback, N1). */
void net_stats_get(NetStats *o) {
    memset(o, 0, sizeof *o);
    o->ping_ms = -1;
    if (g_cfg <= 0) { o->state = NET_OFFLINE; return; }
    if (!g_joined) { o->state = net_lobby_gone() || g_reject[0] ? NET_DISCONNECTED : NET_CONNECTING; return; }
    o->state = NET_CONNECTED;
    int in_room = nnldn_players();
    o->players = in_room ? in_room : 1;
    o->ping_ms = (int)g_ping;
    if (in_room > 1 && TryAcquireSRWLockShared(&g_peers_lock)) {
        uint64_t t = ms_now();
        for (int i = 0; i < g_npeers; i++) if (fresh(&g_peers[i], t)) { o->ping_ms = g_peers[i].rtt; break; }
        ReleaseSRWLockShared(&g_peers_lock);
    }
}

void net_status(char *out, size_t n) {
    if (!net_online()) { if (n) out[0] = 0; return; }
    if (!g_joined) { snprintf(out, n, "online: %s", g_reject[0] ? g_reject : "connecting to the lobby"); return; }
    static const char *m[] = {"lobby", "LAN", "host", "join"};
    snprintf(out, n, "online (%s): %ld players, %ld rooms, 10.13.%u.%u, ping %ld ms%s%s", m[g_mode], (long)g_players, (long)g_rooms, g_ip >> 8 & 255, g_ip & 255,
             (long)g_ping, g_mode == NET_MODE_HOST && g_room_code[0] ? ", room code " : "", g_mode == NET_MODE_HOST ? g_room_code : "");
}
