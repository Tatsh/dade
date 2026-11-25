"""Tests for :mod:`dade.thps2pc.skater`."""
from __future__ import annotations

from typing import Any
import json
import struct

import numpy as np
import pytest

from dade.thps2pc.psx import Scene
from dade.thps2pc.skater import (
    FRAMES_PER_SECOND,
    SCALE,
    Clip,
    build_skater_glb,
    decode_channel,
    part_names,
    part_parents,
    read_skater,
    remap_clips,
)
from dade.thps2pc.test_utils import (
    SectorSpec,
    TextureSpec,
    face_record,
    psx_scene,
    skater_clips,
)

_HIER = 0x52454948
_CONSTANT = b'\x0e\x00\x00'
_ZERO = b'\x0f'


def _glb_json(data: bytes) -> dict[str, Any]:
    length = struct.unpack_from('<I', data, 12)[0]
    result: dict[str, Any] = json.loads(data[20:20 + length])
    return result


def _floats(data: bytes, accessor: int) -> np.ndarray:
    document = _glb_json(data)
    binary = 20 + struct.unpack_from('<I', data, 12)[0] + 8
    entry = document['accessors'][accessor]
    view = document['bufferViews'][entry['bufferView']]
    width = {'SCALAR': 1, 'VEC3': 3, 'VEC4': 4}[entry['type']]
    return np.frombuffer(data, '<f4', entry['count'] * width,
                         binary + view.get('byteOffset', 0)).reshape(-1, width)


def _hierarchy(*parents: int) -> tuple[int, bytes]:
    return _HIER, struct.pack(f'<{len(parents)}H', *parents) + b'\x00\x00'


def _raw(*values: int) -> bytes:
    return b'\x00' + struct.pack(f'<{len(values)}h', *values)


def _skater(*, clips: tuple[int, bytes] | None = None, textured: bool = True) -> bytes:
    root = SectorSpec(vertices=((0, 0, 0), (100, 0, 0), (0, 100, 0), (0, 0, 100)),
                      faces=(face_record((0, 1, 2), uvs=((0, 0), (8, 0), (0, 8)),
                                         flags=0x11), face_record((0, 2, 3), flags=0x10, length=4),
                             face_record((0, 1, 3), flags=0x90,
                                         length=4), face_record((0, 1, 9), flags=0x10, length=4)),
                      count_b=0,
                      flags=(1, 1, 0, 0))
    child = SectorSpec(vertices=((0, 0, 0), (0, 1, 0), (50, 0, 0), (0, 7, 0)),
                       faces=(face_record((0, 1, 2), flags=0x10,
                                          length=4), face_record((1, 2, 3), flags=0x10, length=4)),
                       count_b=0,
                       flags=(0, 2, 0, 2))
    chunks = [_hierarchy(0, 0)]
    if clips is not None:
        chunks.append(clips)
    extra: dict[str, Any] = {}
    if textured:
        extra = {
            'cluts_256': {
                5: [0x7C1F, 0x001F]
            },
            'instances': (TextureSpec(clut_id=5,
                                      height=2,
                                      num_colors=0x100,
                                      page=0,
                                      pixels=bytes((0, 1, 1, 0)),
                                      width=2),)
        }
    return psx_scene(sectors=(root, child), chunks=chunks, checksums=(0xC0FFEE,), **extra)


def _clip_chunk() -> tuple[int, bytes]:
    root = (_ZERO, _ZERO, _ZERO, _ZERO, _ZERO, _ZERO)
    child = (_ZERO, _ZERO, _raw(0, 1024), _raw(200, 200), _ZERO, _ZERO)
    return 0x2C, skater_clips(((2, root + child),))


def _pose_chunk() -> tuple[int, bytes]:
    identity = struct.pack('<9h', 4096, 0, 0, 0, 4096, 0, 0, 0, 4096)
    frame = identity + struct.pack('<3h', 0, 0, 0) + identity + struct.pack('<3h', 10, 0, 0)
    return 0x2A, struct.pack('<III', 1, 12, 1) + frame


@pytest.mark.parametrize(('data', 'frames', 'expected', 'end'), [
    (_ZERO, 3, [0, 0, 0], 1),
    (b'\x0e' + struct.pack('<h', -5), 2, [-5, -5], 3),
    (b'\x10' + struct.pack('<3h', 0, 10, 20), 4, [0, 5, 10, 20], 7),
    (_raw(1, 2, 3), 3, [1, 2, 3], 7),
    (b'\x03' + struct.pack('<h', 100) + b'\x3e', 3, [100, 103, 101], 4),
    (b'\x12' + struct.pack('<h', 10) + b'\x5c', 4, [10, 11, 12, 11], 4),
    (b'\x01' + struct.pack('<h', 32767) + b'\x40', 2, [32767, -32768], 4),
])
def test_decode_channel(data: bytes, frames: int, expected: list[int], end: int) -> None:
    values, offset = decode_channel(data, 0, frames)
    assert values.tolist() == expected
    assert offset == end


