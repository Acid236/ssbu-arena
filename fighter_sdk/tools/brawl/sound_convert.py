"""Sound converter: a replacement soundbank of the Wii predecessor's community expansion engine (.sawnd) -> the
native fighter sound banks (.nus3audio + .nus3bank + .tonelabel; one se_ bank for effects, one vc_ bank for voices).

    python -I sound_convert.py <bank.sawnd> <first sound id | auto> <out folder> <fighter name>
            --template-se <a native se_*.nus3bank> --template-vc <a native vc_*.nus3bank>
            [--names <map.txt>] [--bank-id <n>] [--se-volume 46] [--vc-volume 62]

writes
    <out>/sound/bank/fighter/se_<fighter>_c00.nus3audio .nus3bank .tonelabel         the sound effects
    <out>/sound/bank/fighter_voice/vc_<fighter>_c00.nus3audio .nus3bank .tonelabel   the voice clips
    <out>/<fighter>_sound_map.txt                                                    sound id -> tone name -> track
then reads back what it wrote and checks it: every track decodes to the same PCM as the .sawnd wave, rates and
sample counts kept, one tone per sound, tracks/tones/labels agree.  Exit code 1 if anything does not match.

One Brawl sound = one tone + one track.  The DSP-ADPCM data is copied, never re-encoded (the IDSP container of the
native banks holds the same DSP-ADPCM frames).  Identical tracks are stored once, as the game's own banks do.
Default tone names: se_<fighter>_<sound id in hex> / vc_<fighter>_<sound id in hex>; --names gives other names
(lines "<sound id> <tone name>", '#' starts a comment).

The templates give the parts of a bank that are the same for every fighter: PROP, the mixer group table (GRP),
the default tones (DTON), the silent placeholder wave (PACK), and the layout of a plain tone (the template's most
common plain tone; only name, volume, pitch, rate, channels and sample count are changed).  Use the game's own
se_ and vc_ bank of any fighter.  This file contains no game content.

INPUT (.sawnd, version 2, all big-endian; written by the expansion engine's tools)
    u8 version 2, u32 group field (unused), u32 D = wave data length, N x {u32 file id, u32 data off, u32 data len},
    the N RWSD file headers back to back, then D bytes of wave data (file i: [data off, + data len)).
    N is not stored: it is the N for which the lengths sum to D and the headers fill the gap exactly.
    An expansion bank (number B >= 0x144, the file name is <B in hex>.sawnd) has two files: item 0 = voices,
    item 1 = effects, and owns 0xA5 global sound ids from first = 0x4000 + (B - 0x144) * 0xA5:
        first + i          -> voice entry i   (i < 0x2F)
        first + 0x2F + j   -> effect entry j
    RWSD 1.x: DATA = entries {WsdInfo, tracks -> note events, notes -> wave index}; WAVE = WaveInfo per wave
    (format 2 = DSP-ADPCM, loop flag, channels, rate, loop start, END = NIBBLE COUNT (one past the last sample:
    a 1-sample wave has 3), data location, per channel {data offset, coef[16], gain, ps, yn1, yn2, loop ps/yn}).
    Volume: the expansion engine plays every effect at 0x2E and every voice at 0x3E (0..127, linear, 127 = 1.0);
    note volume is 0..127 linear as well.  Tone volume = 20*log10(product), pitch = 1200*log2(wsd * note pitch).

OUTPUT layout: see nus3 notes at write_idsp / build_nus3audio / build_bank / build_tonelabel below.
Not converted (the converter stops with a message): looping waves, non-ADPCM waves, entries with more than one
note (layered sounds would need mixing).  None occur in the package this was written for; each needs its own
check against real data before it is supported.
"""
import math
import os
import struct
import sys
import zlib

EXP_FIRST_BANK = 0x144
EXP_IDS_PER_BANK = 0xA5
EXP_VOICE_SLOTS = 0x2F
DEFAULT_SE_VOLUME = 0x2E
DEFAULT_VC_VOLUME = 0x3E
PLAIN_H1 = 0x87e7ffff
PLAIN_FLAGS = 0x000c981f
MARK = 0xffffffff


class ConvertError(Exception):
    pass


def _f2u(x):
    return struct.unpack('<I', struct.pack('<f', x))[0]


def _u2f(w):
    return struct.unpack('<f', struct.pack('<I', w))[0]


def hash40(name):
    b = name.encode('ascii')
    return (len(b) << 32) | (zlib.crc32(b.lower()) & 0xffffffff)


def nibbles_to_samples(nib):
    """DSP-ADPCM nibble count (2 header nibbles per 16) -> sample count."""
    frames, rem = divmod(nib, 16)
    return frames * 14 + (rem - 2 if rem else 0)


def samples_to_nibbles(ns):
    frames, rem = divmod(ns, 14)
    return frames * 16 + (rem + 2 if rem else 0)


# ====================================================================== input: .sawnd + RWSD

