"""Model converters: Incoming PC ``.ian`` meshes to Wavefront OBJ and MTL."""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import logging
import struct

from dade.common.context import input_root
from dade.common.obj import encode_obj
from dade.incoming.textures import place_ian_texture

from ._base import ConversionError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = ('IANModel', 'ian_to_obj', 'parse_ian')

log = logging.getLogger(__name__)

_HEADER_SIZE = 0x14
_VERTEX_STRIDE = 0x20
_FACE_STRIDE = 0x1c
_VERTEX = struct.Struct('<8f')
_LOD_FACE_COUNT = struct.Struct('<I')
_U16 = struct.Struct('<H')
_U32 = struct.Struct('<I')
_MATERIAL_NAME = 'material0'
_ASCII_MIN = 0x20
_ASCII_MAX = 0x7e


class IANVertex(NamedTuple):
    """One mesh vertex: object-space position, normal, and texture coordinate."""

    position: tuple[float, float, float]
    """Object-space position (the engine multiplies by the ODL scale at load)."""
    normal: tuple[float, float, float]
    """Vertex normal."""
    uv: tuple[float, float]
    """Texture coordinate."""


class IANModel(NamedTuple):
    """A decoded ``.ian`` model: a single mesh of vertices and a triangle list."""

    name: str
    """Node name embedded in the file (for example ``Line01``)."""
    vertices: tuple[IANVertex, ...]
    """The mesh vertices."""
    triangles: tuple[tuple[int, int, int], ...]
    """Triangles as triples of indices into :py:attr:`vertices`."""


def _read_node_name(data: bytes, face_data_offset: int) -> str:
    end = face_data_offset
    while end > 0 and data[end - 1] == 0:
        end -= 1
    start = end
    while start > 0 and _ASCII_MIN <= data[start - 1] <= _ASCII_MAX:
        start -= 1
    return data[start:end].decode('ascii', errors='replace')


def parse_ian(data: bytes) -> IANModel:
    """
    Parse an Incoming ``.ian`` model, reading the highest-detail level of detail only.

    Parameters
    ----------
    data : bytes
        The raw bytes of the ``.ian`` file.

    Returns
    -------
    IANModel
        The decoded model.

    Raises
    ------
    ConversionError
        If the file is too small or its offsets fall outside the file.
    """
    if len(data) < _HEADER_SIZE + 0x14:
        msg = 'File is too small to be an IAN model.'
        raise ConversionError(msg)
    face_count = _LOD_FACE_COUNT.unpack_from(data, _HEADER_SIZE)[0] & 0xffff
    vertex_count = _U16.unpack_from(data, _HEADER_SIZE + 0x04)[0]
    vertices_offset = _U32.unpack_from(data, _HEADER_SIZE + 0x08)[0]
    face_data_offset = _U32.unpack_from(data, _HEADER_SIZE + 0x0c)[0]
    if (vertices_offset + vertex_count * _VERTEX_STRIDE > len(data)
            or face_data_offset + face_count * _FACE_STRIDE > len(data)):
        msg = 'IAN vertex or face array extends past the end of the file.'
        raise ConversionError(msg)
    name = _read_node_name(data, face_data_offset)
    vertices = tuple(_iter_vertices(data, vertices_offset, vertex_count))
    triangles = tuple(_iter_triangles(data, face_data_offset, face_count))
    return IANModel(name, vertices, triangles)


def _iter_vertices(data: bytes, offset: int, count: int) -> Iterator[IANVertex]:
    for i in range(count):
        px, py, pz, nx, ny, nz, u, v = _VERTEX.unpack_from(data, offset + i * _VERTEX_STRIDE)
        yield IANVertex((px, py, pz), (nx, ny, nz), (u, v))


def _iter_triangles(data: bytes, offset: int, count: int) -> Iterator[tuple[int, int, int]]:
    for i in range(count):
        base = offset + i * _FACE_STRIDE
        yield (_U16.unpack_from(data, base + 0x04)[0], _U16.unpack_from(
            data, base + 0x0c)[0], _U16.unpack_from(data, base + 0x14)[0])


def _obj_text(model: IANModel, mtl_name: str) -> str:
    header = (
        f'# Converted from Incoming .ian model `{model.name}`.',
        '# Incoming is left-handed with up = -Y; OBJ is right-handed with up = +Y.',
        '# Negating Y alone performs that left-to-right-handed conversion and the up flip, and',
        '# turns the game clockwise-front winding into OBJ counter-clockwise-front (kept as-is).',
        '# Texture V is flipped (1 - v) from the game top-left origin to the OBJ bottom-left.',
        f'mtllib {mtl_name}',
        f'o {model.name or "model"}',
    )
    return encode_obj(
        [(x, -y, z) for x, y, z in (vertex.position for vertex in model.vertices)],
        model.triangles,
        texcoords=[(u, 1.0 - v) for u, v in (vertex.uv for vertex in model.vertices)],
        normals=[(nx, -ny, nz) for nx, ny, nz in (vertex.normal for vertex in model.vertices)],
        header=header,
        material=_MATERIAL_NAME,
        coordinate_format='{}',
        texcoord_format='{}',
        normals_before_texcoords=True)


def ian_to_obj(source: Path, dest_dir: Path) -> tuple[Path, ...]:
    """
    Convert an Incoming ``.ian`` model to Wavefront OBJ and MTL.

    Geometry, normals, and texture coordinates are written. The texture is resolved through the
    referencing ``.odl`` (the ``.ian`` file carries no texture of its own) and, when found, written
    as a PNG next to the model and referenced from the material.

    Parameters
    ----------
    source : Path
        The source ``.ian`` file.
    dest_dir : Path
        The directory the OBJ and MTL are written to.

    Returns
    -------
    tuple[Path, ...]
        The written OBJ, MTL, and (when resolved) texture PNG paths.
    """
    model = parse_ian(source.read_bytes())
    obj_path = dest_dir / f'{source.stem}.obj'
    mtl_path = dest_dir / f'{source.stem}.mtl'
    obj_path.write_text(_obj_text(model, mtl_path.name), encoding='utf-8')
    texture_name = None
    if (root := input_root()) is not None:
        texture_name = place_ian_texture(source, root, dest_dir)
    material = f'newmtl {_MATERIAL_NAME}\nKd 0.8 0.8 0.8\n'
    if texture_name is not None:
        material += f'map_Kd {texture_name}\n'
    mtl_path.write_text(material, encoding='utf-8')
    if texture_name is None:
        return (obj_path, mtl_path)
    return (obj_path, mtl_path, dest_dir / texture_name)
