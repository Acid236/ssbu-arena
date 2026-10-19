"""Find what the installer needs on this PC: prod.keys, a firmware (or its fonts), and your own copy of the game.

    python scripts/find_inputs.py [--json] [paths ...]

paths (optional): extra files or folders to look at - a game file, a folder with game files, an emulator folder (the one with
the emulator exe: portable `user\\keys` and `user\\nand` are looked at), a firmware folder.

As a module:  from find_inputs import scan;  r = scan(extra=())  ->
    dict(keys=[...], firmware=[...], base=[...], updates=[...], dlc=[...], dumps=[...], best=dict(...), notes=[...])
Every item is a dict with at least 'path' and 'desc' (a plain sentence); see the functions below for the other fields.

Nothing is decrypted or copied and no key VALUE is ever read into a result: of a keys file only the key NAMES are looked at
(header_key, key_area_key_application_*, titlekek_*). Game files are recognised from their names ([01006A800016E000][v...])
or a cheap look at the package header (a .nsp/.nsz lists tickets named after their rights id, whose first 16 hex digits are
the title id). Stdlib only, Python 3.10+; works with the python.org embeddable package.

The places searched follow the layout described by WindowSmash's installer (SNO2207/WindowSmash, tools/install_windowsmash.ps1:
emulator key folders, nand\\system\\Contents\\registered, qt-config.ini gamedirs); the code here is written for this project.
"""
import json
import os
import re
import struct
import sys
import time

APP_ID = 0x01006A800016E000                 # Super Smash Bros. Ultimate (base)
UPDATE_ID = 0x01006A800016E800              # its update
# update version number -> game build (docs/VERSIONS.md: 13.0.4 = v1966080, 13.0.5 = v2031616)
BUILDS = {1966080: '13.0.4', 2031616: '13.0.5'}
BUILD_ORDER = ['13.0.5', '13.0.4']          # newest first
GAME_EXT = ('.xci', '.nsp', '.nsz', '.xcz', '.nca')
HUGE = 4 << 30                              # an .xci/.nsp this big and called Smash is a game even if its name has no id

NEEDED_KEYS = ('header_key', 'key_area_key_application_', 'titlekek_')

_SKIP_DIRS = {'.git', 'node_modules', '__pycache__', 'windows', 'program files', 'program files (x86)', 'appdata',
              '$recycle.bin', 'system volume information', 'build', 'toolchain', 'ghidra', 'graphify-out'}


def _env(name):
    return os.environ.get(name) or ''


def _appdata():
    return _env('APPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Roaming')


def _isdir(p):
    try:
        return os.path.isdir(p)
    except OSError:
        return False


def _isfile(p):
    try:
        return os.path.isfile(p)
    except OSError:
        return False


def _listdir(p):
    try:
        return os.listdir(p)
    except OSError:
        return []


def _size(p):
    try:
        return os.path.getsize(p)
    except OSError:
        return 0


def _gb(n):
    return '%.2f GB' % (n / 2 ** 30)


# --------------------------------------------------------------------------------------------------------- emulators

EMULATORS = ('yuzu', 'suyu', 'sudachi', 'eden', 'citron', 'torzu', 'sumi', 'lime', 'nex', 'kenji-nx')


def emulator_dirs():
    """-> [(emulator name, data dir)] for every installed or portable-looking emulator data folder that exists."""
    ad, local, home = _appdata(), _env('LOCALAPPDATA'), os.path.expanduser('~')
    out = []
    for name in EMULATORS:
        for base in (ad, local, os.path.join(home, '.local', 'share'), os.path.join(home, '.config')):
            for variant in (name, name.capitalize(), name.upper(), name + '-emu'):
                d = os.path.join(base, variant)
                if _isdir(d) and (name, d) not in out:
                    out.append((name, d))
    for variant in ('Ryujinx', 'ryujinx'):
        for base in (ad, os.path.join(home, '.config')):
            d = os.path.join(base, variant)
            if _isdir(d):
                out.append(('ryujinx', d))
    return out


