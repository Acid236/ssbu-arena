"""The moveset file read as input for hand-written fighter source: command names, a script walker that follows
subroutines and keeps the frame, the model-switch table (which bones' meshes a switch shows), the attribute block,
the hurt-box list. Names and field meanings are the mod community's public tables, written from memory: a name
ending in "?" is a guess; nothing here was cross-checked against another tool.
"""
import struct

from .psa import HDR, Psa

EVENTS = {
    0x00010100: 'wait', 0x00020000: 'nop', 0x00020100: 'frame', 0x00040100: 'loop', 0x00050000: 'loop end',
    0x00070100: 'call', 0x00080000: 'return', 0x00090100: 'goto', 0x000A0100: 'if', 0x000A0200: 'if',
    0x000A0400: 'if', 0x000B0100: 'and', 0x000B0200: 'and', 0x000B0400: 'and', 0x000C0100: 'or', 0x000C0200: 'or',
    0x000C0400: 'or', 0x000D0100: 'else if', 0x000D0200: 'else if', 0x000D0400: 'else if', 0x000E0000: 'else',
    0x000F0000: 'end if', 0x00100200: 'switch', 0x00110100: 'case', 0x00120000: 'default', 0x00130000: 'end switch',
    0x01000000: 'loop rest', 0x01020000: 'loop rest 2?',
    0x02010200: 'change action (action, requirement)', 0x02040400: 'extra requirement for change action',
    0x02060100: 'enable action status', 0x02080100: 'disable action status', 0x020B0100: 'action status ?',
    0x04000100: 'change sub-action', 0x04000200: 'change sub-action', 0x04060100: 'set animation frame',
    0x04070100: 'frame speed multiplier', 0x04080300: 'animation ?', 0x040D0100: 'animation ?',
    0x040E0200: 'animation ?', 0x04100200: 'animation ?',
    0x05000000: 'reverse direction', 0x05030000: 'posture ?', 0x05040000: 'posture ?',
    0x06000D00: 'hitbox', 0x06030100: 'remove hitbox', 0x06040000: 'remove all hitboxes',
    0x06050100: 'body state (0 normal, 1 invincible, 2 intangible)', 0x06080200: 'bone state (bone, state)',
    0x060A0800: 'grab box', 0x060A0A00: 'grab box', 0x060D0000: 'remove grab boxes', 0x060E1100: 'throw data',
    0x060F0500: 'throw release', 0x06150F00: 'hitbox (special)', 0x06170300: 'armour / defensive box on',
    0x06180300: 'armour / defensive box off', 0x061B0500: 'move hitbox (id, bone, x, y, z)',
    0x062B0D00: 'hitbox (thrown)',
    0x07070200: 'rumble', 0x070B0200: 'rumble loop', 0x08000100: 'edge slide mode', 0x09000100: 'ground ?',
    0x0A000100: 'sound', 0x0A010100: 'sound 2', 0x0A020100: 'sound (transient)', 0x0A030100: 'stop sound',
    0x0A050100: 'sound ?', 0x0A060100: 'sound ?', 0x0A090100: 'sound ?', 0x0A0A0100: 'sound ?',
    0x0B000200: 'model switch (switch, group)', 0x0B010200: 'model switch 2 (switch, group)',
    0x0B020100: 'model visible',
    0x0C050000: 'terminate instance', 0x0C090100: 'final smash state ?', 0x0C0B0000: 'low voice clip',
    0x0C170100: 'misc ?', 0x0C230200: 'time manipulation', 0x0C250100: 'tag display',
    0x0D000200: 'concurrent infinite loop', 0x0D050200: 'concurrent ?', 0x0D070200: 'concurrent ?',
    0x0E000100: 'set air / ground', 0x0E010200: 'add momentum (x, y)', 0x0E060100: 'disallow movement',
    0x0E070100: 'disallow movement 2', 0x0E080200: 'set momentum', 0x0E080400: 'set / add momentum',
    0x10000100: 'generate article', 0x10010100: 'article ?', 0x10030100: 'remove article',
    0x11001000: 'effect (attached)', 0x11010A00: 'effect (external file)', 0x11010B00: 'effect (external file)',
    0x11020A00: 'effect (external, ?)', 0x11031400: 'sword trail', 0x11050100: 'end sword trail',
    0x11150300: 'end effect', 0x11170700: 'screen tint', 0x11180200: 'end screen tint ?',
    0x111A1000: 'effect', 0x111B1000: 'effect (stepping)', 0x111C1000: 'effect ?', 0x11210100: 'effect ?',
    0x12000200: 'variable set', 0x12010200: 'variable add', 0x12050300: 'variable ?', 0x12060200: 'float set',
    0x120A0100: 'bit set', 0x120B0100: 'bit clear', 0x120F0200: 'float multiply', 0x12100200: 'float ?',
    0x12120200: 'float ?', 0x121C0700: 'variable ?', 0x12500200: 'plugin command ?', 0x12510200: 'plugin command ?',
    0x12570100: 'plugin command ?',
    0x18000100: 'slope contour stand', 0x18010200: 'slope contour', 0x18010300: 'slope contour',
    0x1A000100: 'screen shake', 0x1A030400: 'camera bounds', 0x1A040500: 'camera close-up',
    0x1A080000: 'normal camera',
    0x1F000100: 'pick up item', 0x1F000200: 'pick up item', 0x1F010300: 'throw item', 0x1F030100: 'drop item',
    0x1F040200: 'consume item', 0x1F050000: 'item property', 0x1F060100: 'item ?', 0x1F070100: 'item ?',
    0x1F090100: 'item visibility', 0x1F0C0100: 'item ?', 0x1F0E0500: 'generate item in hand',
    0x1F0F0100: 'item ?', 0x1F120600: 'item ?',
    0x21000000: 'end flash', 0x21010400: 'flash overlay', 0x21020500: 'change flash colour',
    0x21050600: 'flash light', 0x21070500: 'flash ?',
    0x64000000: 'ALLOW INTERRUPT (the move can be cancelled from here)',
    # added in the second pass; "(inferred)" = named from how this file uses it, not from a table
    0x00060000: 'loop break? (inferred)', 0x01010000: 'loop rest (wait one frame inside a loop)',
    0x02000300: 'change action status (status, action, requirement)',
    0x02000401: 'change action status (4 arguments)', 0x02010300: 'change action (action, requirement, argument)',
    0x02010500: 'change action (action, requirement + 3 arguments)',
    0x02040100: 'extra requirement for the change action above', 0x02040200: 'extra requirement for the change action above',
    0x020A0100: 'allow a specific interrupt (group)', 0x030B0400: 'action status ? (4 arguments)',
    0x04010200: 'on requirement: switch to the ground (0) / air (1) sub-action of the pair, keeping the frame (inferred)',
    0x04020100: 'extra requirement for the sub-action change above (inferred)',
    0x04020400: 'extra requirement for the sub-action change above (4 arguments)',
    0x04110100: 'animation flag ? (always 1 in this file)',
    0x0C010000: 'misc 0C01 ?', 0x0C060000: 'misc 0C06 ?', 0x0C070000: 'misc 0C07 ?', 0x0C0D0000: 'misc 0C0D ?',
    0x0D060100: 'stop the concurrent loop with this id (inferred)',
    0x10040300: 'article: set its action / animation (article, a, b) ?',
    0x111D0100: 'effect ? (1 argument)', 0x111F0100: 'effect ? (1 argument)',
    0x12030100: 'variable + 1', 0x12040100: 'variable - 1', 0x12070200: 'float add',
    0x12080200: 'float subtract', 0x14050100: 'wind / aesthetic ?',
    # third pass (the questions round). These REPLACE earlier guesses of the same code.
    0x06170300: 'defensive collision on (public name; NOT the super-armour command 1E00; effect of its numbers unknown)',
    0x06180300: 'defensive collision off',
    0x06160100: 'hitbox size multiplier? (inferred)',
    0x12100200: 'float divide', 0x12120200: 'float absolute value? (inferred)',
    0x12500200: 'float sine? (in, out; inferred)', 0x12510200: 'float cosine? (in, out; inferred)',
    0x12570100: 'float = pi? (inferred)',
    0x030B0400: 'place bone (bone, x, y, z)? (inferred: moves the Throw bone before an item is generated on it)',
    0x1F120600: 'GENERATE ITEM (0, item id, bone, angle, speed, 1) (inferred: 0x10009 / 0x10109 / 0x10209 / 0x10309 '
                '= the package item archives ItmZero00 / 01 / 02 / 03)',
    0x65090800: 'item: GENERATE ITEM at a position (kind, item id, x, y, ...) (inferred)',
    0x65050100: 'item: lifetime in frames? (inferred)',
    0x020C0100: 'INTERRUPT GROUP the lines below belong to (1 ground special, 4 ground attack, 7 ground jump, '
                '11 air special, 15 air attack, 18 air jump; public numbering)',
    0x02050400: 'allow status only with requirement (interrupt group, status, requirement)',
    0x02030500: 'change action in an interrupt group (group, status, ?, action, requirement)',
    0x020A0100: 'allow an interrupt group (7 ground jump, 12 / 15 air, 18 air jump; public numbering)',
    0x0E080400: 'set / add momentum (x, y, x mode, y mode: 0 add, 1 set; inferred)',
    0x04100200: 'switch to the animation of sub-action (layer, sub-action)? (inferred)',
    # item / article scripts (all inferred from the package's own use)
    0x12150800: 'READ A VARIABLE OF THE OWNER (into, ..., 36 = RA / 32 = LA, 12 = basic / 20 = float, byte offset = '
                'index x 4) (inferred)',
    0x12150300: 'read a value of the owner (3 arguments) (inferred)',
    0x121A1600: 'READ A VARIABLE OF THE OWNER, long form (into, ..., last two numbers: kind, byte offset) (inferred)',
    0x120D0200: 'multiply an integer variable by a float (float, variable)? (inferred)',
    0x03010400: 'item: set rotation (target, x, y, z)? (inferred)',
    0x03060400: 'item: set scale (target, x, y, z)? (inferred)',
    0x030A0400: 'item: position of bone N into three floats (bone, x, y, z)? (inferred)',
    0x050A0300: 'item: 3-argument command 050A ?', 0x0E050100: 'item: physics mode ?',
    0x06020200: 'change hitbox size (id, size)', 0x65000000: 'item: remove itself? (inferred)',
    0x66060100: 'item: stop moving? (inferred)', 0x66070000: 'item: end? (inferred)',
    0x65170200: 'item: 2-argument command 6517 ?',
}

