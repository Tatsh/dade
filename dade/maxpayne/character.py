"""
Readers for the files that make a character move: its ``.skd`` weights and its animations.

A character is three files. The skin (:py:func:`dade.maxpayne.model.read_model`) is a mesh in its
bind pose, the skeleton is a model whose meshes are the bones, and the ``.skd`` beside the skin
records which bones move each vertex. Animations are ``.kf2`` files of one track per bone, each
track a run of the bone's transform at sparse keyframes.

Every transform is ``M_Matrix4x3`` in the row-vector convention, three basis rows then a
translation, and maps a bone's space into its parent's. A root bone's transform, and a skin mesh's,
maps straight into game space. Composing the skeleton's transforms down the hierarchy gives the
bind pose; on every first-game skin that puts the feet at height nought, and the vertices bound
rigidly to a bone sit beside that bone's collision hull.

Animation keys use the same transforms as the skeleton. A child's translation never changes from
the skeleton's, only its rotation, and a root's translation is the pelvis height above the floor.
Clips are recorded in place; the distance a walk covers comes from the character's script instead.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import struct

from .memoryfile import CHUNK_HEADER_SIZE, BasicType, read_chunk_header, read_int, read_string
from .typing import Animation, AnimationTrack, SkinWeights

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ('InvalidCharacterError', 'read_animation', 'read_weights')

log = logging.getLogger(__name__)

_WEIGHTS = 0x00010014
_TRACK = 0x00010012
_TRACK_HEADER = 0x00010013
_MATRIX_SIZE = 48
_FLOAT_SIZE = 4
_TAGGED_WEIGHTS = 0
"""Version of the first game's ``.skd``, three runs of vertex, bone and weight triples."""
_INFLUENCE_RUNS = 3
"""Runs in a first-game ``.skd``: vertices bound to one bone, then the first and the remaining
influences of the blended vertices."""


class InvalidCharacterError(ValueError):
    """Raised when a buffer is not a readable ``.skd`` or character animation."""


def _read_float(data: bytes, offset: int) -> tuple[float, int]:
    """
    Read one tagged float.

    Parameters
    ----------
    data : bytes
        The stream.
    offset : int
        Byte offset of the tag.

    Returns
    -------
    tuple[float, int]
        The value and the offset just past it.

    Raises
    ------
    InvalidCharacterError
        If the tag at *offset* is not :py:attr:`~dade.maxpayne.memoryfile.BasicType.FLOAT`.
    """
    if data[offset] != BasicType.FLOAT:
        msg = f'Expected a float at offset {offset}, got 0x{data[offset]:02x}.'
        raise InvalidCharacterError(msg)
    return struct.unpack_from('<f', data, offset + 1)[0], offset + 1 + _FLOAT_SIZE


def _read_strings(data: bytes, offset: int) -> tuple[tuple[str, ...], int]:
    """
    Read a count and that many strings.

    Parameters
    ----------
    data : bytes
        The stream.
    offset : int
        Byte offset of the count.

    Returns
    -------
    tuple[tuple[str, ...], int]
        The strings and the offset just past them.
    """
    count, offset = read_int(data, offset)
    out = []
    for _ in range(count):
        value, offset = read_string(data, offset)
        out.append(value)
    return tuple(out), offset


def _read_array(data: bytes, offset: int, kind: str) -> tuple[tuple[str | int | float, ...], int]:
    """
    Read one run of a second-game ``.skd``: an array marker, a count, and that many values.

    Parameters
    ----------
    data : bytes
        The stream.
    offset : int
        Byte offset of the array marker.
    kind : str
        ``'string'``, ``'int'`` or ``'float'``.

    Returns
    -------
    tuple[tuple[str | int | float, ...], int]
        The values and the offset just past them.

    Raises
    ------
    InvalidCharacterError
        If no array marker is at *offset*.
    """
    if data[offset] != BasicType.ARRAY:
        msg = f'Expected an array at offset {offset}, got 0x{data[offset]:02x}.'
        raise InvalidCharacterError(msg)
    count, offset = read_int(data, offset + 1)
    readers: dict[str, Callable[[bytes, int], tuple[str | int | float, int]]] = {
        'float': _read_float,
        'int': read_int,
        'string': read_string
    }
    reader = readers[kind]
    out: list[str | int | float] = []
    for _ in range(count):
        value, offset = reader(data, offset)
        out.append(value)
    return tuple(out), offset


