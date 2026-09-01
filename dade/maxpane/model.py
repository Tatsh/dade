r"""
Reader for the ``.kfs`` and ``.kf2`` models NPCs, pickups and weapons are drawn with.

Both are chunked ``R_MemoryFile`` streams written by the 3ds max exporter, and they carry the same
information in two encodings. A ``.kfs`` skin uses version 0 chunks, where everything is tagged and
faces index positions and texture coordinates separately; a ``.kf2`` object uses version 1, where
the counts are tagged but the vertex and coordinate data are packed float arrays and a flat
sixteen-bit index buffer draws them. The chunk identifiers are shared, so one reader handles both.

Models are Z-up, the convention of the tool that exported them, while the game and glTF are both
Y-up; positions and normals are rotated on the way out so a character stands up. Texture
coordinates are not touched at all: V runs negative, and the game hands it to Direct3D as written
and lets wrapping sort it out.

A model does not embed its images. It carries a search path -- always ``textures`` then
``..\\sharedtextures`` -- and its materials name files to be found along it, so a caller that wants
the model textured has to read those off disk itself.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import struct

from .memoryfile import CHUNK_HEADER_SIZE, TAG_SIZES, BasicType, read_int, read_string
from .typing import Model, ModelFace, ModelMesh

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from .typing import Vector3

__all__ = ('InvalidModelError', 'read_model')

log = logging.getLogger(__name__)

_LIBRARY = 0x0001000F
"""Material library: a search path, a count, then that many material chunks."""
_MATERIAL = 0x00010010
_TEXTURE = 0x00010011
_MESH = 0x00010005
_NODE = 0x00010000
_POSITIONS = 0x00010006
_FACES = 0x00010007
_FACE = 0x00010008
_MATERIALS = 0x0001000C
_COORDS = 0x0001000E

_PACKED = 1
"""Chunk version that packs its payload instead of tagging every value."""
_FLOAT_SIZE = 4
_TRIANGLE = 3
_MAX_ELEMENTS = 4_000_000


class InvalidModelError(ValueError):
    """Raised when a buffer is not a readable model."""


def _chunks(data: bytes, offset: int, end: int) -> Iterator[tuple[int, int, int, int]]:
    """
    Walk the chunks laid consecutively between two offsets.

    Parameters
    ----------
    data : bytes
        A decompressed model.
    offset : int
        Offset of the first chunk tag.
    end : int
        Offset to stop at.

    Yields
    ------
    tuple[int, int, int, int]
        The chunk's identifier and version, and the offsets of its body and of its end.

    Raises
    ------
    InvalidModelError
        If a chunk's size does not fit inside *end*.
    """
    while offset < end:
        if data[offset] != BasicType.CHUNK:
            return
        if offset + CHUNK_HEADER_SIZE > end:
            msg = f'A chunk header at offset {offset} runs past the end of the stream.'
            raise InvalidModelError(msg)
        identifier, version, size = struct.unpack_from('<3I', data, offset + 1)
        if size < CHUNK_HEADER_SIZE or offset + size > end:
            msg = f'Chunk 0x{identifier:08x} at offset {offset} claims {size} bytes.'
            raise InvalidModelError(msg)
        yield identifier, version, offset + CHUNK_HEADER_SIZE, offset + size
        offset += size


def _read_count(data: bytes, offset: int) -> tuple[int, int]:
    """
    Read an element count and reject an implausible one.

    Parameters
    ----------
    data : bytes
        A decompressed model.
    offset : int
        Offset of the count.

    Returns
    -------
    tuple[int, int]
        The count and the offset just past it.

    Raises
    ------
    InvalidModelError
        If the count is negative or beyond anything a model holds.
    """
    count, offset = read_int(data, offset)
    if not 0 <= count < _MAX_ELEMENTS:
        msg = f'Implausible element count {count} at offset {offset}.'
        raise InvalidModelError(msg)
    return count, offset


def _upright(x: float, y: float, z: float) -> Vector3:
    """
    Turn an exporter-space vector into a game-space one.

    Parameters
    ----------
    x : float
        Sideways.
    y : float
        Depth in exporter space.
    z : float
        Up in exporter space.

    Returns
    -------
    Vector3
        The same vector with the up axis moved from Z to Y.
    """
    return (x, -z, y)


def _read_vectors(data: bytes, offset: int, count: int, *,
                  packed: bool) -> tuple[list[Vector3], int]:
    """
    Read a run of three-component vectors, tagged or packed.

    Parameters
    ----------
    data : bytes
        A decompressed model.
    offset : int
        Offset of the first vector.
    count : int
        How many to read.
    packed : bool
        Read raw floats rather than tagged vectors.

    Returns
    -------
    tuple[list[Vector3], int]
        The vectors and the offset just past them.

    Raises
    ------
    InvalidModelError
        If a tagged run holds something that is not a vector.
    """
    out: list[Vector3] = []
    stride = 3 * _FLOAT_SIZE
    if packed:
        out.extend(
            _upright(*struct.unpack_from('<3f', data, offset + index * stride))
            for index in range(count))
        return out, offset + count * stride
    for _ in range(count):
        if data[offset] != BasicType.VECTOR3:
            msg = f'Expected a vector at offset {offset}, got 0x{data[offset]:02x}.'
            raise InvalidModelError(msg)
        out.append(_upright(*struct.unpack_from('<3f', data, offset + 1)))
        offset += 1 + stride
    return out, offset


def _read_face_indices(data: bytes, offset: int, end: int) -> list[tuple[int, ...]]:
    """
    Read the per-face index chunks a version 0 mesh writes.

    Parameters
    ----------
    data : bytes
        A decompressed model.
    offset : int
        Offset of the first face chunk.
    end : int
        Offset to stop at.

    Returns
    -------
    list[tuple[int, ...]]
        One tuple of indices per face.
    """
    out: list[tuple[int, ...]] = []
    for identifier, _version, body, tail in _chunks(data, offset, end):
        if identifier != _FACE:
            break
        count, cursor = _read_count(data, body)
        indices = []
        for _ in range(count):
            value, cursor = read_int(data, cursor)
            indices.append(value)
        out.append(tuple(indices))
        offset = tail
    return out


def _skip_face_chunks(data: bytes, offset: int, end: int) -> int:
    """
    Step over the per-face index chunks to whatever follows them.

    Parameters
    ----------
    data : bytes
        A decompressed model.
    offset : int
        Offset of the first face chunk.
    end : int
        Offset to stop at.

    Returns
    -------
    int
        The offset just past the last face chunk.
    """
    while offset < end and data[offset] == BasicType.CHUNK:
        _identifier, _version, _body, tail = next(_chunks(data, offset, end))
        offset = tail
    return offset


def _read_materials(data: bytes, offset: int, end: int) -> tuple[dict[str, str], tuple[str, ...]]:
    """
    Read the material library: what each material is called and which image it draws with.

    Parameters
    ----------
    data : bytes
        A decompressed model.
    offset : int
        Offset of the library's body.
    end : int
        Offset to stop at.

    Returns
    -------
    tuple[dict[str, str], tuple[str, ...]]
        Material name to image file name, and the directories to look for those images in.
    """
    search, offset = read_string(data, offset)
    _count, offset = read_int(data, offset)
    materials: dict[str, str] = {}
    for identifier, _version, body, tail in _chunks(data, offset, end):
        if identifier != _MATERIAL:
            continue
        name, cursor = read_string(data, body)
        image = ''
        for inner, _v, inner_body, _inner_tail in _chunks(data, _skip_to_chunk(data, cursor, tail),
                                                          tail):
            if inner != _TEXTURE:
                continue
            _slot, at = read_string(data, inner_body)
            for _ in range(2):
                _, at = read_int(data, at)
            files, at = read_int(data, at)
            for _ in range(files):
                image, at = read_string(data, at)
                break
            break
        materials[name] = image
        offset = tail
    return materials, tuple(part for part in search.replace('\\', '/').split(';') if part)


def _skip_to_chunk(data: bytes, offset: int, end: int) -> int:
    """
    Step over tagged values until a chunk begins.

    A material writes a long run of flags and colours before its texture chunk, and none of it is
    needed here, so the values are stepped over by their tag widths rather than decoded.

    Parameters
    ----------
    data : bytes
        A decompressed model.
    offset : int
        Offset to start from.
    end : int
        Offset to stop at.

    Returns
    -------
    int
        The offset of the next chunk, or *end* when there is none.
    """
    while offset < end and data[offset] != BasicType.CHUNK:
        if data[offset] == BasicType.STRING:
            _, offset = read_string(data, offset)
            continue
        width = TAG_SIZES.get(data[offset])
        if width is None:
            return end
        offset += 1 + width
    return offset


def _read_mesh(data: bytes, offset: int, end: int) -> ModelMesh:
    """
    Read one mesh, in either encoding.

    Parameters
    ----------
    data : bytes
        A decompressed model.
    offset : int
        Offset of the mesh's body.
    end : int
        Offset to stop at.

    Returns
    -------
    ModelMesh
        The mesh.
    """
    name = ''
    positions: list[Vector3] = []
    normals: list[Vector3] = []
    coords: list[tuple[float, float]] = []
    position_faces: list[tuple[int, ...]] = []
    coord_faces: list[tuple[int, ...]] = []
    materials: tuple[str, ...] = ()
    face_materials: list[int] = []
    # The mesh chunk's own version does not decide the encoding: a skin's mesh is version 1 with
    # version 0 arrays inside it, and an object's is version 2 with version 1 arrays. Each array
    # chunk says for itself whether it is packed.
    for identifier, inner, body, tail in _chunks(data, offset, end):
        packed = inner >= _PACKED
        if identifier == _NODE:
            name, _ = read_string(data, body)
        elif identifier == _POSITIONS:
            count, cursor = _read_count(data, body)
            positions, cursor = _read_vectors(data, cursor, count, packed=packed)
            if packed:
                normals, _ = _read_vectors(data, cursor, count, packed=True)
        elif identifier == _FACES:
            position_faces = _read_faces(data, body, tail, packed=packed)
        elif identifier == _COORDS:
            coord_faces, coords = _read_coords(data, body, tail, packed=packed)
        elif identifier == _MATERIALS:
            materials, face_materials = _read_mesh_materials(data, body, tail)
    return _assemble(name, positions, normals, coords, position_faces, coord_faces, materials,
                     face_materials)


def _read_faces(data: bytes, offset: int, end: int, *, packed: bool) -> list[tuple[int, ...]]:
    """
    Read the triangles: a flat index buffer when packed, one chunk per face otherwise.

    Parameters
    ----------
    data : bytes
        A decompressed model.
    offset : int
        Offset of the chunk's body.
    end : int
        Offset to stop at.
    packed : bool
        Read a sixteen-bit index buffer rather than per-face chunks.

    Returns
    -------
    list[tuple[int, ...]]
        One tuple of indices per face.
    """
    count, cursor = _read_count(data, offset)
    if not packed:
        return _read_face_indices(data, cursor, end)
    indices = struct.unpack_from(f'<{count}H', data, cursor)
    return [tuple(indices[at:at + _TRIANGLE]) for at in range(0, count - 2, _TRIANGLE)]


def _read_coords(data: bytes, offset: int, end: int, *,
                 packed: bool) -> tuple[list[tuple[int, ...]], list[tuple[float, float]]]:
    """
    Read one texture coordinate set.

    A packed set stores one coordinate per vertex, so its faces are the position faces and no
    per-face indices are written. A tagged set writes per-face indices first and its own pool after.

    Coordinates are stored as three-component vectors whose second component is V and whose third
    is unused, and they go to Direct3D untouched, so they are kept exactly as written. V is
    normally negative, which wraps to the same texel as ``1 + v``; U goes negative too on skins
    that mirror a face across the head, so wrapping is required either way.

    Parameters
    ----------
    data : bytes
        A decompressed model.
    offset : int
        Offset of the chunk's body.
    end : int
        Offset to stop at.
    packed : bool
        Read a packed pool rather than per-face chunks.

    Returns
    -------
    tuple[list[tuple[int, ...]], list[tuple[float, float]]]
        The per-face indices, empty when the set is per-vertex, and the coordinates.
    """
    _set, cursor = read_int(data, offset)
    count, cursor = _read_count(data, cursor)
    if packed:
        vectors, _ = _read_vectors(data, cursor, count, packed=True)
        return [], [(u, w) for u, _v, w in vectors]
    faces = _read_face_indices(data, cursor, end)
    cursor = _skip_face_chunks(data, cursor, end)
    for _ in range(2):
        _, cursor = read_int(data, cursor)
    count, cursor = _read_count(data, cursor)
    vectors, _ = _read_vectors(data, cursor, count, packed=False)
    return faces, [(u, w) for u, _v, w in vectors]


def _read_mesh_materials(data: bytes, offset: int, end: int) -> tuple[tuple[str, ...], list[int]]:
    """
    Read the material names a mesh uses and which one each face draws with.

    Parameters
    ----------
    data : bytes
        A decompressed model.
    offset : int
        Offset of the chunk's body.
    end : int
        Offset to stop at.

    Returns
    -------
    tuple[tuple[str, ...], list[int]]
        The names, and one index per face where the mesh writes them.
    """
    count, cursor = _read_count(data, offset)
    names = []
    for _ in range(count):
        name, cursor = read_string(data, cursor)
        names.append(name)
    if cursor >= end or data[cursor] == BasicType.CHUNK:
        return tuple(names), []
    faces, cursor = _read_count(data, cursor)
    out = []
    for _ in range(faces):
        value, cursor = read_int(data, cursor)
        out.append(value)
    return tuple(names), out


def _assemble(name: str, positions: list[Vector3], normals: list[Vector3],
              coords: list[tuple[float, float]], position_faces: list[tuple[int, ...]],
              coord_faces: list[tuple[int, ...]], materials: tuple[str, ...],
              face_materials: list[int]) -> ModelMesh:
    """
    Put the separately-stored parts of a mesh together, dropping anything malformed.

    Parameters
    ----------
    name : str
        The mesh's name.
    positions : list[Vector3]
        Vertex positions.
    normals : list[Vector3]
        One normal per position, or empty.
    coords : list[tuple[float, float]]
        Texture coordinates.
    position_faces : list[tuple[int, ...]]
        Position indices per face.
    coord_faces : list[tuple[int, ...]]
        Coordinate indices per face, empty when the coordinates are per-vertex.
    materials : tuple[str, ...]
        Material names the faces index.
    face_materials : list[int]
        One material index per face, or empty when every face uses the first.

    Returns
    -------
    ModelMesh
        The assembled mesh.
    """

    # An index has to be in range at both ends: a negative one is in range for Python and picks a
    # vertex from the far end of the pool, which is silently wrong geometry rather than an error.
    def holds(indices: Sequence[int], pool: Sequence[object]) -> bool:
        return len(indices) == _TRIANGLE and all(0 <= i < len(pool) for i in indices)

    faces: list[ModelFace] = []
    for index, triangle in enumerate(position_faces):
        if not holds(triangle, positions):
            continue
        mapped = coord_faces[index] if index < len(coord_faces) else triangle
        if not holds(mapped, coords):
            mapped = (0, 0, 0)
        material = face_materials[index] if index < len(face_materials) else 0
        faces.append(
            ModelFace(coords=(mapped[0], mapped[1], mapped[2]),
                      material=material if 0 <= material < len(materials) else 0,
                      positions=(triangle[0], triangle[1], triangle[2])))
    return ModelMesh(coords=tuple(coords),
                     faces=tuple(faces),
                     materials=materials,
                     name=name,
                     normals=tuple(normals),
                     positions=tuple(positions))


def read_model(data: bytes) -> Model:
    """
    Read a ``.kfs`` skin or ``.kf2`` object.

    Parameters
    ----------
    data : bytes
        A decompressed model.

    Returns
    -------
    Model
        The meshes and the material library.

    Raises
    ------
    InvalidModelError
        If the file is not a chunked stream, or a chunk runs past the end.
    """
    if not data or data[0] != BasicType.CHUNK:
        msg = 'Not a chunked model.'
        raise InvalidModelError(msg)
    materials: dict[str, str] = {}
    search: tuple[str, ...] = ()
    meshes: list[ModelMesh] = []
    for identifier, _version, body, tail in _chunks(data, 0, len(data)):
        if identifier == _LIBRARY:
            materials, search = _read_materials(data, body, tail)
        elif identifier == _MESH:
            meshes.append(_read_mesh(data, body, tail))
    log.debug('Read %d meshes and %d materials.', len(meshes), len(materials))
    return Model(materials=materials, meshes=tuple(meshes), search=search)
