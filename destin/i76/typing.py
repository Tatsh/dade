"""Typed data structures shared across :py:mod:`destin.i76`."""
from __future__ import annotations

from typing import NamedTuple, TypeAlias

__all__ = ('Chunk', 'GeoModel', 'IndexedImage', 'Mesh', 'PakEntry', 'PeSection', 'RgbImage',
           'SdfPart', 'Vector3', 'VqmImage', 'ZfsEntry')

Vector3: TypeAlias = 'tuple[float, float, float]'
"""A point or direction in model space."""

Matrix3: TypeAlias = 'tuple[float, ...]'
"""A row-major 3x3 rotation matrix flattened to nine floats."""


class ZfsEntry(NamedTuple):
    """One member of a ZFSF or ZFS3 archive directory."""

    name: str
    """Member name as stored, trimmed at the first NUL."""
    offset: int
    """Absolute byte offset of the member's data within the archive."""
    size: int
    """Stored (possibly compressed) size in bytes."""
    flags: int
    """Compression flags. Bit 1 selects LZO1X, bit 2 selects LZO1Y, and ``flags >> 8`` is the
    decompressed size hint."""


class PakEntry(NamedTuple):
    """One member of a ``.pak`` bundle, as described by its ``.pix`` text index."""

    name: str
    """Lowercased member name."""
    offset: int
    """Byte offset of the member within the ``.pak``."""
    length: int
    """Length of the member in bytes."""


class IndexedImage(NamedTuple):
    """An 8-bit palette-indexed image."""

    width: int
    """Width in pixels."""
    height: int
    """Height in pixels."""
    pixels: bytes
    """Row-major palette indices, one byte per pixel."""


class RgbImage(NamedTuple):
    """An 8-bit truecolour image."""

    width: int
    """Width in pixels."""
    height: int
    """Height in pixels."""
    pixels: bytes
    """Row-major RGB triples, three bytes per pixel."""


class VqmImage(NamedTuple):
    """A decoded vector-quantised (``.vqm``) image and the codebook it referenced."""

    width: int
    """Width in pixels."""
    height: int
    """Height in pixels."""
    pixels: bytes
    """Row-major palette indices, one byte per pixel."""
    codebook_name: str
    """Name of the ``.cbk`` codebook named in the image header."""


class GeoModel(NamedTuple):
    """A parsed ``.geo`` mesh."""

    vertices: tuple[Vector3, ...]
    """Vertex positions in model space."""
    face_count: int
    """Face count declared by the header."""
    faces: tuple[tuple[int, ...], ...]
    """Per-face vertex index lists, in file order."""


class SdfPart(NamedTuple):
    """One part record from an ``.sdf`` ``SGEO`` chunk."""

    name: str
    """Part name, which doubles as the ``.geo`` member name."""
    rotation: Matrix3
    """Local rotation as a row-major 3x3 matrix."""
    position: Vector3
    """Local translation."""
    parent: str
    """Name of the parent part, or an empty string when the part is a root."""


class Mesh(NamedTuple):
    """An assembled model: every part's geometry baked into world space."""

    vertices: tuple[Vector3, ...]
    """World-space vertex positions for every successfully loaded part."""
    triangles: tuple[tuple[int, int, int], ...]
    """Triangulated faces as triples of indices into :py:attr:`vertices`."""


class Chunk(NamedTuple):
    """One FOURCC chunk from a BWD2 container."""

    tag: str
    """Four-character chunk tag."""
    offset: int
    """Byte offset of the chunk header within the container."""
    size: int
    """Total chunk size in bytes, including the eight-byte header."""
    payload: bytes
    """Chunk payload, excluding the header. Empty for container chunks."""
    children: tuple[Chunk, ...]
    """Parsed child chunks. Empty for leaf chunks."""


class PeSection(NamedTuple):
    """One section header from a Portable Executable image."""

    name: str
    """Section name with trailing NUL padding removed."""
    virtual_size: int
    """Size of the section once mapped into memory."""
    virtual_address: int
    """Relative virtual address of the section."""
    raw_size: int
    """Size of the section's on-disc data."""
    raw_pointer: int
    """File offset of the section's on-disc data."""
    characteristics: int
    """Section characteristics flags."""
    header_offset: int
    """File offset of this section header, used when rewriting the image."""
