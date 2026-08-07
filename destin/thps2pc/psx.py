"""
Parser for Tony Hawk's Pro Skater 2 PC ``.PSX`` scene files.

Structure (little-endian), reverse-engineered from ``THawk2.exe`` and validated against
``SKHAN.PSX`` (471 of 471 sectors parse cleanly)::

    Header:
      +0x00 u32 version         (0x00020004 = "4.2")
      +0x04 u32 chunkListOff    (offset of the chunk list; sector geometry lives before it)
      +0x08 u32 numMeshSections

    Mesh-section descriptors: numMeshSections * 0x24 bytes @ +0x0C
    +0x0C + numMeshSections*0x24:
      u32 numSectors
      u32 sectorOffset[numSectors]

    Sector (at sectorOffset[i]):
      +0x02 u16 countA    (real vertices)
      +0x04 u16 countB    (ghost/stitch vertices)
      +0x06 u16 numFaces
      +0x1C vertices: (countA + countB) * 8 bytes each
      then numFaces faces; a face's first dword has (w0 >> 18) = length in dwords and the low
      18 bits as flags. Face dword 4 is the texture checksum index when w0 & 1.

    Chunk list (at chunkListOff): [u32 id][u32 size][size bytes], id == -1 terminates. Known
    ids: 'HIER', 'RGBs', 6, 7, 10, 0x2a, 0x2c, and 0x45.

Reference: ``FUN_004b2450`` (process), ``FUN_004b20f0`` (chunk walk), ``FUN_004b2b70``
(textures), and ``FUN_0045f520`` with ``InitM3dModelData`` (instance placement).

A face's corner count has two conflicting readings in the original tools. Most of them test bit
``0x10`` of the flags, while the mesh converter instead treated a length of eight dwords or more
as a quad. The two disagree, and so do their quad triangulations (a strip against a fan). Both
are preserved here behind the ``corner_source`` and ``triangulation`` arguments so either can be
reproduced exactly; the flag reading is the default because five of the six original tools used
it. Which one matches the game has not been confirmed against ``THawk2.exe``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple
import logging

from destin.common.io import i16, i32, u16, u32

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .typing import CornerSource, Triangulation, Vector3

__all__ = ('UV_SCALE', 'Chunk', 'Descriptor', 'Face', 'Scene', 'Sector')

log = logging.getLogger(__name__)

UV_SCALE = 128.0
"""Divisor that turns a face's 8-bit texture coordinates into the unit range.

:meta hide-value:
"""

_DESCRIPTOR_SIZE = 0x24
_SECTOR_HEADER_SIZE = 0x1C
_VERTEX_SIZE = 8
_HEADER_SIZE = 12
_QUAD_CORNERS = 4
_TEXTURED_MIN_LENGTH = 7
_QUAD_MIN_LENGTH = 8
_TRIANGLE_FLAG = 0x10
_TEXTURED_FLAG = 1
_FLAG_MASK = 0x3FFFF
_LAYER_MASK = 0xC0
_LAYER_HIDDEN = 0x80


class Chunk(NamedTuple):
    """One record from a scene's chunk list."""

    offset: int
    """Absolute offset of the record's header."""
    id: int
    """Record identifier, or ``-1`` for the terminator."""
    size: int
    """Size of the record's payload in bytes."""


@dataclass(frozen=True)
class Sector:
    """One geometry sector: a block of vertices followed by a block of faces."""

    index: int
    """Position of the sector in the scene's sector table."""
    offset: int
    """Absolute offset of the sector."""
    count_a: int
    """Number of real vertices."""
    count_b: int
    """Number of ghost or stitch vertices."""
    num_faces: int
    """Number of face records that follow the vertices."""
    verts_offset: int
    """Absolute offset of the first vertex."""
    faces_offset: int
    """Absolute offset of the first face record."""
    faces_end: int
    """Absolute offset one past the last face record."""
    @property
    def vertex_count(self) -> int:
        """Total number of vertices, real and ghost."""
        return self.count_a + self.count_b


@dataclass(frozen=True)
class Descriptor:
    """One mesh-section descriptor, which places a sector in the scene's world space."""

    index: int
    """Position of the descriptor in the scene's descriptor table."""
    sequence: int
    """Index of the sector this descriptor places."""
    position: Vector3
    """World position of the sector, already shifted down by twelve fractional bits."""
    flags_18: int
    """Unidentified 16-bit field at ``+0x18``."""
    flags_1a: int
    """Unidentified 16-bit field at ``+0x1A``."""
    bytes_20: tuple[int, int, int]
    """Unidentified bytes at ``+0x20`` through ``+0x22``."""


