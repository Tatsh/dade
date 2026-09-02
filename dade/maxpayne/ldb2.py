"""
Reader for the ``LDB2`` levels of *Max Payne 2*.

The format is specified in ``docs/MAXPAYNE2_LDB.md`` of the ``max-payne-noclip`` project, and this
follows it section by section. It shares the tagged ``R_MemoryFile`` values with the first game and
nothing else: the strings are hoisted into one pool the body addresses by byte offset, geometry
arrives already triangulated in packed float arrays rather than as convex polygons over a shared
corner array, and a room carries the transform that places it instead of leaving it to the exits.

The whole file is read. The rooms hold the architecture and the dynamic meshes near the end hold
the props -- doors, lifts, breakables, vending machines -- which a level looks conspicuously empty
without. The containers in between are walked only far enough to keep the reader's place.

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
    PropAnimation,
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
_TRANSFORM = 12
"""Floats in the ``M_Matrix4x3`` placing a prop: three basis rows then a translation."""

_CURVES = 2
"""Curves an animation carries: how far it has travelled, then how far it has turned."""

_PROP_FLAGS = 8
"""Flags between a prop's lightmap setting and its prefab identifier."""

_IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
"""A prop's vertices are already where the level wants them, so it needs no transform of its
own. Its clips move it from there."""
_MATERIAL_FIELDS = 14
"""Tagged values in one material: see the specification's material section."""

_DDS = 5
"""The ``file_type`` accompanying DirectDraw Surface data."""

_BLEND_MODES = {
    1: 'MASK',
    2: 'BLEND',
    3: 'BLEND',
    4: 'BLEND',
    7: 'MASK',
    8: 'BLEND',
    10: 'MASK',
    11: 'BLEND'
}
"""How each blending mode a material can ask for lands in glTF.

The modes are named in the specification. Everything with `AlphaCompare` in its name is a cut-out
and needs no sorting, so it masks; the ones that blend an edge, add, or blend outright have to be
drawn in order and so blend. The rest draw opaque, whatever else they do with their other
textures."""


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
        if self.at >= len(self.data):
            msg = f'The level ends at {self.at}, where a value was expected.'
            raise InvalidLevel2Error(msg)
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


def _read_materials(reader: _Reader,
                    diffuse: list[TextureImage]) -> tuple[dict[int, Material], dict[int, int]]:
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
    tuple[dict[int, Material], dict[int, int]]
        Material identifier to material, keyed by position as the meshes reference them, and the
        lightmap each one is lit by. The lightmap belongs to the material here, where the first
        game put it on the face.
    """
    out: dict[int, Material] = {}
    lit: dict[int, int] = {}
    for index in range(reader.count()):
        # Not every field is a number: `dual_sided` and `writes_zbuffer` are written as booleans.
        fields = [reader.value() for _ in range(_MATERIAL_FIELDS)]
        first = fields[1] if isinstance(fields[1], int) else 0
        showing = fields[_MATERIAL_FIELDS - 1]
        frame = first + (showing if isinstance(showing, int) else 0)
        image = diffuse[frame] if 0 <= frame < len(diffuse) else None
        image = image or (diffuse[first] if 0 <= first < len(diffuse) else None)
        blend = fields[0]
        sided = fields[10]
        lightmap = fields[3]
        priority = fields[8]
        lit[index] = lightmap if isinstance(lightmap, int) else -1
        out[index] = Material(blend=_BLEND_MODES.get(blend, '') if isinstance(blend, int) else '',
                              category='',
                              dual_sided=bool(sided),
                              image=image.path if image else '',
                              sort_priority=priority if isinstance(priority, int) else 0,
                              texture=image.path if image else '')
    return out, lit


def _read_mesh(reader: _Reader, transform: tuple[float, ...], corners: list[Corner],
               lightmap_of: dict[int, int]) -> list[StaticMesh]:
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
    lightmap_of : dict[int, int]
        Which lightmap each material is lit by.

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
                         lightmap=lightmap_of.get(material, -1),
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


def _read_rooms(reader: _Reader, lightmap_of: dict[int, int]) -> tuple[RenderMesh, tuple[str, ...]]:
    """
    Read the rooms and everything they hold.

    Parameters
    ----------
    reader : _Reader
        A cursor positioned at the room count.
    lightmap_of : dict[int, int]
        Which lightmap each material is lit by.

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
        batches = _read_mesh(reader, transform, corners, lightmap_of)
        meshes.extend(batches)
        names.extend(f'{name}_{index}' for index in range(len(batches)))
        _skip_collisions(reader)
        _skip_volume_lights(reader)
    return RenderMesh(corners=tuple(corners), meshes=tuple(meshes),
                      names=tuple(names)), tuple(names)


