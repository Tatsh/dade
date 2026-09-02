"""
Reader for the world geometry at the head of a ``.ldb`` level.

``X_LevelDBExportLevel::vf03`` in ``MaxED.exe`` writes four arrays before anything else, and the
first two are the whole of the level's static geometry: a pool of vertices, then a table of convex
faces. Each face records where its corners start in the pool and how many there are, and the runs
are contiguous and exhaustive, so the pool is a flat de-indexed corner list rather than something
an index buffer addresses.

That is checkable, and :py:func:`read_geometry` checks it: the vertex counts must sum to exactly
the pool size. On ``Part1_Level6.ldb`` that is 15333 faces over 53263 vertices, with every
consecutive pair contiguous.

Y is up. On a shipped level the Y axis carries far fewer distinct values than X or Z and they
cluster hard, which is what floors and ceilings at fixed heights look like. glTF is also Y-up, so
no axis conversion is needed.

The two arrays that follow are the level BSP, and after them come the containers; neither is needed
for geometry and neither is read here.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import logging
import struct

from .memoryfile import TAG_SIZES, BasicType, read_int, read_string, read_vector3
from .typing import (
    Character,
    Corner,
    Level,
    LevelGeometry,
    LevelItem,
    Material,
    MeshFace,
    Placement,
    Polygon,
    PropAnimation,
    RenderMesh,
    StaticMesh,
    TextureImage,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from .typing import Vector3

__all__ = ('MAX_POLYGON_VERTICES', 'MIN_POLYGON_VERTICES', 'InvalidLevelError', 'read_geometry',
           'read_textures')

log = logging.getLogger(__name__)

MIN_POLYGON_VERTICES = 3
"""Fewest corners a face may have.

:meta hide-value:
"""
MAX_POLYGON_VERTICES = 64
"""Most corners a face may have. Shipped levels stay at or below eight; the ceiling only guards
against a desynchronised read.

:meta hide-value:
"""


class InvalidLevelError(ValueError):
    """Raised when a buffer is not a readable level."""


def _read_array_count(data: bytes, offset: int, label: str) -> tuple[int, int]:
    if offset >= len(data) or data[offset] != BasicType.ARRAY:
        got = f'0x{data[offset]:02x}' if offset < len(data) else 'end of file'
        msg = f'Expected an array marker for {label} at offset {offset}, got {got}.'
        raise InvalidLevelError(msg)
    return read_int(data, offset + 1)


def read_geometry(data: bytes) -> LevelGeometry:
    """
    Read a level's vertex pool and face table.

    Parameters
    ----------
    data : bytes
        A decompressed ``.ldb``.

    Returns
    -------
    LevelGeometry
        The vertices and faces.

    Raises
    ------
    InvalidLevelError
        If the leading arrays are missing or malformed, or the faces do not account for the vertex
        pool exactly.
    """
    count, offset = _read_array_count(data, 0, 'the vertex pool')
    vertices: list[Vector3] = []
    for _ in range(count):
        vertex, offset = read_vector3(data, offset)
        vertices.append(vertex)
    count, offset = _read_array_count(data, offset, 'the face table')
    polygons: list[Polygon] = []
    total = 0
    for _ in range(count):
        first, offset = read_int(data, offset)
        corners, offset = read_int(data, offset)
        polygon_index, offset = read_int(data, offset)
        mesh_index, offset = read_int(data, offset)
        normal, offset = read_vector3(data, offset)
        origin, offset = read_vector3(data, offset)
        if not MIN_POLYGON_VERTICES <= corners <= MAX_POLYGON_VERTICES:
            msg = f'Face {len(polygons)} claims {corners} corners.'
            raise InvalidLevelError(msg)
        if first < 0 or first + corners > len(vertices):
            msg = (f'Face {len(polygons)} spans vertices {first}..{first + corners}, '
                   f'outside a pool of {len(vertices)}.')
            raise InvalidLevelError(msg)
        total += corners
        polygons.append(
            Polygon(first_vertex=first,
                    mesh_index=mesh_index,
                    normal=normal,
                    origin=origin,
                    polygon_index=polygon_index,
                    vertex_count=corners))
    if total != len(vertices):
        msg = (f'Faces account for {total} vertices but the pool holds {len(vertices)}; '
               'the read is out of step.')
        raise InvalidLevelError(msg)
    log.debug('Read %d faces over %d vertices.', len(polygons), len(vertices))
    return LevelGeometry(polygons=tuple(polygons), vertices=tuple(vertices))


def _skip_preamble(data: bytes) -> int:
    """
    Step over the four leading arrays and the format version.

    Parameters
    ----------
    data : bytes
        A decompressed level.

    Returns
    -------
    int
        The offset of the first container.
    """
    count, offset = _read_array_count(data, 0, 'the vertex pool')
    for _ in range(count):
        _, offset = read_vector3(data, offset)
    count, offset = _read_array_count(data, offset, 'the face table')
    for _ in range(count):
        for _ in range(4):
            _, offset = read_int(data, offset)
        _, offset = read_vector3(data, offset)
        _, offset = read_vector3(data, offset)
    count, offset = _read_array_count(data, offset, 'the BSP')
    for _ in range(count):
        _, offset = read_vector3(data, offset)
        _, offset = read_vector3(data, offset)
        for _ in range(6):
            _, offset = read_int(data, offset)
    count, offset = _read_array_count(data, offset, 'the BSP face list')
    for _ in range(count):
        _, offset = read_int(data, offset)
    _version, offset = read_int(data, offset)
    return offset


def read_textures(data: bytes) -> tuple[TextureImage, ...]:
    """
    Read the images a level embeds.

    Each texture is stored as a complete image file, byte for byte as the artist saved it, under
    the absolute path it was authored at. ``X_LevelDBTextureImage``'s writer emits a format code,
    a byte count, and then the file, so nothing needs decoding here.

    Parameters
    ----------
    data : bytes
        A decompressed ``.ldb``.

    Returns
    -------
    tuple[TextureImage, ...]
        The textures, in stored order.

    Raises
    ------
    InvalidLevelError
        If the level's leading arrays are malformed, or a texture runs past the end of the file.
    """
    offset = _skip_preamble(data)
    count, offset = read_int(data, offset)
    textures: list[TextureImage] = []
    for _ in range(count):
        path, offset = read_string(data, offset)
        kind, offset = read_int(data, offset)
        length, offset = read_int(data, offset)
        if offset + length > len(data):
            msg = f'Texture {path!r} claims {length} bytes but the file ends.'
            raise InvalidLevelError(msg)
        textures.append(TextureImage(data=data[offset:offset + length], kind=kind, path=path))
        offset += length
    log.debug('Read %d textures.', len(textures))
    return tuple(textures)


def _read_material_map(data: bytes, offset: int) -> tuple[dict[int, Material], int]:
    """
    Read the identifier-to-material map.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the map marker.

    Returns
    -------
    tuple[dict[int, Material], int]
        The materials and the offset just past the map.

    Raises
    ------
    InvalidLevelError
        If the map or one of its entries is not where it should be.
    """
    if data[offset] != BasicType.MAP:
        msg = f'Expected a map marker at offset {offset}, got 0x{data[offset]:02x}.'
        raise InvalidLevelError(msg)
    count, offset = read_int(data, offset + 1)
    materials: dict[int, Material] = {}
    for _ in range(count):
        key, offset = read_int(data, offset)
        if data[offset] != BasicType.PAIR:
            msg = f'Expected a pair marker at offset {offset}, got 0x{data[offset]:02x}.'
            raise InvalidLevelError(msg)
        category, offset = read_string(data, offset + 1)
        texture, offset = read_string(data, offset)
        materials[key] = Material(alpha='', category=category, image='', texture=texture)
    return materials, offset


def _resolve_images(materials: dict[int, Material], images: dict[str, tuple[str, str]],
                    textures: Sequence[TextureImage]) -> dict[int, Material]:
    """
    Fill in each material's colour and alpha image paths from the category table.

    The category entry's second path is the colour and its third is the alpha mask. Across the 29
    shipped levels every entry's colour path is embedded, and 592 of the 4060 entries name a second,
    different image for the mask: ``cardboardalpha`` draws with ``cardboard10a.JPG`` and takes its
    alpha from ``boxalpha01c.JPG``. The third path is never a fallback for the second.

    Parameters
    ----------
    materials : dict[int, Material]
        Materials as read from the map, with no images yet.
    images : dict[str, tuple[str, str]]
        Lowercased material name to its colour path and alpha path.
    textures : collections.abc.Sequence[TextureImage]
        The level's embedded images.

    Returns
    -------
    dict[int, Material]
        The same materials, each carrying the paths of the images it draws with.
    """
    embedded = {texture.path.lower(): texture.path for texture in textures}
    resolved: dict[int, Material] = {}
    for key, material in materials.items():
        colour, mask = images.get(material.texture.lower(), ('', ''))
        image = embedded.get(colour.lower(), '')
        alpha = embedded.get(mask.lower(), '')
        resolved[key] = material._replace(alpha='' if alpha == image else alpha, image=image)
    missing = sum(1 for material in resolved.values() if not material.image)
    if missing:
        log.debug('%d of %d materials name no embedded image.', missing, len(resolved))
    return resolved


_MATRIX_FLOATS = 12
_MATRIX_SIZE = 1 + 4 * _MATRIX_FLOATS
_MIN_CORNERS = 100
_MAX_CORNERS = 4_000_000
_MAX_MESHES = 100_000
_MAX_PLACEMENTS = 100_000
_PROBE_CORNERS = 64
"""Corners read before a candidate container is parsed in full.

