"""
Diagnostics that cross-reference a scene's mesh descriptors against its sector geometry.

The report answers the questions the original investigation script asked: whether sector vertices
are stored local to their placement or already baked into world space, whether descriptor *i*
places sector *i*, and what the chunk list contains. It is a reading aid for reverse engineering
rather than a converter, so it only ever produces text.
"""
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, NamedTuple
import logging
import statistics

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from .psx import Scene
    from .typing import Vector3

__all__ = ('CENTROID_TOLERANCE', 'LOCAL_THRESHOLD', 'SectorBounds', 'describe', 'sector_bounds')

log = logging.getLogger(__name__)

CENTROID_TOLERANCE = 50
"""Distance within which a descriptor position counts as matching a sector centroid.

:meta hide-value:
"""
LOCAL_THRESHOLD = 200
"""Centroid magnitude below which a sector's vertices look local rather than world-baked.

:meta hide-value:
"""

_PREVIEW_ROWS = 16
_TOP_VALUES = 12


class SectorBounds(NamedTuple):
    """Aggregate geometry for one sector."""

    centroid: Vector3
    """Mean vertex position, rounded towards zero."""
    extent: Vector3
    """Size of the axis-aligned bounding box."""
    vertex_count: int
    """Number of vertices the sector holds."""


def sector_bounds(scene: Scene) -> tuple[SectorBounds, ...]:
    """
    Compute the centroid, extent, and vertex count of every sector.

    Parameters
    ----------
    scene : Scene
        The scene to measure.

    Returns
    -------
    tuple[SectorBounds, ...]
        One entry per sector, in table order. Empty sectors report zeroes.
    """
    bounds = []
    for sector in scene.sectors:
        vertices = scene.vertices(sector)
        if not vertices:
            bounds.append(SectorBounds((0, 0, 0), (0, 0, 0), 0))
            continue
        axes = tuple([vertex[axis] for vertex in vertices] for axis in range(3))
        count = len(vertices)
        bounds.append(
            SectorBounds(
                centroid=(sum(axes[0]) // count, sum(axes[1]) // count, sum(axes[2]) // count),
                extent=(max(axes[0]) - min(axes[0]), max(axes[1]) - min(axes[1]),
                        max(axes[2]) - min(axes[2])),
                vertex_count=count))
    return tuple(bounds)


def _matches_any(position: Vector3, bounds: Sequence[SectorBounds], tolerance: int) -> int:
    for index, entry in enumerate(bounds):
        if all(abs(entry.centroid[axis] - position[axis]) < tolerance for axis in range(3)):
            return index
    return -1


def describe(scene: Scene) -> Iterator[str]:
    """
    Produce the diagnostic report for a scene, one line at a time.

    Parameters
    ----------
    scene : Scene
        The scene to report on.

    Yields
    ------
    str
        Each line of the report, without a trailing newline.
    """
    bounds = sector_bounds(scene)
    yield (f'numMeshSections={len(scene.descriptors)} numSectors={len(scene.sectors)} '
           f'chunkListOff={scene.chunk_list_offset:#x}')
    yield ''
    yield 'Are sector centroids near the origin (which would mean local vertices)?'
    near = sum(1 for entry in bounds if all(
        abs(entry.centroid[axis]) < LOCAL_THRESHOLD for axis in range(3)))
    yield f'  sectors with |centroid| < {LOCAL_THRESHOLD} on all axes: {near}/{len(bounds)}'
    if bounds:
        medians = tuple(
            statistics.median(abs(entry.centroid[axis]) for entry in bounds) for axis in range(3))
        yield (f'  centroid |x| median={medians[0]:.0f} |y| median={medians[1]:.0f} '
               f'|z| median={medians[2]:.0f}')
    yield ''
    yield 'Descriptor[i] against the centroid of sector[i] and sector[i+1]:'
    yield '  i | desc.pos              | sect[i].cent           | sect[i+1].cent'
    for index in range(min(_PREVIEW_ROWS, len(scene.descriptors))):
        position = scene.descriptors[index].position
        current = bounds[index].centroid if index < len(bounds) else (0, 0, 0)
        following = bounds[index + 1].centroid if index + 1 < len(bounds) else (0, 0, 0)
        yield (f'  {index:3} | {position[0]:6},{position[1]:6},{position[2]:6} | '
               f'{current[0]:6},{current[1]:6},{current[2]:6} | '
               f'{following[0]:6},{following[1]:6},{following[2]:6}')
    yield ''
    yield 'Does a descriptor position equal some sector centroid (world-baked vertices)?'
    hits = sum(1 for descriptor in scene.descriptors
               if _matches_any(descriptor.position, bounds, CENTROID_TOLERANCE) >= 0)
    yield f'  descriptors whose position matches a sector centroid: {hits}/{len(scene.descriptors)}'
    yield ''
    for name, values in (('flags_18', [d.flags_18 for d in scene.descriptors]), ('flags_1a', [
            d.flags_1a for d in scene.descriptors
    ])):
        yield f'{name} value distribution: {dict(Counter(values).most_common(_TOP_VALUES))}'
    yield (f'bytes_20 distribution: '
           f'{Counter(d.bytes_20 for d in scene.descriptors).most_common(4)}')
    yield ''
    yield '=== CHUNK LIST ==='
    for chunk in scene.chunks():
        identifier = chunk.id if chunk.id < 0 else hex(chunk.id)
        yield f'  off={chunk.offset:#x} id={identifier} size={chunk.size}'