def _tagged_weights(data: bytes, offset: int) -> SkinWeights:
    """
    Read a first-game ``.skd`` body.

    Three runs of vertex, bone and weight triples come first. The mesh and bone names follow, then
    one vector per vertex that is nought on every shipped skin.

    Parameters
    ----------
    data : bytes
        The stream.
    offset : int
        Offset of the chunk's body.

    Returns
    -------
    SkinWeights
        The weights.
    """
    found: dict[int, list[tuple[int, float]]] = {}
    for _ in range(_INFLUENCE_RUNS):
        count, offset = read_int(data, offset)
        for _ in range(count):
            vertex, offset = read_int(data, offset)
            bone, offset = read_int(data, offset)
            weight, offset = _read_float(data, offset)
            found.setdefault(vertex, []).append((bone, weight))
    meshes, offset = _read_strings(data, offset)
    bones, _ = _read_strings(data, offset)
    total = max(found, default=-1) + 1
    return SkinWeights(bones=bones,
                       influences=tuple(tuple(found.get(v, ())) for v in range(total)),
                       meshes=meshes)


def _array_weights(data: bytes, offset: int) -> SkinWeights:
    """
    Read a second-game ``.skd`` body.

    Six arrays: the mesh names, the bone names, where each vertex's influences start, how many it
    has, and the bones and weights of every influence laid end to end. Two short arrays after them
    divide the vertices into batches and are not needed here.

    Parameters
    ----------
    data : bytes
        The stream.
    offset : int
        Offset of the chunk's body.

    Returns
    -------
    SkinWeights
        The weights.

    Raises
    ------
    InvalidCharacterError
        If an influence range runs past the influence arrays.
    """
    meshes, offset = _read_array(data, offset, 'string')
    bones, offset = _read_array(data, offset, 'string')
    starts, offset = _read_array(data, offset, 'int')
    counts, offset = _read_array(data, offset, 'int')
    indices, offset = _read_array(data, offset, 'int')
    weights, _ = _read_array(data, offset, 'float')
    influences = []
    for start, count in zip(starts, counts, strict=True):
        first, length = int(start), int(count)
        if first < 0 or length < 0 or first + length > min(len(indices), len(weights)):
            msg = f'An influence range {first}+{length} runs past the influence arrays.'
            raise InvalidCharacterError(msg)
        influences.append(
            tuple((int(indices[at]), float(weights[at])) for at in range(first, first + length)))
    return SkinWeights(bones=tuple(map(str, bones)),
                       influences=tuple(influences),
                       meshes=tuple(map(str, meshes)))


def _weights(data: bytes) -> SkinWeights:
    """
    Read a ``.skd`` chunk header and its body.

    Parameters
    ----------
    data : bytes
        A decompressed ``.skd``.

    Returns
    -------
    SkinWeights
        The weights.

    Raises
    ------
    InvalidCharacterError
        If the chunk is not a skin weight chunk.
    """
    identifier, version, _size = read_chunk_header(data)
    if identifier != _WEIGHTS:
        msg = f'Not a skin weight chunk: 0x{identifier:08x}.'
        raise InvalidCharacterError(msg)
    return (_tagged_weights if version == _TAGGED_WEIGHTS else _array_weights)(data,
                                                                               CHUNK_HEADER_SIZE)