def parse_sawnd(data):
    if len(data) < 9 or data[0] != 2:
        raise ConvertError('not a version-2 .sawnd (first byte %#x)' % (data[0] if data else -1))
    dlen = struct.unpack_from('>I', data, 5)[0]
    dstart = len(data) - dlen
    for n in range(1, 64):
        hdr_end = 9 + 12 * n
        if hdr_end > dstart:
            break
        trips = [struct.unpack_from('>III', data, 9 + 12 * i) for i in range(n)]
        if sum(t[2] for t in trips) != dlen:
            continue
        pos, heads = hdr_end, []
        for _ in trips:
            if data[pos:pos + 4] not in (b'RWSD', b'RBNK', b'RSEQ'):
                break
            size = struct.unpack_from('>I', data, pos + 8)[0]
            heads.append((pos, size))
            pos += size
        if len(heads) == n and pos == dstart:
            files = []
            for (fid, doff, dl), (hp, hs) in zip(trips, heads):
                if doff + dl > dlen:
                    raise ConvertError('file %#x wave data outside the data section' % fid)
                files.append(dict(file_id=fid, magic=data[hp:hp + 4].decode(), header=data[hp:hp + hs],
                                  wave_data=data[dstart + doff:dstart + doff + dl]))
            return files
    raise ConvertError('could not find the file table of the .sawnd')


def parse_rwsd(h):
    if h[:4] != b'RWSD':
        raise ConvertError('not an RWSD file')
    ver = struct.unpack_from('>H', h, 6)[0]
    data_off, _ds, wave_off, _ws = struct.unpack_from('>IIII', h, 0x10)
    if h[data_off:data_off + 4] != b'DATA' or h[wave_off:wave_off + 4] != b'WAVE':
        raise ConvertError('RWSD blocks not found')
    body = data_off + 8

    def ref(o):
        t, _dt, _p, off = struct.unpack_from('>BBHI', h, o)
        if t not in (0, 1):
            raise ConvertError('bad RWSD reference type %d at %#x' % (t, o))
        return None if (t == 0 and off == 0) else off

    def refs(off):
        p = body + off
        n = struct.unpack_from('>I', h, p)[0]
        return [ref(p + 4 + 8 * i) for i in range(n)]

    entries = []
    for eoff in refs(0):
        e = body + eoff
        w = body + ref(e)
        info = dict(pitch=struct.unpack_from('>f', h, w)[0], pan=h[w + 4], fx_b=h[w + 7], fx_c=h[w + 8])
        events = []
        for toff in refs(ref(e + 8)):
            for evoff in refs(ref(body + toff)):
                p = body + evoff
                events.append(dict(position=struct.unpack_from('>f', h, p)[0],
                                   note=struct.unpack_from('>I', h, p + 8)[0]))
        notes = []
        for noff in refs(ref(e + 16)):
            p = body + noff
            notes.append(dict(wave=struct.unpack_from('>i', h, p)[0], key=h[p + 12], volume=h[p + 13],
                              pan=h[p + 14], pitch=struct.unpack_from('>f', h, p + 16)[0]))
        entries.append(dict(info=info, events=events, notes=notes))

    waves = []
    n = struct.unpack_from('>I', h, wave_off + 8)[0]
    for i in range(n):
        wi = wave_off + struct.unpack_from('>I', h, wave_off + 12 + 4 * i)[0]
        fmt, loop, nch, rate_hi = h[wi], h[wi + 1], h[wi + 2], h[wi + 3]
        rate = rate_hi << 16 | struct.unpack_from('>H', h, wi + 4)[0]
        loop_start, end, ch_tab, data_loc = struct.unpack_from('>IIII', h, wi + 8)
        chans = []
        for c in range(nch):
            ci = wi + struct.unpack_from('>I', h, wi + ch_tab + 4 * c)[0]
            doff, aoff = struct.unpack_from('>II', h, ci)
            ch = dict(data_offset=doff, vol=struct.unpack_from('>4I', h, ci + 8))
            if fmt == 2:
                a = wi + aoff
                ch['coefs'] = list(struct.unpack_from('>16h', h, a))
                ch['gain'], ch['ps'], ch['yn1'], ch['yn2'] = struct.unpack_from('>HHhh', h, a + 32)
            chans.append(ch)
        waves.append(dict(index=i, format=fmt, loop=loop, channels=nch, rate=rate, loop_start=loop_start,
                          nibbles=end, samples=nibbles_to_samples(end) if fmt == 2 else end,
                          data_location=data_loc, chans=chans))
    return dict(version=ver, entries=entries, waves=waves)


def dsp_decode(raw, coefs, yn1, yn2, nsamples):
    out = []
    h1, h2 = yn1, yn2
    base = 0
    while len(out) < nsamples:
        if base >= len(raw):
            raise ConvertError('DSP-ADPCM data ends early')
        hdr = raw[base]
        scale = 1 << (hdr & 0xF)
        ci = hdr >> 4
        if ci > 7:
            raise ConvertError('bad DSP-ADPCM frame header %#x' % hdr)
        c1, c2 = coefs[2 * ci], coefs[2 * ci + 1]
        for k in range(min(14, nsamples - len(out))):
            byte = raw[base + 1 + (k >> 1)]
            nib = byte >> 4 if not k & 1 else byte & 0xF
            if nib >= 8:
                nib -= 16
            s = (((nib * scale) << 11) + 1024 + c1 * h1 + c2 * h2) >> 11
            s = -32768 if s < -32768 else 32767 if s > 32767 else s
            out.append(s)
            h2, h1 = h1, s
        base += 8
    return out