def test_part_names_orders_by_index() -> None:
    header = ('#ifndef _X_PSH\n#define XPART_X_HEAD\t\t1\n//   parent: x_chest\n'
              '#define XPART_X_CHEST\t\t0\n#endif\n')
    assert part_names(header) == ('x_chest', 'x_head')


def test_read_skater_requires_a_hierarchy() -> None:
    assert read_skater(Scene.parse(psx_scene(sectors=(SectorSpec(((0, 0, 0),), (), 0),)))) is None


def test_read_skater_rejects_a_parent_out_of_range() -> None:
    data = psx_scene(sectors=(SectorSpec(((0, 0, 0),), (), 0),), chunks=(_hierarchy(4),))
    assert read_skater(Scene.parse(data)) is None


def test_read_skater_decodes_compressed_clips() -> None:
    skater = read_skater(Scene.parse(_skater(clips=_clip_chunk())))
    assert skater is not None
    assert skater.parents == (0, 0)
    (clip,) = skater.clips
    assert clip.name == 'clip_000'
    assert clip.rotations.shape == (2, 2, 3, 3)
    np.testing.assert_allclose(clip.rotations[1, 1], [[0, -1, 0], [1, 0, 0], [0, 0, 1]], atol=1e-9)
    np.testing.assert_allclose(clip.translations[:, 1], [[200, 0, 0], [200, 0, 0]])


@pytest.mark.parametrize(('parent', 'expected'), [
    ((_raw(0, 0), _ZERO, _ZERO, _raw(5, 5), _ZERO, _ZERO), [15, 0, 0]),
    ((_ZERO, b'\x0e' + struct.pack('<h', 1024), _ZERO, _ZERO, _ZERO, _ZERO), [0, 0, -10]),
])
def test_read_skater_composes_translations_through_the_parent(parent: tuple[bytes, ...],
                                                              expected: list[int]) -> None:
    child = (_ZERO, _ZERO, _ZERO, _raw(10, 10), _ZERO, _ZERO)
    skater = read_skater(Scene.parse(_skater(clips=(0x2C, skater_clips(((2, parent + child),))))))
    assert skater is not None
    np.testing.assert_allclose(skater.clips[0].translations[0, 1], expected, atol=1e-9)


def test_read_skater_reads_poses() -> None:
    skater = read_skater(Scene.parse(_skater(clips=_pose_chunk())))
    assert skater is not None
    (clip,) = skater.clips
    assert clip.name == 'pose_000'
    np.testing.assert_allclose(clip.rotations[0, 1], np.eye(3))
    np.testing.assert_allclose(clip.translations[0, 1], [10, 0, 0])


def test_read_skater_without_clips() -> None:
    skater = read_skater(Scene.parse(_skater()))
    assert skater is not None
    assert skater.clips == ()


def test_remap_clips_matches_names_without_the_prefix() -> None:
    clip = Clip('a', np.arange(18.0).reshape(1, 2, 3, 3), np.arange(6.0).reshape(1, 2, 3))
    (moved,) = remap_clips((clip,), ('burnq_pelvis', 'burnq_head'), ('hawk_head', 'hawk_pelvis'))
    np.testing.assert_array_equal(moved.translations[0], [[3, 4, 5], [0, 1, 2]])
    with pytest.raises(KeyError):
        remap_clips((clip,), ('burnq_pelvis', 'burnq_head'), ('hawk_tail', 'hawk_pelvis'))


def test_build_skater_glb() -> None:
    skater = read_skater(Scene.parse(_skater(clips=_clip_chunk())))
    assert skater is not None
    data = build_skater_glb(skater, ('x_root', 'x_arm'), skater.clips, 'x')
    document = _glb_json(data)
    assert [node.get('name') for node in document['nodes']] == ['x_root', 'x_arm', 'x']
    assert document['nodes'][0]['children'] == [1]
    assert document['skins'] == [{'inverseBindMatrices': 0, 'joints': [0, 1], 'skeleton': 0}]
    assert document['nodes'][1]['translation'] == pytest.approx([200 * SCALE, 0, 0])
    (animation,) = document['animations']
    assert animation['name'] == 'clip_000'
    assert len(animation['channels']) == 4
    times = document['accessors'][animation['samplers'][0]['input']]
    assert times['max'] == [pytest.approx(1 / FRAMES_PER_SECOND)]
    textured, untextured = document['meshes'][0]['primitives']
    assert 'TEXCOORD_0' in textured['attributes']
    assert 'TEXCOORD_0' not in untextured['attributes']
    assert document['materials'][textured['material']]['name'] == '00C0FFEE'
    assert document['materials'][untextured['material']]['name'] == 'untextured'
    assert document['accessors'][untextured['attributes']['POSITION']]['count'] == 9
    assert len(document['images']) == 1


