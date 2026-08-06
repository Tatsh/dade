"""Tests for :mod:`destin.thps2pc.render`."""
from __future__ import annotations

from typing import TYPE_CHECKING

from destin.thps2pc import render
from destin.thps2pc.psx import Scene
from destin.thps2pc.test_utils import SectorSpec, face_record, psx_scene

if TYPE_CHECKING:
    from destin.thps2pc.raster import Framebuffer


def _body(framebuffer: Framebuffer) -> bytes:
    return framebuffer.to_ppm().split(b'255\n', 1)[1]


def test_render_authoritative_produces_the_requested_canvas(scene: Scene) -> None:
    framebuffer = render.render_authoritative(scene, width=40, height=30, padding=2)
    assert (framebuffer.width, framebuffer.height) == (40, 30)
    assert len(_body(framebuffer)) == 40 * 30 * 3


def test_render_authoritative_draws_something(scene: Scene) -> None:
    framebuffer = render.render_authoritative(scene, width=40, height=30, padding=2)
    assert set(_body(framebuffer)) != {20, 28}


def test_render_authoritative_honours_placement(scene: Scene) -> None:
    placed = render.render_authoritative(scene, width=40, height=30, padding=2)
    unplaced = render.render_authoritative(scene, width=40, height=30, padding=2, placement=False)
    assert len(_body(placed)) == len(_body(unplaced)) == 40 * 30 * 3
    assert _body(placed) != _body(unplaced)


def test_render_authoritative_can_hide_the_nonrendering_layer() -> None:
    visible = face_record((0, 1, 2), flags=0x11)
    hidden = face_record((0, 1, 2), flags=0x11 | 0x80)
    spec = SectorSpec(vertices=((0, 0, 0), (100, 0, 0), (0, 0, 100)),
                      faces=(visible, hidden),
                      count_b=0)
    parsed = Scene.parse(psx_scene(sectors=(spec,), checksums=(1,)))
    shown = render.render_authoritative(parsed, width=32, height=32, padding=2)
    culled = render.render_authoritative(parsed, width=32, height=32, padding=2, hide=True)
    assert _body(shown) == _body(culled)


def _mixed_scenes() -> tuple[Scene, Scene]:
    vertices = ((0, 0, 0), (100, 0, 0), (0, 0, 100))
    drawable = face_record((0, 1, 2), flags=0x11)
    untextured = face_record((0, 1, 2), flags=0x10)
    dangling = face_record((0, 1, 200), flags=0x11)
    only_drawable = SectorSpec(vertices=vertices, faces=(drawable,), count_b=0)
    mixed = SectorSpec(vertices=vertices, faces=(drawable, untextured, dangling), count_b=0)
    return (Scene.parse(psx_scene(sectors=(only_drawable,), checksums=(1,))),
            Scene.parse(psx_scene(sectors=(mixed,), checksums=(1,))))


def test_render_authoritative_skips_untextured_and_dangling_faces() -> None:
    reference, mixed = _mixed_scenes()
    assert _body(render.render_authoritative(mixed, width=32, height=32, padding=2)) == _body(
        render.render_authoritative(reference, width=32, height=32, padding=2))


def test_render_layers_skips_untextured_and_dangling_faces() -> None:
    reference, mixed = _mixed_scenes()
    assert _body(render.render_layers(mixed, width=32, height=32, padding=2)) == _body(
        render.render_layers(reference, width=32, height=32, padding=2))


def test_render_layers_uses_the_layer_palette() -> None:
    faces = tuple(face_record((0, 1, 2), flags=0x11 | layer) for layer in (0x00, 0x40, 0x80, 0xC0))
    spec = SectorSpec(vertices=((0, 0, 0), (200, 0, 0), (0, 0, 200)), faces=faces, count_b=0)
    parsed = Scene.parse(psx_scene(sectors=(spec,), checksums=(1,)))
    body = _body(render.render_layers(parsed, width=48, height=48, padding=2))
    assert bytes(render.LAYER_COLORS[0xC0]) in body


def test_render_node_map_returns_marker_positions(scene: Scene) -> None:
    nodes = (render.SceneryNode('a', 0, 0), render.SceneryNode('b', 100, 100))
    framebuffer, marks = render.render_node_map(scene, nodes, width=64, height=64, padding=2)
    assert len(marks) == 2
    assert all(0 <= mark[0] <= 64 for mark in marks)
    assert bytes((255, 255, 0)) in _body(framebuffer)


def test_render_node_map_accepts_no_nodes(scene: Scene) -> None:
    _, marks = render.render_node_map(scene, (), width=32, height=32, padding=2)
    assert marks == ()


def test_hangar_nodes_are_present() -> None:
    assert len(render.HANGAR_SCENERY_NODES) == 17
    assert render.HANGAR_SCENERY_NODES[0] == render.SceneryNode('109', 5780, -4168)


def test_render_objects_applies_a_highlight(scene: Scene) -> None:
    framebuffer = render.render_objects(scene,
                                        scene,
                                        width=48,
                                        height=48,
                                        padding=2,
                                        highlights={0: (255, 0, 0)})
    assert bytes((255, 0, 0)) in _body(framebuffer)


def test_render_objects_draws_the_level_in_grey_under_the_objects(scene: Scene) -> None:
    record = face_record((0, 1, 2), flags=0x11)
    spec = SectorSpec(vertices=((400, 0, 400), (600, 0, 400), (400, 0, 600)),
                      faces=(record,),
                      count_b=0)
    objects = Scene.parse(psx_scene(sectors=(spec,), checksums=(1,)))
    body = _body(render.render_objects(scene, objects, width=64, height=64, padding=2))
    assert bytes((70, 70, 80)) in body
    assert bytes((255, 50, 50)) in body


def test_render_object_models_yields_one_tile_per_sector(scene: Scene) -> None:
    tiles = list(render.render_object_models(scene, size=24, padding=2))
    assert len(tiles) == len(scene.sectors)
    assert all(framebuffer.width == 24 for _, framebuffer in tiles)


def test_render_object_models_handles_a_sector_without_geometry() -> None:
    spec = SectorSpec(vertices=(), faces=(), count_b=0)
    parsed = Scene.parse(psx_scene(sectors=(spec,)))
    tiles = list(render.render_object_models(parsed, size=16, padding=2))
    assert len(tiles) == 1
    assert set(_body(tiles[0][1])) == {20, 28}
