#!/usr/bin/env python3
"""rb_lobby.c's ping exchange (the games' ping overlay): two players matched for a rollback match put their round trip in
their PING (2 bytes after the 21 of ssbu_lobby.py's); each PONG then ends with "PR", a count and (address u32, ms u16) of
the other one. Then the same inside a Local Wireless room.
    LOBBY_EXE=./rb_lobby python3 test_rb_lobby_ping.py"""
import os
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ssbu_lobby as L  # noqa: E402
from test_ssbu_lobby import Fake, free_port, network_info  # noqa: E402


def ping(f, rtt):
    f.tx(L.PING, struct.pack(">QQBH", f.cookie, int(time.time() * 1000), 0, rtt))


def drain(*fs):
    """forget every packet received so far (also those still in the socket)"""
    time.sleep(0.2)
    for f in fs:
        f.got.clear()
        f.s.settimeout(0.05)
        try:
            while True:
                f.s.recvfrom(65536)
        except OSError:
            pass
        f.s.settimeout(0.2)


def others(f):
    """the (address, ms) list at the end of the next PONG"""
    b = f.rx(L.PONG)
    assert len(b) >= 19 and b[16:18] == b"PR", b
    n = b[18]
    return [struct.unpack_from(">IH", b, 19 + 6 * i) for i in range(n)]


def main():
    port = free_port()
    proc = subprocess.Popen([os.environ.get("LOBBY_EXE", "./rb_lobby"), str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.3)
        lob = ("127.0.0.1", port)
        a, b = Fake(lob, "PA"), Fake(lob, "PB")
        ia, ib = a.join(), b.join()
        ping(a, 42); assert others(a) == [], "alone: nobody listed"
        a.match(L.KIND_ROLLBACK, 1); b.match(L.KIND_ROLLBACK, 2)
        a.until(L.MS_MATCHED); b.until(L.MS_MATCHED)
        ping(a, 42); ping(b, 77)                   # the lobby learns both round trips
        drain(a, b)
        ping(a, 42); ping(b, 77)
        oa, ob = others(a), others(b)
        assert oa == [(ib, 77)] and ob == [(ia, 42)], (oa, ob)
        c, d = Fake(lob, "PC"), Fake(lob, "PD")
        ic, id_ = c.join(), d.join()
        session = os.urandom(16)
        c.ldn(L.BROADCASTS[0], L.M_ADVERTISE, network_info(ic, session))
        time.sleep(0.2)
        d.ldn(ic, L.M_JOIN, session + b"PD".ljust(32, b"\0") + b"\0\0")
        c.ldn(L.BROADCASTS[0], L.M_ADVERTISE, network_info(ic, session, id_))
        time.sleep(0.2)
        ping(c, 30); ping(d, 55)
        drain(c, d)
        ping(c, 30); ping(d, 55)
        oc, od = others(c), others(d)
        assert oc == [(id_, 55)] and od == [(ic, 30)], (oc, od)
        print("rb_lobby ping exchange: ok (rollback pair, Local Wireless room, alone: none)")
        return 0
    finally:
        proc.terminate()
        proc.wait(5)


if __name__ == "__main__":
    sys.exit(main())
