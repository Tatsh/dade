"""
Builders for synthetic Marmalade assets.

These construct valid (if minimal) Derbh archives, IwResGroups, textures, and models in memory so
the decoders can be exercised without shipping any copyrighted game data. They are shipped as part
of the package so downstream packages can reuse them in their own tests.
"""
from __future__ import annotations

from posixpath import basename, dirname
from typing import TYPE_CHECKING
import struct

from .hashstring import iw_hash_string

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = ('build_derbh', 'build_font', 'build_material', 'build_model', 'build_resgroup',
           'build_texture')

_FONT_HEADER_OFFSET = 0x10
_FONT_PALETTE_ENTRIES = 16
_STORED = 0x100


def build_derbh(files: Sequence[tuple[str, bytes]]) -> bytes:
    """
    Build a stored-method Derbh archive from ``(path, data)`` pairs.

    Parameters
    ----------
    files : Sequence[tuple[str, bytes]]
        POSIX paths (``folder/name``) and their contents.

    Returns
    -------
    bytes
        A valid ``DTRZ`` archive.
    """
    folders = ['']
    for path, _ in files:
        folder = dirname(path)
        if folder and folder not in folders:
            folders.append(folder)
    fc = len(files)
    header = bytearray(b'DTRZ')
    header += struct.pack('<H', fc)
    header += struct.pack('<H', len(folders))
    header += b'\x00'
    for path, _ in files:
        header += basename(path).encode('latin-1') + b'\x00'
    for folder in folders[1:]:
        header += folder.encode('latin-1') + b'\x00'
    for path, _ in files:
        header += struct.pack('<HHH', folders.index(dirname(path) or ''), 0, 0)
    attr_end = len(header)
    table_len = (fc + 1) * 16
    data_start = attr_end + table_len
    blobs = [data for _, data in files]
    total = sum(len(b) for b in blobs)
    table = bytearray()
    cursor = data_start
    for blob in blobs:
        table += struct.pack('<IIII', cursor, len(blob), len(blob), _STORED)
        cursor += len(blob)
    table += struct.pack('<IIII', data_start + total, 0, 0, _STORED)  # terminator
    return bytes(header + table + b''.join(blobs))


def build_font(pitch: int, height: int) -> bytes:
    """
    Build a minimal ``CIwGxFont`` body decodable by :func:`destin.marmalade.font.decode_font`.

    The glyph-atlas header is placed at the start of the decoder's scan window, the 4-bit atlas
    runs for ``pitch * height`` bytes, and a 16-entry ARGB4444 palette (entry 0 transparent) follows
    it.

    Parameters
    ----------
    pitch : int
        Row stride in bytes; the atlas width is ``pitch * 2`` (one nibble per pixel).
    height : int
        Atlas height in rows.

    Returns
    -------
    bytes
        A ``CIwGxFont`` body.
    """
    off = _FONT_HEADER_OFFSET
    width = pitch * 2
    atlas_len = pitch * height
    body = bytearray(off + 13 + atlas_len)
    struct.pack_into('<H', body, off + 3, width)
    struct.pack_into('<H', body, off + 5, height)
    struct.pack_into('<H', body, off + 7, pitch)
    for i in range(atlas_len):
        body[off + 13 + i] = (i % _FONT_PALETTE_ENTRIES) | (((i + 1) % _FONT_PALETTE_ENTRIES) << 4)
    palette = bytearray()
    for i in range(_FONT_PALETTE_ENTRIES):
        alpha = 0 if i == 0 else 0xF
        palette += struct.pack('<H', (alpha << 12) | (i << 8) | (i << 4) | i)
    return bytes(body + palette)


def build_material(*,
                   flags: int = 0,
                   colours: Sequence[tuple[int, int, int, int]] | None = None,
                   texture_hashes: Sequence[int] = (),
                   same_as_default: bool = False) -> bytes:
    """
    Build a ``CIwMaterial`` body decodable by :func:`destin.marmalade.material.decode_material`.

    Parameters
    ----------
    flags : int
        Material flags word.
    colours : Sequence[tuple[int, int, int, int]]
        Four RGBA colour channels (ambient, emissive, specular, and a fourth colour). Defaults to
        four opaque-black channels.
    texture_hashes : Sequence[int]
        Referenced texture name-hashes (a zero hash is an unused slot).
    same_as_default : bool
        Whether the material carries only its flags (the same-as-default case).

    Returns
    -------
    bytes
        A ``CIwMaterial`` body.
    """
    if same_as_default:
        return bytes((1,)) + struct.pack('<I', flags)
    body = bytearray((0,))
    body += struct.pack('<I', flags)
    body += bytes(4)  # Two u16 fields the decoder skips.
    for colour in colours or [(0, 0, 0, 0xFF)] * 4:
        body += bytes(colour)
    body += struct.pack('<I', len(texture_hashes))
    for texture_hash in texture_hashes:
        body += struct.pack('<I', texture_hash)
    return bytes(body)


