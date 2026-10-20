#!/usr/bin/env python3
"""Self-test of ssbu_lobby.py without the game: two fake players on 127.0.0.1 (host creates a room, the other lists it,
joins it, both exchange a game datagram through the lobby, both receive PEERS for direct paths), and the HTTP status
endpoint (--status-port: counts only, CORS header, no addresses or names).
O1 room browser: players of two builds (another game version, another mod set) and an older game in one lobby code:
the older game sees only its own build's rooms; LIST flag 1 lists every build with the host's build at the end; ROOMS
names host, players, build and mods; a join across builds never reaches the other host.
    python test_ssbu_lobby.py        (starts the lobby itself on a free port; standard library only)
    LOBBY_EXE=<minilobby.exe> python test_ssbu_lobby.py   (the same against net_minilobby.c built standalone:
        clang -DMINILOBBY_MAIN -x c net_minilobby.c -o minilobby.exe -lws2_32 -ladvapi32; no status endpoint there)"""
import json
import os
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ssbu_lobby as L  # noqa: E402


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def free_tcp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def get_status(port):
    with urllib.request.urlopen("http://127.0.0.1:%d/status" % port, timeout=3) as r:
        return r.status, r.headers, r.read().decode()


class Fake:
    def __init__(self, lobby, name, build=b"build-x", mods=None):
        self.build, self.mods = build, mods
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.bind(("127.0.0.1", 0))
        self.s.settimeout(0.2)
        self.lobby, self.name, self.nonce = lobby, name, os.urandom(8)
        self.got = []

    def tx(self, kind, body):
        self.s.sendto(L.hdr(kind) + body, self.lobby)

    def rx(self, want, secs=2.0):
        end = time.time() + secs
        while time.time() < end:
            for i, (k, b) in enumerate(self.got):
                if k == want:
                    del self.got[i]
                    return b
            try:
                p, _ = self.s.recvfrom(65536)
                self.got.append((p[3], p[4:]))
            except socket.timeout:
                pass
        raise AssertionError("%s: no packet of type %d" % (self.name, want))

    def join(self):
        port = self.s.getsockname()[1]
        self.tx(L.JOIN, self.nonce + b"test".ljust(32, b"\0") + self.name.encode().ljust(32, b"\0") + self.build.ljust(40, b"\0")
                + struct.pack(">IHB", 0x7F000001, port, 1) + (b"MS" + self.mods if self.mods is not None else b""))
        b = self.rx(L.WELCOME)
        assert b[:8] == self.nonce
        self.ip, self.cookie = struct.unpack_from(">IQ", b, 8)
        return self.ip

    def ldn(self, dst, kind, payload):
        self.tx(L.DATA, struct.pack(">IIHH", self.ip, dst, L.LDN_PORT, L.LDN_PORT) + bytes((ord("L"), kind, 0, 0)) + payload)


def network_info(host_ip, session, station_ip=None):
    n = bytearray(L.NI_SIZE)
    n[L.NI_SESSION:L.NI_SESSION + 16] = session
    n[L.NI_NODE_MAX] = 8
    n[L.NI_NODE_COUNT] = 1
    struct.pack_into("<I", n, L.NI_NODES, host_ip)
    n[L.NI_NODES + 0xB] = 1
    n[L.NI_NODES + 0xC:L.NI_NODES + 0xC + 4] = b"Host"
    if station_ip:
        o = L.NI_NODES + L.NODE_LEN
        struct.pack_into("<I", n, o, station_ip)
        n[o + 0xB] = 1
        n[L.NI_NODE_COUNT] = 2
    return bytes(n)


def mods(*entries):
    return bytes((len(entries),)) + b"".join(struct.pack(">IB", h, len(n)) + n for n, h in entries)


def none_of(f, kind, secs=0.6):
    try:
        f.rx(kind, secs)
    except AssertionError:
        return True
    return False