# requirement ids (the condition of "if" / change-action commands). From the public tables as remembered; a name
# ending in "?" is inferred or uncertain.
REQUIREMENTS = {
    0x01: 'animation ended', 0x02: 'animation looped?', 0x03: 'on the ground', 0x04: 'in the air',
    0x05: 'holding a ledge', 0x06: 'on a passable floor', 0x07: 'compare', 0x08: 'bit is set',
    0x09: 'facing right', 0x0A: 'facing left', 0x0B: 'a hitbox connected', 0x0C: 'touching floor / wall / ceiling?',
    0x0D: 'is throwing someone', 0x0F: 'button tap', 0x15: 'article exists', 0x17: 'floor below',
    0x1B: 'air / ground state changed', 0x1C: 'article available', 0x1F: 'holding an item',
    0x20: 'holding an item of type', 0x2B: 'roll a die? / in water?', 0x2D: 'sub-action exists?',
    0x30: 'button pressed this frame', 0x31: 'button released', 0x32: 'button held', 0x33: 'button not held',
    0x34: 'stick direction pressed', 0x35: 'stick direction not pressed', 0x39: 'has not tethered 3 times?',
    0x3D: 'is being thrown?', 0x60: 'plugin requirement?',
}
COMPARE = {0: '<', 1: '<=', 2: '==', 3: '!=', 4: '>=', 5: '>'}
BUTTONS = {0: 'attack', 1: 'special', 2: 'jump', 3: 'shield', 4: 'dodge?', 5: 'taunt?'}

