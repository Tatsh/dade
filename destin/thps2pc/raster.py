"""
Small software rasteriser used by the scene renderers.

The original tools each carried their own copy of a barycentric triangle fill writing into a flat
RGB byte buffer, which was then handed to ImageMagick as a binary PPM. That fill lives here once.
A triangle is covered when a pixel's three edge functions share a sign, so both winding
directions are drawn and no back-face culling happens.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import math

from destin.common.ppm import ppm

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from .typing import Point, Rgb, Vector3

__all__ = ('Framebuffer', 'Projection', 'fit', 'project_isometric')

log = logging.getLogger(__name__)

_EPSILON = 1e-6
_ISO_X = 0.707
_ISO_Y = 0.408


class Projection:
    """Maps scene coordinates onto device pixels, preserving aspect ratio."""
    def __init__(self, minimum: Point, maximum: Point, width: int, height: int,
                 padding: int) -> None:
        self._min = minimum
        self._padding = padding
        span_x = max(maximum[0] - minimum[0], _EPSILON)
        span_y = max(maximum[1] - minimum[1], _EPSILON)
        available_x = max(width - 2 * padding, 1)
        available_y = max(height - 2 * padding, 1)
        self._scale = min(available_x / span_x, available_y / span_y)

    @property
    def scale(self) -> float:
        """Uniform scale factor applied to both axes."""
        return self._scale

    def apply(self, point: Point) -> Point:
        """
        Project one scene point to device space.

        Parameters
        ----------
        point : Point
            The scene point.

        Returns
        -------
        Point
            The device-space point.
        """
        return (self._padding + (point[0] - self._min[0]) * self._scale,
                self._padding + (point[1] - self._min[1]) * self._scale)


class Framebuffer:
    """A flat RGB pixel buffer with an optional depth buffer."""
    def __init__(self, width: int, height: int, background: Rgb = (0, 0, 0)) -> None:
        self.height = height
        """Height of the buffer in pixels."""
        self.width = width
        """Width of the buffer in pixels."""
        self._depth = [math.inf] * (width * height)
        self._pixels = bytearray(bytes(background) * (width * height))

    def fill_disc(self, center: Point, radius: int, color: Rgb) -> None:
        """
        Fill a filled circle centred on a device-space point.

        Parameters
        ----------
        center : Point
            Centre of the disc in device space.
        radius : int
            Radius in pixels.
        color : Rgb
            Colour to write.
        """
        cx, cy = int(center[0]), int(center[1])
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx * dx + dy * dy <= radius * radius:
                    self.put(cx + dx, cy + dy, color)

    def fill_triangle(self,
                      points: Sequence[Point],
                      color: Rgb,
                      depth: float | None = None) -> None:
        """
        Fill a triangle, optionally testing and updating the depth buffer.

        Degenerate triangles are skipped.

        Parameters
        ----------
        points : Sequence[Point]
            The three device-space corners.
        color : Rgb
            Colour to write.
        depth : float | None
            Depth key for the whole triangle. When given, a pixel is written only if this key is
            nearer than what the depth buffer already holds.
        """
        (x0, y0), (x1, y1), (x2, y2) = points[0], points[1], points[2]
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(area) < _EPSILON:
            return
        min_x = max(0, int(min(x0, x1, x2)))
        max_x = min(self.width - 1, int(max(x0, x1, x2)))
        min_y = max(0, int(min(y0, y1, y2)))
        max_y = min(self.height - 1, int(max(y0, y1, y2)))
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                w0 = (x1 - x) * (y2 - y) - (x2 - x) * (y1 - y)
                w1 = (x2 - x) * (y0 - y) - (x0 - x) * (y2 - y)
                w2 = (x0 - x) * (y1 - y) - (x1 - x) * (y0 - y)
                if not ((w0 >= 0 and w1 >= 0 and w2 >= 0) or (w0 <= 0 and w1 <= 0 and w2 <= 0)):
                    continue
                if depth is not None:
                    index = y * self.width + x
                    if depth >= self._depth[index]:
                        continue
                    self._depth[index] = depth
                self.put(x, y, color)

    def put(self, x: int, y: int, color: Rgb) -> None:
        """
        Write one pixel, ignoring coordinates outside the buffer.

        Parameters
        ----------
        x : int
            Column index.
        y : int
            Row index.
        color : Rgb
            Colour to write.
        """
        if 0 <= x < self.width and 0 <= y < self.height:
            offset = (y * self.width + x) * 3
            self._pixels[offset:offset + 3] = bytes(color)

    def to_ppm(self) -> bytes:
        """
        Serialise the buffer as a binary PPM image.

        Returns
        -------
        bytes
            A complete binary PPM image.
        """
        return ppm(bytes(self._pixels), self.width, self.height)


def fit(points: Iterable[Point], width: int, height: int, padding: int) -> Projection:
    """
    Build a projection that fits every point inside a padded canvas.

    Parameters
    ----------
    points : Iterable[Point]
        The points that must be visible.
    width : int
        Canvas width in pixels.
    height : int
        Canvas height in pixels.
    padding : int
        Margin in pixels to leave on every side. A canvas too small to hold twice the padding
        still yields at least one usable pixel per axis rather than a mirrored image.

    Returns
    -------
    Projection
        A projection covering the points' bounding box.

    Raises
    ------
    ValueError
        If no points are supplied.
    """
    collected = list(points)
    if not collected:
        msg = 'Cannot fit a projection to an empty set of points.'
        raise ValueError(msg)
    xs = [p[0] for p in collected]
    ys = [p[1] for p in collected]
    return Projection((min(xs), min(ys)), (max(xs), max(ys)), width, height, padding)


def project_isometric(vertex: Vector3) -> Point:
    """
    Project a scene vertex isometrically, with x and z running right and y running up.

    Parameters
    ----------
    vertex : Vector3
        The scene vertex.

    Returns
    -------
    Point
        The projected point.
    """
    x, y, z = vertex
    return ((x - z) * _ISO_X, -y + (x + z) * _ISO_Y)
