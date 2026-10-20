#!/usr/bin/env python3
"""Online lobby for the SSBU native port: the game's own Local Wireless mode carried over the internet.

Every player's game (SSBU_ONLINE=<this host>:<port>, see recomp-study/net_relay.c) joins this lobby at start and gets an
address of a virtual network 10.13.0.0/16. A room a player creates in Local Wireless is listed to every other player
with the same game build and lobby code, who joins it from the game's own Rooms List. The lobby relays each room's
datagrams between that room's players only, and introduces the players of a room to each other so that their games
can send to each other directly (UDP hole punching); the relay is the fallback.

Design adapted from SNO2207/WindowSmash (tools/ssbu_relay.py), used with the author's permission. Our own code and our
own wire protocol ("SU" version 1, described at the top of recomp-study/net_relay.c); not compatible with theirs.

    python ssbu_lobby.py [--bind 127.0.0.1] [--port 39500] [--verbose] [--status-port 8080 [--status-bind 127.0.0.1]]

--status-port starts a small HTTP endpoint, GET /status, that answers with counts only (players, rooms, version,
uptime_s, up) and Access-Control-Allow-Origin: * so a web page (the project site) can show the lobby's state. It never
returns addresses, names or codes. It listens on 127.0.0.1 by default, to sit behind a TLS reverse proxy (Caddy, see
deploy_lobby.sh); --status-bind 0.0.0.0 serves it directly over plain HTTP.

Python 3.8+, standard library only. No authentication or encryption yet: run it for people you know."""
import argparse
import json
import os
import secrets
import select
import socket
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROTO = 1
LOBBY_VERSION = "1.1"
(JOIN, WELCOME, REJECT, PING, PONG, DATA, LEAVE, LIST, LISTING, LIST_END,
 PEERS, PUNCH, DIRECT, BCAST) = range(1, 15)
RB = 16          # online rollback messages between two games (recomp-study/net_relay.c T_RB, rb_net.c)
NAME_LEN, BUILD_LEN = 32, 40
JOIN_LEN = 4 + 8 + 2 * NAME_LEN + BUILD_LEN + 4 + 2 + 1
SUBNET, BROADCASTS = 0x0A0D0000, (0x0A0DFFFF, 0xFFFFFFFF)
LDN_PORT = 65511
M_ADVERTISE, M_JOIN, M_ACCEPT, M_REJECT, M_KEEP, M_LEAVE, M_GONE, M_KICK = range(1, 9)
NI_SIZE, NI_SESSION, NI_POLICY, NI_NODE_MAX, NI_NODE_COUNT, NI_NODES, NODE_LEN = 0x480, 0x10, 0x62, 0x66, 0x67, 0x68, 0x40
LIST_MAX = 24
CLIENT_TIMEOUT, ROOM_TIMEOUT, LISTED_FOR = 10.0, 10.0, 4.0
MAX_DATA = 1500


def hdr(kind):
    return b"SU" + bytes((PROTO, kind))


def text(raw):
    return raw.split(b"\0", 1)[0].decode("utf-8", "replace")


def vip_text(ip):
    return "10.13.%d.%d" % (ip >> 8 & 255, ip & 255)


def node_name(info, i):
    o = NI_NODES + NODE_LEN * i + 0xC
    return text(info[o:o + NAME_LEN])


def room_nodes(info, owner):
    """The station addresses of a NetworkInfo whose node 0 is owner, or None if it is not one a game makes."""
    count, most = info[NI_NODE_COUNT], info[NI_NODE_MAX]
    if not 1 <= count <= most <= 8:
        return None
    ips = []
    for i in range(8):
        o = NI_NODES + NODE_LEN * i
        if not info[o + 0xB]:
            if i == 0:
                return None
            continue
        ip = struct.unpack_from("<I", info, o)[0]
        if ip & 0xFFFF0000 != SUBNET or (i == 0 and ip != owner) or ip in ips:
            return None
        ips.append(ip)
    return frozenset(ips[1:])


