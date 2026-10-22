"""Replace labelled UTF-16 strings within an MSBT's existing TXT2 capacity.

Unchanged messages, embedded control tags, label indices, other sections and
file size are preserved. Structure was read from the owner's local msg_menu
dump (MsgStdBn, LBL1 buckets, TXT2 offsets); little-endian UTF-16 only.
"""
import struct


def sections(data):
    if data[:10] != b'MsgStdBn\xff\xfe' or data[12] != 1:
        raise ValueError('expected a little-endian UTF-16 MSBT')
    offset = 32
    result = {}
    for _ in range(struct.unpack_from('<H', data, 14)[0]):
        size = struct.unpack_from('<I', data, offset + 4)[0]
        start, end = offset + 16, offset + 16 + size
        if end > len(data):
            raise ValueError('MSBT section exceeds file')
        result[data[offset:offset + 4]] = (start, end)
        offset = (end + 15) & ~15
    return result


def labels(data):
    result = {}
    count = struct.unpack_from('<I', data)[0]
    for i in range(count):
        length, offset = struct.unpack_from('<II', data, 4 + 8 * i)
        for _ in range(length):
            size = data[offset]
            offset += 1
            name = data[offset:offset + size].decode('ascii')
            offset += size
            result[name] = struct.unpack_from('<I', data, offset)[0]
            offset += 4
    return result


def messages(data):
    sec = sections(data)
    start, end = sec[b'LBL1']
    names = labels(data[start:end])
    start, end = sec[b'TXT2']
    text = data[start:end]
    count = struct.unpack_from('<I', text)[0]
    offsets = struct.unpack_from('<%dI' % count, text, 4)
    if offsets[0] < 4 + count * 4 or any(a > b for a, b in zip(offsets, offsets[1:])) or offsets[-1] > len(text):
        raise ValueError('invalid TXT2 offsets')
    chunks = [text[a:b] for a, b in zip(offsets, (*offsets[1:], len(text)))]
    return names, chunks


def apply_grow(data, edits):
    """as apply(), and when the new messages do not fit the TXT2 section is made larger: its size field, the 16-byte
    alignment before the next section and the file size in the header (u32 at 0x12) follow"""
    try:
        return apply(data, edits)
    except ValueError as e:
        if 'exceed existing TXT2 capacity' not in str(e):
            raise
    names, chunks = messages(data)
    for name, text in edits.items():
        chunks[names[name]] = text.encode('utf-16-le') + b'\0\0'
    start, end = sections(data)[b'TXT2']
    head = bytearray(struct.pack('<I', len(chunks)) + bytes(4 * len(chunks)))
    at = len(head)
    for i, chunk in enumerate(chunks):
        struct.pack_into('<I', head, 4 + i * 4, at)
        at += len(chunk)
    payload = bytes(head) + b''.join(chunks)
    after = data[(end + 15) & ~15:]
    out = bytearray(data[:start]) + payload
    struct.pack_into('<I', out, start - 12, len(payload))
    out += bytes((-len(out)) % 16) + after
    struct.pack_into('<I', out, 0x12, len(out))
    new_names, new_chunks = messages(bytes(out))
    if new_names != names or len(new_chunks) != len(chunks):
        raise ValueError('MSBT structure changed')
    return bytes(out)


def apply(data, edits):
    names, chunks = messages(data)
    for name, text in edits.items():
        if '\0' in text:
            raise ValueError('replacement contains NUL: ' + name)
        chunks[names[name]] = text.encode('utf-16-le') + b'\0\0'
    start, end = sections(data)[b'TXT2']
    count = len(chunks)
    head = bytearray(struct.pack('<I', count) + bytes(4 * count))
    at = len(head)
    for i, chunk in enumerate(chunks):
        struct.pack_into('<I', head, 4 + i * 4, at)
        at += len(chunk)
    payload = bytes(head) + b''.join(chunks)
    if len(payload) > end - start:
        raise ValueError('replacement messages exceed existing TXT2 capacity by %d bytes' % (len(payload) - (end - start)))
    result = data[:start] + payload.ljust(end - start, b'\0') + data[end:]
    # Verify byte preservation for every other message, including its tags.
    new_names, new_chunks = messages(result)
    changed = {names[name] for name in edits}
    _, old_chunks = messages(data)
    for i, (old, new) in enumerate(zip(old_chunks, new_chunks)):
        if i not in changed and old != new:
            if i != count - 1 or not new.startswith(old) or any(new[len(old):]):
                raise ValueError('unchanged message was modified: %d' % i)
    if new_names != names or len(result) != len(data):
        raise ValueError('MSBT structure changed')
    return result
