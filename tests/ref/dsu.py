"""A DSU ("cemuhook UDP") controller server: the reference emulator's own network controller input.

yuzu-family emulators can take a whole controller (buttons + sticks) from a DSU server
(input_common/drivers/udp_client.cpp, helpers/udp_protocol.h in the suyu source). The emulator is the client: it asks
127.0.0.1:<port> for port info and pad data; this server answers and then streams the pad state. Nothing is sent to
any window and no key press exists anywhere on the desktop.

    pad = DsuPad(26761); pad.start()
    pad.press('a', 0.15)        # hold A for 0.15 s
    pad.stick(0, 1, 0.5)        # left stick up for 0.5 s
    pad.capture()               # the Capture button (mapped by refcfg.py to the emulator's screenshot)
"""
import socket, struct, threading, time, zlib

MAGIC_SERVER, MAGIC_CLIENT, PROTOCOL = b'DSUS', b'DSUC', 1001
T_VERSION, T_PORTINFO, T_PADDATA = 0x100000, 0x100001, 0x100002
# bit index in PadData.digital_button
BIT = {'minus': 0, 'lstick': 1, 'rstick': 2, 'plus': 3, 'dup': 4, 'dright': 5, 'ddown': 6, 'dleft': 7,
       'zl': 8, 'zr': 9, 'l': 10, 'r': 11, 'x': 12, 'a': 13, 'b': 14, 'y': 15}
MAC = bytes([0x02, 0x53, 0x53, 0x42, 0x55, 0x01])


class DsuPad:
    def __init__(self, port):
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1', port))
        self.sock.settimeout(0.002)
        self.buttons = set()
        self.lx = self.ly = 0.0
        self.home = self.shot = False
        self.client = None
        self.requests = 0
        self.counter = 0
        self.lock = threading.Lock()
        self.stop_flag = False
        self.thread = None

    def _packet(self, mtype, payload):
        body = struct.pack('<I', mtype) + payload
        head = MAGIC_SERVER + struct.pack('<HHII', PROTOCOL, len(body), 0, 0x55425353)
        crc = zlib.crc32(head + body) & 0xffffffff
        return head[:8] + struct.pack('<I', crc) + head[12:] + body

    def _portinfo(self, active):
        # id, state (2 = connected), model (2 = full gyro), connection (1 = USB), mac, battery (5 = full), is_pad_active
        return struct.pack('<BBBB6sBB', 0, 2, 2, 1, MAC, 5, 1 if active else 0)

    def _paddata(self):
        with self.lock:
            bits = 0
            for b in self.buttons:
                bits |= 1 << BIT[b]
            lx, ly, home, shot = self.lx, self.ly, self.home, self.shot
        self.counter += 1
        ax = lambda v: max(0, min(255, int(round(127 + 127 * v))))
        return (self._portinfo(True) + struct.pack('<IHBBBBBB', self.counter, bits, 1 if home else 0, 1 if shot else 0,
                                                   ax(lx), ax(ly), 127, 127)
                + bytes(12) + bytes(12) + struct.pack('<Q', int(time.perf_counter() * 1e6)) + struct.pack('<6f', 0, -1.0, 0, 0, 0, 0))

    def _loop(self):
        next_send = time.perf_counter()
        while not self.stop_flag:
            try:
                data, addr = self.sock.recvfrom(256)
            except (socket.timeout, ConnectionResetError, OSError):
                data = None
            if data and len(data) >= 20 and data[:4] == MAGIC_CLIENT:
                mtype, = struct.unpack_from('<I', data, 16)
                self.requests += 1
                if mtype == T_VERSION:
                    self.sock.sendto(self._packet(T_VERSION, struct.pack('<H', PROTOCOL)), addr)
                elif mtype == T_PORTINFO:
                    count, = struct.unpack_from('<I', data, 20)
                    for i in range(min(count, 4)):
                        if 24 + i < len(data) and data[24 + i] == 0:
                            self.sock.sendto(self._packet(T_PORTINFO, self._portinfo(False)), addr)
                elif mtype == T_PADDATA:
                    self.client = addr
            now = time.perf_counter()
            if self.client and now >= next_send:
                next_send = now + 0.004
                try:
                    self.sock.sendto(self._packet(T_PADDATA, self._paddata()), self.client)
                except OSError:
                    pass

    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_flag = True
        if self.thread:
            self.thread.join(1)
        self.sock.close()

    def connected(self):
        return self.client is not None

    # ---- state
    def set(self, buttons=(), lx=0.0, ly=0.0):
        with self.lock:
            self.buttons = set(buttons)
            self.lx, self.ly = lx, ly

    def release(self):
        self.set()

    def press(self, names, seconds=0.134):
        """hold the buttons (one name or a list) for `seconds`, then release"""
        self.set([names] if isinstance(names, str) else names)
        time.sleep(seconds)
        self.release()

    def stick(self, x, y, seconds):
        self.set((), x, y)
        time.sleep(seconds)
        self.release()

    def press_home(self, seconds=0.15):          # unused: Home suspends the game in the emulator (black screen)
        with self.lock:
            self.home = True
        time.sleep(seconds)
        with self.lock:
            self.home = False

    def capture(self, seconds=0.12):
        with self.lock:
            self.shot = True
        time.sleep(seconds)
        with self.lock:
            self.shot = False


if __name__ == '__main__':
    import sys
    p = DsuPad(int(sys.argv[1]) if len(sys.argv) > 1 else 26761)
    p.start()
    print('DSU server on 127.0.0.1:%d; waiting for a client' % p.port)
    while True:
        time.sleep(1)
        print('requests', p.requests, 'client', p.client)