class Client:
    def __init__(self, at, nonce, ip, name, part, lan, direct, now):
        self.at, self.nonce, self.ip, self.name, self.part = at, nonce, ip, name, part
        self.lan, self.direct = lan, direct
        self.cookie = secrets.randbits(64)
        self.seen = now
        self.room = None          # the Room this player hosts
        self.claim = None         # the session id of the room it asked to join
        self.peers_version = 0
        self.peers_sent = None


class Room:
    def __init__(self, owner, session, now):
        self.owner, self.session, self.created = owner, session, now
        self.info, self.nodes, self.updated = b"", frozenset(), now
        self.secrets = {}         # frozenset({a, b}) -> pair secret

    def is_open(self):
        return self.info[NI_POLICY] != 1 and self.info[NI_NODE_COUNT] < self.info[NI_NODE_MAX]


class Lobby:
    def __init__(self, sock, verbose):
        self.sock, self.verbose = sock, verbose
        self.by_at, self.by_ip, self.rooms = {}, {}, {}
        self.next_ip = SUBNET + 2
        self.stats = {"relayed game datagrams": 0, "ldn messages": 0, "dropped": 0}

    def say(self, *what):
        print(time.strftime("%H:%M:%S"), *what, flush=True)

    def log(self, *what):
        if self.verbose:
            self.say(*what)

    def send(self, data, at):
        try:
            self.sock.sendto(data, at)
        except OSError:
            pass

    # ---- who is where
    def members(self, room):
        out = [room.owner]
        for ip in room.nodes:
            c = self.by_ip.get(ip)
            if c is not None and c.claim == room.session:
                out.append(c)
        return out

    def room_of(self, c):
        if c.room is not None:
            return c.room
        r = self.rooms.get(c.claim) if c.claim else None
        return r if r is not None and c.ip in r.nodes else None

    def new_ip(self):
        for _ in range(0x10000):
            ip = self.next_ip
            self.next_ip = SUBNET + 2 if ip >= SUBNET + 0xFFFE else ip + 1
            if ip & 0xFF not in (0, 255) and ip not in self.by_ip:
                return ip
        return None

    def close_room(self, room, why):
        gone = hdr(DATA) + struct.pack(">IIHH", room.owner.ip, BROADCASTS[0], LDN_PORT, LDN_PORT) + bytes((ord("L"), M_GONE, 0, 0)) + room.session
        for m in self.members(room):
            if m is not room.owner:
                self.send(gone, m.at)
                m.claim = None
                self.send_peers(m)
        self.rooms.pop(room.session, None)
        if room.owner.room is room:
            room.owner.room = None
            self.send_peers(room.owner)
        self.say("room of %s closed (%s)" % (room.owner.name, why))

    def drop(self, c, why):
        if c.room is not None:
            self.close_room(c.room, "host left")
        if c.claim:
            r = self.rooms.get(c.claim)
            if r is not None and c.ip in r.nodes:   # tell its host at once
                self.send(hdr(DATA) + struct.pack(">IIHH", c.ip, r.owner.ip, LDN_PORT, LDN_PORT) + bytes((ord("L"), M_LEAVE, 0, 0)) + r.session, r.owner.at)
        self.by_at.pop(c.at, None)
        self.by_ip.pop(c.ip, None)
        self.say("%s (%s) left: %s" % (c.name, vip_text(c.ip), why))

    # ---- direct paths: each member of a room learns the others' addresses and a pair secret
    def send_peers(self, c):
        room = self.room_of(c)
        entries = []
        if room is not None and c.direct:
            for m in self.members(room):
                if m is c or not m.direct:
                    continue
                pair = frozenset((c.ip, m.ip))
                secret = room.secrets.setdefault(pair, secrets.randbits(64) | 1)
                pub_ip = struct.unpack(">I", socket.inet_aton(m.at[0]))[0]
                entries.append(struct.pack(">I32sIHIHQ", m.ip, m.name.encode()[:NAME_LEN], pub_ip, m.at[1], m.lan[0], m.lan[1], secret))
        body = b"".join(entries)
        if body == c.peers_sent:
            return
        c.peers_sent = body
        c.peers_version += 1
        self.send(hdr(PEERS) + struct.pack(">IB", c.peers_version, len(entries)) + body, c.at)
        if entries:
            self.log("%s introduced to %d player(s) of its room" % (c.name, len(entries)))

    def room_changed(self, room):
        for m in self.members(room):
            self.send_peers(m)

    # ---- packets
    def packet(self, p, at, now):
        if len(p) < 4 or p[:2] != b"SU" or p[2] != PROTO:
            return
        kind = p[3]
        c = self.by_at.get(at)
        if kind == JOIN:
            return self.on_join(p, at, c, now)
        if c is None:
            return
        c.seen = now
        if kind == PING and len(p) >= 21 and struct.unpack_from(">Q", p, 4)[0] == c.cookie:
            same = [x for x in self.by_at.values() if x.part == c.part]
            rooms = [r for r in self.rooms.values() if r.owner.part == c.part]
            self.send(hdr(PONG) + p[12:20] + struct.pack(">HH", len(same), len(rooms)), at)
        elif kind == LEAVE and len(p) >= 12 and struct.unpack_from(">Q", p, 4)[0] == c.cookie:
            self.drop(c, "left")
        elif kind == LIST and len(p) >= 16 and struct.unpack_from(">Q", p, 4)[0] == c.cookie:
            self.on_list(c, p[12:16], now)
        elif kind == RB and 16 < len(p) <= 1500 and struct.unpack_from(">Q", p, 4)[0] == c.cookie:
            # online rollback message: to one player of the same lobby code (destination 0 = all others, only with a private code)
            dst = struct.unpack_from(">I", p, 12)[0]
            if dst == 0 and c.part[1] == "public":
                return
            out = hdr(RB) + struct.pack(">I", c.ip) + p[16:]
            for x in list(self.by_at.values()):
                if x is not c and x.part == c.part and (dst == 0 or x.ip == dst):
                    self.send(out, x.at)
        elif kind == DATA and len(p) >= 16:
            self.on_data(c, p, 4, now, ())
        elif kind == BCAST and len(p) >= 5:
            n = p[4]
            skip = set(struct.unpack_from(">%dI" % n, p, 5)) if len(p) >= 5 + 4 * n else set()
            body = 5 + 4 * n
            if len(p) >= body + 12:
                self.on_data(c, hdr(DATA) + p[body:], 4, now, skip)

    def on_join(self, p, at, c, now):
        if len(p) < JOIN_LEN:
            return
        nonce = p[4:12]
        code, name = text(p[12:44]), text(p[44:76]) or "Player"
        build = p[76:116].rstrip(b"\0")
        lan = struct.unpack_from(">IH", p, 116)
        direct = bool(p[122] & 1)
        part = (build, code)
        if c is not None and c.nonce != nonce:
            self.drop(c, "restarted")
            c = None
        if c is None:
            for other in list(self.by_at.values()):   # the same game from a new port (its router remapped it)?
                if other.nonce == nonce and other.part == part:
                    del self.by_at[other.at]
                    other.at = at
                    self.by_at[at] = c = other
                    break
        if c is None:
            ip = self.new_ip()
            if ip is None:
                self.send(hdr(REJECT) + nonce + b"the lobby is full".ljust(64, b"\0"), at)
                return
            c = Client(at, nonce, ip, name, part, lan, direct, now)
            self.by_at[at], self.by_ip[ip] = c, c
            self.say("%s joined (code %r, build %s) as %s from %s:%d, LAN %s:%d, direct %s" % (
                name, code, build.decode("ascii", "replace"), vip_text(ip), at[0], at[1], socket.inet_ntoa(struct.pack(">I", lan[0])), lan[1],
                "yes" if direct else "no"))
        c.seen, c.lan, c.direct = now, lan, direct
        self.send(hdr(WELCOME) + nonce + struct.pack(">IQ", c.ip, c.cookie), at)

    def on_list(self, c, seq, now):
        rooms = sorted((r for r in self.rooms.values() if r.owner.part == c.part and r.owner is not c and now - r.updated <= LISTED_FOR),
                       key=lambda r: (not r.is_open(), -r.info[NI_NODE_COUNT], r.created))[:LIST_MAX]
        for r in rooms:
            self.send(hdr(LISTING) + seq + struct.pack(">I", r.owner.ip) + r.info, c.at)
        self.send(hdr(LIST_END) + seq + bytes((len(rooms),)), c.at)
        if rooms:
            self.log("%s scanned: %d room(s)" % (c.name, len(rooms)))

    def on_data(self, c, p, off, now, skip):
        if len(p) - off - 12 > MAX_DATA + NI_SIZE:
            self.stats["dropped"] += 1
            return
        src, dst, sport, dport = struct.unpack_from(">IIHH", p, off)
        if src != c.ip:
            self.stats["dropped"] += 1
            return
        if sport == LDN_PORT or dport == LDN_PORT:
            return self.on_ldn(c, p, dst, sport, dport, now)
        room = self.room_of(c)
        if room is None:
            self.stats["dropped"] += 1
            return
        members = self.members(room)
        sent = 0
        for m in members:
            if m is c or m.ip in skip:
                continue
            if dst in BROADCASTS or m.ip == dst:
                self.send(p, m.at)
                sent += 1
        self.stats["relayed game datagrams"] += sent
        if not sent and dst not in BROADCASTS:
            self.stats["dropped"] += 1

    def on_ldn(self, c, p, dst, sport, dport, now):
        if sport != LDN_PORT or dport != LDN_PORT or len(p) < 20 or p[16] != ord("L"):
            self.stats["dropped"] += 1
            return
        self.stats["ldn messages"] += 1
        kind, body = p[17], p[20:]
        if dst in BROADCASTS:
            if kind == M_ADVERTISE and len(body) >= NI_SIZE:
                self.on_advertise(c, p, bytes(body[:NI_SIZE]), now)
            elif kind == M_GONE and c.room is not None and body[:16] == c.room.session:
                self.close_room(c.room, "closed by its host")
            return
        b = self.by_ip.get(dst)
        if b is None or b is c or b.part != c.part:
            self.stats["dropped"] += 1
            return
        if kind == M_JOIN:
            if b.room is None or body[:16] != b.room.session:
                self.stats["dropped"] += 1
                return
            if c.room is not None:
                self.close_room(c.room, "its host joins another room")
            c.claim = b.room.session
            self.say("%s asks to join %s's room" % (c.name, b.name))
        elif kind == M_LEAVE:
            if c.claim and b.room is not None and b.room.session == c.claim:
                c.claim = None
                self.send(p, b.at)
                self.send_peers(c)
                return
        self.send(p, b.at)

    def on_advertise(self, c, p, info, now):
        nodes = room_nodes(info, c.ip)
        if nodes is None:
            self.stats["dropped"] += 1
            return
        session = info[NI_SESSION:NI_SESSION + 16]
        room = self.rooms.get(session)
        if room is not None and room.owner is not c:
            self.stats["dropped"] += 1
            return
        if room is None:
            if c.room is not None:
                self.close_room(c.room, "replaced by a new room")
            c.claim = None
            room = c.room = self.rooms[session] = Room(c, session, now)
            self.say("%s opened a room (%d players at most)" % (c.name, info[NI_NODE_MAX]))
        before = self.members(room)
        changed = nodes != room.nodes
        room.info, room.nodes, room.updated = info, nodes, now
        after = self.members(room)
        if changed:
            names = ", ".join(node_name(info, i) or "?" for i in range(8) if info[NI_NODES + NODE_LEN * i + 0xB])
            self.say("room of %s: %d player(s): %s" % (c.name, info[NI_NODE_COUNT], names))
            self.room_changed(room)
            for m in before:
                if m not in after:
                    self.send_peers(m)
        for m in set(before) | set(after):
            if m is not c:
                self.send(p, m.at)

    def sweep(self, now):
        for c in list(self.by_at.values()):
            if now - c.seen > CLIENT_TIMEOUT:
                self.drop(c, "silent for %d s" % CLIENT_TIMEOUT)
        for r in list(self.rooms.values()):
            if now - r.updated > ROOM_TIMEOUT:
                self.close_room(r, "no advertisement for %d s" % ROOM_TIMEOUT)