ELEMENTS = {0: 'normal', 1: 'none', 2: 'slash', 3: 'electric', 4: 'ice', 5: 'fire', 6: 'coin', 7: 'cape',
            8: 'slip', 9: 'sleep', 0xB: 'bury', 0xC: 'stun', 0xE: 'flower', 0x13: 'grass', 0x14: 'water',
            0x15: 'darkness', 0x16: 'paralyze', 0x17: 'aura', 0x18: 'plunge', 0x19: 'down', 0x1A: 'flinchless'}

# offset in the attribute block -> (public name, kind, native parameter of the same meaning or None, note)
ATTRIBUTES = [
    (0x000, 'walk initial velocity', 'f', 'walk_accel_add', 'same meaning (first-frame walk speed)?'),
    (0x004, 'walk acceleration', 'f', 'walk_accel_mul', 'same meaning?'),
    (0x008, 'walk maximum velocity', 'f', 'walk_speed_max', 'same unit (units / frame)'),
    (0x00C, 'ground friction', 'f', 'ground_brake', 'same unit'),
    (0x010, 'dash initial velocity', 'f', 'dash_speed', 'same unit'),
    (0x014, 'dash / run acceleration A', 'f', 'run_accel_mul', 'same meaning?'),
    (0x018, 'dash / run acceleration B', 'f', 'run_accel_add', 'same meaning?'),
    (0x01C, 'run terminal velocity', 'f', 'run_speed_max', 'same unit'),
    (0x024, 'grounded maximum x velocity', 'f', None, ''),
    (0x028, 'dash cancel frame window', 'i', None, ''),
    (0x02C, 'guard-on maximum momentum', 'f', None, ''),
    (0x030, 'jump start-up frames', 'i', 'jump_squat_frame', 'frames'),
    (0x034, 'jump horizontal initial velocity', 'f', 'jump_speed_x', 'same unit'),
    (0x038, 'jump vertical initial velocity', 'f', 'jump_y', 'CONVERT: the native value is a HEIGHT'),
    (0x03C, 'ground-to-air momentum multiplier', 'f', 'jump_speed_x_mul', 'same meaning?'),
    (0x040, 'jump horizontal maximum velocity', 'f', 'jump_speed_x_max', 'same unit'),
    (0x044, 'short hop vertical initial velocity', 'f', 'mini_jump_y', 'CONVERT: height'),
    (0x048, 'air jump multiplier', 'f', 'jump_aerial_y', 'CONVERT: height of (multiplier x jump velocity)'),
    (0x050, 'footstool vertical initial velocity', 'f', None, ''),
    (0x060, 'jump count', 'i', 'jump_count_max', 'same'),
    (0x064, 'gravity', 'f', 'air_accel_y', 'same unit'),
    (0x068, 'terminal fall velocity', 'f', 'air_speed_y_stable', 'same unit'),
    (0x06C, 'air friction y', 'f', None, ''),
    (0x074, 'air mobility A', 'f', 'air_accel_x_mul', 'same meaning?'),
    (0x078, 'air mobility B', 'f', 'air_accel_x_add', 'same meaning?'),
    (0x07C, 'air x terminal velocity', 'f', 'air_speed_x_stable', 'same unit'),
    (0x080, 'air friction x', 'f', 'air_brake_x', 'same unit'),
    (0x084, 'fast-fall terminal velocity', 'f', 'dive_speed_y', 'same unit'),
    (0x094, 'jab 2 window (frames)', 'f', None, 'combo window: in the native scripts (ENABLE_COMBO flag frame)'),
    (0x098, 'jab 3 window (frames)', 'f', None, ''),
    (0x0B0, 'weight', 'f', 'weight', 'same scale (100 = the reference fighter)'),
    (0x0B4, 'size', 'f', 'scale', 'same'),
    (0x0B8, 'size on the results screen', 'f', None, ''),
    (0x138, 'light landing lag (frames)?', 'f', 'landing_frame_light', 'alignment judged by the values'),
    (0x13C, 'normal landing lag (frames)?', 'f', 'landing_frame', 'alignment judged by the values'),
    (0x140, 'neutral air landing lag?', 'f', 'landing_attack_air_frame_n', 'alignment judged by the values'),
    (0x144, 'forward air landing lag?', 'f', 'landing_attack_air_frame_f', ''),
    (0x148, 'back air landing lag?', 'f', 'landing_attack_air_frame_b', ''),
    (0x14C, 'up air landing lag?', 'f', 'landing_attack_air_frame_hi', ''),
    (0x150, 'down air landing lag?', 'f', 'landing_attack_air_frame_lw', ''),
]