def portable_dirs(extra_dirs):
    """Emulator folders given by the user (the one with the exe): <dir>\\user is a yuzu-family portable data folder,
    <dir>\\portable a Ryujinx one."""
    out = []
    for d in extra_dirs:
        for sub, name in (('user', 'portable-yuzu-family'), ('portable', 'ryujinx'), ('', 'folder')):
            p = os.path.join(d, sub) if sub else d
            if _isdir(p):
                out.append((name, p))
    return out


def keys_dirs(emus):
    out = [os.path.join(os.path.expanduser('~'), '.switch')]
    for name, d in emus:
        if name == 'ryujinx':
            out += [os.path.join(d, 'system')]
        else:
            out += [os.path.join(d, 'keys'), d]
    return out


# ---------------------------------------------------------------------------------------------------------- keys

def key_names(path):
    """The key NAMES of a keys file (never the values): a set of str."""
    names = set()
    try:
        with open(path, 'r', errors='replace') as f:
            for line in f:
                if '=' in line:
                    names.add(line.split('=', 1)[0].strip().lower())
    except OSError:
        pass
    return names


def describe_keys(path):
    names = key_names(path)
    base = os.path.basename(path).lower()
    item = {'path': path, 'file': base, 'names': len(names)}
    if base.startswith('prod'):
        kaek = sorted(n for n in names if re.fullmatch(r'key_area_key_application_[0-9a-f]{2}', n))
        tk = sorted(n for n in names if re.fullmatch(r'titlekek_[0-9a-f]{2}', n))
        has_header = 'header_key' in names
        item.update(header_key=has_header, key_area_key_application=len(kaek), titlekek=len(tk),
                    newest_generation=max([int(n.rsplit('_', 1)[1], 16) for n in kaek + tk] or [-1]))
        item['complete'] = bool(has_header and kaek and tk)
        miss = [x for x, ok in (('header_key', has_header), ('key_area_key_application_*', bool(kaek)),
                                ('titlekek_*', bool(tk))) if not ok]
        item['desc'] = ('%s: prod.keys, has what decrypting needs (header_key, %d key_area_key_application, %d titlekek, up to '
                        'generation %02x)' % (path, len(kaek), len(tk), item['newest_generation'])
                        if item['complete'] else '%s: prod.keys, but missing: %s' % (path, ', '.join(miss)))
    else:
        item.update(complete=bool(names), kind='title.keys')
        item['desc'] = '%s: title.keys (%d title key entries)' % (path, len(names))
    return item


def find_keys(dirs):
    out, seen = [], set()
    for d in dirs:
        for fname in ('prod.keys', 'title.keys'):
            p = os.path.join(d, fname)
            if _isfile(p):
                key = os.path.normcase(os.path.abspath(p))
                if key not in seen:
                    seen.add(key)
                    out.append(describe_keys(p))
    return out


# ---------------------------------------------------------------------------------------------------- firmware / fonts

def _nca_entries(d):
    """NCAs of a folder: loose files `x.nca` or yuzu/Ryujinx-style folders `x.nca\\00`. -> (count, cnmt count)."""
    n = c = 0
    for name in _listdir(d):
        if name.lower().endswith('.nca'):
            n += 1
            c += name.lower().endswith('.cnmt.nca')
    return n, c


def firmware_at(d):
    """-> item for a folder that holds a firmware (NCA files) or the extracted system fonts, else None."""
    if not _isdir(d):
        return None
    names = _listdir(d)
    low = [x.lower() for x in names]
    n, c = _nca_entries(d)
    if n >= 40:
        packed = any(_isdir(os.path.join(d, x)) for x in names[:5] if x.lower().endswith('.nca'))
        return {'kind': 'nca-folder', 'path': d, 'ncas': n, 'nca_folders': packed,
                'use': '--firmware "%s"' % d,
                'desc': 'firmware: %d NCA %s in %s (for tools/extract/dump_folder.py --firmware)' % (
                    n, 'folders (x.nca\\00)' if packed else 'files', d)}
    font_ext = ('.ttf', '.bfttf', '.otf')
    fonts = [x for x in low if x.endswith(font_ext) and 'nintendo' in x]     # the Switch's own font names
    if not fonts and os.path.basename(d).lower() == 'fonts':                 # a folder called fonts: any font file
        fonts = [x for x in low if x.endswith(font_ext)]
    if fonts:
        return {'kind': 'fonts', 'path': d, 'fonts': len(fonts),
                'use': 'copy to <dump>\\sysdata\\fonts',
                'desc': 'system fonts already extracted: %d font files in %s (the <dump>\\sysdata\\fonts layout)' % (len(fonts), d)}
    return None


