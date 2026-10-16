"""The moveset file of the Wii predecessor (the "misc data" entry of a fighter's main archive): sections, the
sub-action table and its four script lists, and a listing of the hitbox commands per sub-action.

File: 0x20-byte header {u32 file size, u32 data size, u32 relocation count, u32 section count, u32 external count},
data (every offset inside is relative to the data start), relocation table (u32 each), section table and external
table ({u32 data offset, u32 name offset} each), names.
The "data" section starts with a table of offsets; the ones used here: 0x00 sub-action flags (8 bytes each:
u8 blend frames, u8 flags, u16, u32 animation name offset), 0x30 / 0x34 / 0x38 / 0x3C the four per-sub-action script
lists (main, effects, sounds, other: one u32 offset per sub-action).
Script: 8-byte commands {u8 module, u8 id, u8 parameter count, u8 0, u32 parameter offset}; parameters 8 bytes
{u32 type, u32 value} (type 0 integer, 1 fixed point / 60000, 2 offset, 3 boolean, 5 variable, 6 requirement);
a list ends with an all-zero command.
"""
import struct

HDR = 0x20
SUBACTION_LISTS = (('main', 0x30), ('gfx', 0x34), ('sfx', 0x38), ('other', 0x3C))

EVENT_NAMES = {
    0x00010100: 'wait (frames)', 0x00020100: 'wait until (frame)', 0x00040100: 'loop', 0x00050000: 'loop end',
    0x00070100: 'call', 0x00080000: 'return', 0x00090100: 'goto', 0x000A0100: 'if', 0x000A0200: 'if',
    0x000A0400: 'if', 0x000E0000: 'else', 0x000F0000: 'end if',
    0x06000D00: 'hitbox', 0x06150F00: 'hitbox (special)', 0x06040000: 'remove all hitboxes',
    0x06030100: 'remove hitbox', 0x060A0800: 'grab box', 0x060A0A00: 'grab box', 0x060D0000: 'remove grab boxes',
    0x060E1100: 'throw', 0x062B0D00: 'hitbox (thrown)', 0x06050100: 'body state', 0x06080200: 'bone state',
}


class Psa:
    def __init__(self, data):
        self.d = d = data
        self.file_size, self.data_size, self.reloc_count, self.section_count, self.external_count = \
            struct.unpack_from('>5I', d, 0)
        if self.file_size > len(d) + 0x20 or HDR + self.data_size > len(d):
            raise ValueError('not a moveset file (sizes)')
        tab = HDR + self.data_size + self.reloc_count * 4
        names = tab + (self.section_count + self.external_count) * 8
        self.sections = {}
        self.externals = []
        for i in range(self.section_count + self.external_count):
            off, so = struct.unpack_from('>II', d, tab + i * 8)
            nm = self._cstr(names + so, absolute=True)
            if i < self.section_count:
                self.sections[nm] = off
            else:
                self.externals.append((nm, off))
        self.relocs = set(struct.unpack_from('>%dI' % self.reloc_count, d, HDR + self.data_size))
        self.subactions = []
        if 'data' in self.sections:
            self._read_subactions()

    def _cstr(self, off, absolute=False):
        p = off if absolute else HDR + off
        e = self.d.index(b'\0', p)
        return self.d[p:e].decode('ascii', 'replace')

    def u32(self, off):
        return struct.unpack_from('>I', self.d, HDR + off)[0]

    def _read_subactions(self):
        base = self.sections['data']
        self.header = [self.u32(base + i * 4) for i in range(31)]
        flags = self.u32(base)
        lists = {nm: self.u32(base + o) for nm, o in SUBACTION_LISTS}
        starts = sorted(v for v in lists.values() if v)
        count = (starts[1] - starts[0]) // 4 if len(starts) > 1 else 0
        # the lists follow each other; every list has one offset per sub-action
        self.subaction_count = count
        for i in range(count):
            blend, fl, _p, so = struct.unpack_from('>BBHI', self.d, HDR + flags + i * 8)
            name = self._cstr(so) if 0 < so < self.data_size else ''
            self.subactions.append({'index': i, 'name': name, 'blend': blend, 'flags': fl,
                                    'scripts': {nm: self.u32(lists[nm] + i * 4) if lists[nm] else 0
                                                for nm, _o in SUBACTION_LISTS}})

    def script(self, off, limit=4000):
        """-> list of (event code, [(type, value)])."""
        out = []
        if not off or off >= self.data_size:
            return out
        for i in range(limit):
            p = HDR + off + i * 8
            if p + 8 > HDR + self.data_size:
                break
            mod, eid, n, unk, po = struct.unpack_from('>BBBBI', self.d, p)
            code = mod << 24 | eid << 16 | n << 8 | unk
            if code == 0 and po == 0:
                break
            params = []
            if n and 0 < po < self.data_size:
                for k in range(n):
                    params.append(struct.unpack_from('>II', self.d, HDR + po + k * 8))
            out.append((code, params))
        return out

    @staticmethod
    def val(p):
        t, v = p
        if t == 1:
            return (v - (1 << 32) if v & 0x80000000 else v) / 60000.0
        if t == 0:
            return v - (1 << 32) if v & 0x80000000 else v
        return v

    def hitboxes(self, sub):
        """Walks the main script of one sub-action linearly (no branch evaluation) and lists the hitbox commands
        with the frame the timers give. -> list of dicts."""
        out = []
        frame = 0.0
        for code, params in self.script(sub['scripts']['main']):
            if code == 0x00010100 and params:
                frame += self.val(params[0])
            elif code == 0x00020100 and params:
                frame = self.val(params[0])
            elif code in (0x06000D00, 0x06150F00, 0x062B0D00) and len(params) >= 13:
                v = [self.val(p) for p in params]
                raw = [p[1] for p in params]
                h = {'frame': frame, 'kind': EVENT_NAMES[code], 'bone': raw[0] >> 16, 'id': raw[0] & 0xFFFF,
                     'damage': v[1], 'angle': v[2], 'kb_fixed': raw[3] >> 16, 'kb_growth': raw[3] & 0xFFFF,
                     'shield_damage': raw[4] >> 16, 'kb_base': raw[4] & 0xFFFF, 'size': v[5],
                     'offset': (v[6], v[7], v[8]), 'trip': v[9], 'hitlag': v[10], 'sdi': v[11], 'flags': raw[12],
                     'variable': [i for i, p in enumerate(params) if p[0] == 5]}
                out.append(h)
            elif code == 0x06040000:
                out.append({'frame': frame, 'kind': 'remove all hitboxes'})
            elif code in (0x060A0800, 0x060A0A00) and len(params) >= 6:
                v = [self.val(p) for p in params]
                out.append({'frame': frame, 'kind': 'grab box', 'id': v[0], 'bone': v[1], 'size': v[2],
                            'offset': (v[3], v[4], v[5])})
            elif code == 0x060E1100 and len(params) >= 6:
                v = [self.val(p) for p in params]
                out.append({'frame': frame, 'kind': 'throw', 'id': v[0], 'bone': v[1], 'damage': v[2],
                            'angle': v[3], 'kb_growth': v[4], 'kb_fixed': v[5],
                            'kb_base': v[6] if len(v) > 6 else None})
        return out

    def event_census(self):
        seen = {}
        total = 0
        for s in self.subactions:
            for nm, off in s['scripts'].items():
                for code, _p in self.script(off):
                    seen[code] = seen.get(code, 0) + 1
                    total += 1
        return total, seen
