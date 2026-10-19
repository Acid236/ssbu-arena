/* U1: what the stats overlay of the settings menu shows about online play (menu.cpp, F2; plan\phases\U1_settings_menu.md).
 *
 * The overlay calls net_stats_get() once per drawn frame on the render thread. menu.cpp has a default that answers
 * "Offline" (net_stats_get_default, bound with /alternatename): the online code defines net_stats_get() itself and
 * the linker takes that one instead, with no change here. It must be cheap and must not block (read a few ints).
 *
 * Who fills which field:
 *   state, players, ping_ms       the online layer (nnldn.c / net_relay.c, track N3): connection state, players in the
 *                                 session (this PC included), round-trip time to the other side in ms (-1 = unknown)
 *   delay                         the rollback code (rb_*.c, track N1/R2): input delay in frames used now
 *   rollback_last, rollback_max   the rollback code: frames rolled back at the last rollback, the most this session
 * Run-ahead is not here: the overlay reads it itself (graphics.ini runahead / SSBU_RUNAHEAD, r1_state.c r1_ra_phase). */
#ifndef NET_STATS_H
#define NET_STATS_H
#ifdef __cplusplus
extern "C" {
#endif
enum { NET_OFFLINE = 0, NET_CONNECTING = 1, NET_CONNECTED = 2, NET_DISCONNECTED = 3 };
typedef struct { int state; int players; int ping_ms; int delay; int rollback_last, rollback_max; } NetStats;
void net_stats_get(NetStats *out);          /* fills every field; the default: state NET_OFFLINE, ping -1, the rest 0 */
#ifdef __cplusplus
}
#endif
#endif
