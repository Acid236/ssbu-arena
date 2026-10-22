"""The classic Arena menu's routes, made in the owner's main_menu_layer_top bytecode (no game instructions here).

Each main-menu button is a table {parts = <pane>, state = STATE_<X>_IN} or {parts, func_decide = callback}. Here:
    Smash   (melee)       unchanged
    Arena   (spirits)     func_decide = callback, func_arg = 0: nothing yet (Battle Arena, later)
    Ranked  (online)      func_decide = callback, func_arg = 0: nothing yet
    LDN     (other)       func_decide = callback, func_arg = 3: the side bar's Local Wireless command (the big tile, at
                          the top right, made taller over the Vault's place: prepare_menu_classic.py)
    Settings (colle)      func_decide = callback, func_arg = 5: the side bar's Options command, the game's own options
                          (+ there opens the Arena settings); the Vault tile, made small above Exit
    Exit    (eshop)       sequence = SEQUENCE_OTHER_AMIIBO: runtime/competitive.c catches the Games & More sequence
                          (not part of the competitive build) and asks to exit the game
The callback (proto 1, callback_proto) returns at once for argument 0, else asks the side bar (prg_func.open_pallet) for
that command; competitive.c confirms it in the side bar's native controller.
"""
from lua_chunk import Chunk, abc, abx, constant, OPS
import menu_actions

# func_arg of the shared callback: 0 nothing (yet), else the side bar (pallet) command to run: 3 Local Wireless,
# 5 Options (the native one-based button ids; runtime/competitive.c reads it and confirms that command)
PLACEHOLDER = {'set_parts_btn_spirits': 0, 'set_parts_btn_online': 0, 'set_parts_btn_other': 3, 'set_parts_btn_colle': 5}
SEQUENCE = {'set_parts_btn_eshop': 'SEQUENCE_OTHER_AMIIBO'}
# the selector's cone for the d-pad (60 in the game): wide enough that up from Exit reaches the small Settings tile
DIRECTIONAL_DEGREE = 90


def callback_proto(p):
    """function(self, arg): 0 -> return; else prg_func.open_pallet(0, 0, 1, arg): the fourth argument (0 in the earlier
    preview) carries the command, which competitive.c's hook of open_pallet reads from the Lua stack"""
    p['constants'] = []
    k = lambda value: constant(p, value)
    prg, open_pallet = k('prg_func'), k('open_pallet')
    zero, one = constant(p, 0, 19), constant(p, 1, 19)
    p['code'] = [abc('EQ', 0, 1, 256 + zero), abx('JMP', 0, 131071 + 1), abc('RETURN', 0, 1),
                 abc('GETTABUP', 0, 0, 256 + prg), abc('GETTABLE', 0, 0, 256 + open_pallet),
                 abc('MOVE', 4, 1), abx('LOADK', 1, zero), abc('MOVE', 2, 1), abx('LOADK', 3, one),
                 abc('CALL', 0, 5, 1), abc('RETURN', 0, 1)]
    p['meta'] = p['meta'][:8] + bytes((2, 0, 5))
    p['lines'], p['locals'], p['upnames'] = b'', [], []


def top(data):
    chunk = Chunk(data)
    init = chunk.root['protos'][0]
    values = [v for _, v in init['constants']]
    for s in ('set_parts_btn_spirits', 'set_parts_btn_online', 'set_parts_btn_colle', 'set_parts_btn_other',
              'set_parts_btn_eshop', 'callback_eshop_decide'):
        if s not in values:
            raise ValueError('unexpected main menu initializer: no ' + s)
    at = values.index('directional_degree') + 1
    kind, _ = init['constants'][at]
    init['constants'][at] = (kind, DIRECTIONAL_DEGREE)
    k = lambda s: constant(init, s)
    decide, arg, callback, seq_key = k('func_decide'), k('func_arg'), k('callback_eshop_decide'), k('sequence')
    nums = {v: constant(init, v, 19) for v in set(PLACEHOLDER.values())}
    seqs = {name: k(s) for name, s in SEQUENCE.items()}
    values = [v for _, v in init['constants']]
    out, current, done = [], None, set()
    for w in init['code']:
        op, a, b, c = OPS[w & 63], w >> 6 & 255, w >> 23, w >> 14 & 511
        name = lambda x: values[x - 256] if x >= 256 else None
        if op == 'SETTABLE' and name(b) == 'parts' and c >= 256:
            current = name(c)
        # the value read for the button: a state (GETTABUP STATE_*) or the eShop callback (GETTABLE callback_eshop_decide)
        if current in PLACEHOLDER and op == 'GETTABUP' and str(name(c)).startswith('STATE_'):
            out.append(abc('GETTABLE', a, 0, 256 + callback))
        elif current in SEQUENCE and ((op == 'GETTABUP' and str(name(c)).startswith('STATE_'))
                                      or (op == 'GETTABLE' and name(c) == 'callback_eshop_decide')):
            out.append(abc('GETTABUP', a, 0, 256 + seqs[current]))
        # the key it is stored under
        elif current in PLACEHOLDER and op == 'SETTABLE' and name(b) in ('state', 'func_decide'):
            out.extend((abc('SETTABLE', a, 256 + decide, c), abc('SETTABLE', a, 256 + arg, 256 + nums[PLACEHOLDER[current]])))
            done.add(current)
        elif current in SEQUENCE and op == 'SETTABLE' and name(b) in ('state', 'func_decide'):
            out.append(abc('SETTABLE', a, 256 + seq_key, c))
            done.add(current)
        else:
            out.append(w)
    missing = (set(PLACEHOLDER) | set(SEQUENCE)) - done
    if missing:
        raise ValueError('buttons not rerouted: ' + ', '.join(sorted(missing)))
    init['code'] = out
    init['lines'], init['locals'], init['upnames'] = b'', [], []
    callback_proto(chunk.root['protos'][1])
    return chunk.dump()


common = menu_actions.common          # ZR does not open the (hidden) side bar
