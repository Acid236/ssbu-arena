"""Patch panes of the BFLYT layouts inside a LayoutLibrary SARC (layout.arc) in place: same file size, same offsets.
    python bflyt_patch.py <in layout.arc> <out layout.arc> <edits.json>
edits.json: {"<layout>.bflyt": {"<pane name>": {"pos": [x, y], "size": [w, h], "scale": [sx, sy], "alpha": 0..255,
                                                 "visible": true|false}}}
Positions are in the layout's own units (1920 x 1080, origin at the centre, +y up). Reads and writes only these
fields of pan1 / pic1 / txt1 / wnd1 / bnd1 / prt1 sections. No game content in this file."""
import json, struct, sys

# PRT1 record structure: public SwitchThemesCommon/Bflyt/Prt1Pane.cs and
# Switch-Toolbox File_Format_Library/FileFormats/Layout/CAFE/Panes/PRT1.cs.
# Basic pane-info offsets / usage bits below were inferred from this dump's
# overrides and checked against the game. No new records or content are added.


def texture_uv(d, pane, materials):
    """Use the picture's UVs instead of the original pane-size projection."""
    if d[pane:pane+4] != b'pic1' or d[pane+0x66] != 1:
        raise ValueError('texture_uv requires a one-coordinate picture')
    struct.pack_into('<8f', d, pane+0x68, 0,0,1,0,0,1,1,1)
    mat = materials[struct.unpack_from('<H',d,pane+0x64)[0]]
    flags = struct.unpack_from('<I',d,mat+28)[0]
    struct.pack_into('<I',d,mat+28,flags & ~0x18000)
    transform = mat + 44 + 4*(flags&3)
    for i in range((flags>>2)&3):
        struct.pack_into('<5f',d,transform+20*i,0,0,0,1,1)
    mapping = transform + 20*((flags>>2)&3)
    for i in range((flags>>4)&3):
        # Standard vertex UV generator (the same as the ordinary frame).
        d[mapping+16*i:mapping+16*i+16] = bytes(16)


def material_offsets(d, start, end):
    o = start + struct.unpack_from('<H',d,start+6)[0]
    while o < end:
        size = struct.unpack_from('<I',d,o+4)[0]
        if d[o:o+4] == b'mat1':
            return [o+struct.unpack_from('<I',d,o+12+4*i)[0]
                    for i in range(struct.unpack_from('<H',d,o+8)[0])]
        o += size
    return []


def texture_names(d, start, end):
    o = start + struct.unpack_from('<H', d, start + 6)[0]
    while o < end:
        size = struct.unpack_from('<I', d, o + 4)[0]
        if d[o:o+4] == b'txl1':
            count = struct.unpack_from('<H', d, o+8)[0]
            base = o + 12
            names = []
            for i in range(count):
                p = base + struct.unpack_from('<I', d, base+4*i)[0]
                names.append(d[p:d.index(0,p)].decode())
            return names
        o += size
    return []