def room_browser(lob):
    """O1: three builds in the lobby code "test"; an older game, two newer ones (another version, another mod set)."""
    v4 = Fake(lob, "V4", b"ssbu-recomp-ldn1-13.0.4", mods())
    v5m = Fake(lob, "V5m", b"ssbu-recomp-ldn1-13.0.5+m1234abcd", mods((b"Alpha", 0x11), (b"Beta", 0x22)))
    old = Fake(lob, "Old", b"ssbu-recomp-ldn1-13.0.5")             # an older game: no mod block, no flag
    v5 = Fake(lob, "V5", b"ssbu-recomp-ldn1-13.0.5", mods())
    i4, i5m, iold, i5 = v4.join(), v5m.join(), old.join(), v5.join()
    s4, s5m = os.urandom(16), os.urandom(16)
    v4.ldn(L.BROADCASTS[0], L.M_ADVERTISE, network_info(i4, s4))
    v5m.ldn(L.BROADCASTS[0], L.M_ADVERTISE, network_info(i5m, s5m))
    time.sleep(0.2)
    # the older game: LIST without the flag -> only its own build (none of the two rooms), 0 rooms
    old.tx(L.LIST, struct.pack(">QI", old.cookie, 1))
    assert old.rx(L.LIST_END)[4] == 0 and none_of(old, L.LISTING, 0.2), "an older game saw a room of another build"
    # a newer game: LIST flag 1 -> both rooms, each with its host's build at the end
    v5.tx(L.LIST, struct.pack(">QIB", v5.cookie, 2, 1))
    got = {}
    for _ in range(2):
        b = v5.rx(L.LISTING)
        assert len(b) == 8 + L.NI_SIZE + 40, len(b)
        got[struct.unpack_from(">I", b, 4)[0]] = b[8 + L.NI_SIZE:].rstrip(b"\0")
    assert v5.rx(L.LIST_END)[4] == 2
    assert got == {i4: b"ssbu-recomp-ldn1-13.0.4", i5m: b"ssbu-recomp-ldn1-13.0.5+m1234abcd"}, got
    # ROOMS: host, players, build, mods; the room's own host sees it flagged as its own
    v5.tx(L.ROOMS, struct.pack(">QI", v5.cookie, 3))
    info = {}
    for _ in range(2):
        b = v5.rx(L.ROOM_INFO)
        seq, host, players, most, flags = struct.unpack_from(">IIBBB", b)
        name = b[11:43].rstrip(b"\0")
        build = b[43:83].rstrip(b"\0")
        info[name] = (seq, host, players, most, flags, build, b[83:])
    assert v5.rx(L.ROOMS_END)[4] == 2
    assert info[b"V4"] == (3, i4, 1, 8, 1 | 4, b"ssbu-recomp-ldn1-13.0.4", b"\0"), info[b"V4"]
    assert info[b"V5m"][:6] == (3, i5m, 1, 8, 1 | 4, b"ssbu-recomp-ldn1-13.0.5+m1234abcd") and info[b"V5m"][6] == mods((b"Alpha", 0x11), (b"Beta", 0x22)), info[b"V5m"]
    v4.tx(L.ROOMS, struct.pack(">QI", v4.cookie, 4))
    mine = [v4.rx(L.ROOM_INFO) for _ in range(2)]
    assert any(struct.unpack_from(">I", b, 4)[0] == i4 and b[10] & 2 for b in mine), "the host's own room is not flagged as its own"
    v4.rx(L.ROOMS_END)
    # an older game's room: listed with flag 4 off (its mods are not known)
    so = os.urandom(16)
    old.ldn(L.BROADCASTS[0], L.M_ADVERTISE, network_info(iold, so))
    time.sleep(0.2)
    v5.tx(L.ROOMS, struct.pack(">QI", v5.cookie, 5))
    seen = {}
    for _ in range(3):
        b = v5.rx(L.ROOM_INFO)
        seen[b[11:43].rstrip(b"\0")] = b[10]
    v5.rx(L.ROOMS_END)
    assert seen[b"Old"] & 4 == 0 and seen[b"Old"] & 1, seen
    # a join across builds never reaches the other host (the lobby parts LDN messages by build)
    v5.ldn(i4, L.M_JOIN, s4 + b"V5".ljust(32, b"\0") + b"\0\0")
    assert none_of(v4, L.DATA), "a join of another build reached the host"
    # the same build joins: the older game's room, from the newer game of the same build without mods
    v5.ldn(iold, L.M_JOIN, so + b"V5".ljust(32, b"\0") + b"\0\0")
    j = old.rx(L.DATA)
    assert j[12:14] == bytes((ord("L"), L.M_JOIN)), j[:16]
    # a broken mod block is dropped (the player stays, its mods unknown)
    bad = Fake(lob, "Bad", b"ssbu-recomp-ldn1-13.0.5+m0", bytes((3, 0, 0, 0, 1, 40)) + b"x" * 40)
    ib = bad.join()
    bad.ldn(L.BROADCASTS[0], L.M_ADVERTISE, network_info(ib, os.urandom(16)))
    time.sleep(0.2)
    v5.tx(L.ROOMS, struct.pack(">QI", v5.cookie, 6))
    seen = {}
    for _ in range(4):
        b = v5.rx(L.ROOM_INFO)
        seen[b[11:43].rstrip(b"\0")] = (b[10], b[83:])
    v5.rx(L.ROOMS_END)
    assert seen[b"Bad"][0] & 4 == 0, seen[b"Bad"]
    for f in (v4, v5m, old, v5, bad):
        f.tx(L.LEAVE, struct.pack(">Q", f.cookie))
    time.sleep(0.2)


