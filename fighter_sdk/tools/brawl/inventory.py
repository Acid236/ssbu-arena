"""Inventory of an extracted fighter package of the Wii predecessor's mod builds.

    python -I inventory.py <extracted package folder> [--hitboxes] [--textures <png folder>]

Walks every archive (.pac / .pcs), names each entry's format and counts what is inside (bones, meshes, vertices,
triangles, textures by format, animations by class with frame counts and track encodings, sub-actions and script
commands of the moveset file). Other files are listed with a format guess from their first bytes. Every reader
runs its sanity checks on the way (index ranges, finite values, key order). Nothing from the package is executed.
"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brawl import arc, brres, chr0, mdl0, psa, tex0     # noqa: E402

MAGICS = [(b'RSTM', 'stream audio (BRSTM)'), (b'THP\0', 'movie (THP)'), (b'\x89PNG', 'PNG image'),
          (b'MDL0', 'model (MDL0)'), (b'CLR0', 'colour animation (CLR0)'), (b'bres', 'resource directory'),
          (b'ARC\0', 'archive'), (b'RSAR', 'sound archive'), (b'RWSD', 'sound data')]


def guess(path, head):
    low = path.lower()
    for m, name in MAGICS:
        if head.startswith(m):
            return name
    if low.endswith('.rel'):
        return 'relocatable code module (machine code of the console CPU): CODE'
    if low.endswith('.sawnd'):
        return 'sound bank patch (sound data + wave data)'
    if low.endswith(('.json', '.xml', '.txt', '.ini', '.asm')):
        return 'text / configuration'
    if low.endswith('.exe') or head[:2] == b'MZ' or head[:4] == b'\x7fELF':
        return 'PC program of the mod build tools (never run here)'
    return 'unknown'


def rel_summary(d):
    """Header fields of a relocatable module (public format): section count, sizes, entry points."""
    (mid, _n, _p, nsec, sec_off, name_off, name_size, ver, bss, rel_off, imp_off, imp_size) = struct.unpack_from(
        '>12I', d, 0)
    code = data = 0
    for i in range(nsec):
        off, size = struct.unpack_from('>II', d, sec_off + i * 8)
        if off & 1:
            code += size
        elif off:
            data += size
    return 'module id %d, version %d, %d sections: %d bytes executable, %d bytes data, %d bytes bss, %d import ' \
           'tables' % (mid, ver, nsec, code, data, bss, imp_size // 8)


def model_line(m, check):
    tv = tt = 0
    maxinf = 0
    problems = []
    for me in m.meshes:
        try:
            m.decode(me)
        except Exception as ex:           # report, keep going
            problems.append('%s: %s' % (me.name, ex))
            continue
        n = len(me.positions)
        tv += n
        tt += len(me.triangles)
        if any(max(t) >= n for t in me.triangles):
            problems.append('%s: index out of range' % me.name)
        if not all(math.isfinite(x) for p in me.positions for x in p):
            problems.append('%s: non-finite position' % me.name)
        for w in me.weights:
            maxinf = max(maxinf, len(w))
            if abs(sum(x[1] for x in w) - 1.0) > 1e-3:
                problems.append('%s: weights do not sum to 1' % me.name)
                break
    worst = 0.0
    stale = []
    for b in m.bones:
        dlt = max(abs(b.world[i][j] - b.stored_world[i][j]) for i in range(3) for j in range(4))
        if dlt > 1e-3:
            stale.append(b.name)
        else:
            worst = max(worst, dlt)
    s = 'MDL0 v%d %s: %d bones, %d meshes, %d materials, %d unique vertices, %d triangles (header: %d), ' \
        'influences <= %d, box (%.1f %.1f %.1f)-(%.1f %.1f %.1f); bone matrices recomputed vs stored: worst %.1e' % (
            m.version, m.name, len(m.bones), len(m.meshes), len(m.materials), tv, tt, m.num_triangles, maxinf,
            *m.box_min, *m.box_max, worst)
    if stale:
        s += '; stored matrix differs from the recomputed one for: ' + ', '.join(stale)
    if tt != m.num_triangles:
        problems.append('triangle count differs from the header')
    check['models'] += 1
    check['problems'] += problems
    return s


def walk(a, ind, out, check, opts, label):
    for e in a.entries:
        k = e.kind()
        head = '%s- entry type %d (%s) index %d group %d: %d bytes%s' % (
            ind, e.type, arc.ENTRY_TYPES.get(e.type, '?'), e.index, e.group, e.size,
            ' [redirect to entry %d]' % e.redirect if e.redirect >= 0 else '')
        if k == 'ARC':
            sub = arc.Arc(e.data)
            out.append(head + ': nested archive "%s", %d entries' % (sub.name, len(sub.entries)))
            walk(sub, ind + '  ', out, check, opts, label)
        elif k == 'BRRES':
            b = brres.Brres(e.data)
            out.append(head + ': resource directory ' + ', '.join('%s x%d' % kv for kv in b.counts().items()))
            for name, off in b.models():
                out.append(ind + '    ' + model_line(mdl0.Mdl0(e.data, off), check))
            pal = {}
            for name, off in b.palettes():
                pal[name] = tex0.read_palette(e.data, off)
            fm = {}
            for name, off in b.textures():
                t = tex0.Tex0(e.data, off)
                fm[t.format_name] = fm.get(t.format_name, 0) + 1
                check['textures'] += 1
                check['formats'][t.format_name] = check['formats'].get(t.format_name, 0) + 1
                if opts.get('textures'):
                    w, h, rgba = t.decode(pal[name][0] if name in pal else None)
                    tex0.write_png(os.path.join(opts['textures'], '%s_%s.png' % (label, name)), w, h, rgba)
                elif t.format in (8, 9, 10) and name not in pal:
                    check['problems'].append('texture %s: no palette of the same name' % name)
            if fm:
                out.append(ind + '    textures by format: ' + ', '.join('%s x%d' % kv for kv in sorted(fm.items())))
            anims = b.chr()
            if anims:
                frames = 0
                kinds = {}
                bad = 0
                for name, off in anims:
                    c = chr0.Chr0(e.data, off)
                    frames += c.frames
                    for kk, v in c.track_kinds().items():
                        kinds[kk] = kinds.get(kk, 0) + v
                    for en in c.entries:
                        for part in (en.scale, en.rot, en.trans):
                            for t in part or ():
                                if t.keys is not None:
                                    fr = [x[0] for x in t.keys]
                                    if fr != sorted(fr) or fr[-1] > c.frames + 1 or not all(
                                            math.isfinite(x[1]) for x in t.keys):
                                        bad += 1
                                elif t.values is not None and not all(math.isfinite(x) for x in t.values):
                                    bad += 1
                check['anims'] += len(anims)
                check['frames'] += frames
                check['bad_tracks'] += bad
                out.append(ind + '    CHR0 x%d: %d frames in total; tracks by encoding: %s; tracks failing the '
                           'key-order / finite check: %d' % (len(anims), frames, ', '.join(
                               '%s x%d' % kv for kv in sorted(kinds.items())), bad))
        elif k == 'EFLS':
            out.append(head + ': effect list (names of effect resources)')
        elif e.type == 1 and e.size > 0x40:
            try:
                p = psa.Psa(e.data)
                line = head + ': moveset / parameter data: sections %s; %d external references' % (
                    ', '.join(p.sections) or '-', len(p.externals))
                if p.subactions:
                    total, seen = p.event_census()
                    nh = sum(1 for s in p.subactions for h in p.hitboxes(s) if h['kind'].startswith('hitbox'))
                    named = sum(1 for s in p.subactions if s['name'])
                    line += '; %d sub-actions (%d with an animation name), %d script commands in their 4 lists ' \
                            '(%d distinct), %d hitbox commands' % (p.subaction_count, named, total, len(seen), nh)
                    check['psa'].append((label, p))
                out.append(line)
            except Exception as ex:
                out.append(head + ': misc data (not read as a moveset file: %s)' % ex)
        else:
            out.append(head)


def main(argv):
    root = argv[0]
    opts = {}
    if '--textures' in argv:
        opts['textures'] = argv[argv.index('--textures') + 1]
        os.makedirs(opts['textures'], exist_ok=True)
    check = {'models': 0, 'textures': 0, 'formats': {}, 'anims': 0, 'frames': 0, 'bad_tracks': 0, 'problems': [],
             'psa': []}
    total = 0
    for dirpath, dirs, files in os.walk(root):
        dirs.sort()
        for fn in sorted(files):
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root).replace('\\', '/')
            size = os.path.getsize(p)
            total += size
            with open(p, 'rb') as f:
                data = f.read() if fn.lower().endswith(('.pac', '.pcs', '.rel')) else f.read(16)
            if fn.lower().endswith(('.pac', '.pcs')):
                a = arc.Arc(data)
                print('%s  %d bytes: archive "%s", %d entries%s' % (
                    rel, size, a.name, len(a.entries), ', LZ77-compressed (%d unpacked)' % a.size if a.compressed
                    else ''))
                out = []
                walk(a, '  ', out, check, opts, os.path.splitext(fn)[0])
                print('\n'.join(out))
            elif fn.lower().endswith('.rel'):
                print('%s  %d bytes: %s; %s' % (rel, size, guess(p, data[:16]), rel_summary(data)))
            else:
                print('%s  %d bytes: %s' % (rel, size, guess(p, data)))
    print()
    print('TOTAL %d bytes; models read %d, textures %d (%s), bone animations %d (%d frames), tracks failing checks '
          '%d' % (total, check['models'], check['textures'], ', '.join(
              '%s x%d' % kv for kv in sorted(check['formats'].items())), check['anims'], check['frames'],
              check['bad_tracks']))
    for p in check['problems']:
        print('PROBLEM: ' + p)
    if '--hitboxes' in argv:
        for label, p in check['psa']:
            print()
            print('HITBOX LISTING of %s (main script walked linearly; "var" = the value is a variable reference)'
                  % label)
            for s in p.subactions:
                hb = p.hitboxes(s)
                if not any(h['kind'] != 'remove all hitboxes' for h in hb):
                    continue
                print('sub-action %#x %s' % (s['index'], s['name']))
                for h in hb:
                    if h['kind'].startswith('hitbox'):
                        print('  frame %5.1f  %-16s id %d bone %d  damage %s angle %s  base %d growth %d fixed %d  '
                              'size %.2f offset (%.2f %.2f %.2f)  shield %d hitlag x%.2f sdi x%.2f trip %.2f '
                              'flags %#010x%s' % (
                                  h['frame'], h['kind'], h['id'], h['bone'], h['damage'], h['angle'], h['kb_base'],
                                  h['kb_growth'], h['kb_fixed'], h['size'], *h['offset'], h['shield_damage'],
                                  h['hitlag'], h['sdi'], h['trip'], h['flags'],
                                  ' var%s' % h['variable'] if h['variable'] else ''))
                    elif h['kind'] == 'remove all hitboxes':
                        print('  frame %5.1f  remove all hitboxes' % h['frame'])
                    else:
                        print('  frame %5.1f  %s %s' % (h['frame'], h['kind'], {k: v for k, v in h.items()
                                                                               if k not in ('frame', 'kind')}))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
    else:
        main(sys.argv[1:])
