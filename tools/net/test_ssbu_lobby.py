#!/usr/bin/env python3
"""Self-test of ssbu_lobby.py without the game: two fake players on 127.0.0.1 (host creates a room, the other lists it,
joins it, both exchange a game datagram through the lobby, both receive PEERS for direct paths).
    python test_ssbu_lobby.py        (starts the lobby itself on a free port; standard library only)"""
import os
import socket
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ssbu_lobby as L  # noqa: E402


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Fake:
    def __init__(self, lobby, name):
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
        self.tx(L.JOIN, self.nonce + b"test".ljust(32, b"\0") + self.name.encode().ljust(32, b"\0") + b"build-x".ljust(40, b"\0")
                + struct.pack(">IHB", 0x7F000001, port, 1))
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


def main():
    port = free_port()
    proc = subprocess.Popen([sys.executable, "-I", os.path.join(HERE, "ssbu_lobby.py"), "--bind", "127.0.0.1", "--port", str(port), "--stats", "0"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        time.sleep(0.5)
        lob = ("127.0.0.1", port)
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
        a.ldn(L.BROADCASTS[0], L.M_GONE, session)
        assert b.rx(L.DATA)[13] == L.M_GONE
        print("lobby self-test: ok (join, list, room join, PEERS, broadcast + unicast relay, outsider refused, room closed)")
        return 0
    finally:
        proc.terminate()
        out = proc.communicate(timeout=5)[0]
        if os.environ.get("LOBBY_LOG"):
            print(out)


if __name__ == "__main__":
    sys.exit(main())
