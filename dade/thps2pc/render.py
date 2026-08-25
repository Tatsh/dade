"""
Top-down and isometric renderers for ``.PSX`` scenes.

Every renderer here projects a scene with :py:mod:`dade.thps2pc.raster` and returns a
:py:class:`dade.thps2pc.raster.Framebuffer`, leaving the caller to decide where the image goes.
The top-down views drop the y axis and draw x against z; the model view uses an isometric
projection with a depth buffer instead.

Faces are decoded with the flag-derived corner count and the strip triangulation, matching the
original renderers.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import colorsys
import logging
import math
import operator

from .raster import Framebuffer, fit, project_isometric

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from .psx import Scene, Sector
    from .typing import Point, Rgb, Vector3

__all__ = ('HANGAR_SCENERY_NODES', 'LAYER_COLORS', 'SceneryNode', 'render_authoritative',
           'render_layers', 'render_node_map', 'render_object_models', 'render_objects')

log = logging.getLogger(__name__)

LAYER_COLORS: dict[int, Rgb] = {
    0x00: (110, 110, 110),
    0x40: (70, 120, 230),
    0x80: (230, 60, 60),
    0xC0: (60, 210, 80)
}
"""Colour for each render layer: permanent, then the three conditional layers.

:meta hide-value:
"""

_GREY = (70, 70, 80)
_HANGAR_BACKGROUND = (15, 15, 20)
_LIGHT = (0.3, -0.8, 0.5)
_MODEL_BACKGROUND = (20, 20, 28)
_OBJECT_BACKGROUND = (12, 12, 16)
_TOP_BACKGROUND = (20, 20, 28)


class SceneryNode(NamedTuple):
    """A named point of interest marked on a top-down render."""

    label: str
    """Text drawn beside the marker."""
    x: int
    """Position along the x axis in scene units."""
    z: int
    """Position along the z axis in scene units."""


HANGAR_SCENERY_NODES: tuple[SceneryNode,
                            ...] = (SceneryNode('109', 5780, -4168), SceneryNode(
                                '336', 793, -10666), SceneryNode('342', 1831, -10658),
                                    SceneryNode('355', -7114, -4954), SceneryNode(
                                        '466', -3610, -296), SceneryNode(
                                            '471', 9147, -3173), SceneryNode('472', -5721, -1770),
                                    SceneryNode('473', -5721, -4948), SceneryNode(
                                        '501', 1768, 4337), SceneryNode('632', 7304, -4848),
                                    SceneryNode('633', -5691, 2687), SceneryNode(
                                        '634', 11706, 5747), SceneryNode(
                                            '666', 27, -5481), SceneryNode('667', 280, -1467),
                                    SceneryNode('668', 5517, -3486), SceneryNode(
                                        '669', 9339, -4932), SceneryNode('670', 9298, -1685))
"""
The seventeen scenery-node positions the original tool marked on the Hangar.

These were transcribed from an earlier analysis pass whose source is not part of this package, so
they are not derived from any file read here and apply only to the Hangar.

