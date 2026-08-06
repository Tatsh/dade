"""
Builders for synthetic Incoming asset bytes.

These construct minimal but valid assets in memory so the converters can be exercised without
shipping any copyrighted game data. They are shipped as part of the package so downstream code can
reuse them in its own tests.
"""
from __future__ import annotations

import struct

__all__ = ('ctl_records', 'ian_model', 'mbin_pair', 'mlt_container', 'osb_bank', 'pvr_pack',
           'pvrt_chunk')

_PVRT_SUBHEADER = struct.Struct('<BBHHH')


def pvrt_chunk(width: int = 2, height: int = 2, *, data_format: int = 1, extra: int = 0) -> bytes:
    """
    Build a single standard PVRT chunk with zeroed pixel data.

    Parameters
    ----------
    width : int
        Texture width.
    height : int
        Texture height.
    data_format : int
        PowerVR data-format identifier.
    extra : int
        Extra trailing pixel bytes beyond ``width * height * 2``.

    Returns
    -------
    bytes
        The PVRT chunk.
    """
    pixel_data = bytes(width * height * 2 + extra)
    subheader = _PVRT_SUBHEADER.pack(0, data_format, 0, width, height)
    return b'PVRT' + struct.pack('<I', len(subheader) + len(pixel_data)) + subheader + pixel_data


def pvr_pack(chunks: list[bytes], *, sizes: list[int] | None = None) -> bytes:
    """
    Build a ``*_T.PVR`` pack from PVRT chunks.

    Parameters
    ----------
    chunks : list[bytes]
        The PVRT chunks to pack.
    sizes : list[int] | None
        Table-of-contents sizes overriding the actual chunk lengths (to simulate truncation).

    Returns
    -------
    bytes
        The pack bytes.
    """
    toc_length = len(chunks) * 8
    offset = toc_length
    toc = b''
    body = b''
    for index, chunk in enumerate(chunks):
        toc += struct.pack('<II', offset, sizes[index] if sizes else len(chunk))
        body += chunk
        offset += len(chunk)
    return toc + body


def ian_model(vertices: list[tuple[float, ...]],
              faces: list[tuple[int, int, int]],
              name: str = 'M') -> bytes:
    """
    Build an IAN model with one level of detail.

    Parameters
    ----------
    vertices : list[tuple[float, ...]]
        Eight-float vertices (position, normal, UV).
    faces : list[tuple[int, int, int]]
        Triangles as vertex-index triples.
    name : str
        Node name embedded before the face data.

    Returns
    -------
    bytes
        The IAN model bytes.
    """
    p_vertices = 0x28
    vertex_bytes = b''.join(struct.pack('<8f', *v) for v in vertices)
    name_bytes = b'\x00' + name.encode('ascii') + b'\x00'
    p_faces = p_vertices + len(vertex_bytes) + len(name_bytes)
    lod = struct.pack('<IHHIII', len(faces), len(vertices), 0, p_vertices, p_faces, 0)
    face_data = bytearray()
    for i0, i1, i2 in faces:
        record = bytearray(28)
        struct.pack_into('<H', record, 0x04, i0)
        struct.pack_into('<H', record, 0x0c, i1)
        struct.pack_into('<H', record, 0x14, i2)
        face_data += record
    return bytes(0x14) + lod + vertex_bytes + name_bytes + bytes(face_data)


def mbin_pair(*,
              texture_index: int = 8,
              vertex_count: int = 3,
              extra_offsets: tuple[int, ...] = ()) -> tuple[bytes, bytes]:
    """
    Build a matching ``(*_M.BIN, *_ML.BIN)`` pair with one mesh object.

    Parameters
    ----------
    texture_index : int
        Texture-pack index packed into the object record.
    vertex_count : int
        Number of vertices in the object.
    extra_offsets : tuple[int, ...]
        Additional ``*_ML.BIN`` offsets inserted before the terminator.

    Returns
    -------
    tuple[bytes, bytes]
        The ``*_M.BIN`` and ``*_ML.BIN`` bytes.
    """
    header = bytearray(0x90)
    p_vertices = 0x90
    vertices = b''.join(
        struct.pack('<10f', float(x), 0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0, 0.25, 0.75)
        for x in range(vertex_count))
    p_faces = p_vertices + len(vertices)
    struct.pack_into('<5I', header, 0x10, 0, 1, (texture_index << 16) | vertex_count, p_vertices,
                     p_faces)
    faces = struct.pack('<4I', (5 << 16) | 3, 0, 1, 2)
    m_bin = bytes(header) + vertices + faces
    ml_bin = b''.join(struct.pack('<I', o) for o in (0, *extra_offsets, 0xffffffff))
    return m_bin, ml_bin


def osb_bank(*,
             lea: int = 4,
             pitch: int = 0x7800,
             count: int = 1,
             sosp_magic: bytes = b'SOSP',
             bank_magic: bytes = b'SOSB') -> bytes:
    """
    Build an OSB sound bank with one SOSP record.

    Parameters
    ----------
    lea : int
        Sample count of the record.
    pitch : int
        Packed FNS/OCT pitch word.
    count : int
        Record count in the header.
    sosp_magic : bytes
        Magic written into the record (set to a wrong value to test rejection).
    bank_magic : bytes
        Magic written into the bank header (set to a wrong value to test rejection).

    Returns
    -------
    bytes
        The OSB bank bytes.
    """
    record_offset = 0x14
    header = bank_magic + struct.pack('<III', 1, 0, count)
    table = struct.pack('<I', record_offset)
    record = bytearray(56)
    record[0:4] = sosp_magic
    struct.pack_into('<H', record, 0x06, record_offset + 56)
    struct.pack_into('<H', record, 0x0a, lea)
    struct.pack_into('<H', record, 0x10, pitch)
    return header + table + bytes(record) + bytes((lea + 1) >> 1)


def mlt_container(*, count: int = 1, magic: bytes = b'SMLT') -> bytes:
    """
    Build an SMLT multi-unit container.

    Parameters
    ----------
    count : int
        Number of units.
    magic : bytes
        Container magic (set to a wrong value to test rejection).

    Returns
    -------
    bytes
        The MLT container bytes.
    """
    header = magic + struct.pack('<II', 0x101, count)
    header += bytes(0x20 - len(header))
    units = b''.join(
        struct.pack('<4sIIIIIII', b'SOSB', i, 0x18000, 0x100, 0x80, 0x100, 0, 0)
        for i in range(count))
    return header + units


def ctl_records(count: int) -> bytes:
    """
    Build a CTL file with ``count`` 16-byte records.

    Parameters
    ----------
    count : int
        Number of records, including the seed record.

    Returns
    -------
    bytes
        The CTL bytes.
    """
    return b''.join(struct.pack('<4I', i, i, i, i) for i in range(count))