def status_json(lobby, started, now):
    """The /status document: counts only. Never addresses, names, lobby codes or builds."""
    return json.dumps({"up": True, "players": len(lobby.by_at), "rooms": len(lobby.rooms),
                       "version": "%s (protocol SU %d)" % (LOBBY_VERSION, PROTO), "uptime_s": int(now - started)})


def start_status_server(lobby, bind, port, started):
    """Serve GET /status on a daemon thread. Returns the server (its .server_address has the real port)."""
    class Handler(BaseHTTPRequestHandler):
        server_version = "ssbu-lobby-status"
        sys_version = ""

        def head(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()

        def do_GET(self):
            if self.path.split("?", 1)[0].rstrip("/") == "/status":
                body = status_json(lobby, started, time.monotonic()).encode()
                self.head(200, body, "application/json")
            else:
                body = b'{"error":"not found"}'
                self.head(404, body, "application/json")
            self.wfile.write(body)

        def do_HEAD(self):
            ok = self.path.split("?", 1)[0].rstrip("/") == "/status"
            self.head(200 if ok else 404, b"", "application/json")

        def do_OPTIONS(self):
            self.head(204, b"", "text/plain")

        def log_message(self, *args):   # no request log: it would hold the callers' addresses
            pass

    srv = ThreadingHTTPServer((bind, port), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, name="status-http", daemon=True).start()
    return srv


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=39500)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--stats", type=float, default=10.0, help="seconds between statistics lines (0: none)")
    ap.add_argument("--status-port", type=int, default=0, help="TCP port of the HTTP status endpoint GET /status (0: off)")
    ap.add_argument("--status-bind", default="127.0.0.1", help="address of the status endpoint (default 127.0.0.1, behind a proxy)")
    o = ap.parse_args()
    started = time.monotonic()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if os.name == "nt":   # (no ICMP "port unreachable" errors on receive)
        try:
            sock.ioctl(socket.SIO_UDP_CONNRESET, False)
        except (AttributeError, OSError):
            pass
    sock.bind((o.bind, o.port))
    lobby = Lobby(sock, o.verbose)
    lobby.say("lobby on UDP %s:%d (protocol SU %d)" % (o.bind, o.port, PROTO))
    if o.status_port:
        srv = start_status_server(lobby, o.status_bind, o.status_port, started)
        lobby.say("status endpoint on http://%s:%d/status" % srv.server_address[:2])
    last_sweep = last_stats = time.monotonic()
    while True:
        r, _, _ = select.select([sock], [], [], 0.5)
        now = time.monotonic()
        if r:
            try:
                p, at = sock.recvfrom(65536)
            except OSError:
                continue
            try:
                lobby.packet(p, at, now)
            except Exception as e:   # one bad packet never stops the lobby
                lobby.say("error on a packet from %s: %r" % (at[0], e))
        if now - last_sweep >= 1.0:
            last_sweep = now
            lobby.sweep(now)
        if o.stats and now - last_stats >= o.stats:
            last_stats = now
            if lobby.by_at:
                lobby.say("stats: %d player(s), %d room(s), %s" % (len(lobby.by_at), len(lobby.rooms),
                                                                   ", ".join("%s %d" % kv for kv in lobby.stats.items())))


if __name__ == "__main__":
    sys.exit(main())
