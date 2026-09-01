from __future__ import annotations

from dade.maxpane.decals import layer_faces

_FLOOR = ((0.0, 0.0, 0.0), (8.0, 0.0, 0.0), (8.0, 0.0, 8.0), (0.0, 0.0, 8.0))
_RUG = ((2.0, 0.0, 2.0), (5.0, 0.0, 2.0), (5.0, 0.0, 5.0), (2.0, 0.0, 5.0))
_UP = (0.0, 1.0, 0.0)


def test_layer_faces_leaves_a_lone_face_alone() -> None:
    assert layer_faces([(_UP, _FLOOR)]) == [0]


def test_layer_faces_lifts_the_smaller_of_two_stacked_faces() -> None:
    assert layer_faces([(_UP, _FLOOR), (_UP, _RUG)]) == [0, 1]


def test_layer_faces_keeps_the_wider_face_on_its_plane_whichever_comes_first() -> None:
    # The rug is given first, but the floor is what the level built and has to stay put.
    assert layer_faces([(_UP, _RUG), (_UP, _FLOOR)]) == [1, 0]


def test_layer_faces_stacks_three_deep() -> None:
    coaster = ((3.0, 0.0, 3.0), (4.0, 0.0, 3.0), (4.0, 0.0, 4.0), (3.0, 0.0, 4.0))
    assert layer_faces([(_UP, _FLOOR), (_UP, _RUG), (_UP, coaster)]) == [0, 1, 2]


def test_layer_faces_ignores_faces_that_only_meet_along_an_edge() -> None:
    # Architecture is tiled, so neighbouring wall panels share a seam and nothing more.
    right = ((8.0, 0.0, 0.0), (16.0, 0.0, 0.0), (16.0, 0.0, 8.0), (8.0, 0.0, 8.0))
    assert layer_faces([(_UP, _FLOOR), (_UP, right)]) == [0, 0]


def test_layer_faces_ignores_a_face_on_a_different_plane() -> None:
    ceiling = tuple((x, 4.0, z) for x, _y, z in _RUG)
    assert layer_faces([(_UP, _FLOOR), (_UP, ceiling)]) == [0, 0]


def test_layer_faces_ignores_a_face_turned_the_other_way() -> None:
    # A viewer never sees both sides of one surface at once, so back to back is not a clash.
    assert layer_faces([(_UP, _FLOOR), ((0.0, -1.0, 0.0), _RUG)]) == [0, 0]


def test_layer_faces_skips_a_face_with_no_plane() -> None:
    assert layer_faces([((0.0, 0.0, 0.0), _FLOOR), (_UP, ()), (_UP, _FLOOR)]) == [0, 0, 0]


def test_layer_faces_handles_a_wall_that_leans_on_z() -> None:
    # The in-plane frame picks a different helper axis for a normal that leans on Z.
    wall = ((0.0, 0.0, 0.0), (0.0, 8.0, 0.0), (8.0, 8.0, 0.0), (8.0, 0.0, 0.0))
    tag = ((2.0, 2.0, 0.0), (2.0, 5.0, 0.0), (5.0, 5.0, 0.0), (5.0, 2.0, 0.0))
    assert layer_faces([((0.0, 0.0, 1.0), wall), ((0.0, 0.0, 1.0), tag)]) == [0, 1]
