"""Tests for Mario Kart World skeletons and skins."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple
import math
import struct

import numpy as np
import pytest

from dade.common.gltf import GLBDocument
from dade.mkw.skeleton import (
    FRAMES_PER_SECOND,
    add_animations,
    add_skin,
    bind_shape,
    joint_accessors,
    read_skeleton,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dade.mkw.skeleton import Skeleton

FSKL = 0x100
BONES = 0x200
MATRICES = 0x500
NAMES = 0x600


class Bone(NamedTuple):
    """A bone record to write into a synthetic skeleton."""

    name: str
    """Name of the bone."""
    parent: int
    """Index of the parent bone, or -1 for a root."""
    scale: tuple[float, float, float]
    """Scale relative to the parent."""
    rotation: tuple[float, float, float, float]
    """Quaternion, or Euler angles in radians followed by an unused value."""
    translation: tuple[float, float, float]
    """Translation relative to the parent."""


def _archive(bones: Sequence[Bone],
             matrices: Sequence[int],
             smooth: int,
             *,
             flags: int = 0,
             count: int | None = None) -> bytes:
    data = bytearray(0x1000)
    data[0x10:0x14] = b'FMDL'
    struct.pack_into('<Q', data, 0x28, FSKL)
    data[FSKL:FSKL + 4] = b'FSKL'
    struct.pack_into('<I', data, FSKL + 4, flags)
    struct.pack_into('<QQ', data, FSKL + 0x10, BONES, MATRICES)
    struct.pack_into('<HHH', data, FSKL + 0x38,
                     len(bones) if count is None else count, smooth,
                     len(matrices) - smooth)
    struct.pack_into(f'<{len(matrices)}H', data, MATRICES, *matrices)
    for index, bone in enumerate(bones):
        offset = BONES + index * 0x58
        name = NAMES + index * 0x20
        struct.pack_into('<Q', data, offset, name)
        struct.pack_into(f'<H{len(bone.name)}s', data, name, len(bone.name), bone.name.encode())
        struct.pack_into('<h', data, offset + 0x22, bone.parent)
        struct.pack_into('<3f4f3f', data, offset + 0x30, *bone.scale, *bone.rotation,
                         *bone.translation)
    return bytes(data)


def _rotation_x(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array(((1, 0, 0), (0, c, -s), (0, s, c)))


def _rotation_y(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array(((c, 0, s), (0, 1, 0), (-s, 0, c)))


def _rotation_z(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array(((c, -s, 0), (s, c, 0), (0, 0, 1)))


def _transform(rotation: np.ndarray, scale: Sequence[float],
               translation: Sequence[float]) -> np.ndarray:
    matrix = np.eye(4)
    matrix[:3, :3] = rotation @ np.diag(scale)
    matrix[:3, 3] = translation
    return matrix


def _quaternion_rotation(quaternion: Sequence[float]) -> np.ndarray:
    x, y, z, w = quaternion
    return np.array(((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
                     (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
                     (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y))))


REST = Bone('Root', -1, (1, 1, 1), (0, 0, 0, 1), (0, 0, 0))
ROOT = REST._replace(translation=(1, 2, 3))
ARM = Bone('Arm', 0, (2, 2, 2), (0, 0, math.sqrt(0.5), math.sqrt(0.5)), (1, 0, 0))


def _chain() -> Skeleton:
    skeleton = read_skeleton(_archive((ROOT, ARM), (0, 1), 1), 0x10)
    assert skeleton is not None
    return skeleton


def test_read_skeleton_quaternion_world() -> None:
    skeleton = _chain()
    root = _transform(np.eye(3), (1, 1, 1), (1, 2, 3))
    arm = root @ _transform(_rotation_z(math.pi / 2), (2, 2, 2), (1, 0, 0))
    assert skeleton.names == ('Root', 'Arm')
    assert skeleton.parents == (-1, 0)
    assert skeleton.matrices == (0, 1)
    assert skeleton.smooth_count == 1
    np.testing.assert_allclose(skeleton.world, np.stack((root, arm)), atol=1e-6)
    np.testing.assert_allclose(np.linalg.inv(skeleton.world[1]), np.linalg.inv(arm), atol=1e-6)
    np.testing.assert_allclose(skeleton.translations, ((1, 2, 3), (1, 0, 0)))
    np.testing.assert_allclose(skeleton.scales, ((1, 1, 1), (2, 2, 2)))


@pytest.mark.parametrize('angles', [(0.1, 0.2, 0.3), (math.pi, 0, 0), (0, math.pi, 0),
                                    (0, 0, math.pi), (0.0, 0.0, 0.0)])
def test_read_skeleton_euler_rotation(angles: tuple[float, float, float]) -> None:
    bone = REST._replace(rotation=(*angles, 0))
    skeleton = read_skeleton(_archive((bone,), (0,), 1, flags=0x1000), 0x10)
    assert skeleton is not None
    expected = _rotation_z(angles[2]) @ _rotation_y(angles[1]) @ _rotation_x(angles[0])
    np.testing.assert_allclose(skeleton.world[0][:3, :3], expected, atol=1e-6)
    np.testing.assert_allclose(_quaternion_rotation(skeleton.rotations[0]), expected, atol=1e-6)
    assert math.isclose(float(np.linalg.norm(skeleton.rotations[0])), 1.0)


@pytest.mark.parametrize('pointer', [0, 0xFC0, FSKL])
def test_read_skeleton_returns_none_without_skeleton(pointer: int) -> None:
    data = bytearray(_archive((REST,), (0,), 1))
    struct.pack_into('<Q', data, 0x28, pointer)
    if pointer == FSKL:
        data[FSKL:FSKL + 4] = b'FSKA'
    assert read_skeleton(bytes(data), 0x10) is None


@pytest.mark.parametrize('count', [0, 0x401, 50])
def test_read_skeleton_rejects_bone_count(count: int) -> None:
    with pytest.raises(ValueError, match='Invalid BFRES skeleton'):
        read_skeleton(_archive((REST,), (0,), 1, count=count), 0x10)


@pytest.mark.parametrize('parent', [1, 2])
def test_read_skeleton_rejects_bad_parent(parent: int) -> None:
    with pytest.raises(ValueError, match='bone parent'):
        read_skeleton(_archive((REST, REST._replace(name='Child', parent=parent)), (0,), 1), 0x10)


def test_read_skeleton_rejects_bad_matrix_table() -> None:
    with pytest.raises(ValueError, match='matrix table'):
        read_skeleton(_archive((REST,), (0, 1), 1), 0x10)


def test_bind_shape_without_influences_follows_shape_bone() -> None:
    skeleton = _chain()
    binding = bind_shape(skeleton, np.array(((1.0, 0.0, 0.0), (0.0, 0.0, 1.0))),
                         np.array(((1.0, 0.0, 0.0), (0.0, 0.0, 0.0))), None, None, 1)
    np.testing.assert_allclose(binding.positions, ((2, 4, 3), (2, 2, 5)), atol=1e-6)
    assert binding.normals is not None
    np.testing.assert_allclose(binding.normals, ((0, 1, 0), (0, 0, 0)), atol=1e-6)
    np.testing.assert_array_equal(binding.joints, ((1, 0, 0, 0), (1, 0, 0, 0)))
    np.testing.assert_array_equal(binding.weights, ((1, 0, 0, 0), (1, 0, 0, 0)))


def test_bind_shape_smooth_and_rigid_entries() -> None:
    skeleton = _chain()
    positions = np.array(((1.0, 0.0, 0.0), (1.0, 0.0, 0.0)))
    binding = bind_shape(skeleton, positions, None, np.array(((0, 1), (1, 0))),
                         np.array(((200, 55), (255, 0))), 0)
    assert binding.normals is None
    np.testing.assert_allclose(binding.positions, ((1, 0, 0), (2, 4, 3)), atol=1e-6)
    np.testing.assert_array_equal(binding.joints, ((0, 1, 0, 0), (1, 0, 0, 0)))
    np.testing.assert_allclose(binding.weights, ((200 / 255, 55 / 255, 0, 0), (1, 0, 0, 0)))
    np.testing.assert_allclose(binding.weights.sum(axis=1), (1, 1))


def test_bind_shape_normalises_weights_and_limits_influences() -> None:
    skeleton = _chain()
    binding = bind_shape(skeleton, np.zeros((2, 3)), None, np.zeros((2, 5), dtype=np.int64),
                         np.array(((10, 10, 10, 10, 200), (0, 0, 0, 0, 0))), 0)
    np.testing.assert_allclose(binding.weights, ((0.25, 0.25, 0.25, 0.25), (1, 0, 0, 0)))
    assert binding.joints.shape == (2, 4)


@pytest.mark.parametrize('weights', [None, np.array(((100,), (5,)))])
def test_bind_shape_single_or_unweighted_influence(weights: np.ndarray | None) -> None:
    skeleton = _chain()
    indices = np.array(((0,), (0,))) if weights is not None else np.array(((0, 0), (0, 0)))
    binding = bind_shape(skeleton, np.zeros((2, 3)), None, indices, weights, 0)
    np.testing.assert_array_equal(binding.weights, ((1, 0, 0, 0), (1, 0, 0, 0)))


def _payload(document: GLBDocument, accessor: int) -> bytes:
    view = document.views[document.accessors[accessor]['bufferView']]
    return bytes(document.blob[view['byteOffset']:view['byteOffset'] + view['byteLength']])


def test_add_skin_builds_bone_nodes_and_inverse_bind_matrices() -> None:
    skeleton = _chain()
    document = GLBDocument()
    document.nodes.append({'name': 'existing'})
    assert add_skin(document, skeleton) == 0
    root, arm = document.nodes[1:]
    assert root['name'] == 'Root'
    assert root['children'] == [2]
    assert 'children' not in arm
    assert arm['translation'] == [1.0, 0.0, 0.0]
    assert arm['scale'] == [2.0, 2.0, 2.0]
    np.testing.assert_allclose(arm['rotation'], (0, 0, math.sqrt(0.5), math.sqrt(0.5)), atol=1e-6)
    skin = document.skins[0]
    assert skin['joints'] == [1, 2]
    assert skin['skeleton'] == 1
    accessor = document.accessors[skin['inverseBindMatrices']]
    assert accessor['type'] == 'MAT4'
    assert accessor['count'] == 2
    matrices = np.frombuffer(_payload(document, skin['inverseBindMatrices']), '<f4').reshape(
        2, 4, 4).transpose(0, 2, 1)
    expected = np.linalg.inv(
        _transform(np.eye(3), (1, 1, 1), (1, 2, 3)) @ _transform(_rotation_z(math.pi / 2),
                                                                 (2, 2, 2), (1, 0, 0)))
    np.testing.assert_allclose(matrices[1], expected, atol=1e-6)
    np.testing.assert_allclose(matrices[0] @ skeleton.world[0], np.eye(4), atol=1e-6)


def test_joint_accessors_write_vec4_data() -> None:
    binding = bind_shape(_chain(), np.zeros((2, 3)), None, np.array(((0, 1), (1, 0))),
                         np.array(((128, 127), (255, 0))), 0)
    document = GLBDocument()
    joints, weights = joint_accessors(document, binding)
    assert document.accessors[joints]['componentType'] == 5123
    assert document.accessors[joints]['type'] == 'VEC4'
    assert document.accessors[weights]['type'] == 'VEC4'
    assert np.frombuffer(_payload(document, joints), '<u2').tolist() == [0, 1, 0, 0, 1, 0, 0, 0]
    np.testing.assert_allclose(np.frombuffer(_payload(document, weights),
                                             '<f4').reshape(2, 4).sum(axis=1), (1, 1),
                               rtol=1e-6)


def _keys(*values: float) -> list[dict[str, float]]:
    return [{
        'frame': float(frame),
        'slope': 0.0,
        'value': value
    } for frame, value in enumerate(values)]


def _values(document: GLBDocument, accessor: int) -> np.ndarray:
    return np.frombuffer(_payload(document, accessor), '<f4').reshape(
        document.accessors[accessor]['count'], -1)


def _skinned() -> tuple[GLBDocument, Skeleton]:
    skeleton = _chain()
    document = GLBDocument()
    document.nodes.append({'name': 'existing'})
    add_skin(document, skeleton)
    return document, skeleton


def _sampled(document: GLBDocument, animation: dict[str, Any]) -> dict[tuple[int, str], np.ndarray]:
    return {
        (channel['target']['node'], channel['target']['path']):
            _values(document, animation['samplers'][channel['sampler']]['output'])
        for channel in animation['channels']
    }


def test_add_animations_samples_quaternion_clip() -> None:
    document, skeleton = _skinned()
    clip = {
        'bones': [{
            'base': {
                'rotation': [0.0, 0.0, 0.0, 0.0],
                'translation': [4.0, 5.0, 6.0]
            },
            'curves': [{
                'channel': 'translate.x',
                'keys': _keys(0.0, 1.0, 2.0)
            }, {
                'channel': 'rotate.z',
                'keys': _keys(0.0, 0.6, 0.0)
            }, {
                'channel': 'rotate.w',
                'keys': _keys(1.0, -0.8, -2.0)
            }, {
                'channel': 'scale.x',
                'keys_raw': [9.0]
            }],
            'name': 'Arm'
        }, {
            'base': {},
            'curves': [],
            'name': 'Missing'
        }],
        'frame_count': 2,
        'rotation': 'quaternion'
    }
    assert add_animations(document, skeleton, 0, [('Wave', clip)]) == 1
    animation = document.animations[0]
    assert animation['name'] == 'Wave'
    assert [channel['target'] for channel in animation['channels']] == [{
        'node': 2,
        'path': 'scale'
    }, {
        'node': 2,
        'path': 'rotation'
    }, {
        'node': 2,
        'path': 'translation'
    }]
    assert {sampler['interpolation'] for sampler in animation['samplers']} == {'LINEAR'}
    times = animation['samplers'][0]['input']
    assert {sampler['input'] for sampler in animation['samplers']} == {times}
    np.testing.assert_allclose(_values(document, times)[:, 0],
                               np.arange(3) / FRAMES_PER_SECOND,
                               rtol=1e-6)
    assert document.accessors[times]['min'] == [0.0]
    assert document.accessors[times]['max'] == pytest.approx([2 / FRAMES_PER_SECOND])
    sampled = _sampled(document, animation)
    np.testing.assert_allclose(sampled[2, 'scale'], [(2, 2, 2)] * 3)
    np.testing.assert_allclose(sampled[2, 'translation'], ((0, 5, 6), (1, 5, 6), (2, 5, 6)),
                               atol=1e-6)
    np.testing.assert_allclose(sampled[2, 'rotation'],
                               ((0, 0, 0, 1), (0, 0, -0.6, 0.8), (0, 0, 0, 1)),
                               atol=1e-6)


def test_add_animations_uses_rest_pose_without_base() -> None:
    document, skeleton = _skinned()
    clip = {
        'bones': [{
            'base': {},
            'curves': [],
            'name': 'Arm'
        }],
        'frame_count': -5,
        'rotation': 'quaternion'
    }
    assert add_animations(document, skeleton, 0, [('Rest', clip)]) == 1
    sampled = _sampled(document, document.animations[0])
    assert document.accessors[document.animations[0]['samplers'][0]['input']]['count'] == 1
    np.testing.assert_allclose(sampled[2, 'scale'], ((2, 2, 2),))
    np.testing.assert_allclose(sampled[2, 'translation'], ((1, 0, 0),))
    np.testing.assert_allclose(sampled[2, 'rotation'], ((0, 0, math.sqrt(0.5), math.sqrt(0.5)),),
                               atol=1e-6)


def test_add_animations_converts_euler_clip() -> None:
    document, skeleton = _skinned()
    clip = {
        'bones': [{
            'base': {
                'rotation': [0.1, 0.2, 0.3, 0.0]
            },
            'curves': [],
            'name': 'Root'
        }, {
            'base': {},
            'curves': [{
                'channel': 'rotate.x',
                'keys': _keys(0.0, math.pi / 2)
            }],
            'name': 'Arm'
        }],
        'frame_count': 1,
        'rotation': 'euler-xyz'
    }
    assert add_animations(document, skeleton, 0, [('Turn', clip)]) == 1
    sampled = _sampled(document, document.animations[0])
    root, arm = sampled[1, 'rotation'], sampled[2, 'rotation']
    np.testing.assert_allclose(sampled[1, 'translation'], [(1, 2, 3)] * 2)
    expected = _rotation_z(0.3) @ _rotation_y(0.2) @ _rotation_x(0.1)
    for quaternion in root:
        np.testing.assert_allclose(_quaternion_rotation(quaternion), expected, atol=1e-6)
    np.testing.assert_allclose(_quaternion_rotation(arm[0]), _rotation_z(math.pi / 2), atol=1e-6)
    np.testing.assert_allclose(_quaternion_rotation(arm[1]),
                               _rotation_z(math.pi / 2) @ _rotation_x(math.pi / 2),
                               atol=1e-6)
    np.testing.assert_allclose(np.linalg.norm(arm, axis=1), (1, 1), rtol=1e-6)
    assert float(np.dot(arm[0], arm[1])) >= 0


def test_add_animations_skips_clips_without_skeleton_bones() -> None:
    document, skeleton = _skinned()
    clip = {
        'bones': [{
            'base': {},
            'curves': [],
            'name': 'Tail'
        }],
        'frame_count': 1,
        'rotation': 'quaternion'
    }
    assert add_animations(document, skeleton, 0, [('Tail', clip), ('Empty', {
        **clip, 'bones': []
    })]) == 0
    assert document.animations == []


def test_add_animations_unmatched_clip_adds_no_accessor() -> None:
    document, skeleton = _skinned()
    accessors = len(document.accessors)
    clip = {
        'bones': [{
            'base': {},
            'curves': [],
            'name': 'Tail'
        }],
        'frame_count': 3,
        'rotation': 'quaternion'
    }
    assert add_animations(document, skeleton, 0, [('Tail', clip)]) == 0
    assert len(document.accessors) == accessors
    assert document.animations == []


def test_add_animations_zero_quaternion_is_identity() -> None:
    document, skeleton = _skinned()
    clip = {
        'bones': [{
            'base': {
                'rotation': [0.0, 0.0, 0.0, 0.0]
            },
            'curves': [],
            'name': 'Arm'
        }],
        'frame_count': 0,
        'rotation': 'quaternion'
    }
    assert add_animations(document, skeleton, 0, [('Still', clip)]) == 1
    rotation = next(value
                    for (_, path), value in _sampled(document, document.animations[0]).items()
                    if path == 'rotation')
    np.testing.assert_allclose(rotation, [[0.0, 0.0, 0.0, 1.0]])
