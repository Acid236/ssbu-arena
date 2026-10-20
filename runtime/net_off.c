/* Online play is not in the Linux build yet (net_relay.c uses Winsock extensions and COM UPnP; tools/lifter/build.py
 * leaves it out there). These are the net_relay.h functions nnldn.c calls, answering as with SSBU_ONLINE unset:
 * net_online() is 0, so nnldn_register() registers nothing and the game's Local Wireless stays the offline console's. */
#include <stdint.h>
#include "net_relay.h"

int net_online(void) { return 0; }
int net_mode(void) { return 0; }
int net_log_level(void) { return 0; }
void net_start(void) {}
uint32_t net_my_ip(void) { return 0; }
int net_lobby_gone(void) { return 0; }
void net_list_rooms(uint32_t seq) { (void)seq; }
void net_send(uint32_t src, uint16_t sport, uint32_t dst, uint16_t dport, const void *data, uint32_t len) {
    (void)src; (void)sport; (void)dst; (void)dport; (void)data; (void)len;
}
int net_room_refusal(uint32_t host, char *why, size_t n) { (void)host; (void)why; (void)n; return 0; }
