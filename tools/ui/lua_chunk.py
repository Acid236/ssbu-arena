"""Small Lua 5.3 chunk reader/writer for local UI-script transformations.

Format and instruction layout: lua.org/source/5.3/{lundump.c,ldump.c,lopcodes.h}.
Supports the game's little-endian 64-bit integers / 32-bit floats. Contains no
game bytecode or source; callers always provide their own extracted chunk.
"""
import struct


OPS = ('MOVE LOADK LOADKX LOADBOOL LOADNIL GETUPVAL GETTABUP GETTABLE SETTABUP '
       'SETUPVAL SETTABLE NEWTABLE SELF ADD SUB MUL MOD POW DIV IDIV BAND BOR '
       'BXOR SHL SHR UNM BNOT NOT LEN CONCAT JMP EQ LT LE TEST TESTSET CALL '
       'TAILCALL RETURN FORLOOP FORPREP TFORCALL TFORLOOP SETLIST CLOSURE VARARG EXTRAARG').split()


def abc(op, a=0, b=0, c=0):
    return OPS.index(op) | a << 6 | c << 14 | b << 23


def abx(op, a=0, bx=0):
    return OPS.index(op) | a << 6 | bx << 14


class Chunk:
    def __init__(self, data):
        self.data, self.at = data, 0
        if data[:17] != b'\x1bLua\x53\x00\x19\x93\r\n\x1a\n\x04\x08\x04\x08\x04':
            raise ValueError('unsupported Lua chunk header')
        self.header = self.take(30)
        self.root = self.proto()
        if self.at != len(data):
            raise ValueError('unparsed chunk data')

    def take(self, n):
        b = self.data[self.at:self.at + n]
        if len(b) != n:
            raise ValueError('truncated Lua chunk')
        self.at += n
        return b

    def u32(self):
        return struct.unpack('<I', self.take(4))[0]

    def string(self):
        n = self.take(1)[0]
        if n == 255:
            n = struct.unpack('<Q', self.take(8))[0]
        return self.take(n - 1).decode('utf-8') if n else None

    def proto(self):
        p = {'source': self.string(), 'meta': self.take(11)}
        p['code'] = [self.u32() for _ in range(self.u32())]
        p['constants'] = []
        for _ in range(self.u32()):
            tag = self.take(1)[0]
            if tag == 0:
                value = None
            elif tag == 1:
                value = bool(self.take(1)[0])
            elif tag == 3:
                value = struct.unpack('<f', self.take(4))[0]
            elif tag == 19:
                value = struct.unpack('<q', self.take(8))[0]
            elif tag in (4, 20):
                value = self.string()
            else:
                raise ValueError('unknown Lua constant tag %d' % tag)
            p['constants'].append((tag, value))
        p['upvalues'] = self.take(2 * self.u32())
        p['protos'] = [self.proto() for _ in range(self.u32())]
        p['lines'] = self.take(4 * self.u32())
        p['locals'] = [(self.string(), self.take(8)) for _ in range(self.u32())]
        p['upnames'] = [self.string() for _ in range(self.u32())]
        return p

    def dump(self):
        return self.header + dump_proto(self.root)


def pack_string(s):
    if s is None:
        return b'\0'
    b = s.encode('utf-8')
    n = len(b) + 1
    return (bytes([n]) if n < 255 else b'\xff' + struct.pack('<Q', n)) + b


def dump_proto(p):
    u = lambda n: struct.pack('<I', n)
    out = bytearray(pack_string(p['source']) + p['meta'])
    out += u(len(p['code'])) + struct.pack('<%dI' % len(p['code']), *p['code'])
    out += u(len(p['constants']))
    for tag, value in p['constants']:
        out += bytes([tag])
        if tag == 1:
            out += bytes([value])
        elif tag == 3:
            out += struct.pack('<f', value)
        elif tag == 19:
            out += struct.pack('<q', value)
        elif tag in (4, 20):
            out += pack_string(value)
    out += u(len(p['upvalues']) // 2) + p['upvalues']
    out += u(len(p['protos'])) + b''.join(dump_proto(x) for x in p['protos'])
    out += u(len(p['lines']) // 4) + p['lines']
    out += u(len(p['locals'])) + b''.join(pack_string(n) + b for n, b in p['locals'])
    out += u(len(p['upnames'])) + b''.join(pack_string(n) for n in p['upnames'])
    return bytes(out)


def constant(p, value, tag=4):
    item = tag, value
    if item not in p['constants']:
        p['constants'].append(item)
    return p['constants'].index(item)


def inspect(p, path='root', code=False):
    values = [x[1] for x in p['constants']]
    print(path, 'params/vararg/stack', list(p['meta'][8:]), 'constants', values)
    if code:
        for pc, w in enumerate(p['code']):
            op, a, b, c, bx = OPS[w & 63], w >> 6 & 255, w >> 23, w >> 14 & 511, w >> 14
            rk = lambda v: repr(values[v - 256]) if v >= 256 and v - 256 < len(values) else 'r%d' % v
            detail = repr(values[bx]) if op == 'LOADK' else ('%d %s' % (b, rk(c)) if op in ('GETTABUP', 'GETTABLE', 'SELF') else ('%s %s' % (rk(b), rk(c)) if op in ('SETTABLE', 'SETTABUP') else '%d %d' % (b, c)))
            print('%3d %-9s r%-3d %s' % (pc, op, a, detail))
    for i, child in enumerate(p['protos']):
        inspect(child, '%s/%d' % (path, i), code)


if __name__ == '__main__':
    import sys
    chunk = Chunk(open(sys.argv[1], 'rb').read())
    inspect(chunk.root, code='--code' in sys.argv)
