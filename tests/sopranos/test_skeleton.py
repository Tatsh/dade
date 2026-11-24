from __future__ import annotations

from typing import Any
import math
import struct

import numpy as np
import pytest

from dade.common.exceptions import InvalidFormatError
from dade.common.gltf import GLBDocument
from dade.sopranos.archive import name_hash
from dade.sopranos.skeleton import (
    add_animations,
    add_skin,
    binds,
    find_skeleton,
    read_clips,
    read_skeletons,
)
from dade.sopranos.typing import Clip, Skeleton, Track

from .conftest import build_clips, build_skeletons

_ONE = 0x7800
_MINUS_ONE = 0xF800
_IDENTITY = (0, 0, 0, _ONE)
_HALF = 0x7000
_BASIS = np.array(
    ((1.0, 0.0, 0.0, 0.0), (0.0, 0.0, -1.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
_BONE_RECORD = 0x90
_BONE_TABLE = 0x20


def _at(x: float, y: float, z: float, rows: Any = ((1, 0, 0), (0, 1, 0), (0, 0, 1))) -> list[float]:
    matrix = np.eye(4)
    matrix[:3, :3] = rows
    matrix[3, :3] = (x, y, z)
    return [float(value) for value in matrix.reshape(16)]


def _rig() -> Skeleton:
    skeleton, = read_skeletons(
        build_skeletons([('lib/rig/rig', [('root', -1, _at(0, 0, 0)), ('hip', 0, _at(0, 0, 10)),
                                          ('toe', 1, _at(1, 0, -10))])]))
    return skeleton


def _track(
    bone: str,
    frames: tuple[int, ...] = (0, 1),
    rotations: tuple[tuple[int, int, int, int], ...] = (_IDENTITY, _IDENTITY),
    translations: tuple[tuple[float, float, float], ...] = (),
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
) -> tuple[Any, ...]:
    return (bone, 5 if translations else 4, frames, rotations, translations, offset)


def _clips(*tracks: tuple[Any, ...],
           rate: int = 10,
           name: str = 'lib/anim/walk') -> tuple[Clip, ...]:
    return read_clips(build_clips([(name, 2, rate, tracks)]))


def _read(document: GLBDocument, index: int) -> np.ndarray:
    accessor = document.accessors[index]
    view = document.views[accessor['bufferView']]
    width = {'SCALAR': 1, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}[accessor['type']]
    kind = {5122: '<i2', 5126: '<f4'}[accessor['componentType']]
    values = np.frombuffer(bytes(document.blob), kind, accessor['count'] * width,
                           view['byteOffset'] + accessor.get('byteOffset', 0))
    out = values.reshape(-1, width).astype(np.float64)
    return out / 32767 if accessor.get('normalized') else out


def _animate(clips: tuple[Clip, ...]) -> tuple[GLBDocument, int]:
    document = GLBDocument()
    skeleton = _rig()
    skin = add_skin(document, skeleton, 'note')
    return document, add_animations(document, skeleton, skin, clips)


def _channels(document: GLBDocument) -> dict[tuple[int, str], tuple[np.ndarray, np.ndarray]]:
    animation, = document.animations
    return {
        (c['target']['node'], c['target']['path']): (
            _read(document, animation['samplers'][c['sampler']]['input'])[:, 0],
            _read(document, animation['samplers'][c['sampler']]['output']))
        for c in animation['channels']
    }


def test_read_skeletons_reads_every_bone() -> None:
    skeleton = _rig()
    assert skeleton.name == 'lib/rig/rig'
    assert skeleton.name_hash == name_hash('lib/rig/rig')
    assert [bone.name for bone in skeleton.bones] == ['root', 'hip', 'toe']
    assert [bone.parent for bone in skeleton.bones] == [-1, 0, 1]
    assert skeleton.bones[2].name_hash == name_hash('toe')
    assert skeleton.bones[1].local[12:15] == (0.0, 0.0, 10.0)
    assert skeleton.bones[2].inverse_world[12:15] == (-1.0, 0.0, 0.0)


def test_read_skeletons_walks_the_chain() -> None:
    data = build_skeletons([('a/a', [('root', -1, _at(0, 0, 0))]),
                            ('b/b', [('root', -1, _at(0, 0, 0))])])
    assert [skeleton.name for skeleton in read_skeletons(data)] == ['a/a', 'b/b']


@pytest.mark.parametrize('tail', [bytes(0x18), b''])
def test_read_skeletons_stops_at_an_empty_section(tail: bytes) -> None:
    data = build_skeletons([('a/a', [('root', -1, _at(0, 0, 0))])])
    assert len(read_skeletons(data + tail)) == 1


def test_read_skeletons_stops_at_a_section_running_past_the_end() -> None:
    assert read_skeletons(build_skeletons([('a/a', [('root', -1, _at(0, 0, 0))])])[:-4]) == ()


def test_read_skeletons_rejects_a_bone_table_running_past_the_end() -> None:
    data = bytearray(build_skeletons([('a/a', [('root', -1, _at(0, 0, 0))])]))
    struct.pack_into('<H', data, 0x10, 100)
    with pytest.raises(InvalidFormatError, match='runs past'):
        read_skeletons(bytes(data))


def test_read_skeletons_rejects_a_parent_after_its_child() -> None:
    data = bytearray(
        build_skeletons([('a/a', [('root', -1, _at(0, 0, 0)), ('hip', 0, _at(0, 0, 0))])]))
    struct.pack_into('<h', data, _BONE_TABLE + _BONE_RECORD + 0x80, 1)
    with pytest.raises(InvalidFormatError, match='parent 1'):
        read_skeletons(bytes(data))


def test_read_skeletons_treats_any_negative_parent_as_a_root() -> None:
    data = bytearray(build_skeletons([('a/a', [('root', -1, _at(0, 0, 0))])]))
    struct.pack_into('<h', data, _BONE_TABLE + 0x80, -2)
    assert read_skeletons(bytes(data))[0].bones[0].parent == -1


def test_read_clips_decodes_rotation_keys() -> None:
    clip, = _clips(
        _track('hip', (0, 3), ((_ONE, 0x8000, _MINUS_ONE, 0x3C00), _IDENTITY), offset=(1, 2, 3)))
    assert (clip.name, clip.name_hash, clip.frame_count,
            clip.rate) == ('lib/anim/walk', name_hash('lib/anim/walk'), 2, 10)
    track, = clip.tracks
    assert (track.bone, track.bone_hash, track.offset) == ('hip', name_hash('hip'), (1.0, 2.0, 3.0))
    assert track.frames.tolist() == [0, 3]
    assert track.translations is None
    assert track.rotations.tolist() == [[1.0, 0.0, -1.0, 1.5 / 256], [0.0, 0.0, 0.0, 1.0]]


def test_read_clips_decodes_translation_keys() -> None:
    clip, = _clips(_track('hip', translations=((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))))
    translations = clip.tracks[0].translations
    assert translations is not None
    assert translations.tolist() == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
    assert clip.tracks[0].rotations.tolist() == [[0.0, 0.0, 0.0, 1.0]] * 2


def test_read_clips_skips_a_track_of_an_unknown_kind() -> None:
    clip, = _clips(('hip', 9, (0,), (_IDENTITY,), (), (0.0, 0.0, 0.0)), _track('toe'))
    assert [track.bone for track in clip.tracks] == ['toe']


@pytest.mark.parametrize('tail', [bytes(0x18), b''])
def test_read_clips_stops_at_an_empty_section(tail: bytes) -> None:
    assert len(read_clips(build_clips([('a', 2, 10, [_track('hip')])]) + tail)) == 1


def test_read_clips_stops_at_a_section_running_past_the_end() -> None:
    assert read_clips(build_clips([('a', 2, 10, [_track('hip')])])[:-4]) == ()


def test_find_skeleton_prefers_the_first_with_the_recorded_hash() -> None:
    first = Skeleton('a/x', 7, ())
    second = Skeleton('a/y', 7, ())
    assert find_skeleton('b/z', 7, (), (first, second)) is first


def test_find_skeleton_falls_back_to_a_skeleton_of_the_same_directory() -> None:
    rig = _rig()
    other = Skeleton('elsewhere/rig', 1, rig.bones)
    assert find_skeleton('LIB/RIG/body', 99, ('', 'hip', 'toe'), (other, rig)) is rig


def test_find_skeleton_requires_every_bone() -> None:
    assert find_skeleton('lib/rig/body', 99, ('hip', 'tail'), (_rig(),)) is None


def test_binds_requires_a_bone_for_every_track() -> None:
    rig = _rig()
    assert binds(_clips(_track('hip'), _track('toe'))[0], rig)
    assert not binds(_clips(_track('hip'), _track('tail'))[0], rig)
    assert not binds(Clip('empty', 0, 1, 10, ()), rig)


def test_add_skin_places_the_bones_in_gltf_space() -> None:
    document = GLBDocument()
    skeleton = _rig()
    assert add_skin(document, skeleton, 'provisional') == 0
    skin, = document.skins
    assert skin['joints'] == [0, 1, 2]
    assert skin['skeleton'] == 0
    assert skin['name'] == 'rig'
    assert skin['extras'] == {'note': 'provisional'}
    assert [node['name'] for node in document.nodes] == ['root', 'hip', 'toe']
    assert document.nodes[0]['children'] == [1]
    assert 'children' not in document.nodes[2]
    assert document.nodes[1]['translation'] == [0.0, 10.0, 0.0]
    assert document.nodes[2]['translation'] == [1.0, -10.0, 0.0]
    inverse = _read(document, skin['inverseBindMatrices']).reshape(3, 4, 4)
    assert inverse[2, 3].tolist() == [-1.0, 0.0, 0.0, 1.0]
    assert inverse[:, :, 3].tolist() == [[0.0, 0.0, 0.0, 1.0]] * 3


def _column(quaternion: list[float]) -> np.ndarray:
    x, y, z, w = quaternion
    return np.array(((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
                     (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
                     (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y))))


@pytest.mark.parametrize('rows', [((1, 0, 0), (0, -1, 0), (0, 0, -1)),
                                  ((-1, 0, 0), (0, 1, 0), (0, 0, -1)),
                                  ((-1, 0, 0), (0, -1, 0), (0, 0, 1)),
                                  ((0, 1, 0), (-1, 0, 0), (0, 0, 1))])
def test_add_skin_turns_each_bone_by_its_bind_rotation(rows: Any) -> None:
    document = GLBDocument()
    skeleton, = read_skeletons(build_skeletons([('a/a', [('root', -1, _at(0, 0, 0, rows))])]))
    add_skin(document, skeleton, '')
    expected = (_BASIS.T @ np.array(_at(0, 0, 0, rows)).reshape(4, 4) @ _BASIS)[:3, :3].T
    assert np.allclose(_column(document.nodes[0]['rotation']), expected)


def test_add_animations_writes_each_track_as_channels() -> None:
    document, added = _animate(_clips(_track('hip', (0, 2),
                                             ((0, 0, 0, _ONE), (_HALF, 0, 0, _ONE)))))
    assert added == 1
    assert document.animations[0]['name'] == 'walk'
    channels = _channels(document)
    times, rotations = channels[1, 'rotation']
    assert times.tolist() == pytest.approx([0.0, 0.2])
    # The game's X axis is also glTF's X axis.
    expected = np.array((0.5, 0.0, 0.0, 1.0)) / math.hypot(0.5, 1.0)
    assert rotations[1] == pytest.approx(expected, abs=1e-4)
    assert (1, 'translation') not in channels


def test_add_animations_turns_the_key_axes_into_gltf_space() -> None:
    document, _ = _animate(_clips(_track('hip', (0, 1), ((0, _HALF, 0, _ONE), _IDENTITY))))
    rotation = _channels(document)[1, 'rotation'][1][0]
    # The game's Y axis is glTF's negative Z axis.
    assert rotation == pytest.approx(np.array((0.0, 0.0, -0.5, 1.0)) / math.hypot(0.5, 1.0),
                                     abs=1e-4)


def test_add_animations_writes_a_still_track_as_one_key() -> None:
    document, _ = _animate(_clips(_track('hip', (0, 1, 2), (_IDENTITY,) * 3)))
    times, rotations = _channels(document)[1, 'rotation']
    assert times.tolist() == [0.0]
    assert rotations.tolist() == [[0.0, 0.0, 0.0, 1.0]]


def test_add_animations_adds_translation_keys_to_the_bind_translation() -> None:
    document, _ = _animate(_clips(_track('hip', translations=((1.0, 2.0, 3.0), (0.0, 0.0, 0.0)))))
    times, translations = _channels(document)[1, 'translation']
    assert times.tolist() == pytest.approx([0.0, 0.1])
    assert translations.tolist() == [[1.0, 13.0, -2.0], [0.0, 10.0, 0.0]]


@pytest.mark.parametrize(('offset', 'moved'), [((0.0, 0.0, 0.5), True), ((1e-6, 0.0, 0.0), False)])
def test_add_animations_writes_a_constant_offset_only_when_it_is_not_noise(
        offset: tuple[float, float, float], *, moved: bool) -> None:
    document, _ = _animate(_clips(_track('hip', offset=offset)))
    channels = _channels(document)
    assert ((1, 'translation') in channels) is moved
    if moved:
        assert channels[1, 'translation'][1].tolist() == [[0.0, 10.5, 0.0]]


def test_add_animations_keeps_each_key_in_the_hemisphere_of_the_one_before() -> None:
    document, _ = _animate(
        _clips(_track('hip', (0, 1, 2), ((0, 0, 0, _ONE), (0, 0, 0, _MINUS_ONE), (0, 0, 0, _ONE)))))
    assert _channels(document)[1, 'rotation'][1][:, 3].tolist() == [1.0, 1.0, 1.0]


def test_add_animations_shares_the_times_of_tracks_with_the_same_frames() -> None:
    document, _ = _animate(
        _clips(_track('hip', rotations=(_IDENTITY, (_HALF, 0, 0, _ONE))),
               _track('toe', rotations=(_IDENTITY, (_HALF, 0, 0, _ONE)))))
    samplers = document.animations[0]['samplers']
    assert samplers[0]['input'] == samplers[1]['input']
    assert len(document.views) == 2


def test_add_animations_uses_the_first_of_two_tracks_for_one_bone() -> None:
    document, _ = _animate(
        _clips(_track('hip', translations=((1.0, 0.0, 0.0), (1.0, 0.0, 0.0))),
               _track('HIP', translations=((2.0, 0.0, 0.0), (2.0, 0.0, 0.0)))))
    assert _channels(document)[1, 'translation'][1].tolist() == [[1.0, 10.0, 0.0]]
    assert len(document.animations[0]['channels']) == 2


def test_add_animations_takes_a_missing_rate_as_one_frame_a_second() -> None:
    document, _ = _animate(_clips(_track('hip', rotations=(_IDENTITY, (_HALF, 0, 0, _ONE))),
                                  rate=0))
    assert _channels(document)[1, 'rotation'][0].tolist() == [0.0, 1.0]


def test_add_animations_skips_a_clip_that_does_not_bind() -> None:
    document, added = _animate(_clips(_track('tail')))
    assert added == 0
    assert document.animations == []


def test_add_animations_skips_a_clip_with_no_keys() -> None:
    clip = Clip('lib/empty', 1, 1, 10,
                (Track('hip', name_hash('hip'), np.zeros(0, np.int64), np.zeros((0, 4)), None,
                       (0.0, 0.0, 0.0)),))
    document, added = _animate((clip,))
    assert added == 0
    assert document.animations == []