The array marker's byte value occurs constantly inside float payloads, so a level yields tens of
thousands of candidates. Four corners let hundreds through, and parsing each of those in full costs
seconds; sixty-four rejects effectively all of them for a fixed, tiny cost.

:meta hide-value:
"""


def _expect_tag(data: bytes, offset: int, tag: int) -> int:
    if offset >= len(data) or data[offset] != tag:
        got = f'0x{data[offset]:02x}' if offset < len(data) else 'end of file'
        msg = f'Expected tag 0x{tag:02x} at offset {offset}, got {got}.'
        raise InvalidLevelError(msg)
    return offset + 1


def _read_vector2(data: bytes, offset: int) -> tuple[tuple[float, float], int]:
    offset = _expect_tag(data, offset, BasicType.VECTOR2)
    return struct.unpack_from('<2f', data, offset), offset + 8


def _read_float(data: bytes, offset: int) -> tuple[float, int]:
    offset = _expect_tag(data, offset, BasicType.FLOAT)
    return struct.unpack_from('<f', data, offset)[0], offset + 4


def _read_corners(data: bytes, offset: int, count: int) -> tuple[list[Corner], int]:
    """
    Read the corner array a static mesh container shares between its meshes.

    Each corner is written by ``FUN_005ef230``: a position index, a texture coordinate, a lightmap
    coordinate, a packed colour and a flag.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the first corner.
    count : int
        Number of corners to read.

    Returns
    -------
    tuple[list[Corner], int]
        The corners and the offset just past them.
    """
    out: list[Corner] = []
    for _ in range(count):
        position, offset = read_int(data, offset)
        uv, offset = _read_vector2(data, offset)
        lightmap_uv, offset = _read_vector2(data, offset)
        colour, offset = read_int(data, offset)
        offset = _expect_tag(data, offset, BasicType.BOOL) + 1
        out.append(Corner(colour=colour, lightmap_uv=lightmap_uv, position=position, uv=uv))
    return out, offset


def _read_faces(data: bytes, offset: int) -> tuple[list[MeshFace], int]:
    """
    Read a mesh polygon container.

    ``X_LevelDBExportMeshPolygonContainer::vf01`` writes a count, then a key and a polygon per
    entry, and closes with a map of integers to vectors that carries no pair markers.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the polygon count.

    Returns
    -------
    tuple[list[MeshFace], int]
        The faces and the offset just past the container.
    """
    count, offset = read_int(data, offset)
    out: list[MeshFace] = []
    for _ in range(count):
        _key, offset = read_int(data, offset)
        first, offset = read_int(data, offset)
        corners, offset = read_int(data, offset)
        normal, offset = read_vector3(data, offset)
        flags, offset = read_int(data, offset)
        material, offset = read_int(data, offset)
        lightmap, offset = read_int(data, offset)
        _u, offset = _read_float(data, offset)
        _v, offset = _read_float(data, offset)
        _spare, offset = read_int(data, offset)
        out.append(
            MeshFace(corner_count=corners,
                     first_corner=first,
                     flags=flags,
                     lightmap=lightmap,
                     material=material,
                     normal=normal))
    offset = _expect_tag(data, offset, BasicType.MAP)
    extra, offset = read_int(data, offset)
    for _ in range(extra):
        _, offset = read_int(data, offset)
        _, offset = read_vector3(data, offset)
    return out, offset


def _read_static_mesh(data: bytes, offset: int) -> tuple[StaticMesh, int]:
    """
    Read one placed mesh.

    ``X_LevelDBExportStaticMesh::vf01`` writes a position array, an array-marked normal array, a
    four-by-three transform, and then the mesh's polygon container.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the position count.

    Returns
    -------
    tuple[StaticMesh, int]
        The mesh and the offset just past it.
    """
    count, offset = read_int(data, offset)
    positions: list[Vector3] = []
    for _ in range(count):
        vertex, offset = read_vector3(data, offset)
        positions.append(vertex)
    offset = _expect_tag(data, offset, BasicType.ARRAY)
    count, offset = read_int(data, offset)
    normals: list[Vector3] = []
    for _ in range(count):
        vertex, offset = read_vector3(data, offset)
        normals.append(vertex)
    offset = _expect_tag(data, offset, BasicType.MATRIX4X3)
    transform = struct.unpack_from(f'<{_MATRIX_FLOATS}f', data, offset)
    offset += 4 * _MATRIX_FLOATS
    faces, offset = _read_faces(data, offset)
    return StaticMesh(faces=tuple(faces),
                      normals=tuple(normals),
                      positions=tuple(positions),
                      transform=transform), offset


def _read_corner_count(data: bytes, offset: int, *, minimum: int = _MIN_CORNERS) -> tuple[int, int]:
    """
    Read a mesh container's corner count and reject an implausible one.

    The scan for the static mesh container tries every array marker in the file, so this doubles as
    the cheap first filter there: the marker's byte value occurs constantly inside float payloads
    and almost every hit fails here. The prop container is found by walking rather than scanning,
    so it passes a *minimum* of zero and only needs the upper bound.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the container's array marker.
    minimum : int
        Counts at or below this are rejected.

    Returns
    -------
    tuple[int, int]
        The count and the offset just past it.

    Raises
    ------
    InvalidLevelError
        If the marker is missing or the count is outside the plausible range.
    """
    offset = _expect_tag(data, offset, BasicType.ARRAY)
    count, offset = read_int(data, offset)
    if not minimum < count < _MAX_CORNERS:
        msg = f'Implausible corner count {count} at offset {offset}.'
        raise InvalidLevelError(msg)
    return count, offset


def _read_mesh_container(data: bytes, offset: int) -> tuple[RenderMesh, int]:
    """
    Read a static mesh container.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the container's array marker.

    Returns
    -------
    tuple[RenderMesh, int]
        The mesh and the offset just past the container.

    Raises
    ------
    InvalidLevelError
        If the structure does not hold at *offset*.
    """
    count, offset = _read_corner_count(data, offset)
    corners, offset = _read_corners(data, offset, count)
    count, offset = read_int(data, offset)
    if not 0 <= count < _MAX_MESHES:
        msg = f'Implausible mesh count {count} at offset {offset}.'
        raise InvalidLevelError(msg)
    meshes: list[StaticMesh] = []
    keys: list[int] = []
    for _ in range(count):
        key, offset = read_int(data, offset)
        mesh, offset = _read_static_mesh(data, offset)
        meshes.append(mesh)
        keys.append(key)
    return RenderMesh(corners=tuple(corners), keys=tuple(keys), meshes=tuple(meshes)), offset


def _find_mesh_container(data: bytes, offset: int) -> tuple[RenderMesh, int] | None:
    """
    Locate the static mesh container.

    The exit container sits between the lightmaps and the meshes and is not read here, so the
    meshes' position is not derivable; instead every array marker is tried and the first whose
    whole structure parses is taken. A level holds one such container, so the search stops at the
    first hit rather than looking for a better one.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset to start searching from.

    Returns
    -------
    tuple[RenderMesh, int] | None
        The mesh and the offset just past the container, or :py:obj:`None` when no candidate
        parses.
    """
    marker = bytes((BasicType.ARRAY,))
    position = data.find(marker, offset)
    while position >= 0:
        found = _try_mesh_container(data, position)
        if found is not None and found[0].meshes:
            return found
        position = data.find(marker, position + 1)
    return None


def _try_mesh_container(data: bytes, position: int) -> tuple[RenderMesh, int] | None:
    """
    Attempt to read a static mesh container at one candidate offset.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    position : int
        Offset of a candidate array marker.

    Returns
    -------
    tuple[RenderMesh, int] | None
        The mesh and the offset just past it, or :py:obj:`None` when the structure does not hold
        here.
    """
    try:
        _count, probe = _read_corner_count(data, position)
        _read_corners(data, probe, _PROBE_CORNERS)
        return _read_mesh_container(data, position)
    except (IndexError, InvalidLevelError, struct.error, ValueError):
        return None


def _skip_material_index(data: bytes, offset: int) -> int:
    """
    Step over the map that indexes materials the other way round.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the map marker.

    Returns
    -------
    int
        The offset just past the map.

    Raises
    ------
    InvalidLevelError
        If the map or one of its entries is not where it should be.
    """
    if data[offset] != BasicType.MAP:
        msg = f'Expected a map marker at offset {offset}, got 0x{data[offset]:02x}.'
        raise InvalidLevelError(msg)
    count, offset = read_int(data, offset + 1)
    for _ in range(count):
        if data[offset] != BasicType.PAIR:
            msg = f'Expected a pair marker at offset {offset}, got 0x{data[offset]:02x}.'
            raise InvalidLevelError(msg)
        _, offset = read_string(data, offset + 1)
        _, offset = read_string(data, offset)
        _, offset = read_int(data, offset)
    return offset


def _read_material_categories(data: bytes, offset: int) -> tuple[dict[str, tuple[str, str]], int]:
    r"""
    Read the table naming the image behind each material.

    ``X_LevelDBExportMaterialCategory::read`` writes three strings per entry: the material's name,
    the path of the image it draws with, and a fallback path pointing at the artist's source file.
    The name is what the material map stores, and it only looks like a filename --
    ``PAINTING22CB.JPG`` is the name of the material that draws with ``...\\Painting22b.jpg``. This
    table is the only link between the two, so matching on filename gets a fifth of the level's
    faces wrong.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the category count.

    Returns
    -------
    tuple[dict[str, tuple[str, str]], int]
        Lowercased material name to its image path and fallback path, and the offset just past the
        categories.
    """
    count, offset = read_int(data, offset)
    images: dict[str, tuple[str, str]] = {}
    for _ in range(count):
        _category, offset = read_string(data, offset)
        materials, offset = read_int(data, offset)
        for _ in range(materials):
            name, offset = read_string(data, offset)
            path, offset = read_string(data, offset)
            fallback, offset = read_string(data, offset)
            offset += 2 * (1 + TAG_SIZES[BasicType.BOOL])
            images[name.lower()] = (path, fallback)
    return images, offset


def _read_lightmaps(data: bytes, offset: int) -> tuple[tuple[TextureImage, ...], int]:
    """
    Read the baked lighting atlases.

    Each is an uncompressed 24-bit Targa of 256 by 256 pixels -- 196626 bytes, header included --
    written the same way the level's other images are: an identifier, a format code, a byte count,
    then the file. :py:attr:`Corner.lightmap_uv` addresses them and already arrives in the nought to
    one range they want.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the entry count.

    Returns
    -------
    tuple[tuple[TextureImage, ...], int]
        The atlases and the offset just past the container.
    """
    count, offset = _read_entry_count(data, offset, 'lightmap')
    out: list[TextureImage] = []
    for _ in range(count):
        key, offset = read_int(data, offset)
        kind, offset = read_int(data, offset)
        length, offset = read_int(data, offset)
        out.append(
            TextureImage(data=data[offset:offset + length], kind=kind, path=f'lightmap_{key}.tga'))
        offset += length
    return tuple(out), offset


_IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
_ROOM_ARRAYS = 10
_ROOM_TRAILING = 4


def _compose(a: Sequence[float], b: Sequence[float]) -> tuple[float, ...]:
    """
    Compose two four-by-three transforms, applying *a* then *b*.

    Parameters
    ----------
    a : collections.abc.Sequence[float]
        The transform applied first.
    b : collections.abc.Sequence[float]
        The transform applied second.

    Returns
    -------
    tuple[float, ...]
        Twelve floats: three basis rows then a translation.
    """
    out = [
        sum(a[row * 3 + k] * b[k * 3 + col] for k in range(3)) for row in range(3)
        for col in range(3)
    ]
    out.extend(sum(a[9 + k] * b[k * 3 + col] for k in range(3)) + b[9 + col] for col in range(3))
    return tuple(out)


def _read_any_array(data: bytes, offset: int) -> tuple[list[str | int], int]:
    """
    Read an array whose element type is told by the first element's tag.

    The room record mixes arrays of names with arrays of identifiers and gives no type marker. An
    empty array consumes nothing either way, so peeking at the first element settles it.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the array marker.

    Returns
    -------
    tuple[list[str | int], int]
        The elements and the offset just past the array.
    """
    offset = _expect_tag(data, offset, BasicType.ARRAY)
    count, offset = read_int(data, offset)
    out: list[str | int] = []
    for _ in range(count):
        value: str | int
        if data[offset] == BasicType.STRING:
            value, offset = read_string(data, offset)
        else:
            value, offset = read_int(data, offset)
        out.append(value)
    return out, offset


def _read_exits(data: bytes, offset: int) -> tuple[dict[str, tuple[tuple[float, ...], str]], int]:
    """
    Read the exits, which are what hold a level together.

    ``X_LevelDBExportExit::read`` writes the portal polygon and its normal in the room's own space,
    a ``mat4x3`` mapping that space into the room on the other side, two indices, the name of the
    matching exit over there, and a remap of the portal's corners. The two sides of one doorway
    carry inverse transforms.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the entry count.

    Returns
    -------
    tuple[dict[str, tuple[tuple[float, ...], str]], int]
        Exit name to its transform and its partner's name, and the offset just past the container.
    """
    count, offset = _read_entry_count(data, offset, 'exit')
    exits: dict[str, tuple[tuple[float, ...], str]] = {}
    for _ in range(count):
        key, offset = read_string(data, offset)
        corners, offset = read_int(data, offset)
        for _ in range(corners + 1):
            offset = _expect_tag(data, offset, BasicType.VECTOR3) + TAG_SIZES[BasicType.VECTOR3]
        offset = _expect_tag(data, offset, BasicType.MATRIX4X3)
        transform = struct.unpack_from(f'<{_MATRIX_FLOATS}f', data, offset)
        offset += 4 * _MATRIX_FLOATS
        for _ in range(2):
            _, offset = read_int(data, offset)
        partner, offset = read_string(data, offset)
        offset = _expect_tag(data, offset, BasicType.ARRAY)
        groups, offset = read_int(data, offset)
        for _ in range(groups):
            _, offset = _read_any_array(data, offset)
        exits[key] = (transform, partner)
    return exits, offset


def _read_rooms(data: bytes, offset: int) -> tuple[list[tuple[list[int], str]], int]:
    """
    Read the rooms: the identifiers of the meshes each one owns, and its name.

    ``X_LevelDBExportRoom::read`` writes ten arrays -- the room's mesh identifiers, its exits, its
    objects, its props, its pickups and so on -- then the room's name and five trailing scalars.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the entry count.

    Returns
    -------
    tuple[list[tuple[list[int], str]], int]
        Each room's mesh identifiers and name, and the offset just past the container.
    """
    count, offset = _read_entry_count(data, offset, 'room')
    rooms: list[tuple[list[int], str]] = []
    for _ in range(count):
        _key, offset = read_int(data, offset)
        arrays: list[list[str | int]] = []
        for _ in range(_ROOM_ARRAYS):
            values, offset = _read_any_array(data, offset)
            arrays.append(values)
        name, offset = read_string(data, offset)
        offset = _expect_tag(data, offset, BasicType.FLOAT) + TAG_SIZES[BasicType.FLOAT]
        for _ in range(_ROOM_TRAILING):
            _, offset = read_int(data, offset)
        rooms.append(([i for i in arrays[0] if isinstance(i, int)], name))
    return rooms, offset


def _place_rooms(exits: dict[str, tuple[tuple[float, ...], str]],
                 rooms: Sequence[tuple[list[int], str]]) -> dict[str, tuple[float, ...]]:
    """
    Give every room a world transform by walking the exit graph.

    A level is not stored as one space: each room is modelled about its own origin, so without this
    they all pile onto each other. On ``Part1_Level1.ldb`` 545 of the 703 room pairs overlap by more
    than half the smaller room's volume before the walk and 15 after it.

    Rooms unreachable from the first are given their own component rather than dropped, so nothing
    disappears when a level's graph is not fully connected.

    Parameters
    ----------
    exits : dict[str, tuple[tuple[float, ...], str]]
        Exit name to its transform and its partner's name.
    rooms : collections.abc.Sequence[tuple[list[int], str]]
        Each room's mesh identifiers and name.

    Returns
    -------
    dict[str, tuple[float, ...]]
        Room name to the transform placing it in the world.
    """
    graph: dict[str, list[tuple[str, tuple[float, ...]]]] = {}
    for key, (transform, partner) in exits.items():
        if partner in exits:
            graph.setdefault(key.rsplit('::', 1)[0], []).append((partner.rsplit('::',
                                                                                1)[0], transform))
    placed: dict[str, tuple[float, ...]] = {}
    for _ids, start in rooms:
        if start in placed:
            continue
        placed[start] = _IDENTITY
        queue = [start]
        while queue:
            here = queue.pop()
            for there, transform in graph.get(here, ()):
                if there in placed:
                    continue
                placed[there] = _compose(transform, placed[here])
                queue.append(there)
    return placed


def _read_entry_count(data: bytes, offset: int, label: str) -> tuple[int, int]:
    """
    Read a container's entry count and reject an implausible one.

    The containers are walked in sequence, so one misread ripples into every one that follows; the
    count is the first place that shows, which is why each container checks it before believing it.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the count.
    label : str
        What is being counted, for the message.

    Returns
    -------
    tuple[int, int]
        The count and the offset just past it.

    Raises
    ------
    InvalidLevelError
        If the count is negative or beyond anything a level holds.
    """
    count, offset = read_int(data, offset)
    if not 0 <= count < _MAX_PLACEMENTS:
        msg = f'Implausible {label} count {count} at offset {offset}.'
        raise InvalidLevelError(msg)
    return count, offset


def _read_placement(data: bytes, offset: int) -> tuple[Placement, int]:
    """
    Read the head every placed object shares.

    ``X_LevelDBLevelObject::read`` writes a name, the transform placing the object, a second
    transform, an identifier, and the room the object belongs to.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the object's name.

    Returns
    -------
    tuple[Placement, int]
        The placement and the offset just past it.
    """
    name, offset = read_string(data, offset)
    offset = _expect_tag(data, offset, BasicType.MATRIX4X3)
    transform = struct.unpack_from(f'<{_MATRIX_FLOATS}f', data, offset)
    offset = _expect_tag(data, offset + 4 * _MATRIX_FLOATS, BasicType.MATRIX4X3)
    offset += 4 * _MATRIX_FLOATS
    _identifier, offset = read_int(data, offset)
    room, offset = read_string(data, offset)
    return Placement(name=name, room=room, transform=transform), offset


def _read_string_array(data: bytes, offset: int) -> int:
    """
    Step over an array of strings.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the array marker.

    Returns
    -------
    int
        The offset just past the array.
    """
    offset = _expect_tag(data, offset, BasicType.ARRAY)
    count, offset = read_int(data, offset)
    for _ in range(count):
        _, offset = read_string(data, offset)
    return offset


def _skip_properties(data: bytes, offset: int) -> int:
    """
    Step over one property bag: an array of strings, a map of arrays, then another array.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the first array marker.

    Returns
    -------
    int
        The offset just past the bag.
    """
    offset = _read_string_array(data, offset)
    offset = _expect_tag(data, offset, BasicType.MAP)
    count, offset = read_int(data, offset)
    for _ in range(count):
        _, offset = read_string(data, offset)
        offset = _read_string_array(data, offset)
    return _read_string_array(data, offset)


def _skip_static_light(data: bytes, offset: int) -> int:
    """
    Step over one static light: the placement, an orientation, then ten floats.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the light.

    Returns
    -------
    int
        The offset just past the light.
    """
    _placement, offset = _read_placement(data, offset)
    offset = _expect_tag(data, offset, BasicType.MATRIX3) + TAG_SIZES[BasicType.MATRIX3]
    for _ in range(10):
        offset = _expect_tag(data, offset, BasicType.FLOAT) + TAG_SIZES[BasicType.FLOAT]
    return offset


def _skip_startpoint(data: bytes, offset: int) -> int:
    """
    Step over one start point: the placement then an integer.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the start point.

    Returns
    -------
    int
        The offset just past the start point.
    """
    _placement, offset = _read_placement(data, offset)
    _, offset = read_int(data, offset)
    return offset


def _skip_fsm(data: bytes, offset: int) -> int:
    """
    Step over one state machine.

    ``X_LevelDBExportFSM::read`` writes the placement, an array of strings, a string, a property
    bag, then three maps whose values are themselves property bags.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the machine.

    Returns
    -------
    int
        The offset just past the machine.
    """
    _placement, offset = _read_placement(data, offset)
    offset = _read_string_array(data, offset)
    _, offset = read_string(data, offset)
    offset = _skip_properties(data, offset)
    for _ in range(3):
        offset = _expect_tag(data, offset, BasicType.MAP)
        count, offset = read_int(data, offset)
        for _ in range(count):
            _, offset = read_string(data, offset)
            offset = _skip_properties(data, offset)
    return offset


def _skip_trigger(data: bytes, offset: int) -> int:
    """
    Step over one trigger: the placement, a float, then an integer.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the trigger.

    Returns
    -------
    int
        The offset just past the trigger.
    """
    _placement, offset = _read_placement(data, offset)
    offset = _expect_tag(data, offset, BasicType.FLOAT) + TAG_SIZES[BasicType.FLOAT]
    _, offset = read_int(data, offset)
    return offset


def _read_curve(data: bytes, offset: int) -> tuple[tuple[float, ...], int]:
    """
    Read one animation curve: a three-integer header, a sample count, and that many floats.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the curve.

    Returns
    -------
    tuple[tuple[float, ...], int]
        The samples and the offset just past the curve.
    """
    for _ in range(3):
        _, offset = read_int(data, offset)
    count, offset = read_int(data, offset)
    samples = []
    for _ in range(count):
        offset = _expect_tag(data, offset, BasicType.FLOAT)
        samples.append(struct.unpack_from('<f', data, offset)[0])
        offset += TAG_SIZES[BasicType.FLOAT]
    return tuple(samples), offset


def _read_animation(data: bytes, offset: int, name: str) -> tuple[PropAnimation, int]:
    """
    Read one prop animation.

    ``X_LevelDBExportDynamicMeshAnimation::read`` writes a duration, the transform the prop starts
    at, the one it ends at, three arrays of script lines, then two curves. The scripts are what
    chain clips together -- a door's ``open1`` ends by firing ``DO_Animate(stop1)`` -- and are not
    needed to draw the motion, so they are stepped over.

    The two curves are separate channels, each sampled evenly across the duration. The first is the
    distance travelled in world units -- its last sample matches the gap between the two poses on
    4701 of the 4704 moving clips -- and the second is how far the prop has turned, from nought to
    one, reaching exactly one on 3535 of the 3536 that turn. They carry different sample counts,
    so a prop that both slides and turns eases the two differently.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the animation.
    name : str
        The clip's name, which the container read just before this.

    Returns
    -------
    tuple[PropAnimation, int]
        The clip and the offset just past it.
    """
    offset = _expect_tag(data, offset, BasicType.FLOAT)
    duration = struct.unpack_from('<f', data, offset)[0]
    offset += TAG_SIZES[BasicType.FLOAT]
    poses = []
    for _ in range(2):
        offset = _expect_tag(data, offset, BasicType.MATRIX4X3)
        poses.append(struct.unpack_from(f'<{_MATRIX_FLOATS}f', data, offset))
        offset += TAG_SIZES[BasicType.MATRIX4X3]
    for _ in range(3):
        offset = _read_string_array(data, offset)
    distance, offset = _read_curve(data, offset)
    turn, offset = _read_curve(data, offset)
    return PropAnimation(distance=distance,
                         duration=duration,
                         end=poses[1],
                         name=name,
                         start=poses[0],
                         turn=turn), offset


_DYNAMIC_MESH_FLAGS = 6
_DYNAMIC_MESH_TRAILING = 4


def _read_dynamic_meshes(data: bytes, offset: int) -> tuple[RenderMesh, int]:
    """
    Read the animated props.

    The container mirrors the static mesh one -- a corner pool shared by every prop, then one entry
    per prop -- but keys its entries by name and follows each mesh with the placement, the prop's
    animations, six flags and four integers.

    Props nest: ``::a5::Gas_Bottle_small1::valve.DO`` is a child of ``::a5::Gas_Bottle_small1``, and
    the mesh's own transform is relative to that parent while the placement's is the accumulated
    world one. They agree for a prop with no parent, which is most of them, and disagree on 1356 of
    the 5946 props across the shipped levels -- by as much as 953 units on
    ``Startup_level.ldb``. The placement's is the one to keep, so it replaces the mesh's here and
    the exporter can treat every prop the same way.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the container's array marker.

    Returns
    -------
    tuple[RenderMesh, int]
        The props and the offset just past the container.
    """
    count, offset = _read_corner_count(data, offset, minimum=-1)
    corners, offset = _read_corners(data, offset, count)
    count, offset = _read_entry_count(data, offset, 'prop')
    meshes: list[StaticMesh] = []
    names: list[str] = []
    clips: list[tuple[PropAnimation, ...]] = []
    for _ in range(count):
        name, offset = read_string(data, offset)
        mesh, offset = _read_static_mesh(data, offset)
        placement, offset = _read_placement(data, offset)
        mesh = mesh._replace(transform=placement.transform)
        animations, offset = read_int(data, offset)
        found: list[PropAnimation] = []
        for _ in range(animations):
            clip, offset = read_string(data, offset)
            animation, offset = _read_animation(data, offset, clip)
            found.append(animation)
        offset += _DYNAMIC_MESH_FLAGS * (1 + TAG_SIZES[BasicType.BOOL])
        for _ in range(_DYNAMIC_MESH_TRAILING):
            _, offset = read_int(data, offset)
        meshes.append(mesh)
        names.append(name)
        clips.append(tuple(found))
    return RenderMesh(animations=tuple(clips),
                      corners=tuple(corners),
                      meshes=tuple(meshes),
                      names=tuple(names)), offset


def _read_object_container(data: bytes, offset: int,
                           element: Callable[[bytes, int], int]) -> tuple[list[Placement], int]:
    """
    Read one container of placed objects.

    ``R_Container<T>::read`` writes the entry count, then per entry a key and the element itself.
    Every element begins with the placement, so *element* is only asked to step over the rest.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the entry count.
    element : collections.abc.Callable[[bytes, int], int]
        Reads one whole element and returns the offset just past it.

    Returns
    -------
    tuple[list[Placement], int]
        The placements and the offset just past the container.

    """
    count, offset = _read_entry_count(data, offset, 'placement')
    out: list[Placement] = []
    for _ in range(count):
        _key, offset = read_string(data, offset)
        placement, _ = _read_placement(data, offset)
        offset = element(data, offset)
        out.append(placement)
    return out, offset


def _read_characters(data: bytes, offset: int) -> tuple[tuple[Character, ...], int]:
    """
    Read the NPC placements.

    ``X_LevelDBExportCharacter::read`` follows the placement with the skin's directory name and four
    arrays of strings holding the character's scripted behaviour.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the entry count.

    Returns
    -------
    tuple[tuple[Character, ...], int]
        The characters and the offset just past the container.

    """
    count, offset = _read_entry_count(data, offset, 'character')
    out: list[Character] = []
    for _ in range(count):
        _key, offset = read_string(data, offset)
        placement, offset = _read_placement(data, offset)
        skin, offset = read_string(data, offset)
        for _ in range(4):
            offset = _read_string_array(data, offset)
        out.append(Character(placement=placement, skin=skin))
    return tuple(out), offset


def _read_items(data: bytes, offset: int) -> tuple[tuple[LevelItem, ...], int]:
    """
    Read the pickups.

    ``X_LevelDBExportLevelItem::read`` follows the placement with the item's directory name.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the entry count.

    Returns
    -------
    tuple[tuple[LevelItem, ...], int]
        The pickups and the offset just past the container.

    """
    count, offset = _read_entry_count(data, offset, 'item')
    out: list[LevelItem] = []
    for _ in range(count):
        _key, offset = read_string(data, offset)
        placement, offset = _read_placement(data, offset)
        item, offset = read_string(data, offset)
        out.append(LevelItem(item=item, placement=placement))
    return tuple(out), offset


def _skip_static_point_light(data: bytes, offset: int) -> int:
    """
    Step over one static point light: the placement then six floats.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the light.

    Returns
    -------
    int
        The offset just past the light.
    """
    _placement, offset = _read_placement(data, offset)
    for _ in range(6):
        offset = _expect_tag(data, offset, BasicType.FLOAT) + TAG_SIZES[BasicType.FLOAT]
    return offset


def _read_indexed_container(data: bytes, offset: int, element: Callable[[bytes, int], int]) -> int:
    """
    Step over a container that keys its entries by number rather than by name.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset of the entry count.
    element : collections.abc.Callable[[bytes, int], int]
        Reads one element and returns the offset just past it.

    Returns
    -------
    int
        The offset just past the container.
    """
    count, offset = _read_entry_count(data, offset, 'entry')
    for _ in range(count):
        _key, offset = read_int(data, offset)
        offset = element(data, offset)
    return offset


def _room_of(name: str) -> str:
    """
    Take the room out of an object's name.

    Every placed object is named ``::room::rest``, and that prefix is the only link back to its
    room; the object's own room field is left empty on the shipped levels.

    Parameters
    ----------
    name : str
        The object's name.

    Returns
    -------
    str
        The room's name, or an empty string when the name does not carry one.
    """
    parts = name.split('::')
    return f'::{parts[1]}' if len(parts) > 2 else ''  # noqa: PLR2004


class _Tail(NamedTuple):
    """Everything read after the static meshes, already placed in the world."""

    mesh: RenderMesh
    props: RenderMesh | None
    characters: tuple[Character, ...]
    items: tuple[LevelItem, ...]


def _read_tail_containers(
    data: bytes, offset: int
) -> tuple[tuple[Character, ...], RenderMesh, tuple[LevelItem, ...], list[tuple[list[int], str]]]:
    """
    Read every container after the static meshes, in the order the level writes them.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset just past the static mesh container.

    Returns
    -------
    tuple[tuple[Character, ...], RenderMesh, tuple[LevelItem, ...], list[tuple[list[int], str]]]
        The characters, props, pickups and rooms, each still in its own room's space.
    """
    for element in (_skip_static_light, _skip_startpoint, _skip_fsm):
        _, offset = _read_object_container(data, offset, element)
    characters, offset = _read_characters(data, offset)
    _, offset = _read_object_container(data, offset, _skip_trigger)
    props, offset = _read_dynamic_meshes(data, offset)
    items, offset = _read_items(data, offset)
    offset = _read_indexed_container(data, offset, _skip_static_point_light)
    rooms, offset = _read_rooms(data, offset)
    return characters, props, items, rooms


def _place_props(props: RenderMesh, placed: dict[str, tuple[float, ...]]) -> RenderMesh:
    """
    Move every prop, and both ends of each of its clips, into its room's place in the world.

    Parameters
    ----------
    props : RenderMesh
        The props, still in their own rooms' spaces.
    placed : dict[str, tuple[float, ...]]
        Room name to the transform placing it.

    Returns
    -------
    RenderMesh
        The same props, placed.
    """
    meshes = []
    clips = []
    for index, (mesh, name) in enumerate(zip(props.meshes, props.names, strict=True)):
        room = placed.get(_room_of(name), _IDENTITY)
        meshes.append(mesh._replace(transform=_compose(mesh.transform, room)))
        found = props.animations[index] if index < len(props.animations) else ()
        clips.append(
            tuple(
                clip._replace(end=_compose(clip.end, room), start=_compose(clip.start, room))
                for clip in found))
    return props._replace(animations=tuple(clips), meshes=tuple(meshes))


def _read_tail(data: bytes, offset: int, mesh: RenderMesh, exits: dict[str, tuple[tuple[float, ...],
                                                                                  str]]) -> _Tail:
    """
    Read the containers that follow the static meshes and place everything in one world.

    ``X_LevelDBExportLevel::read`` takes them in a fixed order: static lights, start points, state
    machines, characters, triggers, animated props, pickups, static point lights, then rooms. The
    rooms come last, which is why the whole tail has to be walked before anything can be placed.

    A failure anywhere costs the rest of the tail. The level still renders without it, so the walk
    gives up and hands back what it has rather than raising.

    Parameters
    ----------
    data : bytes
        A decompressed level.
    offset : int
        Offset just past the static mesh container.
    mesh : RenderMesh
        The static meshes, still in their own rooms' spaces.
    exits : dict[str, tuple[tuple[float, ...], str]]
        The level's exits, which say how the rooms fit together.

    Returns
    -------
    _Tail
        The meshes, props, characters and pickups, placed where the level's exits put them.
    """
    characters: tuple[Character, ...] = ()
    items: tuple[LevelItem, ...] = ()
    props: RenderMesh | None = None
    try:
        characters, props, items, rooms = _read_tail_containers(data, offset)
    except (IndexError, InvalidLevelError, struct.error, ValueError):
        log.warning('Could not walk the tail containers; the level is left unassembled.')
        return _Tail(characters=characters, items=items, mesh=mesh, props=props)
    placed = _place_rooms(exits, rooms)
    by_key = {identifier: placed.get(name, _IDENTITY) for ids, name in rooms for identifier in ids}
    return _Tail(characters=tuple(
        c._replace(placement=c.placement._replace(transform=_compose(
            c.placement.transform, placed.get(_room_of(c.placement.name), _IDENTITY))))
        for c in characters),
                 items=tuple(
                     i._replace(placement=i.placement._replace(transform=_compose(
                         i.placement.transform, placed.get(_room_of(i.placement.name), _IDENTITY))))
                     for i in items),
                 mesh=mesh._replace(meshes=tuple(
                     m._replace(transform=by_key.get(key, _IDENTITY))
                     for m, key in zip(mesh.meshes, mesh.keys, strict=True))),
                 props=props and _place_props(props, placed))


def read_level(data: bytes) -> Level:
    """
    Read a level's geometry, images, materials and per-face material assignment.

    Parameters
    ----------
    data : bytes
        A decompressed ``.ldb``.

    Returns
    -------
    Level
        Everything decoded so far.

    Raises
    ------
    InvalidLevelError
        If any structure is not where the format says it should be.
    """
    geometry = read_geometry(data)
    offset = _skip_preamble(data)
    count, offset = read_int(data, offset)
    textures: list[TextureImage] = []
    for _ in range(count):
        path, offset = read_string(data, offset)
        kind, offset = read_int(data, offset)
        length, offset = read_int(data, offset)
        if offset + length > len(data):
            msg = f'Texture {path!r} claims {length} bytes but the file ends.'
            raise InvalidLevelError(msg)
        textures.append(TextureImage(data=data[offset:offset + length], kind=kind, path=path))
        offset += length
    materials, offset = _read_material_map(data, offset)
    offset = _skip_material_index(data, offset)
    images, offset = _read_material_categories(data, offset)
    materials = _resolve_images(materials, images, textures)
    lightmaps, offset = _read_lightmaps(data, offset)
    log.debug('Read %d textures and %d materials.', len(textures), len(materials))
    exits: dict[str, tuple[tuple[float, ...], str]] = {}
    try:
        exits, offset = _read_exits(data, offset)
        found: tuple[RenderMesh, int] | None = _read_mesh_container(data, offset)
    except (IndexError, InvalidLevelError, struct.error, ValueError):
        log.warning('Could not read the exits; searching for the meshes instead.')
        found = _find_mesh_container(data, offset)
    if found is None:
        log.warning('Could not locate the renderable meshes; falling back to the BSP faces.')
        return Level(geometry=geometry,
                     lightmaps=lightmaps,
                     materials=materials,
                     mesh=None,
                     textures=tuple(textures))
    mesh, offset = found
    mesh, props, characters, items = _read_tail(data, offset, mesh, exits)
    log.debug('Read %d props, %d characters and %d items.',
              len(props.meshes) if props else 0, len(characters), len(items))
    return Level(characters=characters,
                 geometry=geometry,
                 items=items,
                 lightmaps=lightmaps,
                 materials=materials,
                 mesh=mesh,
                 props=props,
                 textures=tuple(textures))