def firmware_candidates(emus, extra_dirs):
    out = []
    for name, d in emus + portable_dirs(extra_dirs):
        for sub in (('nand', 'system', 'Contents', 'registered'), ('bis', 'system', 'Contents', 'registered'),
                    ('nand', 'system', 'contents', 'registered'), ('system', 'Contents', 'registered'),
                    ('sysdata', 'fonts'), ('fonts',)):
            out.append(os.path.join(d, *sub))
    out += [os.path.join(os.path.expanduser('~'), 'Downloads'), os.path.join(os.path.expanduser('~'), 'Desktop'),
            os.path.join(os.path.expanduser('~'), 'Documents')]
    out += list(extra_dirs)
    return out


def find_firmware(emus, extra_dirs):
    found, seen = [], set()

    def add(item):
        k = os.path.normcase(os.path.abspath(item['path']))
        if item and k not in seen:
            seen.add(k)
            found.append(item)

    for d in firmware_candidates(emus, extra_dirs):
        it = firmware_at(d)
        if it:
            add(it)
        # one level below the "obvious" folders: Downloads\Firmware.22.5.0, a firmware unzipped in a named folder
        for sub in _listdir(d) if _isdir(d) and d in [os.path.join(os.path.expanduser('~'), x) for x in
                                                      ('Downloads', 'Desktop', 'Documents')] + list(extra_dirs) else []:
            p = os.path.join(d, sub)
            if _isdir(p) and (re.search(r'firmware|fw|sysdata|fonts', sub, re.I) or d in extra_dirs):
                it = firmware_at(p)
                if it:
                    add(it)
    return found


# ------------------------------------------------------------------------------------------------------- game files

_TID = re.compile(r'\[(01[0-9A-Fa-f]{14})\]')
_VER = re.compile(r'\[v(\d+)\]', re.I)
_BUILD = re.compile(r'\b(13\.0\.[45])\b')


def _ids_from_package(path):
    """Cheap header look at a .nsp/.nsz (PFS0): title ids from the ticket / ncz names. -> set of int. XCI: nothing."""
    ids = set()
    try:
        with open(path, 'rb') as f:
            head = f.read(16)
            if head[:4] != b'PFS0':
                return ids
            count, strsize = struct.unpack('<II', head[4:12])
            if count > 4096 or strsize > 1 << 20:
                return ids
            f.seek(16 + 24 * count)
            strings = f.read(strsize)
    except OSError:
        return ids
    for m in re.finditer(rb'([0-9a-fA-F]{32})\.tik', strings):
        ids.add(int(m.group(1)[:16], 16))
    return ids