def read_weights(data: bytes) -> SkinWeights:
    """
    Read a ``.skd``, from either game.

    Parameters
    ----------
    data : bytes
        A decompressed ``.skd``.

    Returns
    -------
    SkinWeights
        The bone names and each vertex's influences.

    Raises
    ------
    InvalidCharacterError
        If the buffer is not a ``.skd``.
    """
    try:
        weights = _weights(data)
    except InvalidCharacterError:
        raise
    except (IndexError, ValueError, struct.error) as e:
        raise InvalidCharacterError(str(e)) from e
    log.debug('Read weights for %d vertices over %d bones.', len(weights.influences),
              len(weights.bones))
    return weights


def _read_track(data: bytes, offset: int, end: int) -> tuple[AnimationTrack, int, int, bool]:
    """
    Read one bone's track.

    Parameters
    ----------
    data : bytes
        The stream.
    offset : int
        Offset of the track chunk's body.
    end : int
        Offset of the track chunk's end.

    Returns
    -------
    tuple[AnimationTrack, int, int, bool]
        The track, the clip's frame count and rate, and the flag stored with the rate.

    Raises
    ------
    InvalidCharacterError
        If the track does not open with its header chunk, or a key is not a transform.
    """
    identifier, _version, size = read_chunk_header(data, offset)
    if identifier != _TRACK_HEADER:
        msg = f'A track at offset {offset} opens with chunk 0x{identifier:08x}.'
        raise InvalidCharacterError(msg)
    bone, cursor = read_string(data, offset + CHUNK_HEADER_SIZE)
    rate, cursor = read_int(data, cursor)
    flag = bool(data[cursor + 1])
    parent, cursor = read_string(data, offset + size)
    frames, cursor = read_int(data, cursor + 2)
    count, cursor = read_int(data, cursor)
    keys = []
    for _ in range(count):
        frame, cursor = read_int(data, cursor)
        if data[cursor] != BasicType.MATRIX4X3 or cursor + 1 + _MATRIX_SIZE > end:
            msg = f'Expected a transform at offset {cursor}.'
            raise InvalidCharacterError(msg)
        keys.append((frame, struct.unpack_from('<12f', data, cursor + 1)))
        cursor += 1 + _MATRIX_SIZE
    return AnimationTrack(bone=bone, keys=tuple(keys), parent=parent), frames, rate, flag


def read_animation(data: bytes) -> Animation:
    """
    Read a character animation ``.kf2``, from either game.

    Each track is a chunk opening with a header chunk recording the bone, the clip's rate and a
    flag. The parent's name, the clip's frame count and the keys follow it.

    Parameters
    ----------
    data : bytes
        A decompressed animation.

    Returns
    -------
    Animation
        The clip.

    Raises
    ------
    InvalidCharacterError
        If the buffer has no tracks, or a track will not read.
    """
    try:
        clip = _animation(data)
    except InvalidCharacterError:
        raise
    except (IndexError, ValueError, struct.error) as e:
        raise InvalidCharacterError(str(e)) from e
    if not clip.tracks:
        msg = 'No animation tracks.'
        raise InvalidCharacterError(msg)
    return clip


def _animation(data: bytes) -> Animation:
    """
    Read every track of a character animation.

    Parameters
    ----------
    data : bytes
        A decompressed animation.

    Returns
    -------
    Animation
        The clip, with no tracks when the buffer has none.

    Raises
    ------
    InvalidCharacterError
        If a chunk records a size smaller than its header.
    """
    tracks = []
    frames = rate = 0
    flag = False
    offset = 0
    while offset < len(data) and data[offset] == BasicType.CHUNK:
        identifier, _version, size = read_chunk_header(data, offset)
        if size < CHUNK_HEADER_SIZE:
            msg = f'Chunk 0x{identifier:08x} at offset {offset} records {size} bytes.'
            raise InvalidCharacterError(msg)
        if identifier == _TRACK:
            track, length, rate, flag = _read_track(data, offset + CHUNK_HEADER_SIZE, offset + size)
            # A track can record a length of one frame inside a longer clip, as tracks of
            # `idle_goon_standing.kf2` do beside others of 240.
            frames = max(frames, length)
            tracks.append(track)
        offset += size
    return Animation(flag=flag, frames=frames, rate=rate, tracks=tuple(tracks))
