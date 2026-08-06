"""
Builders for synthetic Tony Hawk's Pro Skater 2 PC asset bytes.

These construct minimal but valid containers in memory so the readers can be exercised without
shipping any copyrighted game data. They are shipped as part of the package so downstream code can
reuse them in its own tests.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import struct

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = ('FaceSpec', 'PkrFileSpec', 'SectorSpec', 'TextureSpec', 'face_record', 'pkr_archive',
           'psx_lighting', 'psx_scene', 'stored_file')

_DESCRIPTOR_SIZE = 0x24
_SECTOR_HEADER_SIZE = 0x1C
_TERMINATOR = 0xFFFFFFFF
_TEXTURE_INDEX_MIN_LENGTH = 5


class PkrFileSpec(NamedTuple):
    """One file to place in a synthetic pack."""

    name: str
    """File name within its directory."""
    stored: bytes
    """Bytes written into the data region."""
    method: int
    """Compression method recorded for the entry."""
    uncompressed_size: int
    """Size recorded as the entry's decompressed length."""


class FaceSpec(NamedTuple):
    """One face to place in a synthetic sector."""

    corners: Sequence[int]
    """Vertex indices, three or four of them."""
    texture_index: int
    """Index into the scene's checksum table."""
    uvs: Sequence[tuple[int, int]]
    """Raw 8-bit texture coordinates per corner."""
    flags: int
    """Low 18 bits of the face's first dword."""
    length: int
    """Length of the record in dwords."""


class SectorSpec(NamedTuple):
    """One sector to place in a synthetic scene."""

    vertices: Sequence[tuple[int, int, int]]
    """Vertex positions."""
    faces: Sequence[bytes]
    """Encoded face records, as produced by :py:func:`face_record`."""
    count_b: int
    """How many of the vertices are ghost or stitch vertices."""


class TextureSpec(NamedTuple):
    """One texture instance to place in a synthetic lighting file."""

    clut_id: int
    """Identifier of the palette the texture uses."""
    height: int
    """Height in pixels."""
    num_colors: int
    """Palette size: ``0x10`` selects 4 bits per pixel, anything else 8 bits."""
    page: int
    """Index into the file's checksum table."""
    pixels: bytes
    """Packed pixel indices."""
    width: int
    """Width in pixels."""


def stored_file(name: str, payload: bytes) -> PkrFileSpec:
    """
    Describe an uncompressed pack entry.

    Parameters
    ----------
    name : str
        File name within its directory.
    payload : bytes
        The file's contents.

    Returns
    -------
    PkrFileSpec
        A specification using the stored compression method.
    """
    return PkrFileSpec(name=name, stored=payload, method=-2, uncompressed_size=len(payload))


def pkr_archive(directories: Sequence[tuple[str, Sequence[PkrFileSpec]]],
                alignment: int = 4,
                magic: bytes = b'PKR2') -> bytes:
    """
    Build a synthetic ``PKR2`` resource pack.

    Parameters
    ----------
    directories : Sequence[tuple[str, Sequence[PkrFileSpec]]]
        Each directory's name, including its trailing separator, and the files it holds.
    alignment : int
        Value recorded in the header's alignment field.
    magic : bytes
        Magic bytes to write, so a rejection path can be exercised.

    Returns
    -------
    bytes
        The complete pack.
    """
    dir_count = len(directories)
    file_count = sum(len(files) for _, files in directories)
    table_b_start = 16 + dir_count * 40
    data_start = table_b_start + file_count * 48
    table_a = bytearray()
    table_b = bytearray()
    payload = bytearray()
    index = 0
    for name, files in directories:
        table_a += struct.pack('<32sII', name.encode(), table_b_start + index * 48, len(files))
        for spec in files:
            table_b += struct.pack('<32siIII', spec.name.encode(), spec.method,
                                   data_start + len(payload), spec.uncompressed_size,
                                   len(spec.stored))
            payload += spec.stored
            index += 1
    return (struct.pack('<4sIII', magic, alignment, dir_count, file_count) + bytes(table_a) +
            bytes(table_b) + bytes(payload))


def face_record(corners: Sequence[int],
                *,
                texture_index: int = 0,
                uvs: Sequence[tuple[int, int]] | None = None,
                flags: int = 1,
                length: int = 7) -> bytes:
    """
    Encode one face record.

    Parameters
    ----------
    corners : Sequence[int]
        Vertex indices, three or four of them.
    texture_index : int
        Index into the scene's checksum table, written at dword four.
    uvs : Sequence[tuple[int, int]] | None
        Raw 8-bit texture coordinates per corner. Defaults to zeroes.
    flags : int
        Low 18 bits of the first dword. Bit ``0x01`` marks the face textured and bit ``0x10``
        marks it a triangle.
    length : int
        Length of the record in dwords.

    Returns
    -------
    bytes
        The encoded record, exactly ``length * 4`` bytes long.
    """
    record = bytearray(length * 4)
    struct.pack_into('<I', record, 0, (length << 18) | flags)
    for i, corner in enumerate(corners):
        record[4 + i] = corner
    if length >= _TEXTURE_INDEX_MIN_LENGTH:
        struct.pack_into('<I', record, 16, texture_index)
    pairs = list(uvs) if uvs is not None else [(0, 0)] * len(corners)
    for i, (u, v) in enumerate(pairs):
        if 20 + i * 2 + 1 < len(record):
            record[20 + i * 2] = u
            record[20 + i * 2 + 1] = v
    return bytes(record)


