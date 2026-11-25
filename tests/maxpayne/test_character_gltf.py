from __future__ import annotations

from typing import TYPE_CHECKING, Any
import itertools
import json
import logging
import math
import struct

import numpy as np
import pytest

from dade.maxpayne.character import read_animation, read_weights
from dade.maxpayne.gltf import build_character_glb
from dade.maxpayne.model import read_model
from dade.maxpayne.typing import Model, TextureImage

if TYPE_CHECKING:
    from collections.abc import Callable

_IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
_SKIN = (-1.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0, -1.0, 0.0, 0.0, 0.9, 0.0)


def _parse(glb: bytes) -> tuple[dict[str, Any], bytes]:
    json_length = struct.unpack_from('<I', glb, 12)[0]
    document = json.loads(glb[20:20 + json_length])
    start = 20 + json_length
    return document, glb[start + 8:start + 8 + struct.unpack_from('<I', glb, start)[0]]


def _values(document: dict[str, Any], binary: bytes, index: int) -> np.ndarray:
    accessor = document['accessors'][index]
    view = document['bufferViews'][accessor['bufferView']]
    dtype = {5123: '<u2', 5126: '<f4'}[accessor['componentType']]
    width = {'MAT4': 16, 'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[accessor['type']]
    return np.frombuffer(binary, dtype, accessor['count'] * width, view['byteOffset']).reshape(
        accessor['count'], width)


def _skeleton(make_model: Callable[..., bytes], **kwargs: Any) -> Model:
    options: dict[str, Any] = {
        'bones': (('Head', 'Pelvis', (*_IDENTITY, 0.0, 0.5, 0.0)),),
        'name': 'Pelvis',
        'transform': (*_IDENTITY, 0.0, 1.0, 0.0)
    }
    options.update(kwargs)
    return read_model(make_model(**options))


def _skin(make_model: Callable[..., bytes], **kwargs: Any) -> Model:
    options: dict[str, Any] = {'transform': _SKIN}
    options.update(kwargs)
    return read_model(make_model(**options))._replace(
        textures=(TextureImage(data=b'\x89PNGfake', kind=0, path='skin.png'),))


def _trs(node: dict[str, Any]) -> np.ndarray:
    x, y, z, w = node['rotation']
    rotation = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    out = np.eye(4)
    out[:3, :3] = rotation * np.array(node['scale'])
    out[:3, 3] = node['translation']
    return out


def test_build_character_glb_rigs_the_skin(make_model: Callable[..., bytes],
                                           make_weights: Callable[..., bytes]) -> None:
    document, binary = _parse(
        build_character_glb(_skin(make_model),
                            _skeleton(make_model),
                            read_weights(make_weights()),
                            name='cop'))
    assert document['scenes'][0] == {'name': 'cop', 'nodes': [2, 0]}
    skin = document['skins'][0]
    assert skin['joints'] == [0, 1]
    assert skin['skeleton'] == 0
    assert document['nodes'][0]['children'] == [1]
    assert document['nodes'][2]['skin'] == 0
    inverse = _values(document, binary, skin['inverseBindMatrices']).reshape(-1, 4, 4)
    pelvis = _trs(document['nodes'][0])
    head = pelvis @ _trs(document['nodes'][1])
    assert np.allclose(inverse[0].T @ pelvis, np.eye(4), atol=1e-6)
    assert np.allclose(inverse[1].T @ head, np.eye(4), atol=1e-6)
    attributes = document['meshes'][0]['primitives'][0]['attributes']
    joints = _values(document, binary, attributes['JOINTS_0'])
    weights = _values(document, binary, attributes['WEIGHTS_0'])
    assert np.allclose(weights.sum(axis=1), 1.0)
    assert np.all(joints[weights == 0] == 0)
    # The skin's transform takes the exporter's (1, 0, 0) to (-1, 0.9, 0) and its (0, 0, 1) to
    # (0, -0.1, 0), and depth then mirrors.
    positions = _values(document, binary, attributes['POSITION'])
    assert np.allclose(positions, ((0.0, 0.9, 0.0), (-1.0, 0.9, 0.0), (0.0, -0.1, 0.0)))
    normals = _values(document, binary, attributes['NORMAL'])
    assert np.allclose(normals, (0.0, 1.0, 0.0))
    material = document['materials'][document['meshes'][0]['primitives'][0]['material']]
    assert 'baseColorTexture' in material['pbrMetallicRoughness']


def test_build_character_glb_animates_the_joints(make_model: Callable[..., bytes],
                                                 make_weights: Callable[..., bytes],
                                                 make_animation: Callable[..., bytes]) -> None:
    clip = read_animation(make_animation(rate=30))
    document, binary = _parse(
        build_character_glb(_skin(make_model), _skeleton(make_model), read_weights(make_weights()),
                            [('walk', clip)]))
    animation = document['animations'][0]
    assert animation['name'] == 'walk'
    targets = sorted((c['target']['node'], c['target']['path']) for c in animation['channels'])
    # The head turns and the pelvis rises; the head's translation never leaves the bind pose.
    assert targets == [(0, 'rotation'), (0, 'translation'), (1, 'rotation')]
    sampler = animation['samplers'][0]
    times = _values(document, binary, sampler['input'])[:, 0]
    assert times == pytest.approx([0.0, 2 / 30])


def test_build_character_glb_writes_scale_when_a_key_scales(
        make_model: Callable[..., bytes], make_weights: Callable[..., bytes],
        make_animation: Callable[..., bytes]) -> None:
    wide = (2.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.5, 0.0)
    clip = read_animation(
        make_animation((('Head', 'Pelvis', 2, ((0, (*_IDENTITY, 0.0, 0.5, 0.0)), (1, wide))),)))
    document, _ = _parse(
        build_character_glb(_skin(make_model), _skeleton(make_model), read_weights(make_weights()),
                            [('grow', clip)]))
    paths = {c['target']['path'] for c in document['animations'][0]['channels']}
    assert paths == {'rotation', 'scale'}


def test_build_character_glb_keeps_rotations_on_the_short_way_round(
        make_model: Callable[..., bytes], make_weights: Callable[..., bytes],
        make_animation: Callable[..., bytes]) -> None:
    def turn(degrees: float) -> tuple[float, ...]:
        c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
        return (c, 0.0, -s, 0.0, 1.0, 0.0, s, 0.0, c, 0.0, 0.5, 0.0)

    # A turn of 170 degrees comes out of the matrix on the far side from one of 100.
    clip = read_animation(
        make_animation(
            (('Head', 'Pelvis', 3, ((0, turn(100.0)), (1, turn(170.0)), (2, turn(175.0)))),)))
    document, binary = _parse(
        build_character_glb(_skin(make_model), _skeleton(make_model), read_weights(make_weights()),
                            [('spin', clip)]))
    rotations = _values(document, binary, document['animations'][0]['samplers'][0]['output'])
    assert all(np.dot(a, b) > 0 for a, b in itertools.pairwise(rotations))


def test_build_character_glb_skips_a_clip_driving_no_joint(
        make_model: Callable[..., bytes], make_weights: Callable[..., bytes],
        make_animation: Callable[..., bytes]) -> None:
    stray = read_animation(
        make_animation(
            (('Tail', '', 1, ((0, (*_IDENTITY, 0.0, 0.0, 0.0)),)), ('Head', 'Pelvis', 1, ()))))
    document, _ = _parse(
        build_character_glb(_skin(make_model), _skeleton(make_model), read_weights(make_weights()),
                            [('stray', stray)]))
    assert 'animations' not in document


def test_build_character_glb_matches_bones_ignoring_case(make_model: Callable[..., bytes],
                                                         make_weights: Callable[..., bytes],
                                                         caplog: pytest.LogCaptureFixture) -> None:
    weights = read_weights(make_weights(bones=('PELVIS', 'head')))
    with caplog.at_level(logging.WARNING):
        document, binary = _parse(
            build_character_glb(_skin(make_model), _skeleton(make_model), weights))
    assert not caplog.records
    attributes = document['meshes'][0]['primitives'][0]['attributes']
    assert 1 in _values(document, binary, attributes['JOINTS_0'])


def test_build_character_glb_binds_an_unknown_bone_to_the_root(
        make_model: Callable[..., bytes], make_weights: Callable[..., bytes],
        caplog: pytest.LogCaptureFixture) -> None:
    weights = read_weights(make_weights(bones=('Pelvis', 'Tail')))
    with caplog.at_level(logging.WARNING):
        document, binary = _parse(
            build_character_glb(_skin(make_model), _skeleton(make_model), weights))
    assert 'Tail' in caplog.text
    attributes = document['meshes'][0]['primitives'][0]['attributes']
    assert set(_values(document, binary, attributes['JOINTS_0']).ravel()) == {0}


def test_build_character_glb_binds_an_unweighted_vertex_to_the_root(
        make_model: Callable[..., bytes], make_weights: Callable[..., bytes]) -> None:
    # The second vertex lists nothing and the third is past the end of the weights.
    weights = read_weights(make_weights((((1, 1.0),), ())))
    document, binary = _parse(build_character_glb(_skin(make_model), _skeleton(make_model),
                                                  weights))
    attributes = document['meshes'][0]['primitives'][0]['attributes']
    joints = _values(document, binary, attributes['JOINTS_0'])
    weights_out = _values(document, binary, attributes['WEIGHTS_0'])
    assert joints[0][0] == 1
    assert list(joints[1]) == [0, 0, 0, 0]
    assert weights_out[1][0] == pytest.approx(1.0)
    assert weights_out[2][0] == pytest.approx(1.0)


def test_build_character_glb_keeps_the_four_strongest_influences(
        make_model: Callable[..., bytes], make_weights: Callable[..., bytes]) -> None:
    names = ('Pelvis', 'A', 'B', 'C', 'D')
    skeleton = _skeleton(make_model,
                         bones=tuple(
                             (name, 'Pelvis', (*_IDENTITY, 0.0, 0.1, 0.0)) for name in names[1:]))
    five = tuple(enumerate((0.1, 0.3, 0.2, 0.25, 0.15)))
    weights = read_weights(make_weights((five, five, five), bones=names))
    document, binary = _parse(build_character_glb(_skin(make_model), skeleton, weights))
    attributes = document['meshes'][0]['primitives'][0]['attributes']
    strengths = _values(document, binary, attributes['WEIGHTS_0'])
    assert strengths[0] == pytest.approx(np.array((0.3, 0.25, 0.2, 0.15)) / 0.9)


def test_build_character_glb_turns_stored_normals(make_model: Callable[..., bytes],
                                                  make_weights: Callable[..., bytes]) -> None:
    # A packed mesh stores the exporter's up, (0, 0, 1), and the skin's transform turns it down.
    document, binary = _parse(
        build_character_glb(_skin(make_model, packed=True), _skeleton(make_model),
                            read_weights(make_weights())))
    attributes = document['meshes'][0]['primitives'][0]['attributes']
    assert np.allclose(_values(document, binary, attributes['NORMAL']), (0.0, -1.0, 0.0))


def test_build_character_glb_replaces_a_zero_normal(make_model: Callable[..., bytes],
                                                    make_weights: Callable[..., bytes]) -> None:
    model = _skin(make_model, packed=True)
    model = model._replace(meshes=(model.meshes[0]._replace(normals=((0.0, 0.0, 0.0),) * 3),))
    document, binary = _parse(
        build_character_glb(model, _skeleton(make_model), read_weights(make_weights())))
    attributes = document['meshes'][0]['primitives'][0]['attributes']
    assert np.allclose(_values(document, binary, attributes['NORMAL']), (0.0, 1.0, 0.0))


def test_build_character_glb_merges_a_bone_listed_twice(make_model: Callable[..., bytes],
                                                        make_weights: Callable[..., bytes]) -> None:
    # A zero weight and a bone index past the name table are both dropped.
    twice = ((1, 0.2), (0, 0.6), (1, 0.2), (0, 0.0), (7, 0.5))
    document, binary = _parse(
        build_character_glb(_skin(make_model), _skeleton(make_model),
                            read_weights(make_weights((twice, twice, twice)))))
    attributes = document['meshes'][0]['primitives'][0]['attributes']
    assert list(_values(document, binary, attributes['JOINTS_0'])[0]) == [0, 1, 0, 0]
    assert _values(document, binary, attributes['WEIGHTS_0'])[0] == pytest.approx((0.6, 0.4, 0, 0))


def test_build_character_glb_writes_an_untextured_material(
        make_model: Callable[..., bytes], make_weights: Callable[..., bytes]) -> None:
    model = _skin(make_model, materials=(), coords=(), coord_faces=())
    document, binary = _parse(
        build_character_glb(model, _skeleton(make_model), read_weights(make_weights())))
    attributes = document['meshes'][0]['primitives'][0]['attributes']
    assert np.allclose(_values(document, binary, attributes['TEXCOORD_0']), 0.0)
    assert 'baseColorFactor' in document['materials'][0]['pbrMetallicRoughness']


def test_build_character_glb_prefers_the_weighted_mesh(make_model: Callable[..., bytes],
                                                       make_weights: Callable[..., bytes]) -> None:
    model = _skin(make_model, bones=(('extra', '', _SKIN),))
    model = model._replace(meshes=(model.meshes[0]._replace(name='other'), *model.meshes))
    document, _ = _parse(
        build_character_glb(model, _skeleton(make_model),
                            read_weights(make_weights(meshes=('missing',)))))
    assert document['meshes'][0]['name'] == 'other'
    document, _ = _parse(
        build_character_glb(model, _skeleton(make_model),
                            read_weights(make_weights(meshes=('body',)))))
    assert document['meshes'][0]['name'] == 'body'


def test_build_character_glb_roots_a_bone_whose_parent_comes_later(
        make_model: Callable[..., bytes], make_weights: Callable[..., bytes]) -> None:
    skeleton = read_model(
        make_model(name='Head', parent='Pelvis', bones=(('Pelvis', '', (*_IDENTITY, 0, 1, 0)),)))
    document, _ = _parse(
        build_character_glb(_skin(make_model), skeleton, read_weights(make_weights())))
    assert document['scenes'][0]['nodes'] == [2, 0, 1]
    assert document['nodes'][0]['translation'] == [0.0, 0.0, 0.0]


def test_build_character_glb_rejects_a_skin_without_faces(
        make_model: Callable[..., bytes], make_weights: Callable[..., bytes]) -> None:
    with pytest.raises(ValueError, match='no faces'):
        build_character_glb(_skin(make_model, faces=()), _skeleton(make_model),
                            read_weights(make_weights()))


def test_build_character_glb_rejects_an_empty_skeleton(make_model: Callable[..., bytes],
                                                       make_weights: Callable[..., bytes]) -> None:
    with pytest.raises(ValueError, match='no bones'):
        build_character_glb(_skin(make_model), Model(materials={}, meshes=()),
                            read_weights(make_weights()))