def classify_game_file(path):
    """-> item dict or None. kind: base | update | dlc | unknown-game."""
    name = os.path.basename(path)
    low = name.lower()
    if not low.endswith(GAME_EXT):
        return None
    tid = None
    m = _TID.search(name)
    if m:
        tid = int(m.group(1), 16)
    if tid is None and low.endswith(('.nsp', '.nsz')):
        for i in _ids_from_package(path):
            if (i & ~0xFFF) in (APP_ID, APP_ID + 0x1000):      # base or update (same base id), or a DLC (APP_ID + 0x1000 + n)
                tid = i
                break
        if tid is None:
            return None
    verified = tid is not None
    if tid is None:
        # an .xci/.xcz keeps its ids encrypted; call it a candidate when the name or the size says it is this game
        if low.endswith(('.xci', '.xcz')) and (re.search(r'smash|ssbu|ultimate', low) or _size(path) > HUGE):
            tid = APP_ID
        else:
            return None
    if tid == APP_ID:
        kind = 'base'
    elif tid == UPDATE_ID:
        kind = 'update'
    elif (tid & ~0xFFF) == 0x01006A800016F000:
        kind = 'dlc'
    else:
        return None
    v = _VER.search(name)
    version = int(v.group(1)) if v else None
    build = BUILDS.get(version)
    if kind == 'update' and build is None:
        b = _BUILD.search(name) or _BUILD.search(os.path.basename(os.path.dirname(path)))
        build = b.group(1) if b else None
        m2 = re.search(r'(?<!\d)130([45])(?!\d)', name)                   # e.g. update_1305.nsp
        if build is None and m2:
            build = '13.0.' + m2.group(1)
    ext = os.path.splitext(low)[1]
    size = _size(path)
    item = {'kind': kind, 'path': path, 'title_id': '%016X' % tid, 'version': version, 'build': build, 'format': ext[1:],
            'size': size, 'verified': verified, 'needs_zstandard': ext in ('.nsz', '.xcz'),
            'supported': ext in ('.xci', '.nsp', '.nsz', '.nca') and not (kind == 'update' and build is None)}
    label = {'base': 'base game', 'update': 'update', 'dlc': 'DLC (add-on content %s)' % ('0x%03x' % (tid - APP_ID - 0x1000))}[kind]
    if kind == 'dlc':
        item['dlc_index'] = (tid - APP_ID - 0x1000)
    extra = []
    if kind == 'update':
        extra.append('version %s%s' % (version if version is not None else '?', ' = game %s' % build if build else ' (not a supported build)'))
    if ext in ('.nsz', '.xcz'):
        extra.append('compressed: needs pip install zstandard pycryptodome, tools/extract/nsz_to_nsp.py converts it')
    if not verified:
        extra.append('not verified: guessed from its name/size')
    item['desc'] = '%s: %s (%s%s)' % (label, path, _gb(size), ('; ' + '; '.join(extra)) if extra else '')
    return item


def dump_at(d):
    """A dump folder in the form scripts/setup.py --dump wants: exefs\\ (main, rtld, sdk, subsdk0, main.npdm) and romfs\\."""
    ex, rom = os.path.join(d, 'exefs'), os.path.join(d, 'romfs')
    if _isdir(ex) and _isdir(rom):
        files = {x.lower() for x in _listdir(ex)}
        missing = [x for x in ('main', 'rtld', 'sdk', 'subsdk0', 'main.npdm') if x not in files]
        has_arc = _isfile(os.path.join(rom, 'data.arc'))
        fonts = _isdir(os.path.join(d, 'sysdata', 'fonts'))
        problems = (['exefs lacks ' + ', '.join(missing)] if missing else []) + ([] if has_arc else ['romfs\\data.arc missing'])
        return {'kind': 'dump', 'path': d, 'complete': not problems, 'problems': problems, 'fonts': fonts,
                'use': 'python scripts/setup.py --dump "%s"' % d,
                'desc': 'extracted dump (exefs + romfs%s) in %s%s' % (', sysdata\\fonts' if fonts else '', d,
                                                                     (' - incomplete: ' + '; '.join(problems)) if problems else '')}
    return None


def game_dirs_from_configs(emus):
    """Folders the emulators list as game folders: qt-config.ini `Paths\\gamedirs\\N\\path`, Ryujinx Config.json game_dirs."""
    out = []
    for name, d in emus:
        if name == 'ryujinx':
            p = os.path.join(d, 'Config.json')
            if _isfile(p):
                try:
                    with open(p, 'r', encoding='utf-8', errors='replace') as f:
                        cfg = json.load(f)
                    gd = cfg.get('game_dirs') if isinstance(cfg, dict) else None
                    if isinstance(gd, list):
                        out += [x for x in gd if isinstance(x, str)]
                except (OSError, ValueError):
                    pass
            continue
        for ini in (os.path.join(d, 'config', 'qt-config.ini'), os.path.join(d, 'qt-config.ini')):
            if _isfile(ini):
                try:
                    with open(ini, 'r', encoding='utf-8', errors='replace') as f:
                        for line in f:
                            m = re.match(r'Paths\\(?:gamedirs\\\d+\\path|romsPath)=(.*)$', line.strip())
                            if m and m.group(1) and m.group(1) not in ('SDMC', 'UserNAND', 'SysNAND') \
                                    and not m.group(1).endswith('default'):
                                out.append(m.group(1).replace('/', os.sep))
                except OSError:
                    pass
    return [p for p in out if _isdir(p)]