def fmt_var(v):
    mem = {0: 'IC', 1: 'LA', 2: 'RA'}.get(v >> 28, 'mem%d' % (v >> 28))
    kind = {0: 'Basic', 1: 'Float', 2: 'Bit'}.get((v >> 24) & 0xF, 'kind%d' % ((v >> 24) & 0xF))
    return '%s-%s[%d]' % (mem, kind, v & 0xFFFFFF)


def fmt_param(p, pt):
    t, v = pt
    if t == 0:
        return str(v - (1 << 32) if v & 0x80000000 else v)
    if t == 1:
        return '%.4g' % ((v - (1 << 32) if v & 0x80000000 else v) / 60000.0)
    if t == 2:
        return '@%#x' % v
    if t == 3:
        return 'true' if v else 'false'
    if t == 5:
        return fmt_var(v)
    if t == 6:
        r = v & 0x7FFFFFFF
        return '%s[%s req %#x]' % ('NOT ' if v & 0x80000000 else '', REQUIREMENTS.get(r, '?'), r)
    if t == 7:
        return 'BASE-GAME ROUTINE %s' % v
    return 'type%d:%#x' % (t, v)


def walk(p, off, depth=0, frame=0.0, seen=None, limit=3000):
    """Yields (frame, depth, code, params) for a script, following subroutine calls; frames from the timers
    (wait adds, frame sets), scaled by nothing (speed multipliers are listed as commands). Both branches of an
    'if' are yielded in file order. A goto is followed once when it leaves the list forward."""
    seen = set() if seen is None else seen
    if off in seen or depth > 6 or not off or off >= p.data_size:
        return frame
    seen.add(off)
    ext = external_slots(p)
    loops = []
    for i in range(limit):
        pos = HDR + off + i * 8
        if pos + 8 > HDR + p.data_size:
            break
        mod, eid, n, unk, po = struct.unpack_from('>BBBBI', p.d, pos)
        code = mod << 24 | eid << 16 | n << 8 | unk
        if code == 0 and po == 0:
            break
        params = []
        if n and 0 < po < p.data_size:
            params = [struct.unpack_from('>II', p.d, HDR + po + k * 8) for k in range(n)]
        if code == 0x00010100 and params:
            frame += Psa.val(params[0])
        elif code == 0x00020100 and params:
            frame = Psa.val(params[0])
        target = params[0][1] if params and params[0][0] == 2 else None
        if code in (0x00070100, 0x00090100) and (po + 4) in ext:
            # a routine of the base game, named in the file's external table: not in this file
            yield (frame, depth, code, [(7, ext[po + 4])])
            continue
        yield (frame, depth, code, params)
        if code == 0x00040100 and params:
            loops.append((frame, Psa.val(params[0])))
        elif code == 0x00050000 and loops:
            start, count = loops.pop()
            if isinstance(count, (int, float)) and 1 < count < 100:
                frame += (count - 1) * (frame - start)       # the body runs count times
        elif code == 0x00070100 and target is not None and 0 < target < p.data_size:
            frame = yield from walk(p, target, depth + 1, frame, seen, limit)
        elif code == 0x00090100 and target is not None and 0 < target < p.data_size:
            if target not in seen:
                frame = yield from walk(p, target, depth + 1, frame, seen, limit)
            return frame
        elif code == 0x00080000:
            return frame
    return frame