:meta hide-value:
"""


def _sector_color(index: int) -> Rgb:
    hashed = (index * 2654435761) & 0xFFFFFFFF
    return (60 + (hashed & 0x7F) + 32, 60 + ((hashed >> 8) & 0x7F) + 32,
            60 + ((hashed >> 16) & 0x7F) + 32)


def _top_down_triangles(scene: Scene,
                        *,
                        placement: bool = True,
                        hide: bool = False,
                        textured_only: bool = True) -> Iterator[tuple[Sector, tuple[Point, ...]]]:
    origins = scene.placement() if placement else {}
    for sector in scene.sectors:
        origin: Vector3 = origins.get(sector.index, (0, 0, 0))
        vertices = scene.vertices(sector, origin)
        count = len(vertices)
        for face, slots in scene.triangles(sector):
            if textured_only and not face.is_textured:
                continue
            if hide and face.is_hidden:
                continue
            if any(face.corners[slot] >= count for slot in slots):
                continue
            yield sector, tuple((vertices[face.corners[slot]][0], vertices[face.corners[slot]][2])
                                for slot in slots)


def _draw(framebuffer: Framebuffer, triangles: Sequence[tuple[tuple[Point, ...], Rgb]],
          padding: int) -> None:
    projection = fit((point for corners, _ in triangles for point in corners), framebuffer.width,
                     framebuffer.height, padding)
    for corners, color in triangles:
        framebuffer.fill_triangle([projection.apply(point) for point in corners], color)


def render_authoritative(scene: Scene,
                         *,
                         width: int = 1200,
                         height: int = 850,
                         padding: int = 20,
                         placement: bool = True,
                         hide: bool = False) -> Framebuffer:
    """
    Render a scene from above using the descriptor table's instance placement.

    Each sector is tinted by a hash of its index so neighbouring sectors stay distinguishable.

    Parameters
    ----------
    scene : Scene
        The scene to render.
    width : int
        Canvas width in pixels.
    height : int
        Canvas height in pixels.
    padding : int
        Margin in pixels to leave on every side.
    placement : bool
        Whether to offset each sector by its descriptor's world position.
    hide : bool
        Whether to drop faces on the non-rendering layer.

    Returns
    -------
    Framebuffer
        The rendered image.
    """
    triangles = [(corners, _sector_color(sector.index))
                 for sector, corners in _top_down_triangles(scene, placement=placement, hide=hide)]
    framebuffer = Framebuffer(width, height, _TOP_BACKGROUND)
    _draw(framebuffer, triangles, padding)
    log.debug('Rendered %d triangles.', len(triangles))
    return framebuffer


def render_layers(scene: Scene,
                  *,
                  width: int = 1400,
                  height: int = 1000,
                  padding: int = 20) -> Framebuffer:
    """
    Render a scene from above with each face coloured by its render layer.

    Layers are drawn lowest first so the conditional layers stay visible on top of the permanent
    geometry.

    Parameters
    ----------
    scene : Scene
        The scene to render.
    width : int
        Canvas width in pixels.
    height : int
        Canvas height in pixels.
    padding : int
        Margin in pixels to leave on every side.

    Returns
    -------
    Framebuffer
        The rendered image.
    """
    order = {0x00: 0, 0x40: 1, 0x80: 2, 0xC0: 3}
    collected: list[tuple[int, tuple[Point, ...], Rgb]] = []
    origins = scene.placement()
    for sector in scene.sectors:
        origin: Vector3 = origins.get(sector.index, (0, 0, 0))
        vertices = scene.vertices(sector, origin)
        count = len(vertices)
        for face, slots in scene.triangles(sector):
            if not face.is_textured or any(face.corners[slot] >= count for slot in slots):
                continue
            corners = tuple((vertices[face.corners[slot]][0], vertices[face.corners[slot]][2])
                            for slot in slots)
            collected.append((order[face.layer], corners, LAYER_COLORS[face.layer]))
    collected.sort(key=operator.itemgetter(0))
    framebuffer = Framebuffer(width, height, _HANGAR_BACKGROUND)
    _draw(framebuffer, [(corners, color) for _, corners, color in collected], padding)
    log.debug('Rendered %d triangles across %d layers.', len(collected), len(order))
    return framebuffer


def render_node_map(scene: Scene,
                    nodes: Sequence[SceneryNode],
                    *,
                    width: int = 1500,
                    height: int = 1050,
                    padding: int = 30) -> tuple[Framebuffer, tuple[Point, ...]]:
    """
    Render a scene from above in flat grey with scenery nodes marked.

    Parameters
    ----------
    scene : Scene
        The scene to render.
    nodes : Sequence[SceneryNode]
        Nodes to mark. Their positions are included when fitting the view.
    width : int
        Canvas width in pixels.
    height : int
        Canvas height in pixels.
    padding : int
        Margin in pixels to leave on every side.

    Returns
    -------
    tuple[Framebuffer, tuple[Point, ...]]
        The rendered image and each node's device-space position, so labels can be added
        afterwards.
    """
    triangles = [corners for _, corners in _top_down_triangles(scene, hide=True)]
    points = [point for corners in triangles for point in corners]
    points.extend((float(node.x), float(node.z)) for node in nodes)
    projection = fit(points, width, height, padding)
    framebuffer = Framebuffer(width, height, _HANGAR_BACKGROUND)
    for corners in triangles:
        framebuffer.fill_triangle([projection.apply(point) for point in corners], _GREY)
    marks = []
    for node in nodes:
        center = projection.apply((float(node.x), float(node.z)))
        framebuffer.fill_disc(center, 9, (255, 40, 40))
        framebuffer.fill_disc(center, 4, (255, 255, 0))
        marks.append(center)
    log.debug('Rendered %d triangles and %d nodes.', len(triangles), len(nodes))
    return framebuffer, tuple(marks)


def render_object_models(scene: Scene,
                         *,
                         size: int = 220,
                         padding: int = 14) -> Iterator[tuple[Sector, Framebuffer]]:
    """
    Render every sector of an object scene as its own flat-shaded isometric tile.

    Parameters
    ----------
    scene : Scene
        The object scene to render.
    size : int
        Width and height of each tile in pixels.
    padding : int
        Margin in pixels to leave on every side of a tile.

    Yields
    ------
    tuple[Sector, Framebuffer]
        Each sector and its rendered tile, including sectors with no drawable geometry.
    """
    length = math.sqrt(sum(component * component for component in _LIGHT)) or 1.0
    light = tuple(component / length for component in _LIGHT)
    for sector in scene.sectors:
        vertices = scene.vertices(sector)
        count = len(vertices)
        triangles = [
            tuple(vertices[face.corners[slot]] for slot in slots)
            for face, slots in scene.triangles(sector)
            if face.is_textured and not face.is_hidden and not any(face.corners[slot] >= count
                                                                   for slot in slots)
        ]
        framebuffer = Framebuffer(size, size, _MODEL_BACKGROUND)
        if not triangles:
            yield sector, framebuffer
            continue
        projection = fit((project_isometric(vertex) for corners in triangles for vertex in corners),
                         size, size, padding)
        for corners in triangles:
            first, second, third = corners
            edge_a = tuple(second[i] - first[i] for i in range(3))
            edge_b = tuple(third[i] - first[i] for i in range(3))
            normal = (edge_a[1] * edge_b[2] - edge_a[2] * edge_b[1],
                      edge_a[2] * edge_b[0] - edge_a[0] * edge_b[2],
                      edge_a[0] * edge_b[1] - edge_a[1] * edge_b[0])
            magnitude = math.sqrt(sum(component * component for component in normal)) or 1.0
            shade = abs(sum(normal[i] * light[i] for i in range(3)) / magnitude)
            brightness = int(60 + shade * 175)
            depth = float(sum(vertex[0] + vertex[2] for vertex in corners))
            framebuffer.fill_triangle([projection.apply(project_isometric(v)) for v in corners],
                                      (brightness, brightness, min(255, brightness + 15)), depth)
        yield sector, framebuffer


def render_objects(level: Scene,
                   objects: Scene,
                   *,
                   width: int = 1400,
                   height: int = 1000,
                   padding: int = 20,
                   highlights: dict[int, Rgb] | None = None) -> Framebuffer:
    """
    Render a level from above in grey with a second scene's objects drawn over it in colour.

    Parameters
    ----------
    level : Scene
        The level scene, drawn in flat grey.
    objects : Scene
        The object scene, drawn with one colour per sector.
    width : int
        Canvas width in pixels.
    height : int
        Canvas height in pixels.
    padding : int
        Margin in pixels to leave on every side.
    highlights : dict[int, Rgb] | None
        Explicit colours for particular object sector indices. Any other sector cycles through
        hues derived from its index.

    Returns
    -------
    Framebuffer
        The rendered image.
    """
    chosen = highlights or {}
    triangles: list[tuple[tuple[Point, ...],
                          Rgb]] = [(corners, _GREY)
                                   for _, corners in _top_down_triangles(level, hide=True)]
    for sector, corners in _top_down_triangles(objects, hide=True):
        if (color := chosen.get(sector.index)) is None:
            red, green, blue = colorsys.hsv_to_rgb((sector.index * 0.13) % 1.0, 0.8, 1.0)
            color = (int(red * 255), int(green * 255), int(blue * 255))
        triangles.append((corners, color))
    framebuffer = Framebuffer(width, height, _OBJECT_BACKGROUND)
    _draw(framebuffer, triangles, padding)
    log.debug('Rendered %d triangles.', len(triangles))
    return framebuffer
