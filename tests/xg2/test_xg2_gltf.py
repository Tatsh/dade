"""Tests for :mod:`dade.xg2.gltf`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from dade.xg2.bmc import BmcClip
from dade.xg2.f3dex2 import Mesh, Vertex
from dade.xg2.gltf import (
    build_clip_glb,
    build_glb,
    build_level_glb,
    build_pc_glb,
    build_track_glb,
    iter_models,
    pc_bank_size,
)
from dade.xg2.skeleton import Bone, Skeleton
from dade.xg2.typing import Texture
from dade.xg2.xg1_objects import ObjectModel, ObjectPlacement

if TYPE_CHECKING:
    from collections.abc import Callable

_GLB_MAGIC = b'glTF'


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
        Bone('root', -1, 3, 6, (0.0, 1.0, 0.0), (0x0A,)),
        Bone('tip', 0, 0, 9, (1.0, 0.0, 0.0), ()),
    ])
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
