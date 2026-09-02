"""
Reader for the ``LDB2`` levels of *Max Payne 2*.

The format is specified in ``docs/MAXPAYNE2_LDB.md`` of the ``max-payne-noclip`` project, and this
follows it section by section. It shares the tagged ``R_MemoryFile`` values with the first game and
nothing else: the strings are hoisted into one pool the body addresses by byte offset, geometry
arrives already triangulated in packed float arrays rather than as convex polygons over a shared
corner array, and a room carries the transform that places it instead of leaving it to the exits.

Only the head is read -- the pool, the textures, the materials and the rooms. The containers after
them hold the lights, the scripts and the animated props, and none of it is needed to draw a level.

The result is shaped like :py:func:`dade.maxpayne.ldb.read_level`'s so that one exporter serves
both games: each per-material batch becomes a :py:class:`StaticMesh` of three-corner faces placed
by its room's transform.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import struct

from .memoryfile import TAG_SIZES, BasicType
from .typing import (
    Corner,
    Level,
    LevelGeometry,
    Material,
    MeshFace,
    RenderMesh,
    StaticMesh,
    TextureImage,
)

if TYPE_CHECKING:
    from .typing import Vector3

__all__ = ('MAGIC', 'VERSION', 'InvalidLevel2Error', 'read_level2')

log = logging.getLogger(__name__)

MAGIC = b'LDB2'
"""Magic starting every Max Payne 2 level. It is four raw bytes, ahead of the first tag."""

VERSION = 34
"""The only version the shipped levels use. The first game's levels are 32."""

_SIGNED = frozenset({
    BasicType.INT8, BasicType.INT16, BasicType.INT24, BasicType.INT32, BasicType.LONG,
    BasicType.SCHAR, BasicType.SHORT
})

_VECTORS = frozenset({BasicType.VECTOR2, BasicType.VECTOR3, BasicType.VECTOR4, BasicType.MATRIX4X3})

_TRIANGLE = 3
_INDEX_SIZE = 2
_MATERIAL_FIELDS = 14
"""Tagged values in one material: see the specification's material section."""

_DDS = 5
"""The ``file_type`` accompanying DirectDraw Surface data."""


class InvalidLevel2Error(ValueError):
    """Raised when a buffer is not a readable Max Payne 2 level."""


class _Reader:
    """A cursor over the tagged stream, with the packed runs the format also uses."""
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.at = 0

    def value(self) -> int | float | bool | str | tuple[float, ...]:
        """
        Read one tagged value, whatever its type turns out to be.

        Returns
        -------
        int | float | bool | str | tuple[float, ...]
            The value.

        Raises
        ------
        InvalidLevel2Error
            If the tag is not one the format writes.
        """
        tag = self.data[self.at]
        if tag == BasicType.STRING:
            # Not every string went into the pool: a room's name is written here, with its own
            # tagged length ahead of it.
            self.at += 1
            return self.raw(self.count()).decode('latin-1')
        width = TAG_SIZES.get(tag)
        if width is None:
            msg = f'Not a value at offset {self.at}: 0x{tag:02x}.'
            raise InvalidLevel2Error(msg)
        body = self.raw(width + 1)[1:]
        if tag == BasicType.FLOAT:
            return float(struct.unpack('<f', body)[0])
        if tag in _VECTORS:
            return struct.unpack(f'<{width // 4}f', body)
        if tag == BasicType.BOOL:
            return bool(body[0])
        return int.from_bytes(body, 'little', signed=tag in _SIGNED)

    def count(self) -> int:
        """
        Read a tagged value that has to be a whole number.

        Returns
        -------
        int
            The value.

        Raises
        ------
        InvalidLevel2Error
            If what is there is not a whole number.
        """
        value = self.value()
        if not isinstance(value, int) or isinstance(value, bool):
            msg = f'Expected a number at offset {self.at}, got {value!r}.'
            raise InvalidLevel2Error(msg)
        return value

    def raw(self, count: int) -> bytes:
        """
        Take a run of untagged bytes.

        Parameters
        ----------
        count : int
            How many bytes to take.

        Returns
        -------
        bytes
            The bytes.

        Raises
        ------
        InvalidLevel2Error
            If the run does not fit in what is left.
        """
        if count < 0 or self.at + count > len(self.data):
            msg = f'A run of {count} bytes at offset {self.at} runs past the end of the level.'
            raise InvalidLevel2Error(msg)
        out = self.data[self.at:self.at + count]
        self.at += count
        return out

    def floats(self, count: int) -> tuple[float, ...]:
        """
        Take a run of untagged floats.

        Parameters
        ----------
        count : int
            How many floats to take.

        Returns
        -------
        tuple[float, ...]
            The floats.
        """
        return struct.unpack(f'<{count}f', self.raw(count * 4))


def _read_pool(reader: _Reader) -> bytes:
    """
    Read the string pool the whole file addresses by byte offset.

    Parameters
    ----------
    reader : _Reader
        A cursor positioned at the pool's size.

    Returns
    -------
    bytes
        The pool.
    """
    return reader.raw(reader.count())


