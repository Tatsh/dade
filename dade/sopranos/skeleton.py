"""
Skeletons (``.SKL2``) and animation clips (``.SAM2``), and the glTF skins built from them.

A ``.SKL2`` file is a chain of skeletons, each giving its length at ``0x04`` after the CRC-32 of
its lowercased object path. Every bone record stores its bind transform relative to its parent and
the inverse of its world bind transform, both as row-major matrices that transform row vectors. A
bone's world transform is therefore its local transform times its parent's world transform.

A ``.SAM2`` file opens with sixteen bytes and continues with a chain of clips. Every offset inside a
clip is relative to sixteen bytes before the clip. A track stores a key for each frame it lists,
and each key is an offset from the bind pose rather than a pose. The rotation goes before the bind
rotation and the translation is added to the bind translation. A quaternion component is a 16-bit
float particular to the engine, with a sign bit, four bits of exponent biased by 15, and eleven
bits of mantissa with an implicit leading one. Zero and negative zero are zero.

The game is Z-up and glTF is Y-up. Positions are rewritten as ``(x, z, -y)``, and every rotation
and translation follows the same change of basis.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
import logging
import struct

import numpy as np

from dade.common.exceptions import InvalidFormatError
from dade.common.gltf import FLOAT

from .typing import Bone, Clip, Skeleton, Track

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from dade.common.gltf import GLBDocument

__all__ = ('add_animations', 'add_skin', 'binds', 'find_skeleton', 'read_clips', 'read_skeletons')

log = logging.getLogger(__name__)

_SKELETON_HEADER_SIZE = 0x18
_BONES_AT = 0x10
_BONE_SIZE = 0x90
_INVERSE_AT = 0x40
_PARENT_AT = 0x80
_CLIPS_AT = 0x10
_CLIP_BIAS = 0x10
_CLIP_HEADER_SIZE = 0x18
_CLIP_FIELDS_AT = 0x0E
_TRACK_SIZE = 32
_TRACK_FIELDS_AT = 0x0C
_TRACK_OFFSETS_AT = 0x14
_ROTATION = 4
_ROTATION_TRANSLATION = 5
_KEY_WITH_TRANSLATION = np.dtype([('translation', '<f4', 3), ('rotation', '<u2', 4)])
_SIGN = 0x8000
_MAGNITUDE = 0x7FFF
_MANTISSA = 0x7FF
_EXPONENT_SHIFT = 11
_EXPONENT_MASK = 0xF
_EXPONENT_BIAS = 15
_MANTISSA_SCALE = 2048.0
# Row vectors map from the game's Z-up basis to glTF's Y-up one as ``v @ _BASIS``.
_BASIS = np.array(
    ((1.0, 0.0, 0.0, 0.0), (0.0, 0.0, -1.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
_OFFSET_TOLERANCE = 1e-3
_W = 3
_SHORT = 5122
_SHORT_SCALE = 32767


def _string(data: bytes, at: int) -> str:
    """
    Read a NUL-terminated string.

    Parameters
    ----------
    data : bytes
        The bytes to read from.
    at : int
        Offset of the string.

    Returns
    -------
    str
        The string.
    """
    return data[at:].split(b'\0', 1)[0].decode('ascii', 'replace')


def read_skeletons(data: bytes) -> tuple[Skeleton, ...]:
    """
    Read every skeleton of a ``.SKL2`` file.

    Parameters
    ----------
    data : bytes
        The whole file.

    Returns
    -------
    tuple[Skeleton, ...]
        The skeletons, in file order.

    Raises
    ------
    InvalidFormatError
        If a bone table runs past its skeleton or a bone's parent does not come before it.
    """
    skeletons = []
    at = 0
    while at + _SKELETON_HEADER_SIZE <= len(data):
        name_hash, size = struct.unpack_from('<2I', data, at)
        if not size or at + size > len(data):
            break
        section = data[at:at + size]
        count, table, name_at = struct.unpack_from('<3H', section, _BONES_AT)
        if table + count * _BONE_SIZE > size:
            msg = f'The bone table of the skeleton at {at:#x} runs past its end.'
            raise InvalidFormatError(msg)
        bones = []
        for index in range(count):
            record = table + index * _BONE_SIZE
            parent, bone_name_at, bone_hash = struct.unpack_from('<hHI', section,
                                                                 record + _PARENT_AT)
            if parent >= index:
                msg = f'Bone {index} of the skeleton at {at:#x} has parent {parent}.'
                raise InvalidFormatError(msg)
            bones.append(
                Bone(_string(section, bone_name_at), bone_hash, max(parent, -1),
                     struct.unpack_from('<16f', section, record),
                     struct.unpack_from('<16f', section, record + _INVERSE_AT)))
        skeletons.append(Skeleton(_string(section, name_at), name_hash, tuple(bones)))
        at += size
    return tuple(skeletons)


def _decode(raw: np.ndarray) -> np.ndarray:
    """
    Decode the engine's 16-bit quaternion components.

    Parameters
    ----------
    raw : numpy.ndarray
        The stored half-words.

    Returns
    -------
    numpy.ndarray
        The values, ``±(1 + m / 2048) * 2 ** (e - 15)``.
    """
    words = raw.astype(np.int64)
    magnitude = (1.0 + (words & _MANTISSA) / _MANTISSA_SCALE) * np.exp2((
        (words >> _EXPONENT_SHIFT) & _EXPONENT_MASK) - _EXPONENT_BIAS)
    value = np.where(words & _MAGNITUDE, magnitude, 0.0)
    return np.where(words & _SIGN, -value, value)


def read_clips(data: bytes) -> tuple[Clip, ...]:
    """
    Read every animation clip of a ``.SAM2`` file.

    A track of a kind other than rotation (4) or rotation and translation (5) is skipped. The game
    ships no other kind.

    Parameters
    ----------
    data : bytes
        The whole file.

    Returns
    -------
    tuple[Clip, ...]
        The clips, in file order.
    """
    clips = []
    at = _CLIPS_AT
    while at + _CLIP_HEADER_SIZE <= len(data):
        size, name_hash = struct.unpack_from('<2I', data, at)
        if not size or at + size > len(data):
            break
        base = at - _CLIP_BIAS
        name_at, frame_count, rate, track_count, table = struct.unpack_from(
            '<5H', data, at + _CLIP_FIELDS_AT)
        tracks = (_read_track(data, base, base + table + index * _TRACK_SIZE)
                  for index in range(track_count))
        clips.append(
            Clip(_string(data, base + name_at), name_hash, frame_count, rate,
                 tuple(track for track in tracks if track is not None)))
        at += size
    return tuple(clips)


def _read_track(data: bytes, base: int, record: int) -> Track | None:
    """
    Read one track of a clip.

    Parameters
    ----------
    data : bytes
        The whole ``.SAM2`` file.
    base : int
        The offset the clip's offsets are relative to.
    record : int
        Offset of the track's record.

    Returns
    -------
    Track | None
        The track, or :py:obj:`None` for a kind that is not recognised.
    """
    offset = struct.unpack_from('<3f', data, record)
    kind, bone_at, key_count = struct.unpack_from('<3H', data, record + _TRACK_FIELDS_AT)
    bone_hash, frames_at, keys_at = struct.unpack_from('<3I', data, record + _TRACK_OFFSETS_AT)
    match kind:
        case 4:
            translations = None
            rotations = _decode(
                np.frombuffer(data, '<u2', key_count * 4, base + keys_at).reshape(key_count, 4))
        case 5:
            keys = np.frombuffer(data, _KEY_WITH_TRANSLATION, key_count, base + keys_at)
            translations = keys['translation'].astype(np.float64)
            rotations = _decode(keys['rotation'])
        case _:
            log.debug('Skipping a track of kind %d for `%s`.', kind, _string(data, base + bone_at))
            return None
    return Track(_string(data, base + bone_at), bone_hash,
                 np.frombuffer(data, '<u2', key_count, base + frames_at).astype(np.int64),
                 rotations, translations, offset)


def find_skeleton(name: str, skeleton_hash: int, bones: Iterable[str],
                  skeletons: Sequence[Skeleton]) -> Skeleton | None:
    """
    Find the skeleton an object is skinned to.

    The object records its skeleton's hash, and the first skeleton with that hash wins. A few
    objects record a hash no skeleton has. Those fall back to the first skeleton stored under the
    same object directory that has every bone the object uses.

    Parameters
    ----------
    name : str
        The object's path.
    skeleton_hash : int
        The hash the object records.
    bones : Iterable[str]
        The names of the bones the object uses. Empty names are ignored.
    skeletons : Sequence[Skeleton]
        Candidates, the preferred ones first.

    Returns
    -------
    Skeleton | None
        The skeleton, or :py:obj:`None` when none fits.
    """
    if (found := next((s for s in skeletons if s.name_hash == skeleton_hash), None)) is not None:
        return found
    directory = name.rsplit('/', 1)[0].lower()
    wanted = {bone for bone in bones if bone}
    return next((s for s in skeletons if s.name.rsplit('/', 1)[0].lower() == directory
                 and wanted <= {bone.name
                                for bone in s.bones}), None)


def binds(clip: Clip, skeleton: Skeleton) -> bool:
    """
    Report whether every track of a clip drives a bone of a skeleton.

    Parameters
    ----------
    clip : Clip
        The clip.
    skeleton : Skeleton
        The skeleton.

    Returns
    -------
    bool
        ``True`` when the clip has tracks and the skeleton has a bone for each.
    """
    hashes = {bone.name_hash for bone in skeleton.bones}
    return bool(clip.tracks) and all(track.bone_hash in hashes for track in clip.tracks)


def _local(bone: Bone) -> np.ndarray:
    """
    Give a bone's bind transform relative to its parent in glTF's basis.

    Parameters
    ----------
    bone : Bone
        The bone.

    Returns
    -------
    numpy.ndarray
        A ``4 x 4`` matrix that transforms row vectors.
    """
    result: np.ndarray = _BASIS.T @ np.array(bone.local).reshape(4, 4) @ _BASIS
    return result


def _quaternion(rows: np.ndarray) -> np.ndarray:
    """
    Convert a rotation that transforms row vectors to a quaternion.

    Parameters
    ----------
    rows : numpy.ndarray
        A ``3 x 3`` rotation that transforms row vectors.

    Returns
    -------
    numpy.ndarray
        The unit quaternion ``(x, y, z, w)`` of the same rotation applied to column vectors.
    """
    matrix = rows.T
    axis = int(np.argmax((matrix[0, 0], matrix[1, 1], matrix[2, 2], np.trace(matrix))))
    if axis == _W:
        w = np.sqrt(1.0 + np.trace(matrix)) / 2
        quaternion = np.array(
            ((matrix[2, 1] - matrix[1, 2]) / (4 * w), (matrix[0, 2] - matrix[2, 0]) / (4 * w),
             (matrix[1, 0] - matrix[0, 1]) / (4 * w), w))
    else:
        i, j, k = axis, (axis + 1) % 3, (axis + 2) % 3
        s = np.sqrt(1.0 + matrix[i, i] - matrix[j, j] - matrix[k, k]) * 2
        quaternion = np.zeros(4)
        quaternion[i] = s / 4
        quaternion[j] = (matrix[j, i] + matrix[i, j]) / s
        quaternion[k] = (matrix[k, i] + matrix[i, k]) / s
        quaternion[3] = (matrix[k, j] - matrix[j, k]) / s
    result: np.ndarray = quaternion / np.linalg.norm(quaternion)
    return result


def add_skin(document: GLBDocument, skeleton: Skeleton, note: str) -> int:
    """
    Add the bones of a skeleton as nodes at their bind pose, and a skin over them.

    The first bone is the skin's root, every parent coming before its children. The inverse bind
    matrices are computed from the bind transforms the nodes are given rather than
    copied from the file, and the two agree to within 4e-7.

    Parameters
    ----------
    document : GLBDocument
        GLB under construction.
    skeleton : Skeleton
        The skeleton.
    note : str
        Recorded in the skin's ``extras``, for a caveat about how the skin was built.

    Returns
    -------
    int
        Index of the skin.
    """
    first = len(document.nodes)
    world: list[np.ndarray] = []
    for index, bone in enumerate(skeleton.bones):
        local = _local(bone)
        world.append(local if bone.parent < 0 else local @ world[bone.parent])
        node: dict[str, Any] = {
            'name': bone.name,
            'rotation': _quaternion(local[:3, :3]).tolist(),
            'translation': local[3, :3].tolist()
        }
        if children := [
                first + child for child, other in enumerate(skeleton.bones) if other.parent == index
        ]:
            node['children'] = children
        document.nodes.append(node)
    # A row-vector matrix written row by row is the column-vector matrix written column by column,
    # the order glTF reads.
    inverse = np.linalg.inv(np.array(world))
    # glTF requires the projective terms to be exact, and inversion adds rounding noise to them.
    inverse[:, :, 3] = (0.0, 0.0, 0.0, 1.0)
    payload = inverse.astype('<f4').tobytes()
    document.skins.append({
        'extras': {
            'note': note
        },
        'inverseBindMatrices':
            document.accessor(payload, componentType=FLOAT, count=len(inverse), type='MAT4'),
        'joints':
            list(range(first, first + len(world))),
        'name':
            skeleton.name.rsplit('/', 1)[-1],
        'skeleton':
            first
    })
    return len(document.skins) - 1


def _multiply(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """
    Multiply one quaternion by each of several.

    Parameters
    ----------
    left : numpy.ndarray
        The quaternion ``(x, y, z, w)`` on the left.
    right : numpy.ndarray
        The quaternions on the right, ``(n, 4)``.

    Returns
    -------
    numpy.ndarray
        The Hamilton products, ``(n, 4)``.
    """
    ax, ay, az, aw = left
    bx, by, bz, bw = right.T
    return np.stack((aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz),
                    axis=1)


def _rotations(rest: np.ndarray, keys: np.ndarray) -> np.ndarray:
    """
    Turn a track's rotation keys into a glTF rotation output.

    Parameters
    ----------
    rest : numpy.ndarray
        The bone's bind rotation in glTF's basis.
    keys : numpy.ndarray
        The stored keys, ``(n, 4)``.

    Returns
    -------
    numpy.ndarray
        Unit quaternions, each in the hemisphere of the one before it, ``(n, 4)``.
    """
    turned = keys[:, (0, 2, 1, 3)] * (1.0, 1.0, -1.0, 1.0)
    out = _multiply(rest, turned)
    out /= np.linalg.norm(out, axis=1, keepdims=True)
    signs = np.where(np.sum(out[1:] * out[:-1], axis=1) < 0, -1.0, 1.0)
    out[1:] *= np.cumprod(signs)[:, None]
    return out


def add_animations(document: GLBDocument, skeleton: Skeleton, skin: int,
                   clips: Iterable[Clip]) -> int:
    """
    Add every clip that binds to a skeleton as a glTF animation of its skin.

    A key's time is its frame divided by the clip's rate. Rotations are written as normalised
    16-bit integers, half the size of floats and finer than the game's eleven bits of mantissa. A
    track whose keys are all the same is written as one key. A track storing rotations only also has
    a constant offset from the bind translation, and the offset is written as a translation channel
    when it exceeds a thousandth of an inch. Most are a few millionths, rounding noise from the
    cooker. Each clip's keys share one buffer view. Where two tracks drive the same bone, as
    ``!BONE_03`` and ``!Bone_03`` do in one rope clip, the first is used.

    Parameters
    ----------
    document : GLBDocument
        GLB under construction.
    skeleton : Skeleton
        The skeleton the skin was built from.
    skin : int
        Index of the skin.
    clips : Iterable[Clip]
        The candidates. Those :py:func:`binds` rejects are skipped.

    Returns
    -------
    int
        Number of animations added.
    """
    joints = document.skins[skin]['joints']
    by_hash = {bone.name_hash: index for index, bone in enumerate(skeleton.bones)}
    rests = [(_quaternion(local[:3, :3]), local[3, :3])
             for local in (_local(bone) for bone in skeleton.bones)]
    added = 0
    for clip in clips:
        if not binds(clip, skeleton):
            continue
        rate = clip.rate or 1
        blob = bytearray()
        created: list[dict[str, Any]] = []
        times: dict[bytes, int] = {}
        samplers: list[dict[str, Any]] = []
        channels: list[dict[str, Any]] = []
        driven: set[int] = set()
        for track in clip.tracks:
            if not len(track.frames):
                continue
            if (bone := by_hash[track.bone_hash]) in driven:
                log.debug('Skipping a second track for `%s` in `%s`.', track.bone, clip.name)
                continue
            driven.add(bone)
            still = bool(
                np.all(track.rotations == track.rotations[0]) and
                (track.translations is None or np.all(track.translations == track.translations[0])))
            count = 1 if still else len(track.frames)
            frames = track.frames[:count]
            if (key := frames.tobytes()) not in times:
                seconds = (frames / rate).astype('<f4')
                times[key] = _store(document,
                                    blob,
                                    created,
                                    seconds.tobytes(),
                                    componentType=FLOAT,
                                    count=count,
                                    max=[float(seconds.max())],
                                    min=[float(seconds.min())],
                                    type='SCALAR')
            for path, output in _track_outputs(document, blob, created, track, count, rests[bone]):
                samplers.append({'input': times[key], 'interpolation': 'LINEAR', 'output': output})
                channels.append({
                    'sampler': len(samplers) - 1,
                    'target': {
                        'node': joints[bone],
                        'path': path
                    }
                })
        if channels:
            view = document.add_view(bytes(blob))
            for accessor in created:
                accessor['bufferView'] = view
            document.animations.append({
                'channels': channels,
                'name': clip.name.rsplit('/', 1)[-1],
                'samplers': samplers
            })
            added += 1
    return added


def _track_outputs(document: GLBDocument, blob: bytearray, created: list[dict[str, Any]],
                   track: Track, count: int, rest: tuple[np.ndarray,
                                                         np.ndarray]) -> list[tuple[str, int]]:
    """
    Add the sampler outputs of one track.

    Parameters
    ----------
    document : GLBDocument
        GLB under construction.
    blob : bytearray
        The clip's buffer, extended in place.
    created : list[dict[str, Any]]
        The clip's accessors, extended in place.
    track : Track
        The track.
    count : int
        How many of its keys to write.
    rest : tuple[numpy.ndarray, numpy.ndarray]
        The bone's bind rotation and translation in glTF's basis.

    Returns
    -------
    list[tuple[str, int]]
        Each animated path with its output accessor.
    """
    rest_rotation, rest_translation = rest
    rotations = np.round(_rotations(rest_rotation, track.rotations[:count]) * _SHORT_SCALE)
    outputs = [('rotation',
                _store(document,
                       blob,
                       created,
                       rotations.astype('<i2').tobytes(),
                       componentType=_SHORT,
                       count=count,
                       normalized=True,
                       type='VEC4'))]
    if track.translations is not None:
        moved: np.ndarray | None = track.translations[:count]
    elif np.abs(track.offset).max() > _OFFSET_TOLERANCE:
        moved = np.repeat([track.offset], count, axis=0)
    else:
        moved = None
    if moved is not None:
        outputs.append(
            ('translation',
             _store(
                 document,
                 blob,
                 created,
                 (rest_translation + moved[:,
                                           (0, 2, 1)] * (1.0, 1.0, -1.0)).astype('<f4').tobytes(),
                 componentType=FLOAT,
                 count=count,
                 type='VEC3')))
    return outputs


def _store(document: GLBDocument, blob: bytearray, created: list[dict[str, Any]], payload: bytes,
           **fields: Any) -> int:
    """
    Append keyframe data to a clip's buffer and describe it with an accessor.

    The accessor's buffer view is filled in once the clip's buffer is complete.

    Parameters
    ----------
    document : GLBDocument
        GLB under construction.
    blob : bytearray
        The clip's buffer, extended in place.
    created : list[dict[str, Any]]
        The clip's accessors, extended in place.
    payload : bytes
        The data, a whole number of words long.
    fields : Any
        Remaining accessor fields, such as ``componentType``, ``count`` and ``type``.

    Returns
    -------
    int
        Index into the document's accessors.
    """
    created.append({'byteOffset': len(blob), **fields})
    blob.extend(payload)
    document.accessors.append(created[-1])
    return len(document.accessors) - 1