def psx_scene(sectors: Sequence[SectorSpec] = (),
              descriptors: Sequence[tuple[int, tuple[int, int, int]]] = (),
              chunks: Sequence[tuple[int, bytes]] = (),
              checksums: Sequence[int] = (),
              version: int = 0x00020004) -> bytes:
    """
    Build a synthetic ``.PSX`` scene.

    Parameters
    ----------
    sectors : Sequence[SectorSpec]
        The sectors to write, in table order.
    descriptors : Sequence[tuple[int, tuple[int, int, int]]]
        Each descriptor's target sector index and its world position, before the twelve-bit
        fixed-point shift is applied.
    chunks : Sequence[tuple[int, bytes]]
        Chunk list records as an identifier and its payload. A terminator is always appended.
    checksums : Sequence[int]
        The texture checksum table written after the chunk list.
    version : int
        Value recorded in the header's version field.

    Returns
    -------
    bytes
        The complete scene.
    """
    header_size = 0x0C + len(descriptors) * _DESCRIPTOR_SIZE
    table_start = header_size + 4
    body_start = table_start + len(sectors) * 4
    offsets = []
    body = bytearray()
    for spec in sectors:
        offsets.append(body_start + len(body))
        block = bytearray(_SECTOR_HEADER_SIZE)
        struct.pack_into('<HHH', block, 2,
                         len(spec.vertices) - spec.count_b, spec.count_b, len(spec.faces))
        for x, y, z in spec.vertices:
            block += struct.pack('<hhhh', x, y, z, 0)
        for record in spec.faces:
            block += record
        body += block
    chunk_bytes = bytearray()
    for identifier, payload in chunks:
        chunk_bytes += struct.pack('<Ii', identifier & 0xFFFFFFFF, len(payload)) + payload
    chunk_bytes += struct.pack('<I', _TERMINATOR)
    chunk_bytes += b'\x00' * (len(sectors) * 4)
    chunk_bytes += struct.pack('<I', len(checksums))
    for value in checksums:
        chunk_bytes += struct.pack('<I', value)
    chunk_list_offset = body_start + len(body)
    out = bytearray(struct.pack('<III', version, chunk_list_offset, len(descriptors)))
    for sequence, (x, y, z) in descriptors:
        entry = bytearray(_DESCRIPTOR_SIZE)
        struct.pack_into('<iii', entry, 4, x << 12, y << 12, z << 12)
        struct.pack_into('<H', entry, 0x16, sequence)
        out += entry
    out += struct.pack('<I', len(sectors))
    for offset in offsets:
        out += struct.pack('<I', offset)
    out += body
    out += chunk_bytes
    return bytes(out)


def psx_lighting(
    checksums: Sequence[int] = (),
    cluts_16: Mapping[int, Sequence[int]] | None = None,
    cluts_256: Mapping[int, Sequence[int]] | None = None,
    instances: Sequence[TextureSpec] = (),
    chunks: Sequence[tuple[int, bytes]] = ()
) -> bytes:
    """
    Build a synthetic ``*_L.PSX`` lighting file.

    Parameters
    ----------
    checksums : Sequence[int]
        The texture checksum table.
    cluts_16 : Mapping[int, Sequence[int]] | None
        16-colour palettes by identifier. Each is padded to sixteen entries.
    cluts_256 : Mapping[int, Sequence[int]] | None
        256-colour palettes by identifier. Each is padded to 256 entries.
    instances : Sequence[TextureSpec]
        The texture instances to write.
    chunks : Sequence[tuple[int, bytes]]
        Chunk list records as an identifier and its payload. A terminator is always appended.

    Returns
    -------
    bytes
        The complete lighting file.
    """
    tail = bytearray()
    for identifier, payload in chunks:
        tail += struct.pack('<Ii', identifier & 0xFFFFFFFF, len(payload)) + payload
    tail += struct.pack('<I', _TERMINATOR)
    chunk_list_offset = 12
    tail += struct.pack('<I', len(checksums))
    for value in checksums:
        tail += struct.pack('<I', value)
    for table, size in ((cluts_16 or {}, 16), (cluts_256 or {}, 256)):
        tail += struct.pack('<I', len(table))
        for identifier, entries in table.items():
            padded = list(entries) + [0] * (size - len(entries))
            tail += struct.pack('<I', identifier)
            for entry in padded[:size]:
                tail += struct.pack('<H', entry)
    tail += struct.pack('<I', len(instances))
    table_offset = chunk_list_offset + len(tail)
    records = bytearray()
    pointers = bytearray()
    records_start = table_offset + len(instances) * 4
    for spec in instances:
        pointers += struct.pack('<I', records_start + len(records))
        record = bytearray(0x14)
        struct.pack_into('<III', record, 4, spec.num_colors, spec.clut_id, spec.page)
        struct.pack_into('<HH', record, 0x10, spec.width, spec.height)
        records += bytes(record) + spec.pixels
    return (struct.pack('<III', 0x00020004, chunk_list_offset, 0) + bytes(tail) + bytes(pointers) +
            bytes(records))