def walk_limited(root, max_depth, budget):
    """os.walk with a depth limit and a shared entry budget (list [n_left, deadline]); yields (dir, dirnames, filenames)."""
    root = os.path.abspath(root)
    base_depth = root.rstrip(os.sep).count(os.sep)
    for cur, dirs, files in os.walk(root):
        budget[0] -= len(dirs) + len(files)
        if budget[0] < 0 or time.time() > budget[1]:
            return
        depth = cur.rstrip(os.sep).count(os.sep) - base_depth
        yield cur, dirs, files
        if depth >= max_depth:
            dirs[:] = []
        else:
            dirs[:] = [x for x in dirs if x.lower() not in _SKIP_DIRS and not x.startswith('.')]


def find_games(roots, deep_roots=()):
    """Scan folders for game files and extracted dumps. roots: depth 2; deep_roots: depth 3 (user-given or game folders)."""
    games, dumps, seen = [], [], set()
    budget = [60000, time.time() + 25]
    todo = [(r, 2) for r in roots] + [(r, 3) for r in deep_roots]

    def add_dump(it, p):
        k = os.path.normcase(os.path.abspath(p))
        if k not in seen:
            seen.add(k)
            dumps.append(it)

    for root, depth in todo:
        if not _isdir(root):
            continue
        for cur, dirs, files in walk_limited(root, depth, budget):
            it = dump_at(cur)
            if it:                                   # a dump folder: nothing below it is a game for us
                add_dump(it, cur)
                dirs[:] = []
                continue
            for x in list(dirs):                     # a dump one level down: note it and do not walk into it,
                it = dump_at(os.path.join(cur, x))   # but the games next to it in this folder are still listed
                if it:
                    add_dump(it, os.path.join(cur, x))
                    dirs.remove(x)
            for fn in files:
                if fn.lower().endswith(GAME_EXT):
                    p = os.path.join(cur, fn)
                    k = os.path.normcase(os.path.abspath(p))
                    if k in seen:
                        continue
                    seen.add(k)
                    it = classify_game_file(p)
                    if it:
                        games.append(it)
    return games, dumps


# ---------------------------------------------------------------------------------------------------------- scan

def _build_rank(build):
    return BUILD_ORDER.index(build) if build in BUILD_ORDER else 99


def pick_best(keys, firmware, base, updates, dlc, dumps):
    def fmt_rank(it):                                       # a plain package beats a compressed one
        return (0 if it['verified'] else 1, 1 if it['needs_zstandard'] else 0, it['format'] != 'nsp')

    best = {}
    k = next((x for x in keys if x['file'].startswith('prod') and x.get('complete')), None) or \
        next((x for x in keys if x['file'].startswith('prod')), None)
    if k:
        best['prod_keys'] = k['path']
    t = next((x for x in keys if x['file'].startswith('title')), None)
    if t:
        best['title_keys'] = t['path']
    fw = sorted(firmware, key=lambda x: (x['kind'] != 'nca-folder', -x.get('ncas', 0)))
    if fw:
        best['firmware'] = fw[0]['path']
        best['firmware_kind'] = fw[0]['kind']
    sup_up = [u for u in updates if u['build']]
    if sup_up:
        u = sorted(sup_up, key=lambda x: (_build_rank(x['build']),) + fmt_rank(x))[0]
        best['update'] = u['path']
        best['build'] = u['build']
    b = sorted([x for x in base if x['supported']], key=fmt_rank)
    if b:
        best['base'] = b[0]['path']
    best['dlc'] = [d['path'] for d in sorted({d['title_id']: d for d in dlc}.values(), key=lambda x: x['title_id'])]
    ready = [d for d in dumps if d['complete']]
    if ready:
        best['dump'] = ready[0]['path']
    # what the installer would do
    if 'dump' in best:
        best['plan'] = 'use the extracted dump (scripts/setup.py --dump)'
    elif 'base' in best and 'update' in best and 'prod_keys' in best:
        best['plan'] = 'make the dump from base + update (tools/extract/dump_folder.py)'
    else:
        miss = []
        if 'prod_keys' not in best:
            miss.append('prod.keys')
        if 'base' not in best:
            miss.append('the base game')
        if 'update' not in best:
            miss.append('an update 13.0.4 or 13.0.5')
        best['plan'] = 'missing: ' + ', '.join(miss)
    if 'firmware' not in best and 'dump' in best and not any(d.get('fonts') for d in dumps):
        best['firmware_note'] = 'no firmware or fonts found: the game stops at start without the system fonts'
    return best