def patch_parts(d, o, edits, materials):
    if d[o:o + 4] != b'prt1':
        raise ValueError('parts edits require a prt1 pane')
    end = o + struct.unpack_from('<I', d, o + 4)[0]
    count = struct.unpack_from('<I', d, o + 0x54)[0]
    entries = {}
    for i in range(count):
        r = o + 0x60 + 0x28 * i
        name = d[r:r + 24].split(b'\0', 1)[0].decode('ascii')
        entries[name] = r
    for name, changes in edits.items():
        if name not in entries:              # this button keeps the part's own pane (edited in the part's layout)
            continue
        r = entries[name]
        basic = struct.unpack_from('<I', d, r + 36)[0]
        prop = struct.unpack_from('<I', d, r + 28)[0]
        if changes.keys() & EXTRA_KEYS:
            if not prop:
                raise ValueError('no existing property pane for ' + name)
            pane_extras(d, o + prop, changes)
        for key, values in changes.items():
            if key in EXTRA_KEYS:
                continue
            if key == 'visible':
                if not prop:
                    raise ValueError('no existing property pane for ' + name)
                d[o + prop + 8] = (d[o + prop + 8] | 1) if values else (d[o + prop + 8] & ~1)
                continue
            if key == 'alpha':
                if not prop:
                    raise ValueError('no existing property pane for ' + name)
                d[o + prop + 10] = int(values)
                continue
            if key == 'texture_uv':
                prop = struct.unpack_from('<I',d,r+28)[0]
                if not prop:
                    raise ValueError('missing picture property for '+name)
                texture_uv(d,o+prop,materials)
                continue
            if key == 'font_size':
                prop = struct.unpack_from('<I', d, r + 28)[0]
                if not prop or o + prop + 0x78 > end or d[o + prop:o + prop + 4] != b'txt1':
                    raise ValueError('no existing text property for ' + name)
                struct.pack_into('<2f', d, o + prop + 0x70, *map(float, values))
                continue
            if not basic or o + basic + 52 > end:
                if not prop:
                    raise ValueError('no existing basic pane-info or property pane for ' + name)
                # the override is a whole copy of the pane: its own transform fields
                struct.pack_into('<2f', d, o + prop + {'pos': 0x2C, 'scale': 0x2C + 24, 'size': 0x2C + 32}[key], *map(float, values))
                continue
            offset, bit = {'pos': (8, 8), 'scale': (32, 32), 'size': (40, 16)}[key]
            struct.pack_into('<2f', d, o + basic + offset, *map(float, values))
            d[r + 25] |= bit

def pane_extras(d, o, ch):
    """origin (pane base position: x 0 centre / 1 left / 2 right, + 4 * y 0 centre / 1 top / 2 bottom),
    text_pos (the same encoding, where the text sits inside a txt1 pane), vertex_colors (pic1: four RGBA hex strings,
    top-left, top-right, bottom-left, bottom-right; the pane's material multiplies them), window_frames (wnd1: the
    left, right, top and bottom frame sizes; a frame as large as the window keeps it at its texture's shape)."""
    if 'origin' in ch:
        d[o + 9] = (d[o + 9] & 0xF0) | int(ch['origin'])
    if 'text_pos' in ch:
        if d[o:o + 4] != b'txt1':
            raise ValueError('text_pos requires a text pane')
        d[o + 0x5C] = int(ch['text_pos'])
    if 'window_frames' in ch:
        if d[o:o + 4] != b'wnd1':
            raise ValueError('window_frames requires a window pane')
        struct.pack_into('<4H', d, o + 0x5C, *map(int, ch['window_frames']))
    if 'vertex_colors' in ch:
        if d[o:o + 4] != b'pic1':
            raise ValueError('vertex_colors requires a picture pane')
        cols = ch['vertex_colors']
        if len(cols) != 4:
            raise ValueError('vertex_colors needs four colours')
        for i, c in enumerate(cols):
            d[o + 0x54 + 4 * i:o + 0x58 + 4 * i] = bytes.fromhex(c)


EXTRA_KEYS = {'origin', 'text_pos', 'vertex_colors', 'window_frames'}


def material_colours(d, o, ch, materials):
    """material_white / material_black (pic1): the RGBA hex colours of the picture's material (after its name and two
    words: black at +36, white at +40); the texture's white is drawn in the white colour."""
    if not ch.keys() & {'material_white', 'material_black'}:
        return
    if d[o:o + 4] != b'pic1':
        raise ValueError('material colours require a picture pane')
    mat = materials[struct.unpack_from('<H', d, o + 0x64)[0]]
    if 'material_black' in ch:
        d[mat + 36:mat + 40] = bytes.fromhex(ch['material_black'])
    if 'material_white' in ch:
        d[mat + 40:mat + 44] = bytes.fromhex(ch['material_white'])

PANES = (b'pan1', b'pic1', b'txt1', b'wnd1', b'bnd1', b'prt1', b'scr1', b'ali1')


