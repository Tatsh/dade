"""Shared typing helpers for :py:mod:`dade.thps2pc`."""
from __future__ import annotations

from typing import TypeAlias, TypedDict

__all__ = ('CornerSource', 'MeshBatch', 'MeshManifest', 'Point', 'Rgb', 'Triangulation', 'Vector3')

CornerSource: TypeAlias = str
"""How a face's corner count is derived: ``'flag'`` or ``'length'``.

:meta hide-value:
"""

Point: TypeAlias = tuple[float, float]
"""A two-dimensional point in device space.

:meta hide-value:
"""

Rgb: TypeAlias = tuple[int, int, int]
"""An 8-bit-per-channel colour.

:meta hide-value:
"""

Triangulation: TypeAlias = str
"""How a quad is split into two triangles: ``'strip'`` or ``'fan'``.

:meta hide-value:
"""

Vector3: TypeAlias = tuple[int, int, int]
"""An integer position in the scene's world space.

:meta hide-value:
"""


class MeshBatch(TypedDict):
    """A run of triangle vertices that share a single texture."""

    texture: str | None
    """Texture checksum as eight uppercase hexadecimal digits, or ``None`` when untextured."""
    first_vertex: int
    """Index of the batch's first vertex within the interleaved vertex buffer."""
    vertex_count: int
    """Number of vertices the batch contributes to the buffer."""


class MeshManifest(TypedDict):
    """Description of an exported mesh and the batches that make it up."""

    scale: float
    """Uniform scale factor to apply to the packed vertex positions."""
    batches: list[MeshBatch]
    """Every batch, ordered as its vertices appear in the buffer."""