def _string_at(pool: bytes, offset: int) -> str:
    """
    Resolve one byte offset into the string pool.

    Parameters
    ----------
    pool : bytes
        The level's string pool.
    offset : int
        Byte offset of the string's first character.

    Returns
    -------
    str
        The string, or an empty one when the offset is not inside the pool.
    """
    if not 0 <= offset < len(pool):
        return ''
    end = pool.find(b'\x00', offset)
    return pool[offset:end if end >= 0 else len(pool)].decode('latin-1')


def _read_texture_group(reader: _Reader, pool: bytes) -> list[TextureImage]:
    """
    Read one of the four groups that carry a path with each image.

    Parameters
    ----------
    reader : _Reader
        A cursor positioned at the group's count.
    pool : bytes
        The level's string pool.

    Returns
    -------
    list[TextureImage]
        The images.
    """
    out: list[TextureImage] = []
    for _ in range(reader.count()):
        kind = reader.count()
        size = reader.count()
        path = _string_at(pool, reader.count())
        out.append(TextureImage(data=reader.raw(size), kind=kind, path=path))
    return out


def _read_lightmaps(reader: _Reader) -> list[TextureImage]:
    """
    Read the lightmap group, which names no paths because a face addresses it by number.

    Parameters
    ----------
    reader : _Reader
        A cursor positioned at the group's ``is_dds`` flag.

    Returns
    -------
    list[TextureImage]
        The atlases, named after their index so they have a key like any other image.
    """
    kind = _DDS if reader.value() else 0
    return [
        TextureImage(data=reader.raw(reader.count()), kind=kind, path=f'lightmap{index}')
        for index in range(reader.count())
    ]


def _read_materials(reader: _Reader, diffuse: list[TextureImage]) -> dict[int, Material]:
    """
    Read the material table.

    A material names a range of diffuse frames and which of them to show, so a still material
    names the same frame twice. The other three texture groups and the lightmap are indices too,
    but only the diffuse image is needed to draw the level.

    Parameters
    ----------
    reader : _Reader
        A cursor positioned at the table's count.
    diffuse : list[TextureImage]
        The diffuse group, indexed by the frame numbers.

    Returns
    -------
    dict[int, Material]
        Material identifier to material, keyed by position as the meshes reference them.
    """
    out: dict[int, Material] = {}
    for index in range(reader.count()):
        # Not every field is a number: `dual_sided` and `writes_zbuffer` are written as booleans.
        fields = [reader.value() for _ in range(_MATERIAL_FIELDS)]
        first = fields[1] if isinstance(fields[1], int) else 0
        showing = fields[_MATERIAL_FIELDS - 1]
        frame = first + (showing if isinstance(showing, int) else 0)
        image = diffuse[frame] if 0 <= frame < len(diffuse) else None
        image = image or (diffuse[first] if 0 <= first < len(diffuse) else None)
        out[index] = Material(category='',
                              image=image.path if image else '',
                              texture=image.path if image else '')
    return out


def _read_mesh(reader: _Reader, transform: tuple[float, ...],
               corners: list[Corner]) -> list[StaticMesh]:
    """
    Read one room's static mesh batches.

    Each batch is one material's triangles, stored the way the hardware takes them: packed float
    arrays and a sixteen-bit index buffer. A face's normal is taken from its own corners, because
    the format stores one per vertex and none per face.

    Parameters
    ----------
    reader : _Reader
        A cursor positioned at the batch count.
    transform : tuple[float, ...]
        The room's transform, which places every batch in it.
    corners : list[Corner]
        The corner array being built for the whole level, appended to in place.

    Returns
    -------
    list[StaticMesh]
        One mesh per batch.
    """
    out: list[StaticMesh] = []
    for _ in range(reader.count()):
        material = reader.count()
        lit, detailed = bool(reader.value()), bool(reader.value())
        triangles, vertices = reader.count(), reader.count()
        positions = _triples(reader.floats(vertices * 3))
        normals = _triples(reader.floats(vertices * 3))
        coords = _pairs(reader.floats(vertices * 2))
        baked = _pairs(reader.floats(vertices * 2)) if lit else [(0.0, 0.0)] * vertices
        if detailed:
            reader.floats(vertices * 2)
        indices = struct.unpack(f'<{triangles * _TRIANGLE}H',
                                reader.raw(triangles * _TRIANGLE * _INDEX_SIZE))
        faces: list[MeshFace] = []
        for at in range(0, len(indices), _TRIANGLE):
            triangle = indices[at:at + _TRIANGLE]
            if any(i >= vertices for i in triangle):
                continue
            faces.append(
                MeshFace(corner_count=_TRIANGLE,
                         first_corner=len(corners),
                         material=material,
                         normal=_face_normal([positions[i] for i in triangle])))
            corners.extend(
                Corner(lightmap_uv=baked[i], neighbour=0, position=i, uv=coords[i])
                for i in triangle)
        out.append(
            StaticMesh(faces=tuple(faces),
                       normals=tuple(normals),
                       positions=tuple(positions),
                       transform=transform))
    return out


