"""A READING of a relocatable code module of the old console (public format), not a translation: header, sections,
import tables, relocations by kind and target, the tables of function pointers in its data (virtual tables / status
tables), function starts in its code found by the relocation targets and the stack-frame opening instruction, and
the text strings it carries. No instruction is decoded beyond recognising two fixed bit patterns (function entry,
return); nothing is executed.

    python -I rel.py <module.rel> [<out .txt>]
"""
import struct
import sys

R_NAMES = {1: 'ADDR32', 2: 'ADDR24', 3: 'ADDR16', 4: 'ADDR16_LO', 5: 'ADDR16_HI', 6: 'ADDR16_HA', 7: 'ADDR14',
           10: 'REL24', 11: 'REL14', 201: 'NOP', 202: 'SECTION', 203: 'END'}


def read(d):
    h = struct.unpack_from('>12I', d, 0)
    info = {'id': h[0], 'sections': h[3], 'section_off': h[4], 'version': h[7], 'bss': h[8], 'rel_off': h[9],
            'imp_off': h[10], 'imp_size': h[11]}
    pro = struct.unpack_from('>4B3I', d, 0x30)
    info['prolog'], info['epilog'], info['unresolved'] = (pro[0], pro[4]), (pro[1], pro[5]), (pro[2], pro[6])
    secs = []
    for i in range(info['sections']):
        off, size = struct.unpack_from('>II', d, info['section_off'] + i * 8)
        secs.append({'index': i, 'offset': off & ~1, 'size': size, 'exec': bool(off & 1)})
    imports = []
    for i in range(info['imp_size'] // 8):
        mod, off = struct.unpack_from('>II', d, info['imp_off'] + i * 8)
        rels = []
        p = off
        sec, pos = 0, 0
        while True:
            delta, typ, s, addend = struct.unpack_from('>HBBI', d, p)
            p += 8
            pos += delta
            if typ == 203:
                break
            if typ == 202:
                sec, pos = s, 0
                continue
            if typ == 201:
                continue
            rels.append((sec, pos, typ, s, addend))
        imports.append((mod, rels))
    return info, secs, imports


def report(d, out):
    w = out.append
    info, secs, imports = read(d)
    w('module id %d, format version %d, %d sections, bss %d bytes' % (info['id'], info['version'], info['sections'],
                                                                     info['bss']))
    w('entry points (section, offset): prolog %s, epilog %s, unresolved %s' % (info['prolog'], info['epilog'],
                                                                              info['unresolved']))
    for s in secs:
        if s['size']:
            w('  section %2d  %s  file offset %#8x  size %7d' % (s['index'], 'CODE' if s['exec'] else (
                'data' if s['offset'] else 'bss '), s['offset'], s['size']))
    code = [s for s in secs if s['exec']]
    self_ptrs = {}                  # (data section, offset) -> (target section, target offset)
    for mod, rels in imports:
        kinds = {}
        targets = set()
        for sec, pos, typ, tsec, addend in rels:
            kinds[R_NAMES.get(typ, typ)] = kinds.get(R_NAMES.get(typ, typ), 0) + 1
            targets.add((tsec, addend))
            if mod == info['id'] and typ == 1 and not secs[sec]['exec'] and secs[tsec]['exec']:
                self_ptrs[(sec, pos)] = (tsec, addend)
        w('import table for module %d%s: %d relocations %s, %d distinct targets' % (
            mod, ' (the main program)' if mod == 0 else (' (itself)' if mod == info['id'] else ' (another module)'),
            len(rels), dict(sorted(kinds.items(), key=lambda x: str(x[0]))), len(targets)))
        if mod not in (info['id'],):
            calls = {}
            for sec, pos, typ, tsec, addend in rels:
                if typ == 10:
                    calls[addend] = calls.get(addend, 0) + 1
            top = sorted(calls.items(), key=lambda x: -x[1])[:12]
            w('    direct calls into it: %d sites, %d distinct functions; most called (address or section offset x '
              'sites): %s' % (sum(calls.values()), len(calls), ', '.join('%#x x%d' % t for t in top)))
    # function starts: targets of own relocations into code + the frame-opening pattern
    starts = set()
    for mod, rels in imports:
        if mod == info['id']:
            for sec, pos, typ, tsec, addend in rels:
                if secs[tsec]['exec']:
                    starts.add((tsec, addend))
    n_entry = n_ret = 0
    for s in code:
        for o in range(0, s['size'] - 3, 4):
            ins = struct.unpack_from('>I', d, s['offset'] + o)[0]
            if ins >> 16 == 0x9421 and ins & 0x8000:      # open a stack frame
                n_entry += 1
                starts.add((s['index'], o))
            elif ins == 0x4E800020:                       # return
                n_ret += 1
    w('code: %d bytes in %d section(s); %d frame-opening instructions, %d return instructions, %d distinct function '
      'starts (frame openings + own relocation targets in code)' % (sum(s['size'] for s in code), len(code), n_entry,
                                                                   n_ret, len(starts)))
    # tables of function pointers
    tables = []
    for key in sorted(self_ptrs):
        if tables and tables[-1][0] == key[0] and key[1] - tables[-1][2] <= 8:
            tables[-1][2] = key[1]
            tables[-1][3] += 1
        else:
            tables.append([key[0], key[1], key[1], 1])
    w('tables of pointers to its own functions in its data: %d pointers in %d runs; sizes of the runs: %s' % (
        len(self_ptrs), len(tables), ' '.join(str(t[3]) for t in sorted(tables, key=lambda t: -t[3])[:60])))
    used = {v for v in self_ptrs.values()}
    w('distinct functions reachable through those tables: %d' % len(used))
    sizes = sorted(a for (sidx, a) in starts if sidx == code[0]['index']) if code else []
    lens = [b - a for a, b in zip(sizes, sizes[1:])]
    if lens:
        big = sorted(zip(lens, sizes), reverse=True)[:15]
        w('largest functions (bytes at code offset): %s' % ', '.join('%d at %#x' % t for t in big))
    # strings
    strs = []
    for s in secs:
        if s['exec'] or not s['offset']:
            continue
        blob = d[s['offset']:s['offset'] + s['size']]
        cur = bytearray()
        for b in blob + b'\0':
            if 32 <= b < 127:
                cur.append(b)
            else:
                if len(cur) >= 5:
                    strs.append(cur.decode('ascii'))
                cur = bytearray()
    w('text strings in the data sections: %d' % len(strs))
    for t in strs[:400]:
        w('    ' + t)
    return info, secs, imports, tables, self_ptrs


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
    else:
        with open(sys.argv[1], 'rb') as f:
            data = f.read()
        lines = []
        report(data, lines)
        if len(sys.argv) > 2:
            with open(sys.argv[2], 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines) + '\n')
            print('%d lines written to %s' % (len(lines), sys.argv[2]))
        else:
            print('\n'.join(lines))
