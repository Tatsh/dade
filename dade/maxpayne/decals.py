"""Pull coplanar surfaces apart so a viewer's depth buffer can tell them apart."""
from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Hashable, Sequence

    from .typing import Vector3

__all__ = ('DECAL_STEP', 'layer_faces')

DECAL_STEP = 1.0 / 128.0
"""How far apart to hold two surfaces that share a plane, in level units.

A level unit is about a metre, so this lifts a graffiti tag eight millimetres off its wall: far
too little to see, and far enough that a depth buffer stops guessing which one is in front."""

_NORMAL_STEPS = 128.0
"""Grid the normal is rounded onto when deciding whether two faces face the same way."""

_AWAY_STEPS = 16.0
"""Grid a plane's distance from the origin is rounded onto."""

_CELL = 4.0
"""Side of the square the in-plane index buckets faces into."""

_TOUCH = 0.03
"""Overlap two boxes must share before they count as stacked rather than merely adjacent.

Level architecture is tiled, so a wall is many faces whose boxes meet along their edges. Without
this every tile would read as covering its neighbour."""

_FLAT = 1e-9
"""Below this a normal is too short to say which way a face points."""

_PAIR = 2
"""Faces a plane needs before anything on it can be covering anything else."""


def _frame(normal: Vector3) -> tuple[Vector3, Vector3]:
    """
    Pick two axes spanning the plane a normal describes.

    Parameters
    ----------
    normal : Vector3
        A unit normal.

    Returns
    -------
    tuple[Vector3, Vector3]
        Two perpendicular unit vectors lying in the plane.
    """
    x, y, z = normal
    # Cross with whichever axis the normal leans on least, so the result is never degenerate.
    other = (0.0, 0.0, 1.0) if abs(z) < abs(x) or abs(z) < abs(y) else (1.0, 0.0, 0.0)
    ax = y * other[2] - z * other[1]
    ay = z * other[0] - x * other[2]
    az = x * other[1] - y * other[0]
    length = (ax * ax + ay * ay + az * az) ** 0.5 or 1.0
    first = (ax / length, ay / length, az / length)
    return first, (y * first[2] - z * first[1], z * first[0] - x * first[2],
                   x * first[1] - y * first[0])


def _profile(normal: Vector3,
             corners: Sequence[Vector3]) -> tuple[tuple[int, ...], tuple[float, ...]] | None:
    """
    Reduce a face to the plane it lies in and the box it covers within that plane.

    Parameters
    ----------
    normal : Vector3
        The face's outward normal, which need not be unit length.
    corners : collections.abc.Sequence[Vector3]
        The face's corners.

    Returns
    -------
    tuple[tuple[int, ...], tuple[float, ...]] | None
        The quantised plane and the box, or :py:obj:`None` when the face has no plane.
    """
    length = sum(v * v for v in normal) ** 0.5
    if length < _FLAT or not corners:
        return None
    unit = (normal[0] / length, normal[1] / length, normal[2] / length)
    first, second = _frame(unit)
    flat = [(sum(f * p for f, p in zip(first, corner, strict=True)),
             sum(s * p for s, p in zip(second, corner, strict=True))) for corner in corners]
    away = sum(n * p for n, p in zip(unit, corners[0], strict=True))
    # A face and one turned to face the other way never hide each other, so the sign is kept.
    plane = (*(round(v * _NORMAL_STEPS) for v in unit), round(away * _AWAY_STEPS))
    box = (min(p[0] for p in flat), min(p[1] for p in flat), max(
        p[0] for p in flat), max(p[1] for p in flat))
    return plane, box


def _stacked(one: Sequence[float], two: Sequence[float]) -> bool:
    """
    Say whether two in-plane boxes cover a shared patch rather than merely meeting.

    Parameters
    ----------
    one : collections.abc.Sequence[float]
        A box as minimum and maximum on both axes.
    two : collections.abc.Sequence[float]
        The other box.

    Returns
    -------
    bool
        :py:obj:`True` when the two share more than a seam.
    """
    return (min(one[2], two[2]) - max(one[0], two[0]) > _TOUCH
            and min(one[3], two[3]) - max(one[1], two[1]) > _TOUCH)


def _cells(box: Sequence[float]) -> list[tuple[int, int]]:
    """
    List the index squares a box touches.

    Parameters
    ----------
    box : collections.abc.Sequence[float]
        A box as minimum and maximum on both axes.

    Returns
    -------
    list[tuple[int, int]]
        The squares, as integer coordinates.
    """
    return [(x, y) for x in range(int(box[0] // _CELL),
                                  int(box[2] // _CELL) + 1)
            for y in range(int(box[1] // _CELL),
                           int(box[3] // _CELL) + 1)]


def layer_faces(surfaces: Sequence[tuple[Vector3, Sequence[Vector3], Hashable]]) -> list[int]:
    """
    Work out how far off its plane each face has to sit to stop fighting the ones behind it.

    A level draws graffiti, signs and stains as their own polygons laid exactly on the wall, and
    keeps every variant of a switchable surface -- a television showing static or a programme, a
    neon sign lit or dark -- in the same place. The engine chose between them and drew what was
    left in tree order, so none of it ever fought. A viewer that draws the whole level at once has
    only its depth buffer to go on, and two surfaces at the same depth flicker against each other.

    Faces are considered in order of the area they cover, so the surface underneath keeps the
    plane the level gave it and only the smaller things laid over it move.

    Faces are stacked only when they belong to different surfaces, which is what the key says.
    Two faces of one mesh drawing with one material are two pieces of the same thing: a quad split
    along its diagonal gives two triangles with the same bounding box, and lifting either off the
    other opens a hairline crack down the middle of every table top in the level. Two copies of a
    prop, or a tag and the wall behind it, differ in one or the other and do stack.

    Parameters
    ----------
    surfaces : collections.abc.Sequence
        One entry per face: its outward normal, its corners in the space they will be drawn in,
        and a hashable key naming the surface it belongs to.

    Returns
    -------
    list[int]
        How many steps of :py:data:`DECAL_STEP` to lift each face along its normal, one entry per
        face given, and zero for anything nothing else is stacked on.
    """
    boxes: dict[int, tuple[float, ...]] = {}
    planes: defaultdict[tuple[int, ...], list[int]] = defaultdict(list)
    drawn = [key for _normal, _corners, key in surfaces]
    for index, (normal, corners, _key) in enumerate(surfaces):
        found = _profile(normal, corners)
        if found is not None:
            planes[found[0]].append(index)
            boxes[index] = found[1]
    out = [0] * len(surfaces)
    for members in planes.values():
        if len(members) < _PAIR:
            continue
        grid: defaultdict[tuple[int, int], list[int]] = defaultdict(list)
        widest = sorted(members,
                        key=lambda i: -(boxes[i][2] - boxes[i][0]) * (boxes[i][3] - boxes[i][1]))
        for index in widest:
            box = boxes[index]
            squares = _cells(box)
            below = -1
            for square in squares:
                for other in grid[square]:
                    if drawn[other] != drawn[index] and _stacked(box, boxes[other]):
                        below = max(below, out[other])
            out[index] = below + 1
            for square in squares:
                grid[square].append(index)
    return out