def sarc_files(d):
    assert d[:4] == b'SARC'
    doff = struct.unpack_from('<I', d, 0xC)[0]
    sfat = 0x14; n = struct.unpack_from('<H', d, sfat + 6)[0]
    names = sfat + 0xC + 16 * n + 8
    out = {}
    for i in range(n):
        h, attr, s, e = struct.unpack_from('<IIII', d, sfat + 0xC + 16 * i)
        no = (attr & 0xFFFF) * 4
        out[d[names + no:d.index(b'\0', names + no)].decode()] = (doff + s, doff + e)
    return out


def panes(d, start, end):
    """name -> offset of its section, for one BFLYT at d[start:end]."""
    assert d[start:start + 4] == b'FLYT'
    o = start + struct.unpack_from('<H', d, start + 6)[0]
    out = {}
    while o + 8 <= end:
        mag, size = d[o:o + 4], struct.unpack_from('<I', d, o + 4)[0]
        if mag in PANES:
            out[d[o + 0xC:o + 0x24].split(b'\0', 1)[0].decode('ascii', 'replace')] = o
        if size < 8:
            break
        o += size
    return out


def apply(d, edits):
    d = bytearray(d)
    files = sarc_files(d)
    done = 0
    for lay, pe in edits.items():
        s, e = files['blyt/' + lay]
        idx = panes(d, s, e)
        materials = material_offsets(d,s,e)
        for name, ch in pe.items():
            o = idx[name]
            unknown = ch.keys() - {'visible', 'alpha', 'pos', 'scale', 'size', 'parts', 'font_size', 'texture_uv', 'texture', 'material_like', 'material_white', 'material_black'} - EXTRA_KEYS
            if unknown:
                raise ValueError('unknown pane fields: ' + ', '.join(sorted(unknown)))
            if 'visible' in ch:
                d[o + 8] = (d[o + 8] | 1) if ch['visible'] else (d[o + 8] & ~1)
            if 'alpha' in ch:
                d[o + 10] = int(ch['alpha'])
            if 'pos' in ch:
                struct.pack_into('<2f', d, o + 0x2C, *map(float, ch['pos']))
            if 'scale' in ch:
                struct.pack_into('<2f', d, o + 0x2C + 24, *map(float, ch['scale']))
            if 'size' in ch:
                struct.pack_into('<2f', d, o + 0x2C + 32, *map(float, ch['size']))
            if 'font_size' in ch:
                if d[o:o+4] != b'txt1':
                    raise ValueError('font_size requires text pane')
                struct.pack_into('<2f', d, o + 0x70, *map(float, ch['font_size']))
            if 'parts' in ch:
                patch_parts(d, o, ch['parts'], materials)
            if 'material_like' in ch:
                source_layout, source_pane = ch['material_like']
                ss, se = files['blyt/' + source_layout]
                smats = material_offsets(d,ss,se)
                sp = panes(d,ss,se)[source_pane]
                si = struct.unpack_from('<H',d,sp+0x64)[0]
                di = struct.unpack_from('<H',d,o+0x64)[0]
                sm, dm = smats[si], materials[di]
                # Both chosen materials precede another entry; never grow or relocate a record.
                length, capacity = smats[si+1]-sm, materials[di+1]-dm
                if length > capacity:
                    raise ValueError('source material exceeds destination capacity')
                d[dm+28:dm+length] = d[sm+28:sm+length]
            if ch.get('texture_uv'):
                texture_uv(d,o,materials)
            if 'texture' in ch:
                if d[o:o+4] != b'pic1':
                    raise ValueError('texture requires a picture pane')
                mat = materials[struct.unpack_from('<H',d,o+0x64)[0]]
                if struct.unpack_from('<I',d,mat+28)[0] & 3 != 1:
                    raise ValueError('texture requires a single-texture material')
                index = texture_names(d,s,e).index(ch['texture'])
                struct.pack_into('<H',d,mat+44,index)
            pane_extras(d, o, ch)
            material_colours(d, o, ch, materials)
            done += 1
    return bytes(d), done


if __name__ == '__main__':
    src, dst, ej = sys.argv[1:4]
    out, n = apply(open(src, 'rb').read(), json.load(open(ej)))
    open(dst, 'wb').write(out)
    print('%d panes patched -> %s' % (n, dst))