def _skip_values(reader: _Reader, count: int) -> None:
    """
    Step over a run of tagged values whose meaning does not matter here.

    Parameters
    ----------
    reader : _Reader
        A cursor positioned at the first value.
    count : int
        How many to step over.
    """
    for _ in range(count):
        reader.value()


def _skip_records(reader: _Reader, fields: int) -> None:
    """
    Step over a counted run of fixed-width records.

    Parameters
    ----------
    reader : _Reader
        A cursor positioned at the count.
    fields : int
        Tagged values in one record.
    """
    for _ in range(reader.count()):
        _skip_values(reader, fields)


def _skip_to_props(reader: _Reader) -> list[tuple[float, ...]]:
    """
    Walk the containers between the rooms and the props, keeping the transforms on the way.

    Nothing here is drawn, but a prop does not carry the transform that places it: it names a
    state machine, and the state machine has it. So the state machines are walked for their
    transforms and everything else only for its length.

    Parameters
    ----------
    reader : _Reader
        A cursor positioned at the point light count.

    Returns
    -------
    list[tuple[float, ...]]
        One transform per state machine, in the order a prop's identifier indexes them.
    """
    _skip_records(reader, 7)  # Point lights.
    _skip_records(reader, 3)  # Flares.
    _skip_records(reader, 4)  # Level items.
    for _ in range(reader.count()):  # Exits, each naming the rooms it joins.
        _skip_values(reader, 4)
        _skip_values(reader, reader.count())
    _skip_records(reader, 3)  # Jump points.
    _skip_records(reader, 4)  # Waypoints.
    reader.raw(1)
    _skip_records(reader, 2)  # Enemy groups.
    _skip_records(reader, 6)  # Enemies.
    placed: list[tuple[float, ...]] = []
    for _ in range(reader.count()):  # State machines.
        reader.value()  # Name.
        transform = reader.value()
        placed.append(transform if isinstance(transform, tuple) else _IDENTITY)
        _skip_values(reader, 4)  # Parent, local transform, room, default state.
        reader.raw(1)
        _skip_values(reader, reader.count())  # Custom states.
        _skip_values(reader, 4)  # Offsets of the scripts in the pool.
        _skip_records(reader, 5)  # Timers.
    for _ in range(reader.count()):  # Triggers.
        _skip_values(reader, 9)
        if reader.value() == 1 and reader.count() == -1:
            _skip_collisions(reader)
    return placed