def scan(extra=()):
    """Look through this PC. extra: files or folders to look at as well. Returns a dict (see the module docstring)."""
    t0 = time.time()
    extra = [os.path.abspath(p) for p in extra]          # one spelling of each path (mixed / and \ in the output otherwise)
    extra_files = [p for p in extra if _isfile(p)]
    extra_dirs = [p for p in extra if _isdir(p)]
    emus = emulator_dirs()
    port = portable_dirs(extra_dirs)

    keys = find_keys(keys_dirs(emus + port))
    firmware = find_firmware(emus, extra_dirs)

    home = os.path.expanduser('~')
    roots = [os.path.join(home, x) for x in ('Downloads', 'Desktop', 'Documents')]
    deep = game_dirs_from_configs(emus) + extra_dirs
    games, dumps = find_games(roots, deep)
    for p in extra_files:
        it = classify_game_file(p)
        if it and not any(os.path.normcase(g['path']) == os.path.normcase(p) for g in games):
            games.append(it)

    base = [g for g in games if g['kind'] == 'base']
    updates = sorted([g for g in games if g['kind'] == 'update'], key=lambda g: (_build_rank(g['build']), g['path']))
    dlc = [g for g in games if g['kind'] == 'dlc']
    result = {'keys': keys, 'firmware': firmware, 'base': base, 'updates': updates, 'dlc': dlc, 'dumps': dumps,
              'emulators': [{'name': n, 'path': p} for n, p in emus + port], 'notes': []}
    result['best'] = pick_best(keys, firmware, base, updates, dlc, dumps)
    unsupported = [u for u in updates if not u['build']]
    if unsupported:
        result['notes'].append('%d update(s) of a version this port does not run (only 13.0.4 = v1966080 and 13.0.5 = v2031616)'
                               % len(unsupported))
    if any(g['needs_zstandard'] for g in games):
        result['notes'].append('.nsz/.xcz files need: pip install zstandard pycryptodome (tools/extract/nsz_to_nsp.py)')
    result['seconds'] = round(time.time() - t0, 1)
    return result


def summary(r):
    lines = ['Found:']
    b = r['best']

    def section(title, items, empty):
        lines.append('  %s' % title)
        if not items:
            lines.append('    - %s' % empty)
        for it in items:
            lines.append('    - %s' % it['desc'])

    section('Keys:', r['keys'], 'no prod.keys (put it in %USERPROFILE%\\.switch\\prod.keys, dump it from your own console)')
    section('Firmware / system fonts:', r['firmware'], 'none (a firmware folder of .nca files, or its sysdata\\fonts)')
    section('Base game:', r['base'], 'none')
    section('Updates:', r['updates'], 'none (13.0.4 or 13.0.5 needed)')
    lines.append('  DLC: %d package(s)%s' % (len(r['dlc']), ' (not needed to run: they only unlock their content, '
                                            'tools/audit/dlc_list.py writes config\\dlc.txt)' if r['dlc'] else ''))
    section('Extracted dumps:', r['dumps'], 'none')
    lines.append('  Best choice:')
    for key, label in (('prod_keys', 'prod.keys'), ('firmware', 'firmware'), ('base', 'base'), ('update', 'update'),
                       ('dump', 'dump')):
        if key in b:
            extra = ' (game %s)' % b['build'] if key == 'update' else ''
            lines.append('    %-9s %s%s' % (label, b[key], extra))
    if b.get('firmware_note'):
        lines.append('    note      ' + b['firmware_note'])
    lines.append('    plan      %s' % b['plan'])
    for n in r['notes']:
        lines.append('  Note: ' + n)
    return '\n'.join(lines)


def main(argv):
    as_json = '--json' in argv
    extra = [a for a in argv if not a.startswith('--')]
    r = scan(extra)
    print(json.dumps(r, indent=1) if as_json else summary(r))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