_EXT_CACHE = {}


def external_slots(p):
    """{offset of a pointer slot: name of the base game's routine it refers to}. The external table gives the
    first slot of each name; the slot holds the offset of the next one."""
    key = id(p)
    if key not in _EXT_CACHE:
        out = {}
        for name, off in p.externals:
            guard = 0
            while off != 0xFFFFFFFF and 0 < off < p.data_size and guard < 1000:
                out[off] = name
                off = p.u32(off)
                guard += 1
        _EXT_CACHE[key] = out
    return _EXT_CACHE[key]


def describe(p, code, params, bone_name):
    """One readable line for a command."""
    name = EVENTS.get(code, 'command %08x' % code)
    v = [Psa.val(x) for x in params]
    raw = [x[1] for x in params]
    var = ['' if x[0] != 5 else fmt_var(x[1]) for x in params]

    def val(i):
        return var[i] if var[i] else ('%g' % v[i])
    if code in (0x06000D00, 0x06150F00, 0x062B0D00) and len(params) >= 13:
        fl = raw[12]
        s = '%s id %d bone %s  damage %s angle %s  kb base %d growth %d fixed %d  size %s  offset (%s, %s, %s)  ' \
            'shield damage %d  hitlag x%s  sdi x%s  trip %s  element %s  flags %#010x' % (
                name, raw[0] & 0xFFFF, bone_name(raw[0] >> 16), val(1), val(2), raw[4] & 0xFFFF, raw[3] & 0xFFFF,
                raw[3] >> 16, val(5), val(6), val(7), val(8), raw[4] >> 16, val(10), val(11), val(9),
                ELEMENTS.get(fl & 0x1F, '%#x' % (fl & 0x1F)), fl)
        if code == 0x06150F00 and len(params) >= 15:
            s += '  rehit %s  special flags %#x' % (val(13), raw[14])
        return s
    if code in (0x060A0800, 0x060A0A00) and len(params) >= 6:
        return '%s id %s bone %s size %s offset (%s, %s, %s) action %s air/ground %s' % (
            name, val(0), bone_name(raw[1]), val(2), val(3), val(4), val(5), val(6) if len(v) > 6 else '-',
            val(7) if len(v) > 7 else '-')
    if code == 0x060E1100 and len(params) >= 7:
        return '%s id %s bone %s  damage %s angle %s  kb growth %s fixed %s base %s  element %s  (+%d more)' % (
            name, val(0), bone_name(raw[1]), val(2), val(3), val(4), val(5), val(6),
            ELEMENTS.get(raw[7], raw[7]) if len(raw) > 7 else '-', len(params) - 8)
    if code == 0x061B0500 and len(params) >= 5:
        return 'move hitbox id %s to bone %s offset (%s, %s, %s)' % (val(0), bone_name(raw[1]), val(2), val(3), val(4))
    if code == 0x06080200 and len(params) >= 2:
        return 'bone state: bone %s state %s' % (bone_name(raw[0]), val(1))
    if code in (0x11001000, 0x111A1000, 0x111B1000, 0x11010A00, 0x11010B00, 0x11020A00) and len(params) >= 8:
        return '%s id %#x bone %s offset (%s, %s, %s) rotation (%s, %s, %s) scale %s  (+%d more)' % (
            name, raw[0], bone_name(raw[1]), val(2), val(3), val(4), val(5), val(6), val(7),
            val(8) if len(v) > 8 else '-', max(0, len(params) - 9))
    if code in (0x0A000100, 0x0A010100, 0x0A020100, 0x0A030100) and params:
        return '%s id %#x' % (name, raw[0])
    parts = [fmt_param(p, x) for x in params]
    for i, x in enumerate(params):
        if x[0] == 6 and (x[1] & 0x7FFFFFFF) == 7 and i + 2 < len(params) and params[i + 2][0] == 0:
            parts[i + 2] = COMPARE.get(params[i + 2][1], '?op%d' % params[i + 2][1])       # variable OP value
        if x[0] == 6 and (x[1] & 0x7FFFFFFF) in (0x30, 0x31, 0x32, 0x33, 0x0F) and i + 1 < len(params) \
                and params[i + 1][0] == 0:
            parts[i + 1] = 'button ' + BUTTONS.get(params[i + 1][1], str(params[i + 1][1]))
    return name + (': ' + ', '.join(parts) if params else '')


