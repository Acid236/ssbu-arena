#!/usr/bin/env python3
"""rb_lobby.c with --ticket-secret-file (SSBU Arena accounts): a JOIN without a ticket, with a forged or an expired one is
refused with its reason; a ticket made as the accounts database makes it (public.lobby_ticket: HMAC-SHA256 of
"<user id>|<name>|<expiry>" keyed by the secret's text, hex) is let in, and the lobby lists the player under the
ticket's name, not the one the game sent.
    LOBBY_EXE=./rb_lobby python3 test_rb_lobby_ticket.py"""
import hashlib
import hmac
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ssbu_lobby as L  # noqa: E402
from test_ssbu_lobby import Fake, free_port  # noqa: E402


def ticket(secret, name, expires_in=3600, uid=None):
    payload = "%s|%s|%d" % (uid or uuid.uuid4(), name, int(time.time()) + expires_in)
    return payload + "." + hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def join_raw(f, tk):
    """a JOIN with an empty mod set and, when given, the ticket block; the WELCOME or the REJECT reason"""
    port = f.s.getsockname()[1]
    body = (f.nonce + f.code.ljust(32, b"\0") + f.name.encode().ljust(32, b"\0") + f.build.ljust(40, b"\0")
            + struct.pack(">IHB", 0x7F000001, port, 1) + b"MS" + bytes([0]))
    if tk is not None:
        t = tk.encode()
        body += b"TK" + struct.pack(">H", len(t)) + t
    f.tx(L.JOIN, body)
    end = time.time() + 2
    while time.time() < end:
        try:
            p, _ = f.s.recvfrom(65536)
        except socket.timeout:
            continue
        if p[3] == L.WELCOME:
            return "welcome", None
        if p[3] == L.REJECT:
            return "reject", p[12:76].rstrip(b"\0").decode()
    raise AssertionError("no answer to the JOIN")


def main():
    secret = os.urandom(32).hex()
    with tempfile.NamedTemporaryFile("w", suffix=".secret", delete=False) as sf:
        sf.write(secret + "\n")
    port = free_port()
    log = tempfile.TemporaryFile()
    proc = subprocess.Popen([os.environ.get("LOBBY_EXE", "./rb_lobby"), "--port", str(port), "--bind", "127.0.0.1",
                             "--ticket-secret-file", sf.name], stdout=log, stderr=subprocess.STDOUT)
    try:
        time.sleep(0.3)
        lob = ("127.0.0.1", port)
        r = join_raw(Fake(lob, "NoTicket"), None)
        assert r[0] == "reject" and "sign in" in r[1], r
        good = ticket(secret, "Alice")
        r = join_raw(Fake(lob, "Mallory"), good[:-1] + ("0" if good[-1] != "0" else "1"))
        assert r[0] == "reject" and "sign in" in r[1], r
        r = join_raw(Fake(lob, "Mallory"), ticket(secret, "Alice").replace("Alice", "Admin", 1))
        assert r[0] == "reject", r
        r = join_raw(Fake(lob, "Late"), ticket(secret, "Late", expires_in=-5))
        assert r[0] == "reject" and "expired" in r[1], r
        r = join_raw(Fake(lob, "Mallory"), ticket("0" * 64, "Alice"))
        assert r[0] == "reject", r
        r = join_raw(Fake(lob, "WhatTheGameSays"), good)
        assert r == ("welcome", None), r
        time.sleep(0.3)
        log.seek(0)
        text = log.read().decode(errors="replace")
        assert "signed-in players only" in text and "Alice joined" in text and "WhatTheGameSays" not in text, text
        print("rb_lobby tickets: ok (no ticket, forged, renamed, expired, wrong key: refused; valid: in, listed as its name)")
        return 0
    finally:
        proc.terminate()
        proc.wait(5)
        os.unlink(sf.name)


if __name__ == "__main__":
    sys.exit(main())
