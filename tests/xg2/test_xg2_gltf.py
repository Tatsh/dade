"""Tests for :mod:`dade.xg2.gltf`."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
import json
import math
import struct

from dade.xg2.bmc import BmcClip
from dade.xg2.f3dex2 import Mesh, Vertex
from dade.xg2.gltf import (
    build_clip_glb,
    build_glb,
    build_level_glb,
    build_pc_glb,
    build_rider_glb,
    build_track_glb,
    iter_models,
    pc_bank_size,
    pose_clip,
)
from dade.xg2.skeleton import Bone, Skeleton
from dade.xg2.typing import Texture
from dade.xg2.xg1_objects import ObjectModel, ObjectPlacement

if TYPE_CHECKING:
    from collections.abc import Callable

_GLB_MAGIC = b'glTF'
_IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def _document(glb: bytes) -> dict[str, Any]:
    length = struct.unpack_from('<I', glb, 12)[0]
    document: dict[str, Any] = json.loads(glb[20:20 + length])
    return document


def _triangle_mesh(*, lit: bool, texture: int | None = 0x400) -> Mesh:
    vertices = [
        Vertex(0, 0, 0, 0, 0, 10, 20, 200, 255),
        Vertex(1, 0, 0, 64, 0, 30, 40, 200, 255),
        Vertex(0, 1, 0, 0, 64, 50, 60, 200, 255),
    ]
    return Mesh(texture, lit, vertices, [(0, 1, 2)])


def _translucent_texture() -> Texture:
    return Texture('ci8', 0x400, 2, 2, bytes([0xFF, 0, 0, 0x80] * 4))


def _object_model(identifier: int = 0) -> ObjectModel:
    return ObjectModel(identifier, ((0, 0, 0), (1, 0, 0), (0, 1, 0)), ((0, 0), (0, 0), (0, 0)),
                       ((0.0, 1.0, 0.0),) * 3, (0, 1, 2), 0xFF, 0xFF, 0xFF)


def _lit_model() -> bytes:
    header = struct.pack('>2I', 0x05000008, 0)
    commands = [(0x01004008, 0), (0x05000204, 0), (0xDF000000, 0)]
    vertex_at = len(header) + len(commands) * 8
    commands[0] = (0x01004008, 0x05000000 | vertex_at)
    body = b''.join(struct.pack('>2I', w0, w1) for w0, w1 in commands)
    vertices = b''.join(
        struct.pack('>3hH2h4B', x, y, 0, 0, 0, 0, 0, 0, 127, 255)
        for x, y in ((0, 0), (1, 0), (1, 1), (0, 1)))
    return header + body + vertices


def _pc_model() -> tuple[bytes, bytes]:
    table = struct.pack('<I', 0x05000004)
    commands = ((0xAC000000, 0), (0, 0x05000400), (0x04000C00, 0), (0x05000204, 0), (0xDF000000, 0))
    body = b''.join(struct.pack('<2I', w0, w1) for w0, w1 in commands)
    vertices = b''.join(
        struct.pack('<3hH2h4B', x, y, 0, 0, 0, 0, 255, 255, 255, 255)
        for x, y in ((0, 0), (1, 0), (0, 1)))
    return table + body, vertices


def test_build_glb_of_a_flat_model() -> None:
    glb = build_glb(_lit_model(), [], 'bike')
    assert glb is not None
    assert glb[:4] == _GLB_MAGIC


def test_build_glb_of_an_empty_model() -> None:
    assert build_glb(b'\x00' * 32, [], 'nothing') is None


def test_build_level_glb_with_a_translucent_texture() -> None:
    glb = build_level_glb([_triangle_mesh(lit=False)], [_translucent_texture()], 'lvl', 0.5)
    assert glb is not None
    assert glb[:4] == _GLB_MAGIC


def test_build_level_glb_of_a_lit_untextured_mesh() -> None:
    glb = build_level_glb([_triangle_mesh(lit=True, texture=None)], [], 'lvl')
    assert glb is not None


def test_build_level_glb_of_nothing() -> None:
    assert build_level_glb([], [], 'lvl') is None


def test_build_pc_glb_uses_the_vertex_bank() -> None:
    model, vertices = _pc_model()
    glb = build_pc_glb(model, vertices, [], 'pc')
    assert glb is not None
    assert glb[:4] == _GLB_MAGIC


def test_pc_bank_size_reports_the_furthest_load() -> None:
    model, _vertices = _pc_model()
    assert pc_bank_size(model) == 3 * 16


def test_pc_bank_size_skips_a_data_entry() -> None:
    model = struct.pack('<I', 0x05000004) + struct.pack('<4I', 0, 0, 0, 0)
    assert pc_bank_size(model) == 0


def test_build_level_glb_of_a_zero_length_normal() -> None:
    vertices = [
        Vertex(0, 0, 0, 0, 0, 0, 0, 0, 255),
        Vertex(1, 0, 0, 0, 0, 0, 0, 0, 255),
        Vertex(0, 1, 0, 0, 0, 0, 0, 0, 255),
    ]
    glb = build_level_glb([Mesh(None, lit=True, vertices=vertices, triangles=[(0, 1, 2)])], [],
                          'lvl')
    assert glb is not None


def test_build_clip_glb_aligns_opposed_rotations() -> None:
    skeleton = Skeleton(6, [Bone('hip', -1, 0, 6, (), _IDENTITY, (0.0, 0.0, 0.0))], (9, 8))
    # The root turns about X by nothing, then by all but a sliver of a full turn; the second
    # frame's quaternion lies on the far hemisphere and is flipped to meet the first.
    channels = [[0.0, 65520.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]]
    translations, rotations = pose_clip(BmcClip('walk.asf', 2, channels), skeleton)
    assert translations == [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)]
    assert sum(a * b for a, b in zip(*rotations[0], strict=True)) > 0
    assert build_clip_glb(BmcClip('walk.asf', 2, channels), 'anim', skeleton) is not None


def test_pose_clip_follows_the_channel_codes() -> None:
    # Code 8 translates Z, Y, then X; code 6 has no meaning and only consumes its curve; code 3
    # turns about the basis's first column, which this basis makes the Y axis.
    turned = ((0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    skeleton = Skeleton(4, [Bone('knee', -1, 2, 4, (3, 10), turned, (0.0, 5.0, 0.0))], (8, 6),
                        _IDENTITY, (0.0, 1.0, 0.0))
    channels = [[1.0], [2.0], [3.0], [99.0], [16384.0], [0.0]]
    translations, rotations = pose_clip(BmcClip('walk.asf', 1, channels), skeleton)
    assert translations == [(12.0, 8.0, 4.0)]
    assert rotations[0] == [(0.0, 0.0, 0.0, 1.0)]
    x, y, z, w = rotations[1][0]
    # A quarter turn about Y; the bone's second curve is all its dof leaves, and its later codes
    # find no curve.
    assert (round(x, 6), round(y, 6), round(z, 6), round(w, 6)) == (0.0, round(
        math.sqrt(0.5), 6), 0.0, round(math.sqrt(0.5), 6))


def test_build_clip_glb_places_the_joints_at_their_pivots() -> None:
    skeleton = Skeleton(6, [
        Bone('hip', -1, 0, 6, (), _IDENTITY, (0.0, 0.0, 0.0)),
        Bone('knee', 0, 1, 6, (3,), _IDENTITY, (0.0, -10.0, 0.0)),
    ], (9, 8), _IDENTITY, (1.0, 2.0, 3.0))
    clip = BmcClip('walk.asf', 2, [[0.0, 0.0]] * 7)
    glb = build_clip_glb(clip, 'anim', skeleton)
    assert glb is not None
    document = _document(glb)
    assert [node['translation'] for node in document['nodes']] == [[1.0, 2.0, 3.0],
                                                                   [-1.0, -2.0, -3.0],
                                                                   [0.0, -10.0, 0.0]]
    assert document['scenes'][0]['nodes'] == [0]
    assert 'meshes' not in document


def test_build_rider_glb_skins_the_mesh(make_rider: Callable[..., bytes]) -> None:
    texture = Texture('ci8', 0x380, 2, 2, bytes([0xFF] * 16))
    clips = [('walk', BmcClip('walk.asf', 2, [[0.0, 4096.0]] * 7)),
             ('other', BmcClip('man2sk.asf', 2, [[0.0, 0.0]] * 3)),
             ('empty', BmcClip('walk.asf', 0, []))]
    glb = build_rider_glb(make_rider(), [texture], clips, 'rider')
    assert glb is not None
    document = _document(glb)
    (skin,) = document['skins']
    assert [document['nodes'][j]['name'] for j in skin['joints']] == ['root', 'hip', 'knee']
    assert document['nodes'][0] == {'mesh': 0, 'name': 'rider', 'skin': 0}
    attributes = document['meshes'][0]['primitives'][0]['attributes']
    assert {'JOINTS_0', 'NORMAL', 'POSITION', 'TEXCOORD_0', 'WEIGHTS_0'} <= set(attributes)
    assert [animation['name'] for animation in document['animations']] == ['walk']
    assert document['scenes'][0]['nodes'] == [0, 1]


def test_build_rider_glb_of_an_untextured_rider(make_rider: Callable[..., bytes]) -> None:
    assert build_rider_glb(make_rider(), [], [], 'rider') is not None


def test_build_rider_glb_of_a_rider_that_draws_nothing(make_rider: Callable[..., bytes]) -> None:
    model = make_rider()
    # The display list's first command ends it.
    silent = model[:0x20] + struct.pack('>2I', 0xDF000000, 0) + model[0x28:]
    assert build_rider_glb(silent, [], [], 'rider') is None


def test_build_rider_glb_of_a_model_that_is_not_a_rider() -> None:
    assert build_rider_glb(_lit_model(), [], [], 'bike') is None


def test_build_track_glb_without_a_glow_model() -> None:
    flame = ObjectPlacement(40, 50, 60, (), (0xF0, 0x3C, 0x3C))
    glb = build_track_glb([_triangle_mesh(lit=False)], [_translucent_texture()], [flame], None,
                          'track')
    assert glb is not None


def test_iter_models_yields_a_flat_model() -> None:
    model = _lit_model()
    assert [suffix for suffix, _blob in iter_models(model)] == ['']


def test_iter_models_walks_a_sub_archive(make_sub_archive: Callable[..., bytes]) -> None:
    blob = make_sub_archive([_lit_model(), b'\x00' * 32])
    models = list(iter_models(blob))
    assert len(models) == 1
    assert models[0][0].startswith('_')


def test_build_clip_glb_without_a_skeleton() -> None:
    clip = BmcClip('walk.asf', 3, [[float(v)] * 3 for v in range(9)])
    glb = build_clip_glb(clip, 'anim')
    assert glb is not None
    assert glb[:4] == _GLB_MAGIC


def test_build_clip_glb_with_a_matching_skeleton() -> None:
    skeleton = Skeleton(6, [
        Bone('spine', -1, 3, 6, (0x0A,), _IDENTITY, (0.0, 1.0, 0.0)),
        Bone('tip', 0, 0, 9, (), _IDENTITY, (1.0, 0.0, 0.0)),
    ], (9, 8))
    clip = BmcClip('walk.asf', 3, [[float(v)] * 3 for v in range(skeleton.channels)])
    glb = build_clip_glb(clip, 'anim', skeleton)
    assert glb is not None
    assert glb[:4] == _GLB_MAGIC


def test_build_clip_glb_of_an_empty_clip() -> None:
    assert build_clip_glb(BmcClip('walk.asf', 0, []), 'anim') is None


def test_build_track_glb_places_pickups_and_flames() -> None:
    pickup = ObjectPlacement(10, 20, 30, (_object_model(), _object_model()), (0x3C, 0xF0, 0x3C))
    flame = ObjectPlacement(40, 50, 60, (), (0xF0, 0x3C, 0x3C))
    glb = build_track_glb([_triangle_mesh(lit=False)], [_translucent_texture()], [pickup, flame],
                          _object_model(), 'track', 0.5)
    assert glb is not None
    assert glb[:4] == _GLB_MAGIC


def test_build_track_glb_without_placements_falls_back() -> None:
    glb = build_track_glb([_triangle_mesh(lit=False)], [_translucent_texture()], [], None, 'track')
    assert glb is not None


def test_build_track_glb_of_nothing() -> None:
    assert build_track_glb([], [], [], None, 'track') is None