def model_switches(p):
    """-> (switches, defaults): switches[i] = list of groups, a group = list of bone indices whose meshes it
    shows; defaults = {switch: group}."""
    base = p.header[1]
    if not base:
        return [], {}
    ref_off, n_switch, data_off, n_data = (p.u32(base + i * 4) for i in range(4))
    first = p.u32(ref_off)
    switches = []
    for s in range(n_switch):
        goff, gcount = p.u32(first + s * 8), p.u32(first + s * 8 + 4)
        groups = []
        for g in range(gcount):
            boff, bcount = p.u32(goff + g * 8), p.u32(goff + g * 8 + 4)
            groups.append([p.u32(boff + k * 4) for k in range(bcount)] if boff else [])
        switches.append(groups)
    defaults = {s: 0 for s in range(n_switch)}
    for k in range(n_data):
        defaults[p.u32(data_off + k * 8)] = p.u32(data_off + k * 8 + 4)
    return switches, defaults


def visibility_timeline(p, sub, switches, defaults):
    """-> list of (frame, {bone index: visible}) changes for one sub-action, the first at frame 0 with every
    switched bone (defaults), then one per model-switch command of its four scripts."""
    state = dict(defaults)

    def bones(st):
        out = {}
        for s, groups in enumerate(switches):
            for g, lst in enumerate(groups):
                for b in lst:
                    out[b] = out.get(b, False) or st.get(s, 0) == g
        return out
    events = []
    for nm, off in sub['scripts'].items():
        for frame, _d, code, params in walk(p, off):
            # both forms of the command are taken to address the same switch table (the second form is the one
            # the arm cannon uses; its own table in the file was not decoded)
            if code in (0x0B000200, 0x0B010200) and len(params) >= 2 and params[0][0] == 0 and params[1][0] == 0 \
                    and params[0][1] < len(switches) and params[1][1] < 0x80000000:
                events.append((frame, params[0][1], params[1][1]))
    events.sort(key=lambda e: e[0])
    out = []
    i = 0
    while i < len(events) and events[i][0] <= 0:
        state[events[i][1]] = events[i][2]
        i += 1
    out.append((0.0, bones(state)))
    for frame, s, g in events[i:]:
        state[s] = g
        out.append((frame, bones(state)))
    return out


def attributes(p):
    base = p.header[2]
    out = []
    for off, name, kind, native, note in ATTRIBUTES:
        raw = p.d[HDR + base + off:HDR + base + off + 4]
        val = struct.unpack('>f', raw)[0] if kind == 'f' else struct.unpack('>i', raw)[0]
        out.append((off, name, val, native, note))
    return out


def hurtboxes(p):
    """-> list of dicts (offset, stretch, radius, bone, zone, flags). Location: the misc section's 4th / 5th words."""
    misc = p.header[4]
    off, count = p.u32(misc + 0x0C), p.u32(misc + 0x10)
    out = []
    for i in range(count):
        v = struct.unpack_from('>7fI', p.d, HDR + off + i * 0x20)
        fl = v[7]
        out.append({'offset': v[0:3], 'stretch': v[3:6], 'radius': v[6], 'bone': fl >> 23,
                    'zone': (fl >> 19) & 3, 'flags': fl})
    return out
