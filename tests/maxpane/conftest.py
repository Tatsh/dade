"""Fixtures for the Max Payne tests."""
from __future__ import annotations

from itertools import starmap
from typing import TYPE_CHECKING
import math
import struct
import zlib

import pytest

from dade.maxpane.crypto import next_seed

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

_ARCHIVER_ID = 3
_SYSTEMTIME = struct.pack('<8H', 2001, 7, 3, 11, 17, 54, 28, 0)
_LEVEL_VERSION = 32
"""The only level format version the game reads. `X_LevelDBExportLevel::vf00` throws on any
other."""


def _encrypt(data: bytes, seed: int) -> bytes:
    """
    Invert :py:func:`dade.maxpane.crypto.decrypt` so tests can build archives.

    Parameters
    ----------
    data : bytes
        Plaintext.
    seed : int
        Signed cipher seed.

    Returns
    -------
    bytes
        Ciphertext that decrypts back to *data*.
    """
    if seed == 0:
        seed = 1
    out = bytearray(len(data))
    for index, byte in enumerate(data):
        seed = next_seed(seed)
        rotated = ((byte - (seed & 0xFF)) & 0xFF) ^ ((((index & 0xFF) + 3) & 0xFF) * 6 & 0xFF)
        rotation = index % 5
        out[index] = (((rotated >> rotation) | (rotated <<
                                                (8 - rotation))) & 0xFF if rotation else rotated)
    return bytes(out)


@pytest.fixture
def encrypt_ras() -> Callable[[bytes, int], bytes]:
    """
    Expose the archive cipher's inverse.

    Returns
    -------
    collections.abc.Callable[[bytes, int], bytes]
        A callable taking plaintext and a seed and returning ciphertext.
    """
    return _encrypt


@pytest.fixture
def make_ras() -> Callable[..., bytes]:
    """
    Build a RAS archive in memory.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable returning a complete archive.
    """
    def build(members: Sequence[tuple[str, bytes]] = (('a.txt', b'hello'), ('b.bin', b'world')),
              *,
              directories: Sequence[str] = ('\\', '\\data\\'),
              modified: bool = True,
              seed: int = 0x1234,
              version: float = 1.2) -> bytes:
        stamp = _SYSTEMTIME if modified else bytes(16)
        file_table = bytearray()
        for name, payload in members:
            file_table += name.encode() + b'\x00'
            file_table += struct.pack('<6I', len(payload), len(payload), 0,
                                      len(directories) - 1, 0, _ARCHIVER_ID)
            file_table += stamp
        directory_table = bytearray()
        for name in directories:
            directory_table += name.encode() + b'\x00' + stamp
        fields = struct.pack('<4IfIIII', len(members), len(directories), len(file_table),
                             len(directory_table), version, 0, zlib.crc32(bytes(file_table)),
                             zlib.crc32(bytes(directory_table)), _ARCHIVER_ID)
        return (b'RAS\x00' + struct.pack('<i', seed) + _encrypt(fields, seed) +
                _encrypt(bytes(file_table), seed) + _encrypt(bytes(directory_table), seed) +
                b''.join(payload for _, payload in members))

    return build


def _tag(tag: int, payload: bytes = b'') -> bytes:
    return bytes((tag,)) + payload


def _int(value: int) -> bytes:
    """Write an integer the way ``operator<<`` compacts it."""
    magnitude = abs(value)
    for mask, tag, width in ((0xFF800000, 0x02, 4), (0x007F8000, 0x12, 3), (0x00007F80, 0x13, 2)):
        if magnitude & mask:
            return _tag(tag, value.to_bytes(width, 'little', signed=True))
    return _tag(0x14, value.to_bytes(1, 'little', signed=True))


def _vec3(x: float, y: float, z: float) -> bytes:
    return _tag(0x16, struct.pack('<3f', x, y, z))


def _vec2(u: float, v: float) -> bytes:
    return _tag(0x15, struct.pack('<2f', u, v))


def _string(text: str) -> bytes:
    return _tag(0x0D) + _int(len(text)) + text.encode('latin-1')


_IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)