def build_resgroup(name: str, resources: Mapping[str, Sequence[bytes]]) -> bytes:
    """
    Build an IwResGroup with a name and per-class resource bodies.

    Parameters
    ----------
    name : str
        Group name (stored in the ``ResGroupMembers`` section).
    resources : Mapping[str, Sequence[bytes]]
        Map of class name to a sequence of raw resource bodies.

    Returns
    -------
    bytes
        A valid ``.group.bin``.
    """
    out = bytearray((0x3D, 0, 0, 0, 0, 0))
    members = name.encode('latin-1') + b'\x00'
    out += struct.pack('<II', iw_hash_string('ResGroupMembers'), len(members) + 4) + members
    payload = bytearray(struct.pack('<I', len(resources)))
    for cls, bodies in resources.items():
        payload += struct.pack('<II', iw_hash_string(cls), len(bodies))
        payload += bytes((1, 1))  # names_omitted, has_size
        for i, body in enumerate(bodies):
            payload += struct.pack('<II', 4 + 4 + len(body), 0x1000 + i) + body
    out += struct.pack('<II', iw_hash_string('ResGroupResources'), len(payload) + 4) + payload
    out += struct.pack('<I', 0)
    return bytes(out)


def build_texture(width: int, height: int, bpp: int, texels: bytes) -> bytes:
    """
    Build a ``CIwTexture`` body decodable by :func:`~destin.marmalade.texture.decode_texture`.

    The width, height, and pitch triple is written into the 16-byte header (width at offset 7,
    height at offset 9, and pitch at offset 11) so that the decoder's scan finds it at offset
    ``0x4``, and the texel bytes are appended after the header so that their start lands in the
    decoder's accepted range.

    Parameters
    ----------
    width, height : int
        Image dimensions.
    bpp : int
        Bytes per pixel (1, 2, 3, or 4); pitch is ``width * bpp``.
    texels : bytes
        Raw texel data of length ``width * bpp * height``.

    Returns
    -------
    bytes
        A ``CIwTexture`` body.
    """
    pitch = width * bpp
    header = bytearray(16)
    struct.pack_into('<H', header, 7, width)
    struct.pack_into('<H', header, 9, height)
    struct.pack_into('<H', header, 11, pitch)
    return bytes(header + texels)


def build_model(vertices: Sequence[tuple[int, int, int]],
                triangles: Sequence[tuple[int, int, int]],
                *,
                uvs: Sequence[tuple[int, int]] | None = None) -> bytes:
    """
    Build a minimal ``CIwModel`` body with Verts and GLTriList blocks.

    Parameters
    ----------
    vertices : Sequence[tuple[int, int, int]]
        Integer ``x, y, z`` positions.
    triangles : Sequence[tuple[int, int, int]]
        Vertex-index triples.
    uvs : Sequence[tuple[int, int]]
        Per-vertex fixed-point ``u, v`` texture coordinates; when given, a ``CIwModelBlockGLUVs``
        block is appended (its length must match *vertices*).

    Returns
    -------
    bytes
        A ``CIwModel`` body decodable by :func:`destin.marmalade.model.decode_model`.
    """
    verts_data = b''.join(struct.pack('<hhh', *v) for v in vertices)
    verts_block = (struct.pack('<I', iw_hash_string('CIwModelBlockVerts')) + b'\x00' * 6 +
                   struct.pack('<H', len(vertices)) + b'\x00' * 4 + verts_data)
    uvs_block = b''
    if uvs is not None:
        uvs_data = b''.join(struct.pack('<hh', u, v) for u, v in uvs)
        uvs_block = (struct.pack('<I', iw_hash_string('CIwModelBlockGLUVs')) + b'\x00' * 6 +
                     struct.pack('<H', len(uvs)) + b'\x00' * 4 + uvs_data)
    idx = [i for tri in triangles for i in tri]
    idx_data = b''.join(struct.pack('<H', i) for i in idx)
    tri_block = bytearray(struct.pack('<I', iw_hash_string('CIwModelBlockGLTriList')))
    tri_block += b'\x00' * (0x12 - len(tri_block))
    tri_block += idx_data
    tri_block += b'\x00' * (0x1A - len(tri_block))
    tri_block += struct.pack('<H', len(idx))
    return bytes(verts_block + uvs_block + tri_block)