def _read_animations(reader: _Reader, pool: bytes) -> list[PropAnimation]:
    """
    Read the clips one prop can play.

    A clip is two curves sampled over its length -- how far the prop has travelled and how far it
    has turned -- between a start and an end transform, which is the same shape the first game
    uses.

    Parameters
    ----------
    reader : _Reader
        A cursor positioned at the clip count.
    pool : bytes
        The level's string pool.

    Returns
    -------
    list[PropAnimation]
        The clips.
    """
    out: list[PropAnimation] = []
    for _ in range(reader.count()):
        name = _string_at(pool, reader.count())
        length = reader.value()
        start, end = reader.value(), reader.value()
        curves: list[tuple[float, ...]] = []
        for _ in range(_CURVES):
            _skip_values(reader, 3)
            reader.value()  # Sample rate.
            points = reader.count()
            reader.floats(points)  # The times, which are evenly spaced.
            curves.append(reader.floats(points))
        _skip_values(reader, 3)  # The state machines the clip starts.
        if (isinstance(start, tuple) and len(start) == _TRANSFORM and isinstance(end, tuple)
                and len(end) == _TRANSFORM):
            out.append(
                PropAnimation(distance=curves[0],
                              duration=float(length) if isinstance(length, (int, float)) else 0.0,
                              end=end,
                              name=name,
                              start=start,
                              turn=curves[1]))
    return out


def _read_props(
        reader: _Reader, pool: bytes, lightmap_of: dict[int, int],
        placed: list[tuple[float, ...]]) -> tuple[RenderMesh, list[tuple[PropAnimation, ...]]]:
    """
    Read the dynamic meshes: the doors, lifts and breakables a room's walls do not include.

    A prefab is written once and referred to afterwards, so the geometry is only present the first
    time an identifier is seen, or when a later copy carries its own lighting. A reader that always
    expects a mesh loses its place; the specification's dynamic mesh section sets out the rule.

    Parameters
    ----------
    reader : _Reader
        A cursor positioned at the prop count.
    pool : bytes
        The level's string pool.
    lightmap_of : dict[int, int]
        Which lightmap each material is lit by.
    placed : list[tuple[float, ...]]
        One transform per state machine, which is where a prop naming it stands.

    Returns
    -------
    tuple[RenderMesh, list[tuple[PropAnimation, ...]]]
        The props and the clips each can play.
    """
    corners: list[Corner] = []
    meshes: list[StaticMesh] = []
    names: list[str] = []
    clips: list[tuple[PropAnimation, ...]] = []
    seen: set[int] = set()
    for index in range(reader.count()):
        machine = reader.count()  # The state machine driving it, and placing it.
        transform = placed[machine] if 0 <= machine < len(placed) else _IDENTITY
        lightmapped = reader.value()
        _skip_values(reader, _PROP_FLAGS)
        prefab = reader.count()
        share = reader.value()
        _skip_values(reader, 3)  # Bounding box.
        batches: list[StaticMesh] = []
        if prefab < 0 or prefab not in seen:
            batches = _read_mesh(reader, transform, corners, lightmap_of)
            _skip_collisions(reader)
        elif lightmapped != 0:
            batches = _read_mesh(reader, transform, corners, lightmap_of)
            if not share:
                _skip_collisions(reader)
        if prefab >= 0:
            seen.add(prefab)
        # A state machine holds where its prop was placed, and that is where the level draws it at
        # rest. A clip is authored around that pose and may be written in a parent's space, so its
        # own transforms cannot stand in for one: a door's first clip closes it, starting from open,
        # and a prop hanging off a parent keeps a translation near the parent rather than the world.
        playable = tuple(_read_animations(reader, pool))
        for at, batch in enumerate(batches):
            meshes.append(batch._replace(transform=transform))
            names.append(f'prop{index}_{at}')
            clips.append(playable)
    return RenderMesh(corners=tuple(corners),
                      meshes=tuple(meshes),
                      names=tuple(names),
                      animations=tuple(clips)), clips


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
    materials, lightmap_of = _read_materials(reader, diffuse)
    mesh, _names = _read_rooms(reader, lightmap_of)
    placed = _skip_to_props(reader)
    props, _clips = _read_props(reader, pool, lightmap_of, placed)
    log.debug('Read %d meshes of architecture and %d of props.', len(mesh.meshes),
              len(props.meshes))
    return Level(geometry=LevelGeometry(polygons=(), vertices=()),
                 lightmaps=tuple(lightmaps),
                 materials=materials,
                 mesh=mesh,
                 props=props,
                 textures=tuple(diffuse))