_HALF_TURN = (-1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, -1.0)
"""Half a turn about the up axis. Its trace is negative, which is the case a quaternion has to
pivot on rather than take straight."""
_REFLECTED = (-1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
"""A left-handed basis, which no quaternion can hold on its own."""
_TILT = (math.cos(math.radians(2)), 0.0, -math.sin(math.radians(2)), 0.0, 1.0, 0.0,
         math.sin(math.radians(2)), 0.0, math.cos(math.radians(2)))
"""Two degrees about the up axis: far enough to be worth a channel, close enough that walking the
arc between the two rotations would divide by nearly zero."""
_STRETCHED = (2.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
"""Twice as wide, with no rotation. A clip ending here moves nothing a channel can carry."""


def _matrix(translation: tuple[float, float, float] = (0.0, 0.0, 0.0),
            basis: Sequence[float] = _IDENTITY) -> bytes:
    return _tag(0x1A, struct.pack('<12f', *basis, *translation))


def _placement(name: str = '', translation: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> bytes:
    """Write the head every placed object shares: name, two transforms, an identifier, a room."""
    return _string(name) + _matrix(translation) + _matrix() + _int(0) + _string('')


def _string_array(values: Sequence[str] = ('line',)) -> bytes:
    return _tag(0x1C) + _int(len(values)) + b''.join(_string(v) for v in values)


def _properties() -> bytes:
    """0x005e7c00: a string array, a map of arrays, then another string array."""
    return (_string_array() + _tag(0x1F) + _int(1) + _string('key') + _string_array() +
            _string_array())


def _properties_map() -> bytes:
    """0x005e9c70: a map whose values are whole property bags."""
    return _tag(0x1F) + _int(1) + _string('state') + _properties()


def _object_container(entries: Sequence[bytes]) -> bytes:
    return _int(len(entries)) + b''.join(entries)


def _placement_containers(characters: Sequence[tuple[str, str, tuple[float, float, float]]],
                          items: Sequence[tuple[str, str, tuple[float, float, float]]],
                          props: bytes,
                          *,
                          corrupt: str = '') -> bytes:
    """
    Write the containers the level keeps after its static meshes.

    ``X_LevelDBExportLevel::vf00`` takes them in this order: static lights, start points, state
    machines, characters, triggers, animated props, then pickups.

    Parameters
    ----------
    characters : collections.abc.Sequence[tuple[str, str, tuple[float, float, float]]]
        Key, skin and position per NPC.
    items : collections.abc.Sequence[tuple[str, str, tuple[float, float, float]]]
        Key, item name and position per pickup.
    props : bytes
        An encoded dynamic mesh container.
    corrupt : str
        ``'placements'`` writes a count no level could hold, so the walk has to abandon the tail.

    Returns
    -------
    bytes
        The encoded containers.
    """
    out = bytearray()
    if corrupt == 'placements':
        return bytes(_tag(0x02, struct.pack('<i', -1)))
    # One static light, so the walk has to step over a matrix and ten floats to move on.
    out += _object_container([
        _string('Light::0') + _placement() + _tag(0x19, struct.pack('<9f', *_IDENTITY)) +
        b''.join(_tag(0x09, struct.pack('<f', 0.5)) for _ in range(10))
    ])
    out += _object_container([_string('start') + _placement() + _int(0)])
    out += _object_container([
        _string('fsm') + _placement() + _string_array() + _string('') + _properties() +
        _properties_map() * 3
    ])
    out += _object_container([
        _string(key) + _placement(key, position) + _string(skin) + _string_array() * 4
        for key, skin, position in characters
    ])
    out += _object_container(
        [_string('trigger') + _placement() + _tag(0x09, struct.pack('<f', 1.0)) + _int(0)])
    out += props
    out += _object_container(
        [_string(key) + _placement(key, position) + _string(item) for key, item, position in items])
    return bytes(out)


def _exit_container(exits: Sequence[tuple[str, str, tuple[float, float, float]]]) -> bytes:
    """
    Write the exits, which are what say how the rooms fit together.

    Parameters
    ----------
    exits : collections.abc.Sequence[tuple[str, str, tuple[float, float, float]]]
        This exit's name, its partner's name, and the translation into the partner's room.

    Returns
    -------
    bytes
        The encoded container.
    """
    out = bytearray(_int(len(exits)))
    for name, partner, translation in exits:
        out += _string(name)
        out += _tag(0x11, b'\x04')
        for corner in ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)):
            out += _vec3(*corner)
        out += _vec3(0.0, 0.0, 1.0)
        out += _matrix(translation)
        out += _int(0) + _int(1)
        out += _string(partner)
        out += _tag(0x1C) + _int(1) + _tag(0x1C) + _int(4) + b''.join(_int(i) for i in range(4))
    return bytes(out)


def _room_container(rooms: Sequence[tuple[int, Sequence[int], str]]) -> bytes:
    """
    Write the point light container, then the rooms.

    Parameters
    ----------
    rooms : collections.abc.Sequence[tuple[int, collections.abc.Sequence[int], str]]
        Each room's key, the mesh keys it owns, and its name.

    Returns
    -------
    bytes
        Both encoded containers.
    """
    # One static point light, so the walk has to step over a placement and six floats.
    out = bytearray(_int(1) + _int(0) + _placement() + _tag(0x09, struct.pack('<f', 1.0)) * 6)
    out += _int(len(rooms))
    for key, ids, name in rooms:
        out += _int(key)
        out += _tag(0x1C) + _int(len(ids)) + b''.join(_int(i) for i in ids)
        for index in range(9):
            # One array of names, so the reader's element-type peek is exercised both ways.
            entries = (f'{name}::object',) if index == 3 else ()
            out += _tag(0x1C) + _int(len(entries)) + b''.join(_string(e) for e in entries)
        out += _string(name)
        out += _tag(0x09, struct.pack('<f', 0.5))
        out += _int(0) * 4
    return bytes(out)


def _static_mesh_container(triangles: int,
                           materials: Sequence[int],
                           *,
                           mesh_count: int | None = None,
                           meshes: int = 1,
                           extra: Sequence[int] = (3,),
                           layout: str = '',
                           corrupt: str = '') -> bytes:
    """
    Build a static mesh container holding meshes of independent triangles.

    Parameters
    ----------
    triangles : int
        Number of triangles per mesh. The container needs enough corners to be recognised, so keep
        this comfortably above the reader's minimum.
    materials : collections.abc.Sequence[int]
        Material identifier per triangle, cycled if shorter than *triangles*.
    mesh_count : int | None
        Override the mesh count written ahead of the meshes, to exercise the reader's guard.
    meshes : int
        Number of meshes actually written. They share the one corner array.
    extra : collections.abc.Sequence[int]
        Keys for the map of extra vectors that closes each face array.
    layout : str
        ``'wind_back'`` stores a normal that opposes the corner order, so the exporter has to
        reverse each fan. ``'stacked'`` puts every triangle in one plane on top of the last instead
        of one above the other, which is how a level lays graffiti and signage over a wall.
        ``'collinear'`` puts every triangle's corners on one line, so no triangle says which way
        its face points.
    corrupt : str
        ``'faces'`` points the last face past the end of the corner array, ``'corners'`` points the
        last corner past the end of the position pool. Both are exporter guards, not reader ones.

    Returns
    -------
    bytes
        The encoded container.
    """
    out = bytearray(_corner_pool(triangles * 3, corrupt=corrupt))
    out += _int(meshes if mesh_count is None else mesh_count)
    for mesh in range(meshes):
        out += _int(mesh)  # Its key.
        out += _mesh_body(triangles, materials, mesh, extra=extra, layout=layout, corrupt=corrupt)
    return bytes(out)


def _corner_pool(corners: int, *, corrupt: str = '') -> bytes:
    out = bytearray(_tag(0x1C) + _int(corners))
    for index in range(corners):
        position = corners + 1 if corrupt == 'corners' and index == corners - 1 else index
        out += (_int(position) + _vec2(index / max(corners, 1), 0.5) + _vec2(0.0, 0.0) +
                _tag(0x11, b'\xff') + _tag(0x0E, b'\x00'))
    return bytes(out)


def _mesh_body(
    triangles: int,
    materials: Sequence[int],
    mesh: int = 0,
    *,
    extra: Sequence[int] = (3,),
    layout: str = '',
    corrupt: str = '',
    lightmap: int = 0,
    translation: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> bytes:
    """One mesh's positions, normals, transform and faces, without its key."""
    corners = triangles * 3
    # After the exporter's depth mirror each triangle's corners wind about +Y, so a +Y normal
    # leaves the fan as written and a -Y one forces it to be reversed.
    normal = (0.0, -1.0, 0.0) if layout == 'wind_back' else (0.0, 1.0, 0.0)
    # A collinear face has no side to face, which is what the exporter's winding has to survive.
    corner = (((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)) if layout == 'collinear' else
              ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)))
    out = bytearray(_int(corners))
    for index in range(corners):
        x, y, z = corner[index % 3]
        out += _vec3(x + mesh, 0.0 if layout == 'stacked' else float(index // 3), z + y)
    out += _tag(0x1C) + _int(corners)
    for _ in range(corners):
        out += _vec3(0.0, 0.0, 1.0)
    out += _matrix(translation)
    out += _int(triangles)
    for index in range(triangles):
        first = corners if corrupt == 'faces' and index == triangles - 1 else index * 3
        out += (_int(index) + _int(first) + _int(3) + _vec3(*normal) + _tag(0x11, b'\x01') +
                _int(materials[index % len(materials)]) + _int(lightmap) +
                _tag(0x09, struct.pack('<f', 0.0)) + _tag(0x09, struct.pack('<f', 0.0)) + _int(0))
    out += _tag(0x1F) + _int(len(extra))
    for key in extra:
        out += _int(key) + _vec3(0.0, 1.0, 0.0)
    return bytes(out)


def _animation(start: tuple[float, float, float] = (0.0, 0.0, 0.0),
               end: tuple[float, float, float] = (0.0, 0.0, 0.0),
               *,
               duration: float = 1.0,
               samples: int = 2,
               spin: Sequence[float] = _IDENTITY) -> bytes:
    """
    0x005f56e0: a duration, two transforms, three script arrays, then two float curves.

    The first curve is the distance travelled in world units and the second is how far the prop has
    turned, from nought to one; both run straight from one end to the other here.
    """
    travel = math.dist(start, end)
    out = bytearray(_tag(0x09, struct.pack('<f', duration)) + _matrix(start) + _matrix(end, spin))
    out += _string_array() * 3
    for total in (travel, 1.0):
        out += _int(113) + _int(3) + _int(1) + _int(samples)
        for index in range(samples):
            out += _tag(0x09, struct.pack('<f', total * index / max(samples - 1, 1)))
    return bytes(out)


def _dynamic_mesh_container(props: Sequence[tuple[str, tuple[float, float, float]]],
                            materials: Sequence[int],
                            *,
                            triangles: int = 2,
                            animations: int = 1,
                            swing: tuple[float, float, float] = (0.0, 0.0, 0.0),
                            spin: Sequence[float] = _IDENTITY,
                            samples: int = 2) -> bytes:
    """
    Build the container holding the animated props.

    Parameters
    ----------
    props : collections.abc.Sequence[tuple[str, tuple[float, float, float]]]
        Name and placement per prop.
    materials : collections.abc.Sequence[int]
        Material identifier per triangle, cycled.
    triangles : int
        Triangles per prop.
    animations : int
        Animations attached to each prop.
    swing : tuple[float, float, float]
        Where each clip ends, relative to where the prop starts. Leave it at the origin for a clip
        that moves nothing, which the exporter drops.
    spin : collections.abc.Sequence[float]
        The basis each clip ends on.
    samples : int
        Samples in each clip's curve.

    Returns
    -------
    bytes
        The encoded container.
    """
    out = bytearray(_corner_pool(triangles * 3))
    out += _int(len(props))
    for name, translation in props:
        out += _string(name)
        out += _mesh_body(triangles, materials, translation=translation)
        out += _placement(name, translation)
        out += _int(animations)
        # A clip's poses are absolute, not relative: the shipped door's start matrix carries the
        # same translation as the prop's own placement.
        moved = (translation[0] + swing[0], translation[1] + swing[1], translation[2] + swing[2])
        for index in range(animations):
            out += _string(f'clip{index}') + _animation(
                translation, moved, samples=samples, spin=spin)
        out += _tag(0x0E, b'\x01') * 6
        out += _int(0) * 4
    return bytes(out)


@pytest.fixture
def bases() -> dict[str, Sequence[float]]:
    """
    Expose the bases a clip can end on.

    Returns
    -------
    dict[str, collections.abc.Sequence[float]]
        ``half_turn`` rotates the prop about the up axis, ``tilt`` barely does, ``reflected`` is
        left-handed, and ``stretched`` only changes the prop's size.
    """
    return {
        'half_turn': _HALF_TURN,
        'reflected': _REFLECTED,
        'stretched': _STRETCHED,
        'tilt': _TILT
    }


@pytest.fixture
def make_mesh_container() -> Callable[..., bytes]:
    """
    Build a static mesh container on its own.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable returning the encoded container.
    """
    return _static_mesh_container


@pytest.fixture
def make_ldb() -> Callable[..., bytes]:
    """
    Build a minimal level in memory.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable returning a decompressed ``.ldb``.
    """
    def build(*,
              faces: Sequence[Sequence[tuple[float, float, float]]] = (
                  ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.0, 0.0, 1.0)),
                  ((0.0, 2.0, 0.0), (1.0, 2.0, 0.0), (1.0, 2.0, 1.0)),
              ),
              mesh_indices: Sequence[int] = (7, 9),
              textures: Sequence[tuple[str, int, bytes]] = (('C:\\A.TGA', 0, b'\x00\x01\x02'),),
              materials: Sequence[tuple[int, str,
                                        str]] = ((7, 'wood', 'A.TGA'), (9, 'metal', 'B.JPG')),
              triangles: int = 40,
              face_materials: Sequence[int] = (7, 9),
              categories: Sequence[tuple[str, Sequence[tuple[str, str, str]]]] | None = None,
              lightmaps: Sequence[tuple[int, int, bytes]] = (),
              complete: bool = True,
              bsp: tuple[int, int] = (0, 0),
              meshes: int = 1,
              layout: str = '',
              corrupt: str = '',
              characters: Sequence[tuple[str, str, tuple[float, float,
                                                         float]]] = (('::room::e1', 'transit_cop',
                                                                      (1.0, 2.0, 3.0)),),
              items: Sequence[tuple[str, str, tuple[float, float,
                                                    float]]] = (('::room::ammo', 'ammo_ingram',
                                                                 (4.0, 5.0, 6.0)),),
              props: Sequence[tuple[str, tuple[float, float,
                                               float]]] = (('::room::door.DO', (7.0, 8.0, 9.0)),),
              motion: tuple[tuple[float, float, float], Sequence[float],
                            int] = ((0.0, 0.0, 0.0), _IDENTITY, 2),
              placements: bool = True,
              world: tuple[Sequence[tuple[str, str, tuple[float, float, float]]],
                           Sequence[tuple[int, Sequence[int], str]]] = ((), ((0, (0,), '::room'),)),
              junk: bytes = b'') -> bytes:
        out = bytearray()
        vertices = [corner for face in faces for corner in face]
        out += _tag(0x1C) + _int(len(vertices))
        for corner in vertices:
            out += _vec3(*corner)
        out += _tag(0x1C) + _int(len(faces))
        first = 0
        for index, (face, mesh) in enumerate(zip(faces, mesh_indices, strict=True)):
            out += _int(first) + _int(len(face)) + _int(index) + _int(mesh)
            out += _vec3(0.0, 1.0, 0.0) + _vec3(*face[0])
            first += len(face)
        out += _tag(0x1C) + _int(bsp[0])
        for _ in range(bsp[0]):
            out += _vec3(0.0, 1.0, 0.0) + _vec3(0.0, 0.0, 0.0)
            out += b''.join(_int(0) for _ in range(6))
        out += _tag(0x1C) + _int(bsp[1])
        out += b''.join(_int(0) for _ in range(bsp[1]))
        out += _int(_LEVEL_VERSION)
        out += _int(len(textures))
        for path, kind, blob in textures:
            out += _string(path) + _int(kind) + _int(len(blob)) + blob
        if not complete:
            return bytes(out)
        out += _tag(0x1F) + _int(len(materials))
        for key, category, texture in materials:
            out += _int(key) + _tag(0x25) + _string(category) + _string(texture)
        out += _tag(0x1F) + _int(len(materials))
        for key, category, texture in materials:
            out += _tag(0x25) + _string(category) + _string(texture) + _int(key)
        if categories is None:
            # A level's category table is what ties a material's name to an embedded image, so by
            # default give every material an entry naming the texture whose basename matches.
            by_base = {p.replace('\\', '/').rsplit('/', 1)[-1].lower(): p for p, _, _ in textures}
            categories = [(category, ((texture, by_base.get(texture.lower(), ''), ''),))
                          for _, category, texture in materials]
        out += _int(len(categories))
        for category, entries in categories:
            out += _string(category) + _int(len(entries))
            for a, b, c in entries:
                out += _string(a) + _string(b) + _string(c) + _tag(0x0E, b'\x00') * 2
        out += _int(len(lightmaps))
        for key, kind, blob in lightmaps:
            out += _int(key) + _int(kind) + _int(len(blob)) + blob
        out += junk
        if triangles and face_materials:
            out += _exit_container(world[0])
            out += _static_mesh_container(triangles,
                                          face_materials,
                                          meshes=meshes,
                                          layout=layout,
                                          corrupt=corrupt)
            if placements:
                out += _placement_containers(characters,
                                             items,
                                             _dynamic_mesh_container(props,
                                                                     face_materials or (0,),
                                                                     samples=motion[2],
                                                                     spin=motion[1],
                                                                     swing=motion[0]),
                                             corrupt=corrupt)
                out += _room_container(world[1])
        return bytes(out)

    return build


