"""Transform the owner's menu bytecode: four selectable tiles and real routes.

MenuSequenceScene's local exit dispatch (13.0.4, 0x710232ce40; jump table
0x71044fc8c0) maps exit 5 to the LocalTop state (6), and exit 7 to state 15.
These values were inferred from the local dump; runtime verification is
recorded in README.md. This tool contains no original game instructions.
"""
from lua_chunk import Chunk, abc, abx, constant, OPS


# buttons taken out of the cursor's table: Online (the Ranked card is drawn by the Vault button: the Online tile's own
# selection glow is not part of the layout) and eShop
UNLISTED = ('set_parts_btn_online', 'set_parts_btn_eshop')


def callback_proto(p):
    p['constants'] = []
    k = lambda value: constant(p,value)
    prg, open_pallet = k('prg_func'), k('open_pallet')
    zero = constant(p, 0, 19)
    one = constant(p, 1, 19)
    # argument 0 (the Ranked card, not playable yet): return at once, the menu stays as it is
    p['code'] = [abc('EQ',0,1,256+zero), abx('JMP',0,131071+1), abc('RETURN',0,1),
                 abc('GETTABUP',0,0,256+prg), abc('GETTABLE',0,0,256+open_pallet),
                 abx('LOADK',1,zero),abc('MOVE',2,1),abx('LOADK',3,one),abc('MOVE',4,1),
                 abc('CALL',0,5,1), abc('RETURN',0,1)]
    p['meta'] = p['meta'][:8] + bytes((2,0,5))
    p['lines'], p['locals'], p['upnames'] = b'', [], []


def top(data):
    chunk = Chunk(data)
    init = chunk.root['protos'][0]
    values = [v for _,v in init['constants']]
    if not all(s in values for s in ('set_parts_btn_spirits','set_parts_btn_other','STATE_SPIRITS_IN','STATE_OTHER_IN')):
        raise ValueError('unexpected main menu initializer')
    k = lambda s: constant(init,s)
    decide, arg, callback = [k(s) for s in ('func_decide','func_arg','callback_eshop_decide')]
    sequence, option = [k(s) for s in ('sequence','SEQUENCE_OPTION')]
    five, seven, zero = constant(init,5,19), constant(init,7,19), constant(init,0,19)
    output, current, table = [], None, None
    for w in init['code']:
        op,a,b,c = OPS[w&63], w>>6&255, w>>23, w>>14&511
        if op == 'SETTABLE' and b >= 256 and values[b-256] == 'parts' and c >= 256:
            current = values[c-256]
        if op == 'GETTABLE' and c >= 256 and values[c-256] == 'button_table':
            table = 'button_table'
        elif op == 'GETTABLE' and c >= 256 and values[c-256] in ('footer_table','preview_table'):
            table = values[c-256]
        if op == 'GETTABUP' and c >= 256 and values[c-256]=='STATE_OTHER_IN':
            output.append(abc('GETTABUP',a,0,256+option))
        elif op == 'SETTABLE' and current=='set_parts_btn_other' and b>=256 and values[b-256]=='state':
            output.append(abc('SETTABLE',a,256+sequence,c))
        elif op == 'GETTABUP' and c >= 256 and values[c-256] in ('STATE_COLLECTION_IN','STATE_SPIRITS_IN'):
            output.append(abc('GETTABLE',a,0,256+callback))
        elif op == 'SETTABLE' and current in ('set_parts_btn_spirits','set_parts_btn_other','set_parts_btn_colle') and b >= 256 and values[b-256]=='state':
            value = {'set_parts_btn_spirits': five, 'set_parts_btn_other': seven, 'set_parts_btn_colle': zero}[current]
            output.extend((abc('SETTABLE',a,256+decide,c),abc('SETTABLE',a,256+arg,256+value)))
        elif table == 'button_table' and current in UNLISTED and op == 'SETTABLE' and a==1 and b==2 and c==3:
            output.append(abc('MOVE',0,0))
        else:
            output.append(w)
    init['code'] = output
    init['lines'], init['locals'], init['upnames'] = b'', [], []
    callback_proto(chunk.root['protos'][1])
    return chunk.dump()


def main_menu(data):
    chunk = Chunk(data)
    p = chunk.root['protos'][8]
    values = [v for _,v in p['constants']]
    if values[-1] != 'SCENE_EXIT_CODE_NORMAL':
        raise ValueError('unexpected main menu finish routine')
    key = constant(p,'competitive_exit_code')
    exit_key = constant(p,'exit_code')
    # Apply a requested local destination after the ordinary fade/finalization.
    p['code'][-1:] = [abc('GETTABUP',0,0,256+key),abc('TEST',0,0,0),
                     abx('JMP',0,131072),abc('SETTABUP',0,256+exit_key,0),abc('RETURN',0,1)]
    p['lines'], p['locals'], p['upnames'] = b'', [], []
    init = chunk.root['protos'][1]
    key = constant(init,'competitive_exit_code')
    init['code'][:0] = [abc('LOADNIL',1,0),abc('SETTABUP',0,256+key,1)]
    init['lines'], init['locals'], init['upnames'] = b'', [], []
    return chunk.dump()


def common(data):
    chunk = Chunk(data)
    p = chunk.root['protos'][1]
    values = [v for _,v in p['constants']]
    for i,w in enumerate(p['code']):
        if OPS[w&63] == 'GETTABUP' and (w>>14&511)>=256 and values[(w>>14&511)-256]=='prg_func':
            next_word=p['code'][i+1]
            if OPS[next_word&63]=='GETTABLE' and values[(next_word>>14&511)-256]=='open_pallet':
                p['code'][i] = abc('RETURN',0,1)
                break
    else:
        raise ValueError('pallet action not found')
    return chunk.dump()


def footer(data):
    """Keep the native help controller; its layout is hidden separately."""
    return data
