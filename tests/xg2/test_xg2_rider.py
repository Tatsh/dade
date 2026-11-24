"""Tests for :mod:`dade.xg2.rider`."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dade.xg2.rider import MAX_INFLUENCES, parse_rider

if TYPE_CHECKING:
    from collections.abc import Callable

_SIX_BONES = (('hip', -1, 0, (), (0, 0, 0)), *((f'b{i}', 0, 0, (), (0, 0, 0)) for i in range(5)))


def test_parse_rider_reads_the_bind_pose_and_the_weights(make_rider: Callable[..., bytes]) -> None:
    rider = parse_rider(make_rider())
    assert rider is not None
    assert [bone.name for bone in rider.skeleton.bones] == ['hip', 'knee']
    (mesh,) = rider.meshes
    assert mesh.texture == 0x380
    assert mesh.triangles == [(0, 1, 2)]
    assert [(v.x, v.y, v.z) for v in mesh.vertices] == [(0, 0, 0), (100, 0, 0), (0, 100, 0)]
    assert {v.alpha for v in mesh.vertices} == {0xFF}
    # The stored (0, 4, 0) becomes (x, -z, y) at unit length.
    assert (mesh.vertices[0].red, mesh.vertices[0].green, mesh.vertices[0].blue) == (0, 0, 127)
    # The third vertex's S doubles from 0x7000 and wraps.
    assert mesh.vertices[2].s == -0x2000
    # The first position is rigid on bone 0, then half blended towards bone 1.
    assert rider.weights[0][0] == ((1, 2, 0, 0), (0.5, 0.5, 0.0, 0.0))
    assert rider.weights[0][1] == ((2, 0, 0, 0), (1.0, 0.0, 0.0, 0.0))


def test_parse_rider_gives_an_ungrouped_position_to_the_root(
        make_rider: Callable[..., bytes]) -> None:
    rider = parse_rider(make_rider(groups=((0, 0xFFFF, 0, ()),)))
    assert rider is not None
    assert set(rider.weights[0]) == {((0, 0, 0, 0), (1.0, 0.0, 0.0, 0.0))}


def test_parse_rider_ignores_positions_past_the_last(make_rider: Callable[..., bytes]) -> None:
    rider = parse_rider(make_rider(groups=((1, 2, 5, ((9, 0x8000), (2, 0x4000))),)))
    assert rider is not None
    # Blending a position towards the bone it already follows leaves it there.
    assert rider.weights[0][2] == ((2, 0, 0, 0), (1.0, 0.0, 0.0, 0.0))


def test_parse_rider_keeps_the_strongest_influences(make_rider: Callable[..., bytes]) -> None:
    groups = ((0, 0, 3, ()), *((bone, 0xFFFF, 0, ((0, 0xC000),)) for bone in range(1, 6)))
    rider = parse_rider(make_rider(bones=_SIX_BONES, groups=groups))
    assert rider is not None
    joints, weights = rider.weights[0][0]
    assert len(joints) == MAX_INFLUENCES
    assert joints[0] == 6
    assert sum(weights) == pytest.approx(1.0)


@pytest.mark.parametrize('options', [{
    'count': 0
}, {
    'count': 1000
}, {
    'indices': (0, 1, 300)
}, {
    'indices': (0, 1, 255)
}, {
    'skin_magic': b'JUNK'
}, {
    'groups': ((5, 0, 1, ()),)
}])
def test_parse_rider_rejects_a_malformed_rider(make_rider: Callable[..., bytes],
                                               options: dict[str, object]) -> None:
    assert parse_rider(make_rider(**options)) is None


@pytest.mark.parametrize('cut', [4, 16, 24])
def test_parse_rider_rejects_a_truncated_skin(make_rider: Callable[..., bytes], cut: int) -> None:
    model = make_rider()
    assert parse_rider(model[:-cut]) is None


def test_parse_rider_of_a_model_without_a_skeleton() -> None:
    assert parse_rider(b'\x00' * 64) is None