def _triples(values: tuple[float, ...]) -> list[Vector3]:
    """
    Group a packed run into three-component vectors.

    Parameters
    ----------
    values : tuple[float, ...]
        The run.

    Returns
    -------
    list[Vector3]
        The vectors.
    """
    return [(values[at], values[at + 1], values[at + 2]) for at in range(0, len(values), 3)]


def _pairs(values: tuple[float, ...]) -> list[tuple[float, float]]:
    """
    Group a packed run into two-component vectors.

    Parameters
    ----------
    values : tuple[float, ...]
        The run.

    Returns
    -------
    list[tuple[float, float]]
        The vectors.
    """
    return [(values[at], values[at + 1]) for at in range(0, len(values), 2)]


def _face_normal(triangle: list[Vector3]) -> Vector3:
    """
    Work a triangle's normal out of its corners.

    Parameters
    ----------
    triangle : list[Vector3]
        The three corners, in stored order.

    Returns
    -------
    Vector3
        The normal, not normalised, and zero for a degenerate triangle.
    """
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = triangle
    u = (bx - ax, by - ay, bz - az)
    v = (cx - ax, cy - ay, cz - az)
    return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])


def _skip_collisions(reader: _Reader) -> None:
    """
    Step over one room's collision shapes, which a viewer does not draw.

    Parameters
    ----------
    reader : _Reader
        A cursor positioned at the shape count.
    """
    for _ in range(reader.count()):
        vertices, triangles = reader.count(), reader.count()
        reader.raw(vertices * 3 * 4)
        reader.raw(triangles * _TRIANGLE * _INDEX_SIZE)
        reader.raw(triangles)
        reader.value()  # Convex.
        reader.value()  # Collision mask.
        reader.raw(3 * 4)  # Havok origin.
        reader.raw(4)
        reader.raw(struct.unpack('<i', reader.raw(4))[0])  # Havok MOPP code.


def _skip_volume_lights(reader: _Reader) -> None:
    """
    Step over one room's volume lights, which light what moves rather than what is drawn.

    Parameters
    ----------
    reader : _Reader
        A cursor positioned at the light count.
    """
    for _ in range(reader.count()):
        width, height, depth = reader.count(), reader.count(), reader.count()
        reader.value()  # Minimum corner.
        reader.value()  # Maximum corner.
        reader.raw(width * height * depth * 3 * 4)


def _read_rooms(reader: _Reader) -> tuple[RenderMesh, tuple[str, ...]]:
    """
    Read the rooms and everything they hold.

    Parameters
    ----------
    reader : _Reader
        A cursor positioned at the room count.

    Returns
    -------
    tuple[RenderMesh, tuple[str, ...]]
        The level's geometry and one name per mesh.

    Raises
    ------
    InvalidLevel2Error
        If a room does not carry the transform that places it.
    """
    corners: list[Corner] = []
    meshes: list[StaticMesh] = []
    names: list[str] = []
    for _ in range(reader.count()):
        name = reader.value()
        transform = reader.value()
        reader.value()
        for _ in range(3):
            reader.value()  # The room's bounding box.
        if not isinstance(transform, tuple):
            msg = f'A room at offset {reader.at} has no transform.'
            raise InvalidLevel2Error(msg)
        batches = _read_mesh(reader, transform, corners)
        meshes.extend(batches)
        names.extend(f'{name}_{index}' for index in range(len(batches)))
        _skip_collisions(reader)
        _skip_volume_lights(reader)
    return RenderMesh(corners=tuple(corners), meshes=tuple(meshes),
                      names=tuple(names)), tuple(names)


def read_level2(data: bytes) -> Level:
    """
    Read a Max Payne 2 level.

    Parameters
    ----------
    data : bytes
        A whole ``.ldb``, decompressed.

    Returns
    -------
    Level
        The level, shaped as :py:func:`dade.maxpayne.ldb.read_level` shapes the first game's so
        that :py:func:`dade.maxpayne.gltf.build_glb` draws either.

    Raises
    ------
    InvalidLevel2Error
        If the buffer is not a level this reader knows.
    """
    if data[:len(MAGIC)] != MAGIC:
        msg = f'Not a Max Payne 2 level: {data[:len(MAGIC)]!r}.'
        raise InvalidLevel2Error(msg)
    reader = _Reader(data)
    reader.raw(len(MAGIC))
    version = reader.count()
    if version != VERSION:
        msg = f'Unsupported Max Payne 2 level version {version}.'
        raise InvalidLevel2Error(msg)
    pool = _read_pool(reader)
    reader.value()  # The physical world size.
    diffuse = _read_texture_group(reader, pool)
    lightmaps = _read_lightmaps(reader)
    for _ in range(3):
        _read_texture_group(reader, pool)  # Detail, reflection and gloss.
    materials = _read_materials(reader, diffuse)
    mesh, _names = _read_rooms(reader)
    log.debug('Read %d rooms worth of geometry, %d meshes.', len(mesh.names), len(mesh.meshes))
    return Level(geometry=LevelGeometry(polygons=(), vertices=()),
                 lightmaps=tuple(lightmaps),
                 materials=materials,
                 mesh=mesh,
                 textures=tuple(diffuse))
