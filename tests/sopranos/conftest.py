"""Builders for the binary formats used by The Sopranos: Road to Respect."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import numpy as np
import pytest

from dade.sopranos.archive import DIR_TAG, END_TAG, SECTOR_SIZE, STR_TAG, name_hash
from dade.sopranos.level import INDEX_OFFSET, RECORD_SIZE

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

FORMAT_PALETTED = 2
"""Pixel format code for an image with a 256-entry CLUT."""
FORMAT_RGB = 4
"""Pixel format code for a 24-bit image."""
FORMAT_RGBA = 5
"""Pixel format code for a 32-bit image."""

IMAGE_HEADER_SIZE = 0x2C
SECTION_START_AT = 0x0C
IMAGES_AT = 0x80

_TRIANGLE_LIST = 3
_NREG = 3


def gif_tag(count: int, primitive: int, nreg: int = _NREG, mode: int = 0) -> bytes:
    """
    Build the GIFtag that opens a draw packet.

    Parameters
    ----------
    count : int
        Vertex count, given by the tag in NLOOP.
    primitive : int
        GS primitive type.
    nreg : int
        Per-vertex register count.
    mode : int
        The tag's fourth word.

    Returns
    -------
    bytes
        Sixteen bytes.
    """
    return struct.pack('<4I', count | 0x8000, (primitive << 15) | (nreg << 28), 0x512, mode)


def prop_packet(vertices: Sequence[tuple[float, float, float, float, float]],
                primitive: int = _TRIANGLE_LIST,
                slots: Sequence[tuple[int, int]] = (),
                mode: int = 0) -> bytes:
    """
    Build one ``.SGP2`` draw packet.

    Parameters
    ----------
    vertices : Sequence[tuple[float, float, float, float, float]]
        Each vertex as ``(x, y, z, u, v)``.
    primitive : int
        GS primitive type.
    slots : Sequence[tuple[int, int]]
        Each vertex's two bone palette slots, written to the low bytes of U and V. Vertices past
        the end select slot 0 twice.
    mode : int
        The GIFtag's fourth word.

    Returns
    -------
    bytes
        The tag followed by thirty-two bytes per vertex.
    """
    body = bytearray()
    for index, (x, y, z, u, v) in enumerate(vertices):
        row = bytearray(struct.pack('<8f', x, y, z, 0.0, u, v, 0.0, 0.0))
        first, second = slots[index] if index < len(slots) else (0, 0)
        row[16] = first * 4
        row[20] = second * 4
        body += row
    return gif_tag(len(vertices), primitive, mode=mode) + bytes(body)


def palette_commands(palette: Sequence[int]) -> bytes:
    """
    Build the opcode 6 commands that load a bone palette.

    Parameters
    ----------
    palette : Sequence[int]
        Indices into the section's bone list, twelve to a command.

    Returns
    -------
    bytes
        One sixteen-byte command per twelve entries.
    """
    return b''.join(
        struct.pack('<2H', 6, len(palette)) + bytes(palette[start:start + 12]).ljust(12, b'\0')
        for start in range(0, len(palette), 12))


def build_skeletons(skeletons: Sequence[tuple[str, Sequence[tuple[str, int, Sequence[float]]]]],
                    *,
                    hashes: Sequence[int] = ()) -> bytes:
    """
    Build a ``.SKL2`` file.

    Parameters
    ----------
    skeletons : Sequence[tuple[str, Sequence[tuple[str, int, Sequence[float]]]]]
        Per skeleton, its path and its bones as ``(name, parent, local)``, the local transform
        being sixteen floats of a row-major matrix for row vectors.
    hashes : Sequence[int]
        Hashes to record in place of the paths' own, in skeleton order.

    Returns
    -------
    bytes
        The whole file.
    """
    out = bytearray()
    for number, (name, bones) in enumerate(skeletons):
        table = 0x20
        strings_at = table + len(bones) * 0x90
        strings = bytearray(name.encode() + b'\0')
        records = bytearray()
        world: list[np.ndarray] = []
        for bone_name, parent, local in bones:
            matrix = np.array(local, dtype=np.float64).reshape(4, 4)
            world.append(matrix if parent < 0 else matrix @ world[parent])
            records += struct.pack('<16f', *local)
            records += struct.pack('<16f', *np.linalg.inv(world[-1]).reshape(16))
            records += struct.pack('<hHI', parent, strings_at + len(strings), name_hash(bone_name))
            records += bytes(8)
            strings += bone_name.encode() + b'\0'
        body = bytes(records) + bytes(strings)
        body += bytes(-len(body) % 16)
        hash_ = hashes[number] if number < len(hashes) else name_hash(name)
        header = struct.pack('<2I', hash_, table + len(body)) + bytes(8)
        header += struct.pack('<3H', len(bones), table, strings_at)
        out += header.ljust(table, b'\0') + body
    return bytes(out)


def build_clips(
    clips: Sequence[tuple[str, int, int,
                          Sequence[tuple[str, int, Sequence[int], Sequence[Sequence[int]],
                                         Sequence[Sequence[float]], tuple[float, float, float]]]]]
) -> bytes:
    """
    Build a ``.SAM2`` file.

    Parameters
    ----------
    clips : Sequence[tuple[str, int, int, Sequence[tuple[...]]]]
        Per clip, its path, frame count, rate, and tracks. Each track is ``(bone, kind, frames,
        rotations, translations, offset)``: the rotations are four stored half-words a key, the
        translations three floats a key (written for kind 5 only), and the offset the constant
        offset of a kind 4 track.

    Returns
    -------
    bytes
        The whole file.
    """
    out = bytearray(16)
    for name, frame_count, rate, tracks in clips:
        table = 0x18
        data_at = table + len(tracks) * 32
        data = bytearray()
        records = bytearray()
        for bone, kind, frames, rotations, translations, offset in tracks:
            frames_at = data_at + len(data)
            data += struct.pack(f'<{len(frames)}H', *frames)
            data += bytes(-len(data) % 4)
            keys_at = data_at + len(data)
            for index, rotation in enumerate(rotations):
                if kind == 5:
                    data += struct.pack('<3f', *translations[index])
                data += struct.pack('<4H', *rotation)
            bone_at = data_at + len(data)
            data += bone.encode() + b'\0'
            data += bytes(-len(data) % 4)
            records += struct.pack('<3f', *offset)
            records += struct.pack('<4H', kind, bone_at + 0x10, len(frames), 0)
            records += struct.pack('<3I', name_hash(bone), frames_at + 0x10, keys_at + 0x10)
        name_at = data_at + len(data)
        data += name.encode() + b'\0'
        data += bytes(-len(data) % 4)
        size = data_at + len(data)
        header = struct.pack('<2I', size, name_hash(name)) + bytes(6)
        header += struct.pack('<5H', name_at + 0x10, frame_count, rate, len(tracks), table + 0x10)
        out += header + bytes(records) + bytes(data)
    return bytes(out)


def build_archive(files: Mapping[str, bytes], *, named: bool = True) -> bytes:
    """
    Build a ``.FS`` archive.

    Parameters
    ----------
    files : Mapping[str, bytes]
        File contents by name.
    named : bool
        Include the string table, allowing entries to be matched to names.

    Returns
    -------
    bytes
        The whole archive.
    """
    body = bytearray()
    rows = []
    for name, payload in files.items():
        body += bytes(-len(body) % SECTOR_SIZE)
        rows.append((len(body) // SECTOR_SIZE, len(payload), name_hash(name)))
        body += payload
    body += bytes(-len(body) % SECTOR_SIZE)
    toc = len(body)
    chunks = bytearray()
    if named:
        names = b'\0'.join(name.encode() for name in files) + b'\0'
        chunks += struct.pack('<4sI', STR_TAG, len(names)) + names
    entries = b''.join(struct.pack('<4I', 0, *row) for row in rows)
    chunks += struct.pack('<4sI', DIR_TAG, len(entries)) + entries
    chunks += struct.pack('<4sI', END_TAG, 0)
    return bytes(body + chunks + struct.pack('<I', toc))


def build_level(assets: Mapping[str, bytes]) -> bytes:
    """
    Build a ``.LVL`` container.

    Parameters
    ----------
    assets : Mapping[str, bytes]
        Sub-asset contents by name.

    Returns
    -------
    bytes
        The whole container.
    """
    start = INDEX_OFFSET + len(assets) * RECORD_SIZE
    records = bytearray()
    body = bytearray()
    for name, payload in assets.items():
        records += struct.pack('<2I', start + len(body), len(payload))
        records += name.encode().ljust(0x20, b'\0')
        body += payload
    return struct.pack('<I', len(assets)) + bytes(12) + bytes(records) + bytes(body)


def build_image(name: str,
                width: int,
                height: int,
                pixel_format: int,
                pixels: bytes,
                palette: bytes = b'',
                blend_mode: int = 0) -> bytes:
    """
    Build one image record as embedded in a bank or geometry blob.

    Parameters
    ----------
    name : str
        The image's recorded source path.
    width : int
        Width in pixels.
    height : int
        Height in pixels.
    pixel_format : int
        One of the ``FORMAT_*`` codes.
    pixels : bytes
        The pixel data.
    palette : bytes
        The CLUT, for a paletted image.
    blend_mode : int
        The cooker's blend mode, as stored in byte ``0x1B``.

    Returns
    -------
    bytes
        The complete record.
    """
    encoded = name.encode() + b'\0'
    data_at = IMAGE_HEADER_SIZE + len(encoded)
    data_at += -data_at % 4
    palette_at = data_at + len(pixels) if palette else 0
    total = palette_at + len(palette) if palette else data_at + len(pixels)
    header = bytearray(IMAGE_HEADER_SIZE)
    struct.pack_into('<4I', header, 0, 0x65, total, IMAGE_HEADER_SIZE, name_hash(name))
    struct.pack_into('<2H', header, 0x14, width, height)
    header[0x1A] = pixel_format
    header[0x1B] = blend_mode
    struct.pack_into('<2I', header, 0x24, data_at, palette_at)
    padding = bytes(data_at - IMAGE_HEADER_SIZE - len(encoded))
    return bytes(header) + encoded + padding + pixels + palette


def build_bank(images: Sequence[bytes]) -> bytes:
    """
    Build a ``.TEX2`` bank around image records.

    Parameters
    ----------
    images : Sequence[bytes]
        Records from :py:func:`build_image`.

    Returns
    -------
    bytes
        The whole bank.
    """
    start = 12 + len(images) * 4
    offsets = []
    body = bytearray()
    for image in images:
        offsets.append(start + len(body))
        body += image
    return (struct.pack('<3I', 0x64, 0, len(images)) + struct.pack(f'<{len(images)}I', *offsets) +
            bytes(body))


@pytest.fixture
def archive_bytes() -> Callable[..., bytes]:
    """
    Give the ``.FS`` archive builder.

    Returns
    -------
    Callable[..., bytes]
        :py:func:`build_archive`.
    """
    return build_archive


@pytest.fixture
def level_bytes() -> Callable[..., bytes]:
    """
    Give the ``.LVL`` container builder.

    Returns
    -------
    Callable[..., bytes]
        :py:func:`build_level`.
    """
    return build_level


def build_section(name: str,
                  materials: Sequence[Sequence[str]],
                  items: Sequence[tuple[str, Sequence[tuple[int, Sequence[bytes]]]]],
                  *,
                  bones: Sequence[str] = (),
                  palettes: Sequence[Sequence[int]] = (),
                  skeleton_hash: int = 0) -> bytes:
    """
    Build one ``.SGP2`` object section.

    Parameters
    ----------
    name : str
        The section's name.
    materials : Sequence[Sequence[str]]
        Per material, the texture names it references.
    items : Sequence[tuple[str, Sequence[tuple[int, Sequence[bytes]]]]]
        Per item, its name and its groups as ``(material index, packets)``.
    bones : Sequence[str]
        The section's bone list. An empty name is written as a zero offset.
    palettes : Sequence[Sequence[int]]
        A bone palette loaded before each group, counting groups across every item. Groups past
        the end load none.
    skeleton_hash : int
        The skeleton hash recorded at ``0x04``.

    Returns
    -------
    bytes
        The section, ready to be placed in a library.
    """
    strings = bytearray(b'\0')
    offsets: dict[str, int] = {}

    def intern(text: str) -> int:
        if text not in offsets:
            offsets[text] = 0x60 + len(strings)
            strings.extend(text.encode() + b'\0')
        return offsets[text]

    # Every name is interned before the layout is measured; no offset moves afterwards.
    intern(name)
    material_names = [[intern(texture) for texture in slots] for slots in materials]
    for item_name, _groups in items:
        intern(item_name)
    bone_offsets = [intern(bone) if bone else 0 for bone in bones]
    group_number = 0
    material_at = 0x60 + len(strings)
    blocks_at = material_at + len(materials) * 0x34
    blocks = bytearray()
    records = []
    for item_name, groups in items:
        block_at = blocks_at + len(blocks)
        packets = bytearray()
        commands = bytearray()
        for material, chunks in groups:
            start = 0x10 + len(packets)
            for chunk in chunks:
                packets += chunk
            if group_number < len(palettes):
                commands += palette_commands(palettes[group_number])
            group_number += 1
            commands += struct.pack('<HHIII', 1, 0, material, 0, 0)
            commands += struct.pack('<HHIII', 7, 0, start, (len(packets) + 0x10 - start) // 16, 0)
        block = struct.pack('<4I', len(packets), 0, 0, len(commands) // 16)
        block += bytes(packets) + bytes(commands)
        records.append((item_name, block_at, len(block)))
        blocks += block
    table_at = blocks_at + len(blocks)
    table = bytearray()
    for index, (item_name, block_at, size) in enumerate(records):
        record_at = table_at + index * 20
        table += struct.pack('<iIIiHH', offsets[item_name] - record_at, 0, size,
                             block_at - record_at, 0, 0)
    material_table = bytearray()
    for slots in material_names:
        record = bytearray(0x34)
        for slot, offset in enumerate(slots):
            struct.pack_into('<I', record, 4 + slot * 16, offset)
        material_table += record
    bone_table = struct.pack(f'<{len(bone_offsets)}I', *bone_offsets)
    header = bytearray(0x60)
    struct.pack_into('<I', header, 0x04, skeleton_hash)
    struct.pack_into('<I', header, 0x08, offsets[name])
    struct.pack_into('<I', header, 0x0C, table_at + len(table) + len(bone_table))
    struct.pack_into('<H', header, 0x3C, len(bone_offsets))
    struct.pack_into('<H', header, 0x3E, len(materials))
    struct.pack_into('<H', header, 0x40, len(records))
    struct.pack_into('<I', header, 0x44, table_at + len(table))
    struct.pack_into('<I', header, 0x50, material_at)
    struct.pack_into('<I', header, 0x54, table_at)
    return (bytes(header) + bytes(strings) + bytes(material_table) + bytes(blocks) + bytes(table) +
            bone_table)


def build_library(sections: Sequence[bytes], images: Sequence[bytes] = ()) -> bytes:
    """
    Build a ``.SGP2`` library around sections and embedded images.

    Parameters
    ----------
    sections : Sequence[bytes]
        Records from :py:func:`build_section`.
    images : Sequence[bytes]
        Records from :py:func:`build_image`, stored before the sections.

    Returns
    -------
    bytes
        The whole library.
    """
    body = b''.join(images)
    start = IMAGES_AT + len(body)
    header = bytearray(IMAGES_AT)
    # The same word ends the image run and starts the section chain. Sections follow images.
    struct.pack_into('<I', header, SECTION_START_AT, start)
    return bytes(header) + body + b''.join(sections)


def mesh_packet(vertices: Sequence[tuple[float, float, float, float, float]],
                primitive: int = _TRIANGLE_LIST) -> bytes:
    """
    Build one ``.EGP2`` draw packet.

    A packet opens with the two bounding-box rows the reader looks for, then its GIFtag, then
    eighty-byte groups of four vertices each.

    Parameters
    ----------
    vertices : Sequence[tuple[float, float, float, float, float]]
        Each vertex as ``(x, y, z, u, v)``.
    primitive : int
        GS primitive type.

    Returns
    -------
    bytes
        The whole packet.
    """
    low = min(v[0] for v in vertices), min(v[1] for v in vertices), min(v[2] for v in vertices)
    # The upper corner is nudged out. A flat run of vertices therefore still gives the box an
    # extent, and the extent is how the reader tells a bounding box from ordinary vertex data.
    high = (max(v[0] for v in vertices) + 1.0, max(v[1] for v in vertices) + 1.0,
            max(v[2] for v in vertices) + 1.0)
    out = bytearray(struct.pack('<4f', *low, 1.0) + struct.pack('<4f', *high, 1.0))
    out += gif_tag(len(vertices), primitive)
    for start in range(0, len(vertices), 4):
        chunk = list(vertices[start:start + 4])
        while len(chunk) < 4:
            chunk.append((0.0, 0.0, 0.0, 0.0, 0.0))
        for x, y, _z, u, v in chunk:
            out += struct.pack('<4f', u, v, x, y)
        out += struct.pack('<4f', *(vertex[2] for vertex in chunk))
    return bytes(out)


def build_geometry(materials: Sequence[tuple[str, int]],
                   meshes: Sequence[tuple[int, Sequence[bytes]]],
                   owners: Mapping[int, int] | None = None,
                   images: Sequence[bytes] = (),
                   pass_sums: Sequence[int] | None = None) -> bytes:
    """
    Build a ``.EGP2`` geometry blob.

    Parameters
    ----------
    materials : Sequence[tuple[str, int]]
        Per material, its texture name and the offset of its image record.
    meshes : Sequence[tuple[int, Sequence[bytes]]]
        Per mesh, the index it records and its packets.
    owners : Mapping[int, int] | None
        Material index by mesh position; meshes omitted are owned by no material.
    images : Sequence[bytes]
        Records from :py:func:`build_image`, embedded after the header.
    pass_sums : Sequence[int] | None
        Prefix sums partitioning the material records between render passes, written as the pass
        table the header points at; :py:obj:`None` puts every material in pass one.

    Returns
    -------
    bytes
        The whole blob.
    """
    owners = {} if owners is None else owners
    embedded = b''.join(images)
    strings = bytearray(b'\0')
    name_offsets = []
    for name, _texture in materials:
        name_offsets.append(len(strings))
        strings.extend(name.encode() + b'\0')
    body = bytearray()
    blocks = []
    base = IMAGES_AT + len(embedded) + len(strings)
    for number, packets in meshes:
        # Each mesh's block must sit exactly a whole number of quadwords past its data.
        body += bytes(-len(body) % 16)
        start = base + len(body)
        for packet in packets:
            body += packet
        body += bytes(-len(body) % 16)
        block = base + len(body)
        blocks.append(block)
        body += struct.pack('<3I', number, start, (block - start) // 16)
    pointers_at = base + len(body)
    pointers = b''.join(struct.pack('<2I', block, 0) for block in blocks)
    body += pointers
    passes_at = base + len(body)
    by_material: dict[int, list[int]] = {}
    for position, material in owners.items():
        by_material.setdefault(material, []).append(position)
    pass_offsets = {}
    passes = bytearray()
    for material, positions in sorted(by_material.items()):
        pass_offsets[material] = passes_at + len(passes)
        for position in positions:
            passes += struct.pack('<2I', 1, pointers_at + position * 8)
    body += passes
    owners_at = base + len(body)
    body += b''.join(
        struct.pack('<4I', material, 0, pass_offsets.get(material, 0), 0)
        for material in range(len(materials)))
    table_at = base + len(body)
    body += b''.join(
        struct.pack('<I', offset) + bytes(0x0C) + struct.pack('<I', texture) + bytes(84 - 0x14)
        for offset, (_name, texture) in zip(name_offsets, materials, strict=True))
    mesh_table_at = base + len(body)
    body += struct.pack(f'<{len(blocks)}I', *blocks) if blocks else b''
    # Room past the mesh table, allowing a test to raise the declared count without over-reading.
    body += bytes(16)
    pass_table_at = 0
    if pass_sums is not None:
        pass_table_at = base + len(body)
        body += struct.pack(f'<{len(pass_sums)}I', *pass_sums)
    header = bytearray(IMAGES_AT)
    struct.pack_into('<I', header, 0x30, max(len(pass_sums) - 1, 0) if pass_sums is not None else 0)
    struct.pack_into('<I', header, 0x34, pass_table_at)
    struct.pack_into('<I', header, 0x14, len(materials))
    struct.pack_into('<I', header, 0x20, len(blocks))
    struct.pack_into('<I', header, 0x50, table_at)
    struct.pack_into('<I', header, 0x4C, IMAGES_AT if embedded else 0)
    struct.pack_into('<I', header, 0x54, IMAGES_AT + len(embedded))
    struct.pack_into('<I', header, 0x58, owners_at)
    struct.pack_into('<I', header, 0x64, mesh_table_at)
    return bytes(header) + embedded + bytes(strings) + bytes(body)
