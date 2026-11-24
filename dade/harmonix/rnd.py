"""
Read Amplitude's Milo ``Rnd`` objects field by field.

Each reader follows the game's ``Load()`` for one class and its bases, and a body must be consumed
exactly. Strings are a ``u32`` length and that many bytes; a list is a ``u32`` count and that many
strings. A transform is twelve floats, the rows ``X``, ``Y``, and ``Z`` of the basis then the
origin, applied to a row vector (``v * M``), and a child's world transform is its local transform
times its parent's world transform.
"""
from __future__ import annotations

import struct

from dade.common.exceptions import InvalidFormatError

from .typing import RndBones, RndFilter, RndKey, RndMesh, RndTransAnim, RndTransform, RndVertex

__all__ = ('read_mesh', 'read_trans_anim')

_MESH_REVISION = 14
_TRANS_ANIM_REVISION = 3
_FLAG_REVISIONS = range(2, 5)  # Transformable revisions with a trailing unused byte.
_FILTER_SIZES = {0: 8, 1: 9, 2: 8, 3: 8, 4: 12}  # ScaleOffset, MinMaxLoop, Zero/First/Second.
_VERTEX = struct.Struct('<3f2f3f4f2f')
_FACE = struct.Struct('<3H')
_EDGE = struct.Struct('<2H')
_MAX_STRING = 0x400


class _Stream:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def take(self, size: int) -> bytes:
        if self.offset + size > len(self.data):
            msg = f'Truncated `Rnd` object at offset {self.offset}.'
            raise InvalidFormatError(msg)
        chunk = self.data[self.offset:self.offset + size]
        self.offset += size
        return chunk

    def unpack(self, fmt: str) -> tuple[float | int, ...]:
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))

    def u8(self) -> int:
        return self.take(1)[0]

    def u32(self) -> int:
        return int(self.unpack('<I')[0])

    def floats(self, count: int) -> tuple[float, ...]:
        return tuple(float(x) for x in self.unpack(f'<{count}f'))

    def string(self) -> str:
        if (size := self.u32()) > _MAX_STRING:
            msg = f'Implausible `Rnd` string length {size}.'
            raise InvalidFormatError(msg)
        return self.take(size).decode('latin-1')

    def strings(self) -> tuple[str, ...]:
        return tuple(self.string() for _ in range(self.u32()))

    def keys(self, width: int) -> tuple[RndKey, ...]:
        out = []
        for _ in range(self.u32()):
            *value, frame = self.floats(width + 1)
            out.append(RndKey(tuple(value), frame))
        return tuple(out)

    def finish(self) -> None:
        if self.offset != len(self.data):
            msg = f'{len(self.data) - self.offset} trailing bytes after the `Rnd` object.'
            raise InvalidFormatError(msg)


def _transform(stream: _Stream) -> RndTransform:
    revision = stream.u32()
    local = stream.floats(12)
    world = stream.floats(12)
    children = stream.strings()
    billboard, origin = 0, (0.0, 0.0, 0.0)
    if revision > 0:
        billboard = stream.u32()
        x, y, z = stream.floats(3)
        origin = (x, y, z)
    if revision in _FLAG_REVISIONS:
        stream.u8()
    return RndTransform(revision, local, world, children, billboard, origin)


def _drawable(stream: _Stream) -> tuple[bool, tuple[str, ...]]:
    stream.u32()  # Revision.
    return stream.u8() != 0, stream.strings()


def _bones(stream: _Stream) -> RndBones | None:
    if not (first := stream.string()):
        return None
    second = stream.string()
    return RndBones((first, second), (stream.floats(12), stream.floats(12)))


def read_mesh(data: bytes) -> RndMesh:
    """
    Read a version-14 ``Rnd::Mesh`` body.

    Parameters
    ----------
    data : bytes
        The ``.mesh`` object body.

    Returns
    -------
    RndMesh
        The mesh.

    Raises
    ------
    InvalidFormatError
        If the body is not a version-14 mesh, is truncated, or has bytes after the mesh.
    """
    stream = _Stream(data)
    if (revision := stream.u32()) != _MESH_REVISION:
        msg = f'Unsupported `Rnd::Mesh` revision {revision}.'
        raise InvalidFormatError(msg)
    transform = _transform(stream)
    showing, draws = _drawable(stream)
    stream.u32()  # Collideable revision.
    collides = stream.strings()
    z_mode, z_func = stream.u32(), stream.u32()
    material, geometry_owner, transform_owner = stream.string(), stream.string(), stream.string()
    sphere = stream.floats(4)
    lod_next = stream.string()
    min_screen = stream.floats(1)[0]
    mutable = stream.u8() != 0
    vertices = tuple(
        RndVertex((v[0], v[1], v[2]), (v[3], v[4]), (v[5], v[6], v[7]), (v[8], v[9], v[10],
                                                                         v[11]), (v[12], v[13]))
        for v in _VERTEX.iter_unpack(stream.take(_VERTEX.size * stream.u32())))
    faces = tuple(
        (a, b, c) for a, b, c in _FACE.iter_unpack(stream.take(_FACE.size * stream.u32())))
    edges = tuple((a, b) for a, b in _EDGE.iter_unpack(stream.take(_EDGE.size * stream.u32())))
    bones = _bones(stream)
    stream.finish()
    return RndMesh(transform, showing, draws, collides, z_mode, z_func, material, geometry_owner,
                   transform_owner, sphere, lod_next, min_screen, mutable, vertices, faces, edges,
                   bones)


def read_trans_anim(data: bytes) -> RndTransAnim:
    """
    Read a revision-3 ``Rnd::TransAnim`` (``.tnm``) body.

    Parameters
    ----------
    data : bytes
        The ``.tnm`` object body.

    Returns
    -------
    RndTransAnim
        The animation.

    Raises
    ------
    InvalidFormatError
        If the body is not a revision-3 animation, has an unknown filter, is truncated, or has
        bytes after the animation.
    """
    stream = _Stream(data)
    if (revision := stream.u32()) != _TRANS_ANIM_REVISION:
        msg = f'Unsupported `Rnd::TransAnim` revision {revision}.'
        raise InvalidFormatError(msg)
    stream.u32()  # Animatable revision.
    filters = []
    for _ in range(stream.u32()):
        if (kind := stream.u32()) not in _FILTER_SIZES:
            msg = f'Unknown `Rnd::Animatable` filter type {kind}.'
            raise InvalidFormatError(msg)
        filters.append(RndFilter(kind, stream.take(_FILTER_SIZES[kind])))
    anims = stream.strings()
    showing, draws = _drawable(stream)
    target = stream.string()
    rotation_keys = stream.keys(4)
    translation_keys = stream.keys(3)
    frames_owner = stream.string()
    translation_interpolation = stream.u32()
    repeat_translation = stream.u8() != 0
    scale_keys = stream.keys(3)
    scale_interpolation = stream.u32()
    follow_path = stream.u8() != 0
    stream.finish()
    return RndTransAnim(tuple(filters), anims, showing, draws, target, rotation_keys,
                        translation_keys, frames_owner, translation_interpolation,
                        repeat_translation, scale_keys, scale_interpolation, follow_path)
