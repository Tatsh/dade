"""
Skeletons of Mario Kart World BFRES v10 models, and the glTF skins built from them.

A bone stores its rest pose as scale, rotation, and translation relative to its parent. The rotation
is Euler angles in radians when the skeleton flags mark it, applied about X, then Y, then Z, and a
quaternion otherwise. The inverse bind matrices of the file are the inverses of the world matrices
built from the rest poses.

A shape binds to the skeleton in one of three ways. With no influences, every vertex follows the
bone of the shape and is stored in the space of the bone. Otherwise each vertex identifies entries
of the skeleton's matrix table. An entry below the smooth count is a smooth matrix, the vertex is
stored in model space, and its weights blend the bones. An entry at or past the smooth count is a
rigid matrix, and the vertex is stored in the space of its single bone.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple
import struct

import numpy as np

from dade.common.gltf import ARRAY_BUFFER, FLOAT, UNSIGNED_SHORT

from .animation import sample_curve

if TYPE_CHECKING:
    from collections.abc import Iterable

    from dade.common.gltf import GLBDocument

__all__ = ('FRAMES_PER_SECOND', 'Binding', 'Skeleton', 'add_animations', 'add_skin', 'bind_shape',
           'joint_accessors', 'read_skeleton')

_BONE_SIZE = 0x58
_EULER = 0x1000
_MAX_BONES = 0x400
_INFLUENCES = 4
_WEIGHT_SCALE = 255.0
_IDENTITY = np.array((0.0, 0.0, 0.0, 1.0))
FRAMES_PER_SECOND = 60.0
"""The rate the frames of an animation are played at, in frames a second.

:meta hide-value:
"""
_PATHS = (('scale', 'scale', 3), ('rotation', 'rotate', 4), ('translation', 'translate', 3))


class Skeleton(NamedTuple):
    """Bones of a model at rest."""

    names: tuple[str, ...]
    """Name of each bone."""
    parents: tuple[int, ...]
    """Index of each bone's parent, or -1 for a root."""
    scales: np.ndarray
    """Scale of each bone relative to its parent, ``(n, 3)``."""
    rotations: np.ndarray
    """Rotation of each bone relative to its parent as a quaternion ``(x, y, z, w)``, ``(n, 4)``."""
    translations: np.ndarray
    """Translation of each bone relative to its parent, ``(n, 3)``."""
    world: np.ndarray
    """World matrix of each bone at rest, ``(n, 4, 4)``."""
    matrices: tuple[int, ...]
    """Bone of each entry of the matrix table, the smooth entries first."""
    smooth_count: int
    """Number of smooth entries in the matrix table."""


class Binding(NamedTuple):
    """Vertices of a shape in model space, with the bones that move them."""

    positions: np.ndarray
    """Positions at rest in model space, ``(n, 3)``."""
    normals: np.ndarray | None
    """Normals in model space, ``(n, 3)``, or :py:obj:`None` when the shape has none."""
    joints: np.ndarray
    """Up to four bones for each vertex, ``(n, 4)``."""
    weights: np.ndarray
    """Weight of each bone in ``joints``, summing to 1, ``(n, 4)``."""


def _u16(data: bytes, offset: int) -> int:
    return int(struct.unpack_from('<H', data, offset)[0])


def _u64(data: bytes, offset: int) -> int:
    return int(struct.unpack_from('<Q', data, offset)[0])


def _string(data: bytes, pointer: int) -> str:
    length = _u16(data, pointer)
    return data[pointer + 2:pointer + 2 + length].decode('utf-8', 'replace')


def _euler_matrix(x: float, y: float, z: float) -> np.ndarray:
    cx, sx, cy, sy, cz, sz = np.cos(x), np.sin(x), np.cos(y), np.sin(y), np.cos(z), np.sin(z)
    rotate_x = np.array(((1, 0, 0), (0, cx, -sx), (0, sx, cx)))
    rotate_y = np.array(((cy, 0, sy), (0, 1, 0), (-sy, 0, cy)))
    rotate_z = np.array(((cz, -sz, 0), (sz, cz, 0), (0, 0, 1)))
    result: np.ndarray = rotate_z @ rotate_y @ rotate_x
    return result