def test_build_skater_glb_binds_references_to_the_exporting_part() -> None:
    skater = read_skater(Scene.parse(_skater(clips=_pose_chunk(), textured=False)))
    assert skater is not None
    data = build_skater_glb(skater, ('x_root', 'x_arm'), skater.clips, 'x')
    document = _glb_json(data)
    (primitive,) = document['meshes'][0]['primitives']
    view = document['bufferViews'][document['accessors'][primitive['attributes']['JOINTS_0']]
                                   ['bufferView']]
    offset = 20 + struct.unpack_from('<I', data, 12)[0] + 8 + view.get('byteOffset', 0)
    joints = data[offset:offset + view['byteLength']:4]
    assert list(joints) == [0, 0, 0, 0, 0, 0, 1, 0, 1, 1, 1, 0]
    assert 'images' not in document


def test_build_skater_glb_adds_a_root_for_several_roots() -> None:
    data = psx_scene(sectors=(SectorSpec(((0, 0, 0),), (), 0), SectorSpec(((0, 0, 0),), (), 0)),
                     chunks=(_hierarchy(0, 1), _pose_chunk()))
    skater = read_skater(Scene.parse(data))
    assert skater is not None
    document = _glb_json(build_skater_glb(skater, ('a', 'b'), skater.clips, 'pair'))
    assert document['nodes'][2] == {'children': [0, 1], 'name': 'pair_root'}
    assert document['skins'][0]['skeleton'] == 2
    assert document['meshes'] == [{'primitives': []}]


def test_build_skater_glb_keeps_quaternions_continuous() -> None:
    angles = np.radians([0, 120, 240, 359, 179])
    rotations = np.array([[[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]]
                          for a in angles])[:, None]
    flipped = np.array([np.diag((1.0, -1.0, -1.0)), np.diag((-1.0, -1.0, 1.0))])[:, None]
    data = psx_scene(sectors=(SectorSpec(((0, 0, 0),), (), 0),), chunks=(_hierarchy(0),))
    skater = read_skater(Scene.parse(data))
    assert skater is not None
    clips = (Clip('spin', rotations, np.zeros((5, 1, 3))), Clip('flip', flipped, np.zeros(
        (2, 1, 3))))
    glb = build_skater_glb(skater, ('a',), clips, 'spin')
    document = _glb_json(glb)
    assert [animation['name'] for animation in document['animations']] == ['spin', 'flip']
    spin, flip = (_floats(
        glb,
        next(sampler['output'] for channel in animation['channels']
             if channel['target']['path'] == 'rotation'
             for sampler in (animation['samplers'][channel['sampler']],)))
                  for animation in document['animations'])
    assert np.all(np.einsum('ij,ij->i', spin[:-1], spin[1:]) >= 0)
    assert np.allclose(np.abs(flip), [[1, 0, 0, 0], [0, 0, 1, 0]], atol=1e-6)


def test_read_skater_places_a_parent_listed_after_its_child() -> None:
    child = (_ZERO, _ZERO, _ZERO, _raw(3, 3), _ZERO, _ZERO)
    root = (_ZERO, _ZERO, _ZERO, _raw(7, 7), _ZERO, _ZERO)
    data = psx_scene(sectors=(SectorSpec(((0, 0, 0),), (), 0), SectorSpec(((0, 0, 0),), (), 0)),
                     chunks=(_hierarchy(1, 1), (0x2C, skater_clips(((2, child + root),)))))
    skater = read_skater(Scene.parse(data))
    assert skater is not None
    np.testing.assert_allclose(skater.clips[0].translations[0], [[10, 0, 0], [7, 0, 0]])


def test_part_parents_reads_the_header_comments() -> None:
    header = ('#define XPART_X_ARM\t\t0\n//   parent: x_body\n\n'
              '#define XPART_X_BODY\t\t1\n//   parent: Scene Root\n')
    assert part_parents(header) == (1, 1)


@pytest.mark.parametrize('header', [
    '#define XPART_X_ARM\t\t0\n//   parent: x_tail\n',
    '#define XPART_X_ARM\t\t0\n//   parent: Scene Root\n#define XPART_X_LEG\t\t1\n',
])
def test_part_parents_rejects_an_incomplete_header(header: str) -> None:
    assert part_parents(header) is None


def test_read_skater_falls_back_to_given_parents() -> None:
    data = psx_scene(sectors=(SectorSpec(((0, 0, 0),), (), 0), SectorSpec(((0, 0, 0),), (), 0)),
                     chunks=(_pose_chunk(),))
    skater = read_skater(Scene.parse(data), (1, 1))
    assert skater is not None
    assert skater.parents == (1, 1)
    assert read_skater(Scene.parse(data), (0,)) is None