def main():
    port, sport = free_port(), free_tcp_port()
    exe = os.environ.get("LOBBY_EXE")
    if exe:
        proc = subprocess.Popen([exe, str(port)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    else:
        proc = subprocess.Popen([sys.executable, "-I", os.path.join(HERE, "ssbu_lobby.py"), "--bind", "127.0.0.1", "--port", str(port), "--stats", "0",
                                 "--status-port", str(sport)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        time.sleep(2.0 if exe else 0.5)
        lob = ("127.0.0.1", port)
        room_browser(lob)
        if exe:
            print("lobby self-test (%s): ok (room browser: builds parted, LIST flag, ROOMS, older game, cross-build join dropped)" % os.path.basename(exe))
            return 0
        code, _, body = get_status(sport)
        st = json.loads(body)
        assert code == 200 and st["up"] is True and st["players"] == 0 and st["rooms"] == 0, body
        a, b = Fake(lob, "Alice"), Fake(lob, "Bob")
        ia, ib = a.join(), b.join()
        assert ia != ib and ia >> 16 == 0x0A0D, (hex(ia), hex(ib))
        session = os.urandom(16)
        a.ldn(L.BROADCASTS[0], L.M_ADVERTISE, network_info(ia, session))
        time.sleep(0.2)
        b.tx(L.LIST, struct.pack(">QI", b.cookie, 7))
        lst = b.rx(L.LISTING)
        seq, owner = struct.unpack_from(">II", lst)
        assert seq == 7 and owner == ia and lst[8 + L.NI_SESSION:8 + L.NI_SESSION + 16] == session
        assert b.rx(L.LIST_END)[4] == 1
        b.ldn(ia, L.M_JOIN, session + b"Bob".ljust(32, b"\0") + b"\0\0")
        j = a.rx(L.DATA)
        assert j[12:14] == bytes((ord("L"), L.M_JOIN)), j[:16]
        a.ldn(ib, L.M_ACCEPT, network_info(ia, session, ib))
        assert b.rx(L.DATA)[13] == L.M_ACCEPT
        a.ldn(L.BROADCASTS[0], L.M_ADVERTISE, network_info(ia, session, ib))
        assert b.rx(L.DATA)[13] == L.M_ADVERTISE
        pa, pb = a.rx(L.PEERS), b.rx(L.PEERS)
        assert pa[4] == 1 and pb[4] == 1, (pa[:5], pb[:5])
        assert struct.unpack_from(">I", pa, 5)[0] == ib and struct.unpack_from(">Q", pa, 5 + 4 + 32 + 12)[0] == struct.unpack_from(">Q", pb, 5 + 4 + 32 + 12)[0]
        a.tx(L.DATA, struct.pack(">IIHH", ia, L.BROADCASTS[0], 49152, 49152) + b"game-broadcast")
        assert b.rx(L.DATA).endswith(b"game-broadcast")
        b.tx(L.DATA, struct.pack(">IIHH", ib, ia, 49152, 49152) + b"game-unicast")
        assert a.rx(L.DATA).endswith(b"game-unicast")
        c = Fake(lob, "Carol")
        ic = c.join()
        c.tx(L.DATA, struct.pack(">IIHH", ic, ia, 49152, 49152) + b"outsider")
        try:
            a.rx(L.DATA, 0.5)
            raise AssertionError("an outsider's datagram reached the room")
        except AssertionError as e:
            if "outsider" in str(e):
                raise
        code, headers, body = get_status(sport)
        st = json.loads(body)
        assert code == 200 and headers.get("Access-Control-Allow-Origin") == "*", (code, dict(headers))
        assert headers.get("Content-Type", "").startswith("application/json")
        assert st["players"] == 3 and st["rooms"] == 1 and st["up"] is True, body
        assert isinstance(st["uptime_s"], int) and st["uptime_s"] >= 0 and st["version"], body
        assert set(st) == {"up", "players", "rooms", "version", "uptime_s"}, body
        for leak in ("127.0.0.1", "10.13.", "Alice", "Bob", "Carol", "Host", "test", "build-x"):
            assert leak not in body, ("status leaks", leak, body)
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/other" % sport, timeout=3)
            raise AssertionError("an unknown path answered 200")
        except urllib.error.HTTPError as e:
            assert e.code == 404
        a.ldn(L.BROADCASTS[0], L.M_GONE, session)
        assert b.rx(L.DATA)[13] == L.M_GONE
        time.sleep(0.2)
        assert json.loads(get_status(sport)[2])["rooms"] == 0
        print("lobby self-test: ok (room browser: builds parted, LIST flag, ROOMS, older game, cross-build join dropped; join, list, room join, PEERS, "
              "broadcast + unicast relay, outsider refused, room closed, status endpoint)")
        return 0
    finally:
        proc.terminate()
        out = proc.communicate(timeout=5)[0]
        if os.environ.get("LOBBY_LOG"):
            print(out)


if __name__ == "__main__":
    sys.exit(main())