def wave_channel_data(wv, wave_data):
    """the DSP-ADPCM bytes of each channel of a wave (exactly ceil(nibbles / 2) bytes)."""
    nbytes = (wv['nibbles'] + 1) // 2
    out = []
    for ch in wv['chans']:
        st = wv['data_location'] + ch['data_offset']
        raw = wave_data[st:st + nbytes]
        if len(raw) < nbytes:
            raise ConvertError('wave %d: data outside the file' % wv['index'])
        out.append(raw)
    return out


def expansion_first_id(bank):
    if bank < EXP_FIRST_BANK:
        raise ConvertError('bank %#x is not an expansion bank (>= %#x)' % (bank, EXP_FIRST_BANK))
    return 0x4000 + (bank - EXP_FIRST_BANK) * EXP_IDS_PER_BANK


def bank_from_filename(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    try:
        return int(stem, 16)
    except ValueError:
        return None


# ====================================================================== output: IDSP

def write_idsp(rate, nsamples, chans):
    """IDSP (big-endian).  chans: [(adpcm bytes, coefs[16], yn1, yn2)].  Not looping.
    0x00 'IDSP' 0, channels, rate, samples, loop start 0, loop end 0, interleave 0x10, 0x40 (first channel
    header), 0x60 (channel header size), data offset 0x40 + 0x60 * channels, data size per channel (bytes of
    the stream rounded up to 0x10), zero to 0x40.  Channel header = the standard DSP-ADPCM header: samples,
    nibbles, rate, loop flag 0, format 0, sa 2, ea nibbles - 1, ca 2, coef[16], gain 0, ps (first frame
    header byte), yn1, yn2, loop ps/yn1/yn2 0, 22 zero bytes.  Data: channels alternate every 0x10 bytes."""
    nch = len(chans)
    nib = samples_to_nibbles(nsamples)
    need = (nib + 1) // 2
    dsz = (need + 0xF) & ~0xF
    doff = 0x40 + 0x60 * nch
    out = bytearray(struct.pack('>4sIIIIIIIIIII', b'IDSP', 0, nch, rate, nsamples, 0, 0, 0x10, 0x40, 0x60,
                                doff, dsz))
    out += bytes(0x40 - len(out))
    streams = []
    for raw, coefs, yn1, yn2 in chans:
        if len(raw) != need:
            raise ConvertError('channel data is %d bytes, %d expected' % (len(raw), need))
        out += struct.pack('>IIIHHIII16hHHhhHhh', nsamples, nib, rate, 0, 0, 2, nib - 1, 2, *coefs, 0, raw[0],
                           yn1, yn2, 0, 0, 0)
        out += bytes(22)
        streams.append(bytes(raw) + bytes(dsz - need))
    for blk in range(0, dsz, 0x10):
        for s in streams:
            out += s[blk:blk + 0x10]
    return bytes(out)


def read_idsp(b):
    """-> (channels, rate, samples, loop start, loop end, [(stream bytes, coefs, ps, yn1, yn2)])"""
    if b[:4] != b'IDSP':
        raise ConvertError('track is not IDSP')
    _z, nch, rate, ns, ls, le, inter, hoff, hsz, doff, dsz = struct.unpack_from('>11I', b, 4)
    chans = []
    for c in range(nch):
        q = hoff + hsz * c
        coefs = list(struct.unpack_from('>16h', b, q + 0x1c))
        _gain, ps, yn1, yn2 = struct.unpack_from('>HHhh', b, q + 0x3c)
        stream = bytearray()
        for blk in range(0, dsz, inter):
            p = doff + blk * nch + c * inter
            stream += b[p:p + inter]
        chans.append((bytes(stream), coefs, ps, yn1, yn2))
    return nch, rate, ns, ls, le, chans


# ====================================================================== output: NUS3AUDIO

def _junk_len(pos):
    """JUNK chunk at pos: k zero bytes (1..16) so that the next chunk's payload starts 16-aligned."""
    k = (-pos) % 16
    return k or 16


def build_nus3audio(tracks):
    """tracks: [(name, IDSP blob)] in tone order.  Little-endian:
    'NUS3' size-8, 'AUDIINDX' 4 n, 'TNID' 4n ids (= index), 'NMOF' 4n absolute name offsets,
    'ADOF' 8n {absolute blob offset, size}, 'TNNM' names NUL-terminated back to back, 'JUNK' k zeros,
    'PACK' blobs 16-aligned in order of first use, identical blobs stored once.
    -> (bytes, blob index of every track)"""
    n = len(tracks)
    names = [t[0].encode('ascii') + b'\0' for t in tracks]
    tnnm = b''.join(names)
    uniq, blobs, which = {}, [], []
    for _name, blob in tracks:
        if len(blob) % 16:
            raise ConvertError('IDSP blob size not a multiple of 16')
        if blob not in uniq:
            uniq[blob] = len(blobs)
            blobs.append(blob)
        which.append(uniq[blob])
    p_tnid = 0x18
    p_nmof = p_tnid + 8 + 4 * n
    p_adof = p_nmof + 8 + 4 * n
    p_tnnm = p_adof + 8 + 8 * n
    p_junk = p_tnnm + 8 + len(tnnm)
    k = _junk_len(p_junk)
    p_pack = p_junk + 8 + k
    pack0 = p_pack + 8
    blob_off, o = [], pack0
    for blob in blobs:
        blob_off.append(o)
        o += len(blob)
    name_off, o = [], p_tnnm + 8
    for nm in names:
        name_off.append(o)
        o += len(nm)
    out = bytearray()
    out += b'NUS3' + struct.pack('<I', 0)
    out += b'AUDIINDX' + struct.pack('<II', 4, n)
    out += b'TNID' + struct.pack('<I%dI' % n, 4 * n, *range(n))
    out += b'NMOF' + struct.pack('<I%dI' % n, 4 * n, *name_off)
    adof = []
    for w in which:
        adof += [blob_off[w], len(blobs[w])]
    out += b'ADOF' + struct.pack('<I%dI' % (2 * n), 8 * n, *adof)
    out += b'TNNM' + struct.pack('<I', len(tnnm)) + tnnm
    assert len(out) == p_junk
    out += b'JUNK' + struct.pack('<I', k) + bytes(k)
    out += b'PACK' + struct.pack('<I', sum(len(b) for b in blobs))
    assert len(out) == pack0 and pack0 % 16 == 0
    for blob in blobs:
        out += blob
    struct.pack_into('<I', out, 4, len(out) - 8)
    return bytes(out), which


def read_nus3audio(d):
    """-> [(name, blob)]"""
    if d[:4] != b'NUS3' or d[8:16] != b'AUDIINDX':
        raise ConvertError('not a nus3audio file')
    ch, p = {}, 8
    while p < len(d):
        if d[p:p + 8] == b'AUDIINDX':
            ch['AUDIINDX'] = (p + 12, struct.unpack_from('<I', d, p + 8)[0])
            p += 12 + ch['AUDIINDX'][1]
            continue
        tag, sz = d[p:p + 4].decode('latin1'), struct.unpack_from('<I', d, p + 4)[0]
        ch[tag] = (p + 8, sz)
        p += 8 + sz
    n = struct.unpack_from('<I', d, ch['AUDIINDX'][0])[0]
    nmof = struct.unpack_from('<%dI' % n, d, ch['NMOF'][0])
    adof = struct.unpack_from('<%dI' % (2 * n), d, ch['ADOF'][0])
    out = []
    for i in range(n):
        name = d[nmof[i]:d.index(b'\0', nmof[i])].decode('ascii')
        out.append((name, d[adof[2 * i]:adof[2 * i] + adof[2 * i + 1]]))
    return out


# ====================================================================== output: NUS3BANK

def _sections(d):
    """NUS3BANK -> [(tag, payload bytes)] in file order."""
    if d[:4] != b'NUS3' or d[8:16] != b'BANKTOC ':
        raise ConvertError('not a nus3bank file')
    _tocsz, n = struct.unpack_from('<II', d, 16)
    toc = [(d[24 + 8 * i:28 + 8 * i].decode('latin1'), struct.unpack_from('<I', d, 28 + 8 * i)[0]) for i in range(n)]
    q, out = 24 + 8 * n, []
    for tag, sz in toc:
        if d[q:q + 4].decode('latin1') != tag:
            raise ConvertError('nus3bank section %s not where the table says' % tag)
        out.append((tag, d[q + 8:q + 8 + sz]))
        q += 8 + sz
    return out


def _lenstr(s, start):
    """u8 length (NUL included), the string, NUL, zero-padded so that (start + size) is a multiple of 4."""
    b = bytes([len(s) + 1]) + s.encode('ascii') + b'\0'
    return b + bytes((-(start + len(b))) % 4)


def _tone_records(tone_payload):
    n = struct.unpack_from('<I', tone_payload, 0)[0]
    return [tone_payload[o:o + s] for o, s in (struct.unpack_from('<II', tone_payload, 4 + 8 * i) for i in range(n))]


def _parse_plain_tone(rec):
    """a plain tone record -> dict(h0, h1, flags, name, words, k = index of the 0xffffffff marker before the
    sample rate) or None for other record kinds (containers, removed slots, other field masks)."""
    if len(rec) <= 12:
        return None
    h0, h1, flags = struct.unpack_from('<III', rec, 0)
    if h1 != PLAIN_H1:
        return None
    n = rec[12]
    name = rec[13:13 + n].rstrip(b'\0').decode('latin1')
    body = 13 + n
    body += (-body) % 4
    W = list(struct.unpack_from('<%dI' % ((len(rec) - body) // 4), rec, body))
    try:
        k = 16
        k += 1 + W[k]                 # group list
        k += 1 + 2 * W[k]             # sends {bus, dB}
        k += 2                        # u32 4, f32 1.0
        while W[k] != MARK:           # play words
            k += 1
    except IndexError:
        return None
    return dict(h0=h0, h1=h1, flags=flags, name=name, words=W, k=k)


def build_tone(shape, name, volume_db, pitch_cents, rate, channels, nsamples):
    """a plain tone: the template shape with name, volume (dB, word 4), pitch (cents, word 6) and the wave
    fields after the 0xffffffff marker (rate, channels, samples) set."""
    W = list(shape['words'])
    k = shape['k']
    W[4] = _f2u(volume_db)
    W[6] = _f2u(pitch_cents)
    W[k + 1:k + 4] = [rate, channels, nsamples]
    head = struct.pack('<III', shape['h0'], shape['h1'], shape['flags'])
    head += _lenstr(name, len(head))
    return head + struct.pack('<%dI' % len(W), *W)


def load_template(path, prefix):
    """-> dict(prop, binf_head, grp, dton, pack, shape) from a native bank of the game."""
    d = open(path, 'rb').read()
    secs = _sections(d)
    tags = [t for t, _ in secs]
    for need in ('PROP', 'BINF', 'GRP ', 'DTON', 'TONE', 'PACK'):
        if need not in tags:
            raise ConvertError('template %s has no %s section' % (path, need))
    S = dict(secs)
    bname = S['BINF'][9:9 + S['BINF'][8]].rstrip(b'\0').decode('latin1')
    if not bname.startswith(prefix + '_'):
        raise ConvertError('template %s is the bank %r, a %s_ bank is needed' % (path, bname, prefix))
    if S['PACK'][:4] != b'RIFF':
        raise ConvertError('template PACK is not the placeholder wave')
    counts, first = {}, {}
    plain = []
    for rec in _tone_records(S['TONE']):
        t = _parse_plain_tone(rec)
        if not t or t['flags'] != PLAIN_FLAGS:
            continue
        W, k = t['words'], t['k']
        if W[k + 4:k + 8] != [0, 0, 0, 0] or W[k + 8] != MARK or W[3] != len(S['PACK']):
            continue
        key = (t['h0'], tuple(W[:4]), W[5], tuple(W[7:k + 1]), tuple(W[k + 4:]))
        counts[key] = counts.get(key, 0) + 1
        first.setdefault(key, t)
        plain.append((key, t, rec))
    if not counts:
        raise ConvertError('template %s has no plain tone' % path)
    best = max(counts, key=lambda c: counts[c])
    shape = dict(first[best])
    # the builder must give back the template's own records of that shape, byte for byte
    same = 0
    for key, t, rec in plain:
        if key != best:
            continue
        W, k = t['words'], t['k']
        if build_tone(shape, t['name'], _u2f(W[4]), _u2f(W[6]), *W[k + 1:k + 4]) != rec:
            raise ConvertError('tone builder does not reproduce template tone %r' % t['name'])
        same += 1
    return dict(path=path, bank_name=bname, prop=S['PROP'], binf_head=S['BINF'][:8], grp=S['GRP '],
                dton=S['DTON'], pack=S['PACK'], shape=shape, shape_count=same, plain_count=len(plain))


def build_bank(tpl, bank_name, bank_id, tones):
    """NUS3BANK (little-endian): 'NUS3' size-8, 'BANKTOC ' 4+8*7 7 {tag, size}[7], then the sections
    PROP (template), BINF (u32 0, u32 3, u8 len, name, pad4, u32 bank id), GRP / DTON (template),
    TONE (u32 count, {off, size}[count] from the payload start, records back to back, 4-aligned),
    JUNK (1..16 zero bytes so PACK's payload is 16-aligned), PACK (template's silent placeholder wave)."""
    binf = tpl['binf_head'] + _lenstr(bank_name, 8)
    binf += struct.pack('<I', bank_id)
    tone = bytearray(struct.pack('<I', len(tones)))
    off = 4 + 8 * len(tones)
    for rec in tones:
        if len(rec) % 4:
            raise ConvertError('tone record size not a multiple of 4')
        tone += struct.pack('<II', off, len(rec))
        off += len(rec)
    for rec in tones:
        tone += rec
    secs = [('PROP', tpl['prop']), ('BINF', binf), ('GRP ', tpl['grp']), ('DTON', tpl['dton']),
            ('TONE', bytes(tone)), ('JUNK', None), ('PACK', tpl['pack'])]
    pos = 24 + 8 * len(secs)
    for tag, pl in secs:
        if tag == 'JUNK':
            break
        pos += 8 + len(pl)
    secs[5] = ('JUNK', bytes(_junk_len(pos)))
    out = bytearray(b'NUS3' + struct.pack('<I', 0) + b'BANKTOC ' + struct.pack('<II', 4 + 8 * len(secs), len(secs)))
    for tag, pl in secs:
        out += tag.encode('latin1') + struct.pack('<I', len(pl))
    for tag, pl in secs:
        if tag == 'PACK':
            assert (len(out) + 8) % 16 == 0
        out += tag.encode('latin1') + struct.pack('<I', len(pl)) + pl
    struct.pack_into('<I', out, 4, len(out) - 8)
    return bytes(out)


def read_bank(d):
    """-> (bank name, bank id, [(tone name, rate, channels, samples, volume dB, pitch cents)])"""
    S = dict(_sections(d))
    b = S['BINF']
    n = b[8]
    name = b[9:9 + n].rstrip(b'\0').decode('latin1')
    p = 9 + n
    p += (-p) % 4
    bid = struct.unpack_from('<I', b, p)[0]
    tones = []
    for rec in _tone_records(S['TONE']):
        t = _parse_plain_tone(rec)
        if not t:
            raise ConvertError('unexpected tone record kind')
        W, k = t['words'], t['k']
        tones.append((t['name'], W[k + 1], W[k + 2], W[k + 3], _u2f(W[4]), _u2f(W[6])))
    return name, bid, tones


# ====================================================================== output: TONELABEL

def build_tonelabel(names):
    """u32 1, u32 count, {u32 crc32(lowercase name), u32 name length | tone index << 8}[count] sorted by
    hash40 = length << 32 | crc."""
    ents = sorted((hash40(nm), i) for i, nm in enumerate(names))
    out = bytearray(struct.pack('<II', 1, len(ents)))
    for h, i in ents:
        out += struct.pack('<II', h & 0xffffffff, (h >> 32) | i << 8)
    return bytes(out)


def read_tonelabel(d):
    ver, n = struct.unpack_from('<II', d, 0)
    out = {}
    for i in range(n):
        crc, w = struct.unpack_from('<II', d, 8 + 8 * i)
        out[(w & 0xff) << 32 | crc] = w >> 8
    return ver, n, out


# ====================================================================== conversion

def _db(lin):
    return 20.0 * math.log10(lin) if lin > 0 else -90.0


def collect_sounds(files, first_id, volumes):
    """-> list of sound dicts in id order, each with its bank kind ('se' / 'vc'), wave and tone parameters."""
    if len(files) != 2 or any(f['magic'] != 'RWSD' for f in files):
        raise ConvertError('an expansion bank has 2 RWSD files (voices, effects); this one has %s' %
                           [f['magic'] for f in files])
    sounds = []
    for item, (kind, id0, slots) in enumerate((('vc', first_id, EXP_VOICE_SLOTS),
                                               ('se', first_id + EXP_VOICE_SLOTS, EXP_IDS_PER_BANK - EXP_VOICE_SLOTS))):
        f = files[item]
        rw = parse_rwsd(f['header'])
        if len(rw['entries']) > slots:
            raise ConvertError('file %#x has %d entries, the bank has %d slots' % (f['file_id'], len(rw['entries']), slots))
        for idx, e in enumerate(rw['entries']):
            sid = id0 + idx
            where = 'sound %#06x (file %#x entry %d)' % (sid, f['file_id'], idx)
            if len(e['notes']) != 1 or len(e['events']) != 1 or e['events'][0]['note'] != 0:
                raise ConvertError('%s has %d notes / %d note events: layered sounds are not supported' %
                                   (where, len(e['notes']), len(e['events'])))
            note = e['notes'][0]
            if not 0 <= note['wave'] < len(rw['waves']):
                raise ConvertError('%s: wave index %d out of range' % (where, note['wave']))
            wv = rw['waves'][note['wave']]
            if wv['format'] != 2:
                raise ConvertError('%s: wave format %d is not DSP-ADPCM' % (where, wv['format']))
            if wv['loop']:
                raise ConvertError('%s: looping wave (loop start %#x): not supported yet' % (where, wv['loop_start']))
            if wv['nibbles'] % 16 in (1, 2) or wv['samples'] < 1:
                raise ConvertError('%s: bad wave end %#x' % (where, wv['nibbles']))
            raw = wave_channel_data(wv, f['wave_data'])
            notes = []
            for c, ch in enumerate(wv['chans']):
                if raw[c][0] != ch['ps']:
                    notes.append('ch%d header ps %#x != first frame %#x (frame used)' % (c, ch['ps'], raw[c][0]))
                if ch['gain']:
                    notes.append('ch%d gain %d ignored' % (c, ch['gain']))
                if wv['channels'] == 1 and ch['vol'][:2] != (0x01000000, 0x01000000):
                    notes.append('channel volume %s ignored' % [v / 0x01000000 for v in ch['vol']])
            pitch = e['info']['pitch'] * note['pitch']
            if pitch <= 0:
                raise ConvertError('%s: pitch %r' % (where, pitch))
            if e['info']['pan'] != 64 or note['pan'] != 64:
                notes.append('pan %d/%d ignored (tones are positioned by the game)' % (e['info']['pan'], note['pan']))
            if e['info']['fx_b'] or e['info']['fx_c']:
                notes.append('effect sends B=%d C=%d ignored' % (e['info']['fx_b'], e['info']['fx_c']))
            vol = volumes[kind] / 127.0 * note['volume'] / 127.0
            sounds.append(dict(id=sid, kind=kind, file_id=f['file_id'], entry=idx, wave=wv['index'],
                               rate=wv['rate'], channels=wv['channels'], samples=wv['samples'],
                               volume_db=_db(vol), pitch_cents=1200.0 * math.log2(pitch),
                               chans=[(raw[c], ch['coefs'], ch['yn1'], ch['yn2']) for c, ch in enumerate(wv['chans'])],
                               notes=notes))
    return sounds


def read_names(path):
    names = {}
    for ln, line in enumerate(open(path, encoding='utf-8'), 1):
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            raise ConvertError('%s:%d: expected "<sound id> <tone name>"' % (path, ln))
        names[int(parts[0], 16)] = parts[1]
    return names


def _check_name(nm):
    if not nm or len(nm) > 254 or not all(c.isalnum() or c == '_' for c in nm) or not nm.isascii():
        raise ConvertError('bad tone name %r (ASCII letters, digits and _ only)' % nm)


def convert(sawnd_path, first_arg, out_dir, fighter, template_se, template_vc, names_path=None, bank_id=None,
            se_volume=DEFAULT_SE_VOLUME, vc_volume=DEFAULT_VC_VOLUME):
    if not fighter or not all(c.islower() or c.isdigit() or c == '_' for c in fighter):
        raise ConvertError('fighter name must be lowercase letters, digits and _')
    data = open(sawnd_path, 'rb').read()
    bank = bank_from_filename(sawnd_path)
    if first_arg == 'auto':
        if bank is None:
            raise ConvertError('the file name is not a bank number: give the first sound id')
        first_id = expansion_first_id(bank)
    else:
        first_id = int(first_arg, 16)
        if bank is not None and bank >= EXP_FIRST_BANK and expansion_first_id(bank) != first_id:
            raise ConvertError('bank %#x owns the ids %#06x..%#06x; first sound id %#06x does not match' % (
                bank, expansion_first_id(bank), expansion_first_id(bank) + EXP_IDS_PER_BANK - 1, first_id))
    if bank_id is None:
        bank_id = 7000 + 2 * (zlib.crc32(fighter.encode()) % 210)
    files = parse_sawnd(data)
    sounds = collect_sounds(files, first_id, {'se': se_volume, 'vc': vc_volume})
    custom = read_names(names_path) if names_path else {}
    tpl = {'se': load_template(template_se, 'se'), 'vc': load_template(template_vc, 'vc')}

    written, report = {}, []
    for kind, sub, bid in (('se', 'fighter', bank_id), ('vc', 'fighter_voice', bank_id + 1)):
        group = [s for s in sounds if s['kind'] == kind]
        for s in group:
            s['name'] = custom.get(s['id'], '%s_%s_%04x' % (kind, fighter, s['id']))
            _check_name(s['name'])
        seen = {}
        for i, s in enumerate(group):
            h = hash40(s['name'])
            if h in seen:
                raise ConvertError('tone names %r and %r have the same hash' % (group[seen[h]]['name'], s['name']))
            seen[h] = i
            s['tone'] = i
            s['blob'] = write_idsp(s['rate'], s['samples'], s['chans'])
        audio, which = build_nus3audio([(s['name'], s['blob']) for s in group])
        tones = [build_tone(tpl[kind]['shape'], s['name'], s['volume_db'], s['pitch_cents'], s['rate'],
                            s['channels'], s['samples']) for s in group]
        bank_bytes = build_bank(tpl[kind], '%s_%s' % (kind, fighter), bid, tones)
        label = build_tonelabel([s['name'] for s in group])
        folder = os.path.join(out_dir, 'sound', 'bank', sub)
        os.makedirs(folder, exist_ok=True)
        stem = os.path.join(folder, '%s_%s_c00' % (kind, fighter))
        for ext, b in (('.nus3audio', audio), ('.nus3bank', bank_bytes), ('.tonelabel', label)):
            with open(stem + ext, 'wb') as o:
                o.write(b)
        for s, w in zip(group, which):
            s['blob_index'] = w
        written[kind] = (stem, bid, group)
        report.append('%s: %d tones, %d unique tracks, bank id %d, template %s (plain tone shape of %d/%d tones)' % (
            stem, len(group), len(set(which)), bid, tpl[kind]['bank_name'], tpl[kind]['shape_count'],
            tpl[kind]['plain_count']))

    map_path = os.path.join(out_dir, '%s_sound_map.txt' % fighter)
    write_map(map_path, sawnd_path, bank, first_id, written, se_volume, vc_volume)
    ok, lines = check(sawnd_path, first_id, written, {'se': se_volume, 'vc': vc_volume})
    return ok, report + ['map: ' + map_path] + lines


def write_map(path, sawnd_path, bank, first_id, written, se_volume, vc_volume):
    L = ['# sound map of %s (bank %s), sound ids %#06x..%#06x' % (
            os.path.basename(sawnd_path), '%#x' % bank if bank is not None else '?', first_id,
            first_id + EXP_IDS_PER_BANK - 1),
         '# voices: ids %#06x.. -> vc bank; effects: ids %#06x.. -> se bank' % (first_id, first_id + EXP_VOICE_SLOTS),
         '# volume: effects %d/127, voices %d/127 (times note volume / 127) -> tone dB' % (se_volume, vc_volume),
         '# track = tone index in its bank (= .nus3audio track index); blob = unique IDSP data index',
         '# placeholder = a 1-sample wave (an empty slot of the package)',
         '#',
         '# id      bank             tone  tone name                         track blob  rate   ch samples   secs    vol_dB  cents  src     notes']
    for kind in ('vc', 'se'):
        stem, _bid, group = written[kind]
        first_use = {}
        for s in group:
            first_use.setdefault(s['blob_index'], s['tone'])
        for s in group:
            flags = ['placeholder'] if s['samples'] <= 1 else []
            if first_use[s['blob_index']] != s['tone']:
                flags.append('same data as track %d' % first_use[s['blob_index']])
            flags += s['notes']
            L.append('%#06x  %-15s  %4d  %-32s  %4d  %4d  %5d  %d  %7d  %6.3f  %+7.2f  %+5.0f  %#x:%-3d %s' % (
                s['id'], os.path.basename(stem), s['tone'], s['name'], s['tone'], s['blob_index'], s['rate'],
                s['channels'], s['samples'], s['samples'] / s['rate'], s['volume_db'], s['pitch_cents'],
                s['file_id'], s['entry'], '; '.join(flags)))
    with open(path, 'w', encoding='utf-8', newline='\n') as o:
        o.write('\n'.join(L) + '\n')


# ====================================================================== read-back check

def check(sawnd_path, first_id, written, volumes):
    """re-read the written files (this module's readers) and the .sawnd (fresh parse), compare everything."""
    lines, bad = [], []
    src = {s['id']: s for s in collect_sounds(parse_sawnd(open(sawnd_path, 'rb').read()), first_id, volumes)}
    total = 0
    for kind in ('se', 'vc'):
        stem, bid, group = written[kind]
        tracks = read_nus3audio(open(stem + '.nus3audio', 'rb').read())
        bname, rbid, tones = read_bank(open(stem + '.nus3bank', 'rb').read())
        ver, nlab, lab = read_tonelabel(open(stem + '.tonelabel', 'rb').read())
        if len(tracks) != len(group) or len(tones) != len(group) or nlab != len(group):
            bad.append('%s: %d tracks / %d tones / %d labels for %d sounds' % (stem, len(tracks), len(tones), nlab, len(group)))
        if rbid != bid or bname != os.path.basename(stem)[:-4]:
            bad.append('%s: bank info %s %d' % (stem, bname, rbid))
        pcm_ok = 0
        for i, s in enumerate(group):
            o = src[s['id']]
            tname, blob = tracks[i]
            nm, rate, nch, ns, vol, cents = tones[i]
            if tname != s['name'] or nm != s['name']:
                bad.append('%s track/tone %d names %r %r' % (stem, i, tname, nm))
            if lab.get(hash40(s['name'])) != i:
                bad.append('%s tonelabel does not map %s to %d' % (stem, s['name'], i))
            ich, irate, ins, ils, ile, ichans = read_idsp(blob)
            if (irate, ich, ins) != (o['rate'], o['channels'], o['samples']) or (rate, nch, ns) != (irate, ich, ins):
                bad.append('%s %s: rate/ch/samples idsp %s tone %s source %s' % (
                    stem, s['name'], (irate, ich, ins), (rate, nch, ns), (o['rate'], o['channels'], o['samples'])))
            if ils or ile:
                bad.append('%s %s: loop %d..%d in a non-looping wave' % (stem, s['name'], ils, ile))
            if abs(vol - o['volume_db']) > 1e-4 or abs(cents - o['pitch_cents']) > 1e-3:
                bad.append('%s %s: volume/pitch %.3f/%.3f, expected %.3f/%.3f' % (
                    stem, s['name'], vol, cents, o['volume_db'], o['pitch_cents']))
            same = True
            for (stream, coefs, ps, yn1, yn2), (raw, scoefs, syn1, syn2) in zip(ichans, o['chans']):
                if ps != raw[0] or stream[:len(raw)] != raw or any(stream[len(raw):]):
                    same = False
                if dsp_decode(stream, coefs, yn1, yn2, ins) != dsp_decode(raw, scoefs, syn1, syn2, o['samples']):
                    same = False
            if same:
                pcm_ok += 1
            else:
                bad.append('%s %s: decoded PCM differs from the .sawnd wave' % (stem, s['name']))
        total += pcm_ok
        lines.append('check %s: %d tracks, %d tones, %d labels (version %d), bank %s id %d; PCM identical %d/%d' % (
            os.path.basename(stem), len(tracks), len(tones), nlab, ver, bname, rbid, pcm_ok, len(group)))
    ids = sorted(s['id'] for k in written for s in written[k][2])
    lines.append('sound ids %#06x..%#06x: %d sounds, %d tones in all, PCM identical %d' % (
        ids[0], ids[-1], len(ids), sum(len(written[k][2]) for k in written), total))
    lines.append('problems: %d' % len(bad))
    lines += ['  ' + b for b in bad[:40]]
    return not bad, lines


def main(argv):
    pos, opts = [], {}
    i = 1
    while i < len(argv):
        a = argv[i]
        if a in ('--names', '--template-se', '--template-vc', '--bank-id', '--se-volume', '--vc-volume'):
            if i + 1 >= len(argv):
                raise SystemExit('%s needs a value' % a)
            opts[a] = argv[i + 1]
            i += 2
        elif a.startswith('--'):
            raise SystemExit('unknown option %s\n%s' % (a, __doc__))
        else:
            pos.append(a)
            i += 1
    if len(pos) != 4 or '--template-se' not in opts or '--template-vc' not in opts:
        raise SystemExit(__doc__)
    try:
        ok, lines = convert(pos[0], pos[1], pos[2], pos[3], opts['--template-se'], opts['--template-vc'],
                            names_path=opts.get('--names'),
                            bank_id=int(opts['--bank-id'], 0) if '--bank-id' in opts else None,
                            se_volume=int(opts.get('--se-volume', str(DEFAULT_SE_VOLUME)), 0),
                            vc_volume=int(opts.get('--vc-volume', str(DEFAULT_VC_VOLUME)), 0))
    except ConvertError as e:
        print('error: %s' % e)
        return 2
    print('\n'.join(lines))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
