"""
Assembler for ``.sdf`` object models.

Reverse-engineered from ``ParseSDFSGEO`` at ``0x4b8470`` and the geometry cache at ``0x4469a0``.
The ``SGEO`` chunk holds a part count followed by 120-byte part records: an eight-byte name that
doubles as the ``.geo`` member name, a row-major 3x3 rotation, a translation, and an eight-byte
parent name at offset 56. Parts form a tree, so each part's world transform is its local transform
composed with its parent's.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import struct

from dade.common.io import read_cstring
from dade.common.obj import encode_obj as common_encode_obj

from .geo import parse as parse_geo
from .typing import Mesh, SdfPart

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from .typing import Matrix3, Vector3

__all__ = ('apply_transform', 'assemble', 'encode_obj', 'parse_sgeo', 'world_transform',
           'write_obj')

log = logging.getLogger(__name__)

_SGEO_TAG = b'SGEO'
"""Tag of the chunk holding the part list.

:meta hide-value:
"""
_PART_SIZE = 120
"""Size in bytes of one part record.

:meta hide-value:
"""


def parse_sgeo(data: bytes) -> tuple[SdfPart, ...]:
    """
    Parse the ``SGEO`` part list out of an ``.sdf``.

    Parameters
    ----------
    data : bytes
        Contents of the ``.sdf`` file.

    Returns
    -------
    tuple[SdfPart, ...]
        Every part record, in file order. Empty when the file has no ``SGEO`` chunk.
    """
    if (found := data.find(_SGEO_TAG)) < 0:
        return ()
    position = found + 8
    count = struct.unpack_from('<I', data, position)[0]
    position += 4
    parts: list[SdfPart] = []
    for _ in range(count):
        parts.append(
            SdfPart(read_cstring(data[position:position + 8]),
                    struct.unpack_from('<9f', data, position + 8),
                    struct.unpack_from('<3f', data, position + 44),
                    read_cstring(data[position + 56:position + 64])))
        position += _PART_SIZE
    return tuple(parts)


def apply_transform(rotation: Matrix3, position: Vector3, vertex: Vector3) -> Vector3:
    """
    Transform a vertex by a rotation and translation.

    Parameters
    ----------
    rotation : Matrix3
        A row-major 3x3 rotation matrix flattened to nine floats.
    position : Vector3
        The translation to add after rotating.
    vertex : Vector3
        The vertex to transform.

    Returns
    -------
    Vector3
        The transformed vertex.
    """
    x, y, z = vertex
    return (x * rotation[0] + y * rotation[3] + z * rotation[6] + position[0],
            x * rotation[1] + y * rotation[4] + z * rotation[7] + position[1],
            x * rotation[2] + y * rotation[5] + z * rotation[8] + position[2])


def world_transform(parts: Mapping[str, SdfPart], name: str,
                    cache: dict[str, tuple[Matrix3, Vector3]]) -> tuple[Matrix3, Vector3]:
    """
    Resolve a part's world transform, composing parents recursively.

    Parameters
    ----------
    parts : collections.abc.Mapping[str, SdfPart]
        Every part, keyed by name.
    name : str
        Name of the part to resolve.
    cache : dict[str, tuple[Matrix3, Vector3]]
        Memoisation of already-resolved transforms. Updated in place.

    Returns
    -------
    tuple[Matrix3, Vector3]
        The part's world rotation and translation.
    """
    if name in cache:
        return cache[name]
    part = parts[name]
    if part.parent in parts and part.parent != name:
        parent_rotation, parent_position = world_transform(parts, part.parent, cache)
        composed = [0.0] * 9
        for row in range(3):
            for column in range(3):
                composed[row * 3 + column] = sum(
                    part.rotation[row * 3 + index] * parent_rotation[index * 3 + column]
                    for index in range(3))
        cache[name] = (tuple(composed),
                       apply_transform(parent_rotation, parent_position, part.position))
    else:
        cache[name] = (part.rotation, part.position)
    return cache[name]


def assemble(data: bytes, load_geo: Callable[[str], bytes | None]) -> Mesh:
    """
    Assemble every part of an ``.sdf`` into a single world-space mesh.

    Parts whose geometry cannot be found or parsed are logged and skipped, matching the game's
    tolerance for absent parts. Faces are triangulated as fans.

    Parameters
    ----------
    data : bytes
        Contents of the ``.sdf`` file.
    load_geo : collections.abc.Callable[[str], bytes | None]
        Resolves a part name to the bytes of its ``.geo`` member, or ``None`` when absent.

    Returns
    -------
    Mesh
        The combined world-space vertices and triangles.
    """
    parts = parse_sgeo(data)
    by_name = {part.name: part for part in parts}
    cache: dict[str, tuple[Matrix3, Vector3]] = {}
    vertices: list[Vector3] = []
    triangles: list[tuple[int, int, int]] = []
    for part in parts:
        if (geo := load_geo(part.name)) is None:
            log.warning('Part `%s` has no geometry.', part.name)
            continue
        if (model := parse_geo(geo)) is None:
            log.warning('Part `%s` has geometry that cannot be parsed.', part.name)
            continue
        rotation, position = world_transform(by_name, part.name, cache)
        base = len(vertices)
        vertices.extend(apply_transform(rotation, position, vertex) for vertex in model.vertices)
        for face in model.faces:
            triangles.extend((base + face[0], base + face[index], base + face[index + 1])
                             for index in range(1,
                                                len(face) - 1))
        log.debug('Part `%s` contributed %d vertices and %d faces.', part.name, len(model.vertices),
                  model.face_count)
    return Mesh(tuple(vertices), tuple(triangles))


def encode_obj(mesh: Mesh, *, name: str = 'model') -> str:
    """
    Encode a mesh as Wavefront OBJ text.

    No material library is referenced, because the ``.geo`` format carries neither texture
    coordinates nor material references. Face indices are one-based, as the format requires.

    Parameters
    ----------
    mesh : Mesh
        The assembled mesh.
    name : str
        Object name recorded in the ``o`` statement.

    Returns
    -------
    str
        The complete OBJ document, ending in a newline.
    """
    return common_encode_obj(mesh.vertices, mesh.triangles, header=(f'o {name}',))


def write_obj(mesh: Mesh, path: Path, *, name: str = 'model') -> None:
    """
    Write a mesh to ``path`` as a Wavefront OBJ.

    Parameters
    ----------
    mesh : Mesh
        The assembled mesh.
    path : pathlib.Path
        Destination ``.obj`` file.
    name : str
        Object name recorded in the ``o`` statement.
    """
    path.write_text(encode_obj(mesh, name=name), encoding='utf-8')
    log.debug('Wrote `%s` (%d vertices, %d triangles).', path, len(mesh.vertices),
              len(mesh.triangles))
