/* Online play over the game's own Local Wireless mode (plan\phases\N3_local_wireless_online.md).
 * Design adapted from SNO2207/WindowSmash (runtime/net.h, net_relay.c, hle_net.c), used with the author's permission;
 * this is our own implementation and our own wire protocol (not compatible with theirs).
 *
 * Every player's game gets an address in a virtual network 10.13.0.0/16 from our lobby (tools_net\ssbu_lobby.py).
 * nnldn.c answers nn::ldn (Local Wireless) and nn::socket on that virtual network; every datagram, broadcasts included,
 * goes through this file: to the lobby, which relays it to the players of the same Local Wireless room, or straight to
 * the other player once the lobby has introduced the two and a UDP hole punch has worked.
 *
 * OFF unless asked for: SSBU_ONLINE=1 (or SSBU_ONLINE=<host:port>, or "online_server = <host:port>" in graphics.ini).
 * Nothing of this file runs, no socket is opened and no import is replaced while it is off. */
#ifndef NET_RELAY_H
#define NET_RELAY_H
#include <stdint.h>
#include <stddef.h>

#define VNET_SUBNET    0x0A0D0000u      /* 10.13.0.0 */
#define VNET_MASK      0xFFFF0000u
#define VNET_GATEWAY   0x0A0D0001u      /* 10.13.0.1: the lobby's own address on the virtual network */
#define VNET_BROADCAST 0x0A0DFFFFu
#define VNET_LDN_PORT  65511            /* nnldn.c's own messages (rooms, joins): always through the lobby */
#define VNET_DEFAULT_PORT 39500

enum { NET_MODE_LOBBY, NET_MODE_LAN, NET_MODE_HOST, NET_MODE_JOIN };
#define VNET_BEACON_PORT 39501          /* LAN mode: the in-game lobby's beacon (multicast 239.255.13.13 and broadcast) */
int net_online(void);                   /* asked for (config read on the first call) */
int net_mode(void);                     /* NET_MODE_* (valid when net_online()) */
const char *net_room_code(void);        /* HOST mode: the room code to give the other player ("" until known); JOIN mode: this
                                           player's own code (for online_peer on the host when its router blocks) */
int net_log_level(void);                /* SSBU_ONLINE_LOG: 0 quiet .. 3 every datagram */
void net_start(void);                   /* opens the socket, starts the client thread (idempotent) */
uint32_t net_my_ip(void);               /* this player's virtual address (host order), 0 until the lobby answered */
int net_lobby_gone(void);               /* asked for, but no answer for a while */
void net_list_rooms(uint32_t seq);      /* asks the lobby for the rooms; answers come as nnldn_listing / nnldn_list_end */
/* One datagram from this player's game (dst may be VNET_BROADCAST). */
void net_send(uint32_t src, uint16_t sport, uint32_t dst, uint16_t dport, const void *data, uint32_t len);
void net_status(char *out, size_t n);   /* one line for logs */
const char *net_lan_code(void);         /* HOST mode: the code for players on the same network ("" until known) */
const char *net_upnp_result(void);      /* HOST mode: what UPnP did, one line ("" until tried) */
/* O1: nnldn.c join(): 1 = the room of host is of another build (version or mod set): why = the cause; the popup is shown */
int net_room_refusal(uint32_t host, char *why, size_t n);
/* O2: nnldn.c scan(): the matched host's address while this game is matched to join its room (0: none) */
uint32_t net_match_host(void);

/* nnldn.c, called by the client thread */
void nnldn_deliver(uint32_t src, uint16_t sport, uint32_t dst, uint16_t dport, const void *data, uint32_t len);
void nnldn_listing(uint32_t seq, uint32_t owner, const uint8_t *info);
void nnldn_list_end(uint32_t seq);
int nnldn_has_node(uint32_t ip);        /* ip is a node of the network this player is in now */
int nnldn_players(void);                /* players in this player's room (itself included), 0 = in no room; never blocks */
/* net_stats_get (net_stats.h, the F2 overlay) is defined in net_relay.c */

void nnldn_register(void);              /* nnnet.c: last registration step; does nothing while online play is off */
#endif
