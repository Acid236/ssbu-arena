"""Extend existing BNTX surfaces without changing names or resource pointers.

New RGBA8 pixels are appended inside BRTD; the relocation section is moved and
its image-section size is updated. Existing headers, relocation entries, and
unmodified texture data keep their positions. BNTX layout reference:
https://github.com/Tyulis/3DSkit/blob/master/doc/BNTX.md
"""
import struct

from menu_textures import texture_slots, swizzle, block_height
from bflyt_patch import sarc_files


def replace_rgba(bntx, images):
    d = bytearray(bntx)
    slots = texture_slots(d)
    relocation = struct.unpack_from('<I', d, 0x18)[0]
    image_section = struct.unpack_from('<Q', d, 0x30)[0]
    image_size = struct.unpack_from('<Q', d, image_section+8)[0]
    if d[relocation:relocation+4] != b'_RLT' or d[image_section:image_section+4] != b'BRTD' or image_section+image_size != relocation:
        raise ValueError('unsupported BNTX image/relocation sections')
    table = bytearray(d[relocation:])
    count = struct.unpack_from('<I', table, 8)[0]
    sections = [16+24*i for i in range(count)]
    matching = [s for s in sections if struct.unpack_from('<I', table, s+8)[0] == image_section]
    if len(matching) != 1:
        raise ValueError('BNTX image relocation section is ambiguous')
    pixels = bytearray()
    for name, image in images.items():
        b = slots[name]
        if struct.unpack_from('<H', d, b+0x16)[0] != 1 or struct.unpack_from('<I', d, b+0x30)[0] != 1:
            raise ValueError('RGBA replacement requires a single mip and array layer')
        # Every new surface retains the existing alignment and pointer-table location.
        alignment = max(4096, struct.unpack_from('<I', d, b+0x54)[0])
        offset = (relocation+len(pixels)+alignment-1)//alignment*alignment
        pixels.extend(bytes(offset-relocation-len(pixels)))
        image = image.convert('RGBA')
        w, h = image.size
        surface = swizzle(image.tobytes(), w, h, bpp=4)
        pixels.extend(surface)
        struct.pack_into('<I', d, b+0x1c, 0x0b06)  # RGBA8 sRGB, same colour space as original BC7
        struct.pack_into('<II', d, b+0x24, w, h)
        struct.pack_into('<I', d, b+0x34, block_height(h).bit_length()-1)
        struct.pack_into('<I', d, b+0x50, len(surface))
        pointer = struct.unpack_from('<Q', d, b+0x70)[0]
        struct.pack_into('<Q', d, pointer, offset)
    # An aligned delta preserves every following SARC member's original alignment.
    pixels.extend(bytes((-len(pixels)) % 4096))
    delta = len(pixels)
    struct.pack_into('<Q', d, image_section+8, image_size+delta)
    struct.pack_into('<I', d, 0x18, relocation+delta)
    struct.pack_into('<I', d, 0x1c, len(d)+delta)
    struct.pack_into('<I', table, 4, relocation+delta)
    section = matching[0]
    struct.pack_into('<I', table, section+12, image_size+delta)
    result = bytes(d[:relocation]+pixels+table)
    if len(result) != len(bntx)+delta:
        raise ValueError('BNTX section sizes do not match')
    return result


def replace_sarc_member(archive, name, replacement):
    files = sarc_files(archive)
    start, end = files[name]
    delta = len(replacement)-(end-start)
    if delta % 4096:
        raise ValueError('SARC member resize must preserve alignment')
    d = bytearray(archive[:start]+replacement+archive[end:])
    struct.pack_into('<I', d, 8, len(d))
    data = struct.unpack_from('<I', d, 12)[0]
    for i in range(len(files)):
        node = 0x20+16*i
        a, b = struct.unpack_from('<II', d, node+8)
        a, b = a+data, b+data
        if (a,b) == (start,end):
            b += delta
        elif a >= end:
            a, b = a+delta, b+delta
        elif b > start:
            raise ValueError('overlapping SARC members')
        struct.pack_into('<II', d, node+8, a-data, b-data)
    updated = sarc_files(d)
    if updated.keys() != files.keys():
        raise ValueError('SARC name table changed')
    for member, (a,b) in files.items():
        aa, bb = updated[member]
        expected = replacement if member == name else archive[a:b]
        if d[aa:bb] != expected:
            raise ValueError('unexpected SARC member change: '+member)
    return bytes(d)