class Face(NamedTuple):
    """One decoded face record."""

    offset: int
    """Absolute offset of the face record."""
    length: int
    """Length of the record in dwords."""
    flags: int
    """The record's low 18 bits."""
    corners: tuple[int, ...]
    """Vertex indices, three for a triangle and four for a quad."""
    uvs: tuple[tuple[float, float], ...]
    """Texture coordinates per corner, empty when the face is untextured."""
    texture_index: int
    """Index into the scene's texture checksum table, or ``-1`` when untextured."""
    @property
    def is_hidden(self) -> bool:
        """Whether the face belongs to the non-rendering layer, such as an air-trick hit box."""
        return (self.flags & _LAYER_MASK) == _LAYER_HIDDEN

    @property
    def is_textured(self) -> bool:
        """Whether the face carries texture coordinates and a texture index."""
        return bool(self.uvs)

    @property
    def layer(self) -> int:
        """The face's render layer: one of ``0x00``, ``0x40``, ``0x80``, or ``0xC0``."""
        return self.flags & _LAYER_MASK


@dataclass(frozen=True)
class Scene:
    """A parsed ``.PSX`` scene, holding its raw bytes alongside the decoded tables."""

    chunk_list_offset: int
    """Absolute offset of the chunk list."""
    data: bytes
    """The whole scene file."""
    descriptors: tuple[Descriptor, ...]
    """Every mesh-section descriptor, in table order."""
    sectors: tuple[Sector, ...]
    """Every sector that lies within the file, in table order."""
    version: int
    """Scene format version."""
    def chunks(self) -> Iterator[Chunk]:
        """
        Walk the chunk list, ending with the terminator record.

        Yields
        ------
        Chunk
            Each record in order. The final one has an id of ``-1``.
        """
        offset = self.chunk_list_offset
        while True:
            chunk = Chunk(offset, i32(self.data, offset), u32(self.data, offset + 4))
            yield chunk
            if chunk.id == -1:
                return
            offset = offset + 8 + chunk.size

    def faces(self, sector: Sector, *, corner_source: CornerSource = 'flag') -> Iterator[Face]:
        """
        Decode a sector's face records.

        Parameters
        ----------
        sector : Sector
            The sector whose faces should be decoded.
        corner_source : CornerSource
            How to derive a face's corner count. ``'flag'`` tests bit ``0x10`` of the flags;
            ``'length'`` treats a record of eight dwords or more as a quad.

        Yields
        ------
        Face
            Each face, stopping early at a record whose length is zero.

        Raises
        ------
        ValueError
            If ``corner_source`` is not a recognised value.
        """
        if corner_source not in {'flag', 'length'}:
            msg = f'Unknown corner source {corner_source!r}; expected "flag" or "length".'
            raise ValueError(msg)
        offset = sector.faces_offset
        for _ in range(sector.num_faces):
            word = u32(self.data, offset)
            length = word >> 18
            if length == 0:
                return
            flags = word & _FLAG_MASK
            textured = bool(flags & _TEXTURED_FLAG) and length >= _TEXTURED_MIN_LENGTH
            if corner_source == 'flag':
                count = 3 if flags & _TRIANGLE_FLAG else 4
            else:
                count = 4 if length >= _QUAD_MIN_LENGTH else 3
            corners = tuple(self.data[offset + 4 + k] for k in range(count))
            uvs = tuple((self.data[offset + 20 + k * 2] / UV_SCALE,
                         self.data[offset + 20 + k * 2 + 1] / UV_SCALE)
                        for k in range(count)) if textured else ()
            yield Face(offset=offset,
                       length=length,
                       flags=flags,
                       corners=corners,
                       uvs=uvs,
                       texture_index=u32(self.data, offset + 16) if textured else -1)
            offset += length * 4

    @classmethod
    def parse(cls, data: bytes) -> Scene:
        """
        Parse a scene's header, descriptor table, and sector table.

        Sectors whose offset is zero or which would start past the end of the file are skipped,
        matching the original tools.

        Parameters
        ----------
        data : bytes
            The whole scene file.

        Returns
        -------
        Scene
            The parsed scene.

        Raises
        ------
        ValueError
            If the data is too small to hold a scene header.
        """
        if len(data) < _HEADER_SIZE:
            msg = 'File is too small to be a PSX scene.'
            raise ValueError(msg)
        version = u32(data, 0)
        chunk_list_offset = u32(data, 4)
        num_mesh_sections = u32(data, 8)
        descriptors = tuple(
            _read_descriptor(data, i, 0x0C + i * _DESCRIPTOR_SIZE)
            for i in range(num_mesh_sections))
        count_offset = 0x0C + num_mesh_sections * _DESCRIPTOR_SIZE
        num_sectors = u32(data, count_offset)
        table = count_offset + 4
        sectors = []
        for i in range(num_sectors):
            offset = u32(data, table + i * 4)
            if offset == 0 or offset + _SECTOR_HEADER_SIZE > len(data):
                continue
            sectors.append(_read_sector(data, i, offset))
        log.debug('Parsed PSX scene version %#x with %d descriptors and %d sectors.', version,
                  num_mesh_sections, len(sectors))
        return cls(chunk_list_offset=chunk_list_offset,
                   data=data,
                   descriptors=descriptors,
                   sectors=tuple(sectors),
                   version=version)

    def placement(self) -> dict[int, Vector3]:
        """
        Map each placed sector index to its world position.

        Returns
        -------
        dict[int, Vector3]
            Sector index to world position. Sectors without a descriptor are absent.
        """
        return {d.sequence: d.position for d in self.descriptors}

    def texture_checksums(self) -> tuple[int, ...]:
        """
        Read the texture checksum table that follows the chunk list.

        The table sits after a per-sector array, so the sector count is needed to find it. This
        layout applies to level and object scenes; the lighting companion file omits the
        per-sector array and is read by :py:func:`destin.thps2pc.textures.parse_lighting`.

        Returns
        -------
        tuple[int, ...]
            Every texture checksum, in table order.
        """
        end = 0
        for chunk in self.chunks():
            end = chunk.offset
        base = end + 4
        count_offset = base + len(self.sectors) * 4
        count = u32(self.data, count_offset)
        start = count_offset + 4
        return tuple(u32(self.data, start + i * 4) for i in range(count))

    def triangles(
            self,
            sector: Sector,
            *,
            corner_source: CornerSource = 'flag',
            triangulation: Triangulation = 'strip') -> Iterator[tuple[Face, tuple[int, int, int]]]:
        """
        Decode a sector's faces and split each quad into two triangles.

        Parameters
        ----------
        sector : Sector
            The sector whose faces should be decoded.
        corner_source : CornerSource
            How to derive a face's corner count. See :py:meth:`faces`.
        triangulation : Triangulation
            How to split a quad. ``'strip'`` emits corners ``(0, 1, 2)`` then ``(1, 3, 2)``;
            ``'fan'`` emits ``(0, 1, 2)`` then ``(0, 2, 3)``.

        Yields
        ------
        tuple[Face, tuple[int, int, int]]
            The face and the three corner slots forming the triangle. Index the face's
            ``corners`` and ``uvs`` with those slots.

        Raises
        ------
        ValueError
            If ``triangulation`` is not a recognised value.
        """
        if triangulation not in {'strip', 'fan'}:
            msg = f'Unknown triangulation {triangulation!r}; expected "strip" or "fan".'
            raise ValueError(msg)
        second = (1, 3, 2) if triangulation == 'strip' else (0, 2, 3)
        for face in self.faces(sector, corner_source=corner_source):
            yield face, (0, 1, 2)
            if len(face.corners) == _QUAD_CORNERS:
                yield face, second

    def vertices(self, sector: Sector, origin: Vector3 = (0, 0, 0)) -> tuple[Vector3, ...]:
        """
        Read a sector's vertices, optionally offset by a world position.

        Parameters
        ----------
        sector : Sector
            The sector whose vertices should be read.
        origin : Vector3
            World position added to every vertex. Defaults to the scene origin.

        Returns
        -------
        tuple[Vector3, ...]
            Every vertex, real and ghost, in table order.
        """
        base = sector.verts_offset
        return tuple((i16(self.data, base + i * _VERTEX_SIZE) + origin[0],
                      i16(self.data, base + i * _VERTEX_SIZE + 2) + origin[1],
                      i16(self.data, base + i * _VERTEX_SIZE + 4) + origin[2])
                     for i in range(sector.vertex_count))


def _read_descriptor(data: bytes, index: int, offset: int) -> Descriptor:
    return Descriptor(index=index,
                      sequence=u16(data, offset + 0x16),
                      position=(i32(data, offset + 4) >> 12, i32(data, offset + 8) >> 12,
                                i32(data, offset + 0x0C) >> 12),
                      flags_18=u16(data, offset + 0x18),
                      flags_1a=u16(data, offset + 0x1A),
                      bytes_20=(data[offset + 0x20], data[offset + 0x21], data[offset + 0x22]))


def _read_sector(data: bytes, index: int, offset: int) -> Sector:
    count_a = u16(data, offset + 2)
    count_b = u16(data, offset + 4)
    num_faces = u16(data, offset + 6)
    verts_offset = offset + _SECTOR_HEADER_SIZE
    position = verts_offset + (count_a + count_b) * _VERTEX_SIZE
    faces_offset = position
    for _ in range(num_faces):
        length = u32(data, position) >> 18
        if length == 0:
            break
        position += length * 4
    return Sector(index=index,
                  offset=offset,
                  count_a=count_a,
                  count_b=count_b,
                  num_faces=num_faces,
                  verts_offset=verts_offset,
                  faces_offset=faces_offset,
                  faces_end=position)