def _quaternion_matrix(x: float, y: float, z: float, w: float) -> np.ndarray:
    return np.array(((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
                     (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
                     (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y))))


def _matrix_quaternion(matrix: np.ndarray) -> tuple[float, float, float, float]:
    trace = float(np.trace(matrix))
    if trace > 0:
        s = 2.0 * np.sqrt(trace + 1.0)
        quaternion = ((matrix[2, 1] - matrix[1, 2]) / s, (matrix[0, 2] - matrix[2, 0]) / s,
                      (matrix[1, 0] - matrix[0, 1]) / s, s / 4)
    else:
        axis = int(np.argmax(np.diag(matrix)))
        i, j, k = axis, (axis + 1) % 3, (axis + 2) % 3
        s = 2.0 * np.sqrt(1.0 + matrix[i, i] - matrix[j, j] - matrix[k, k])
        values = [0.0, 0.0, 0.0, 0.0]
        values[i] = s / 4
        values[j] = (matrix[j, i] + matrix[i, j]) / s
        values[k] = (matrix[k, i] + matrix[i, k]) / s
        values[3] = (matrix[k, j] - matrix[j, k]) / s
        quaternion = (values[0], values[1], values[2], values[3])
    norm = float(np.linalg.norm(quaternion))
    return (quaternion[0] / norm, quaternion[1] / norm, quaternion[2] / norm, quaternion[3] / norm)


def read_skeleton(data: bytes, model: int) -> Skeleton | None:
    """
    Read the skeleton of a model.

    Parameters
    ----------
    data : bytes
        Decompressed BFRES archive.
    model : int
        Offset of the ``FMDL`` block.

    Returns
    -------
    Skeleton | None
        The skeleton, or :py:obj:`None` when the model has none.

    Raises
    ------
    ValueError
        The skeleton has a bone count, a parent index, or a matrix table entry out of range.
    """
    skeleton = _u64(data, model + 0x18)
    if not 0 < skeleton < len(data) - 0x40 or data[skeleton:skeleton + 4] != b'FSKL':
        return None
    euler = bool(struct.unpack_from('<I', data, skeleton + 4)[0] & _EULER)
    count, smooth, rigid = struct.unpack_from('<HHH', data, skeleton + 0x38)
    bones = _u64(data, skeleton + 0x10)
    if not 0 < count <= _MAX_BONES or bones + count * _BONE_SIZE > len(data):
        message = 'Invalid BFRES skeleton.'
        raise ValueError(message)
    matrices = struct.unpack_from(f'<{smooth + rigid}H', data, _u64(data, skeleton + 0x18))
    names, parents = [], []
    scales = np.zeros((count, 3))
    rotations = np.zeros((count, 4))
    translations = np.zeros((count, 3))
    world = np.zeros((count, 4, 4))
    for index in range(count):
        bone = bones + index * _BONE_SIZE
        parent = struct.unpack_from('<h', data, bone + 0x22)[0]
        if parent >= index:
            message = 'Invalid BFRES bone parent.'
            raise ValueError(message)
        scale = struct.unpack_from('<3f', data, bone + 0x30)
        rotation = struct.unpack_from('<4f', data, bone + 0x3C)
        rotation_matrix = (_euler_matrix(*rotation[:3]) if euler else _quaternion_matrix(*rotation))
        local = np.eye(4)
        local[:3, :3] = rotation_matrix * scale
        local[:3, 3] = struct.unpack_from('<3f', data, bone + 0x4C)
        names.append(_string(data, _u64(data, bone)))
        parents.append(parent)
        scales[index] = scale
        rotations[index] = _matrix_quaternion(rotation_matrix)
        translations[index] = local[:3, 3]
        world[index] = world[parent] @ local if parent >= 0 else local
    if any(bone >= count for bone in matrices):
        message = 'Invalid BFRES skeleton matrix table.'
        raise ValueError(message)
    return Skeleton(tuple(names), tuple(parents), scales, rotations, translations, world,
                    tuple(matrices), smooth)


def bind_shape(skeleton: Skeleton, positions: np.ndarray, normals: np.ndarray | None,
               indices: np.ndarray | None, weights: np.ndarray | None, shape_bone: int) -> Binding:
    """
    Transform the vertices of a shape to model space and assign bones to each vertex.

    Parameters
    ----------
    skeleton : Skeleton
        The skeleton of the model.
    positions : numpy.ndarray
        Positions as stored, ``(n, 3)``.
    normals : numpy.ndarray | None
        Normals as stored, ``(n, 3)``, or :py:obj:`None`.
    indices : numpy.ndarray | None
        Matrix table entries for each vertex, ``(n, k)``, or :py:obj:`None` for a shape with no
        influences.
    weights : numpy.ndarray | None
        Weights from 0 to 255 for each entry, ``(n, k)``, or :py:obj:`None` for one influence a
        vertex.
    shape_bone : int
        Bone of the shape, which every vertex follows when the shape has no influences.

    Returns
    -------
    Binding
        The vertices in model space and their bones.
    """
    count = len(positions)
    joints = np.zeros((count, _INFLUENCES), dtype=np.uint16)
    blend = np.zeros((count, _INFLUENCES))
    if indices is None:
        local = np.full(count, shape_bone)
        joints[:, 0] = shape_bone
        blend[:, 0] = 1.0
    else:
        table = np.asarray(skeleton.matrices)
        used = min(indices.shape[1], _INFLUENCES)
        joints[:, :used] = table[indices[:, :used]]
        if weights is None or indices.shape[1] == 1:
            blend[:, 0] = 1.0
        else:
            blend[:, :used] = weights[:, :used] / _WEIGHT_SCALE
        rigid = indices[:, 0] >= skeleton.smooth_count
        local = np.where(rigid, joints[:, 0].astype(np.int64), -1)
    totals = blend.sum(axis=1, keepdims=True)
    blend = np.divide(blend, totals, out=np.zeros_like(blend), where=totals > 0)
    blend[totals[:, 0] == 0, 0] = 1.0
    joints[blend == 0] = 0
    moved = positions.astype(np.float64)
    turned = None if normals is None else normals.astype(np.float64)
    for bone in np.unique(local[local >= 0]):
        rows = local == bone
        matrix = skeleton.world[bone]
        moved[rows] = moved[rows] @ matrix[:3, :3].T + matrix[:3, 3]
        if turned is not None:
            turned[rows] = np.matmul(turned[rows], matrix[:3, :3].T)
    if turned is not None:
        lengths = np.linalg.norm(turned, axis=1, keepdims=True)
        turned = np.divide(turned, lengths, out=np.zeros_like(turned), where=lengths > 0)
    return Binding(moved, turned, joints, blend)


def add_skin(document: GLBDocument, skeleton: Skeleton) -> int:
    """
    Add the bones of a skeleton as nodes, and a skin over them.

    Parameters
    ----------
    document : GLBDocument
        GLB under construction.
    skeleton : Skeleton
        The skeleton.

    Returns
    -------
    int
        Index of the skin.
    """
    first = len(document.nodes)
    for index, name in enumerate(skeleton.names):
        node: dict[str, object] = {
            'name': name,
            'rotation': skeleton.rotations[index].tolist(),
            'scale': skeleton.scales[index].tolist(),
            'translation': skeleton.translations[index].tolist()
        }
        children = [
            first + child for child, parent in enumerate(skeleton.parents) if parent == index
        ]
        if children:
            node['children'] = children
        document.nodes.append(node)
    inverse = np.linalg.inv(skeleton.world)
    payload = b''.join(struct.pack('<16f', *matrix.T.reshape(16)) for matrix in inverse)
    accessor = document.accessor(payload, componentType=FLOAT, count=len(inverse), type='MAT4')
    roots = [first + index for index, parent in enumerate(skeleton.parents) if parent < 0]
    document.skins.append({
        'inverseBindMatrices': accessor,
        'joints': list(range(first, first + len(skeleton.names))),
        'skeleton': roots[0]
    })
    return len(document.skins) - 1


def joint_accessors(document: GLBDocument, binding: Binding) -> tuple[int, int]:
    """
    Add the ``JOINTS_0`` and ``WEIGHTS_0`` accessors of a bound shape.

    Parameters
    ----------
    document : GLBDocument
        GLB under construction.
    binding : Binding
        The shape's binding.

    Returns
    -------
    tuple[int, int]
        Indices of the joints accessor and the weights accessor.
    """
    count = len(binding.joints)
    joints = document.accessor(binding.joints.astype('<u2').tobytes(),
                               ARRAY_BUFFER,
                               componentType=UNSIGNED_SHORT,
                               count=count,
                               type='VEC4')
    weights = document.floats(binding.weights.astype(np.float32).tolist(),
                              'VEC4',
                              target=ARRAY_BUFFER)
    return joints, weights


def _channel(bone: dict[str, Any], kind: str, base: str, rest: np.ndarray,
             frames: np.ndarray) -> np.ndarray:
    curves = {curve['channel']: curve for curve in bone['curves'] if 'keys' in curve}
    stored = bone['base'].get(base)
    columns = []
    for axis in range(len(rest)):
        if (curve := curves.get(f'{kind}.{"xyzw"[axis]}')) is not None:
            columns.append([sample_curve(curve['keys'], float(frame)) for frame in frames])
        else:
            columns.append([stored[axis] if stored is not None else rest[axis]] * len(frames))
    return np.array(columns, dtype=np.float64).T


def _rotations(values: np.ndarray, *, euler: bool) -> np.ndarray:
    quaternions = np.array([
        _matrix_quaternion(_euler_matrix(*row[:3])) if euler else
        (row / np.linalg.norm(row) if np.linalg.norm(row) > 0 else _IDENTITY) for row in values
    ])
    for index in range(1, len(quaternions)):
        if np.dot(quaternions[index], quaternions[index - 1]) < 0:
            quaternions[index] = -quaternions[index]
    return quaternions


def add_animations(document: GLBDocument, skeleton: Skeleton, skin: int,
                   clips: Iterable[tuple[str, dict[str, Any]]]) -> int:
    """
    Add skeletal animation clips to the joints of a skin.

    A clip drives each joint whose bone name matches one of its bone animations, and the other
    joints remain at rest. Each animated joint has its scale, rotation, and translation sampled at
    every frame of the clip at :py:data:`FRAMES_PER_SECOND`. A channel without a curve takes the
    clip's base value, or the rest pose when the clip records no base value. A clip that drives no
    joint of the skin is not added.

    Parameters
    ----------
    document : GLBDocument
        GLB under construction.
    skeleton : Skeleton
        The skeleton the skin was built from.
    skin : int
        Index of the skin.
    clips : collections.abc.Iterable[tuple[str, dict[str, Any]]]
        Each clip with the name to give its glTF animation, as
        :py:func:`dade.mkw.animation.read_animations` reports clips.

    Returns
    -------
    int
        Number of animations added.
    """
    joints = dict(zip(skeleton.names, document.skins[skin]['joints'], strict=True))
    added = 0
    for name, clip in clips:
        frames = np.arange(max(int(clip['frame_count']), 0) + 1, dtype=np.float64)
        times: int | None = None
        samplers: list[dict[str, Any]] = []
        channels: list[dict[str, Any]] = []
        euler = clip['rotation'] == 'euler-xyz'
        for bone in clip['bones']:
            if (node := joints.get(bone['name'])) is None:
                continue
            index = skeleton.names.index(bone['name'])
            rests = {
                'scale': skeleton.scales[index],
                'rotate': (_quaternion_xyz(skeleton.rotations[index])
                           if euler else skeleton.rotations[index]),
                'translate': skeleton.translations[index]
            }
            for path, kind, width in _PATHS:
                rest = np.asarray(rests[kind], dtype=np.float64)[:width]
                if euler and kind == 'rotate':
                    rest = np.append(rest[:3], 1.0)
                values = _channel(bone, kind, path, rest, frames)
                if kind == 'rotate':
                    values = _rotations(values, euler=euler)
                if times is None:
                    times = document.floats(
                        [(float(frame / FRAMES_PER_SECOND),) for frame in frames],
                        'SCALAR',
                        bounds=True)
                samplers.append({
                    'input':
                        times,
                    'interpolation':
                        'LINEAR',
                    'output':
                        document.floats(
                            values.astype(np.float32).tolist(),
                            'VEC4' if kind == 'rotate' else 'VEC3')
                })
                channels.append({
                    'sampler': len(samplers) - 1,
                    'target': {
                        'node': node,
                        'path': path
                    }
                })
        if channels:
            document.animations.append({'channels': channels, 'name': name, 'samplers': samplers})
            added += 1
    return added


def _quaternion_xyz(quaternion: np.ndarray) -> np.ndarray:
    matrix = _quaternion_matrix(*quaternion.tolist())
    return np.array((float(np.arctan2(matrix[2, 1], matrix[2, 2])),
                     float(np.arcsin(np.clip(-matrix[2, 0], -1.0,
                                             1.0))), float(np.arctan2(matrix[1, 0], matrix[0, 0]))))