def _chunk(identifier: int, version: int, body: bytes) -> bytes:
    return _tag(0x0C) + struct.pack('<3I', identifier, version, len(body) + 13) + body


def _model_material(name: str, image: str) -> bytes:
    """One entry of a model's material library, with the texture chunk it ends on."""
    body = _string(name) + _tag(0x0E, b'\x00') * 5 + _int(2) + _int(0) + _int(0)
    body += b''.join(_tag(0x09, struct.pack('<f', 255.0)) for _ in range(4))
    texture = _string('Map #0') + _int(1) + _int(2) + _int(1) + _string(image)
    return _chunk(0x00010010, 1, body + _chunk(0x00010011, 1, texture))


def _face_chunk(indices: Sequence[int]) -> bytes:
    return _chunk(0x00010008, 0, _int(len(indices)) + b''.join(_int(i) for i in indices))


@pytest.fixture
def make_model() -> Callable[..., bytes]:
    """
    Build a model in memory, in either of the two encodings.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable returning a decompressed ``.kfs`` or ``.kf2``.
    """
    def build(*,
              packed: bool = False,
              name: str = 'body',
              positions: Sequence[tuple[float, float, float]] = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                                                                 (0.0, 0.0, 1.0)),
              faces: Sequence[Sequence[int]] = ((0, 1, 2),),
              coords: Sequence[tuple[float, float,
                                     float]] = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
              coord_faces: Sequence[Sequence[int]] = ((0, 1, 2),),
              materials: Sequence[tuple[str, str]] = (('Skin', 'skin.png'),),
              face_materials: Sequence[int] = (0,),
              search: str = 'textures;..\\sharedtextures') -> bytes:
        library = _string(search) + _int(len(materials))
        library += b''.join(starmap(_model_material, materials))
        if packed:
            vertices = _tag(0x11, bytes((len(positions),)))
            vertices += b''.join(struct.pack('<3f', *p) for p in positions)
            vertices += b''.join(struct.pack('<3f', 0.0, 0.0, 1.0) for _ in positions)
            flat = [i for face in faces for i in face]
            triangles = _tag(0x10, struct.pack('<H', len(flat)))
            triangles += b''.join(struct.pack('<H', i) for i in flat)
            uv = _int(0) + _tag(0x11, bytes((len(coords),)))
            uv += b''.join(struct.pack('<3f', *c) for c in coords)
        else:
            vertices = _int(len(positions)) + b''.join(starmap(_vec3, positions))
            triangles = _int(len(faces)) + b''.join(_face_chunk(f) for f in faces)
            uv = _int(0) + _int(len(coord_faces))
            uv += b''.join(_face_chunk(f) for f in coord_faces)
            uv += _int(0) + _int(0) + _int(len(coords))
            uv += b''.join(starmap(_vec3, coords))
        mesh = _chunk(0x00010000, 1, _string(name) + _string(''))
        mesh += _chunk(0x00010006, 1 if packed else 0, vertices)
        mesh += _chunk(0x00010007, 1 if packed else 0, triangles)
        used = _int(len(materials)) + b''.join(_string(n) for n, _ in materials)
        if face_materials:
            used += _int(len(face_materials)) + b''.join(_int(i) for i in face_materials)
        mesh += _chunk(0x0001000C, 1 if packed else 0, used)
        mesh += _chunk(0x0001000E, 1 if packed else 0, uv)
        return _chunk(0x0001000F, 0, library) + _chunk(0x00010005, 2 if packed else 1, mesh)

    return build
