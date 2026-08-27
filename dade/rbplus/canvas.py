"""
The surfaces a chart is drawn on.

:py:mod:`dade.rbplus.render` lays a chart out once and draws it through one of these, so the same
geometry comes out as a raster image or as a vector one. The drawing calls follow Pillow's, since
that is where they started.

Coordinates are always in the layout's own units, which are a whole multiple of the finished size
so that the raster surface can be reduced once at the end and smoothed by it. A vector surface has
no such need, and carries the same numbers as its view box instead.

Nothing here writes a page. A chart read in a browser is the business of
:py:mod:`dade.rbplus.commands.site`, which hands the chart over as data and lets the page lay it
out for the window it is opened in.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, NamedTuple, Protocol
import html
import math

from PIL import Image, ImageDraw

from dade.common.fonts import load_font

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path

__all__ = ('Canvas', 'PillowCanvas', 'SVGCanvas', 'canvas_for')

_FULL_TURN = 360.0
_HALF_TURN = 180.0


class _Part(NamedTuple):
    """One drawn shape, with the box it occupies."""

    markup: str
    left: float
    top: float
    right: float
    bottom: float


def _rgb(color: tuple[int, int, int]) -> str:
    return '#{:02x}{:02x}{:02x}'.format(*color)


def _on_ellipse(cx: float, cy: float, rx: float, ry: float, degrees: float) -> tuple[float, float]:
    # Where an angle lands on an ellipse, measured the way the raster surface measures it: clockwise
    # from three o'clock, with the y axis running down the image.
    radians = math.radians(degrees)
    return cx + rx * math.cos(radians), cy + ry * math.sin(radians)


def _paint(fill: tuple[int, int, int] | None, outline: tuple[int, int, int] | None,
           width: float) -> str:
    parts = [f'fill="{_rgb(fill)}"' if fill is not None else 'fill="none"']
    if outline is not None:
        parts.extend((f'stroke="{_rgb(outline)}"', f'stroke-width="{width:g}"'))
    return ' '.join(parts)


def _span(values: Sequence[float]) -> tuple[float, float]:
    return min(values), max(values)


class Canvas(Protocol):
    """What :py:mod:`dade.rbplus.render` draws through."""
    def line(self,
             xy: Sequence[float],
             *,
             fill: tuple[int, int, int],
             width: int = 1,
             joint: str | None = None) -> None:
        """
        Draw a run of connected segments.

        Parameters
        ----------
        xy : collections.abc.Sequence[float]
            Alternating x and y, at least two points.
        fill : tuple[int, int, int]
            The colour to draw in.
        width : int
            How thick the line is.
        joint : str | None
            How to finish the corners between segments. ``'curve'`` rounds them.
        """
        ...

    def rect(self,
             xy: Sequence[float],
             *,
             fill: tuple[int, int, int] | None = None,
             outline: tuple[int, int, int] | None = None,
             width: int = 1) -> None:
        """
        Draw a rectangle.

        Parameters
        ----------
        xy : collections.abc.Sequence[float]
            Left, top, right, and bottom.
        fill : tuple[int, int, int] | None
            The colour to fill with, or ``None`` to leave it hollow.
        outline : tuple[int, int, int] | None
            The colour to outline with, or ``None`` for no outline.
        width : int
            How thick the outline is.
        """
        ...

    def ellipse(self,
                xy: Sequence[float],
                *,
                fill: tuple[int, int, int] | None = None,
                outline: tuple[int, int, int] | None = None,
                width: int = 1) -> None:
        """
        Draw an ellipse within a bounding box.

        Parameters
        ----------
        xy : collections.abc.Sequence[float]
            Left, top, right, and bottom of the box.
        fill : tuple[int, int, int] | None
            The colour to fill with, or ``None`` to leave it hollow.
        outline : tuple[int, int, int] | None
            The colour to outline with, or ``None`` for no outline.
        width : int
            How thick the outline is.
        """
        ...

    def pieslice(self, xy: Sequence[float], start: float, end: float, *, fill: tuple[int, int,
                                                                                     int]) -> None:
        """
        Draw a slice of an ellipse, closed back through its centre.

        Parameters
        ----------
        xy : collections.abc.Sequence[float]
            Left, top, right, and bottom of the box the ellipse fits.
        start : float
            The angle to start at, in degrees clockwise from three o'clock.
        end : float
            The angle to stop at.
        fill : tuple[int, int, int]
            The colour to fill with.
        """
        ...

    def text(self, xy: Sequence[float], body: str, *, fill: tuple[int, int, int],
             size: int) -> None:
        """
        Draw a line of text with its top left corner at *xy*.

        Parameters
        ----------
        xy : collections.abc.Sequence[float]
            The top left corner.
        body : str
            The text.
        fill : tuple[int, int, int]
            The colour to draw in.
        size : int
            The font size, in the layout's own units.
        """
        ...

    @contextmanager
    def note(self, details: Mapping[str, Any]) -> Iterator[None]:
        """
        Mark everything drawn inside the block as belonging to one note.

        A surface that reports a note carries *details* so the note can describe itself. One that
        cannot ignores them.

        Parameters
        ----------
        details : collections.abc.Mapping[str, typing.Any]
            What the note says about itself.

        Yields
        ------
        None
            Control while the note is drawn.
        """
        ...

    @contextmanager
    def marks(self, kind: str) -> Iterator[None]:
        """
        Mark everything drawn inside the block as ruling of one kind.

        A page offers to leave a kind of ruling out, so it keeps them apart. A surface that draws
        once ignores it.

        Parameters
        ----------
        kind : str
            What the ruling is, such as ``'lane'`` or ``'time'``.

        Yields
        ------
        None
            Control while the ruling is drawn.
        """
        ...

    @contextmanager
    def tied(self, index: int) -> Iterator[None]:
        """
        Mark everything drawn inside the block as following one note's lane.

        A page lays a chart out again under another seed by moving what the seed decides, and this
        says what moves with what. A surface that draws once ignores it.

        Parameters
        ----------
        index : int
            The note whose lane the drawing follows.

        Yields
        ------
        None
            Control while the drawing is done.
        """
        ...

    @contextmanager
    def head(self) -> Iterator[None]:
        """
        Mark a note's own disc, apart from anything that runs on from it.

        A page stretches a column to spread its notes, and keeps whatever is marked here from being
        stretched with it. A picture has nothing to do with this.

        Yields
        ------
        None
            Control while the disc is drawn.
        """
        ...

    def save(self, path: Path, *, scale: float, supersample: int) -> tuple[int, int]:
        """
        Write the surface out.

        Parameters
        ----------
        path : pathlib.Path
            Where to write.
        scale : float
            How large to write it, as a multiple of its usual size.
        supersample : int
            The multiple the layout's units are of the finished size.

        Returns
        -------
        tuple[int, int]
            The finished width and height in pixels.
        """
        ...


class PillowCanvas:
    """A raster surface, drawn oversized and reduced once at the end to smooth every edge."""
    def __init__(self, width: int, height: int, background: tuple[int, int, int]) -> None:
        self._image = Image.new('RGB', (width, height), background)
        self._draw = ImageDraw.Draw(self._image)

    def line(self,
             xy: Sequence[float],
             *,
             fill: tuple[int, int, int],
             width: int = 1,
             joint: str | None = None) -> None:
        """
        Draw a run of connected segments.

        Parameters
        ----------
        xy : collections.abc.Sequence[float]
            Alternating x and y.
        fill : tuple[int, int, int]
            The colour to draw in.
        width : int
            How thick the line is.
        joint : str | None
            How to finish the corners between segments.
        """
        self._draw.line(tuple(xy), fill=fill, width=width, joint=joint)

    def rect(self,
             xy: Sequence[float],
             *,
             fill: tuple[int, int, int] | None = None,
             outline: tuple[int, int, int] | None = None,
             width: int = 1) -> None:
        """
        Draw a rectangle.

        Parameters
        ----------
        xy : collections.abc.Sequence[float]
            Left, top, right, and bottom.
        fill : tuple[int, int, int] | None
            The colour to fill with.
        outline : tuple[int, int, int] | None
            The colour to outline with.
        width : int
            How thick the outline is.
        """
        self._draw.rectangle(tuple(xy), fill=fill, outline=outline, width=width)

    def ellipse(self,
                xy: Sequence[float],
                *,
                fill: tuple[int, int, int] | None = None,
                outline: tuple[int, int, int] | None = None,
                width: int = 1) -> None:
        """
        Draw an ellipse within a bounding box.

        Parameters
        ----------
        xy : collections.abc.Sequence[float]
            Left, top, right, and bottom of the box.
        fill : tuple[int, int, int] | None
            The colour to fill with.
        outline : tuple[int, int, int] | None
            The colour to outline with.
        width : int
            How thick the outline is.
        """
        self._draw.ellipse(tuple(xy), fill=fill, outline=outline, width=width)

    def pieslice(self, xy: Sequence[float], start: float, end: float, *, fill: tuple[int, int,
                                                                                     int]) -> None:
        """
        Draw a slice of an ellipse.

        Parameters
        ----------
        xy : collections.abc.Sequence[float]
            Left, top, right, and bottom of the box.
        start : float
            The angle to start at.
        end : float
            The angle to stop at.
        fill : tuple[int, int, int]
            The colour to fill with.
        """
        self._draw.pieslice(tuple(xy), start, end, fill=fill)

    def text(self, xy: Sequence[float], body: str, *, fill: tuple[int, int, int],
             size: int) -> None:
        """
        Draw a line of text.

        Parameters
        ----------
        xy : collections.abc.Sequence[float]
            The top left corner.
        body : str
            The text.
        fill : tuple[int, int, int]
            The colour to draw in.
        size : int
            The font size.
        """
        x, y = xy
        self._draw.text((x, y), body, fill=fill, font=load_font(size))

    @contextmanager
    def note(self, details: Mapping[str, Any]) -> Iterator[None]:  # noqa: ARG002, PLR6301
        """
        Draw one note. A drawn image reports nothing, so the details are dropped.

        Parameters
        ----------
        details : collections.abc.Mapping[str, typing.Any]
            What the note would say about itself.

        Yields
        ------
        None
            Control while the note is drawn.
        """
        yield

    @contextmanager
    def marks(self, kind: str) -> Iterator[None]:  # noqa: ARG002, PLR6301
        """
        Draw ruling of one kind, which a drawn image always shows.

        Parameters
        ----------
        kind : str
            What the ruling is.

        Yields
        ------
        None
            Control while the ruling is drawn.
        """
        yield

    @contextmanager
    def tied(self, index: int) -> Iterator[None]:  # noqa: ARG002, PLR6301
        """
        Draw what follows a note's lane, which a drawn image lays out only once.

        Parameters
        ----------
        index : int
            The note whose lane the drawing would follow.

        Yields
        ------
        None
            Control while the drawing is done.
        """
        yield

    @contextmanager
    def head(self) -> Iterator[None]:  # noqa: PLR6301
        """
        Draw a note's own disc, which a drawn image has no reason to keep apart.

        Yields
        ------
        None
            Control while the disc is drawn.
        """
        yield

    def save(self, path: Path, *, scale: float, supersample: int) -> tuple[int, int]:
        """
        Reduce the oversized image to its finished size and write it.

        Parameters
        ----------
        path : pathlib.Path
            Where to write.
        scale : float
            How large to write it.
        supersample : int
            The multiple the layout's units are of the finished size.

        Returns
        -------
        tuple[int, int]
            The finished width and height in pixels.
        """
        width = round(self._image.width * scale / supersample)
        height = round(self._image.height * scale / supersample)
        self._image.resize((width, height), Image.Resampling.LANCZOS).save(path)
        return width, height


class SVGCanvas:
    """
    A vector surface.

    Every shape is written at the layout's own coordinates and the view box carries the same
    numbers, so the picture is identical to the raster one and scales without loss. Each shape is
    kept with the box it occupies, which is what lets the page file it under a column.
    """
    def __init__(self, width: int, height: int, background: tuple[int, int, int]) -> None:
        self.width = width
        """The view box's width, in the layout's own units."""
        self.height = height
        """The view box's height, in the layout's own units."""
        self._background = background
        self._parts: list[_Part] = []
        self._notes: list[Mapping[str, Any]] = []
        self._buffer: list[_Part] | None = None

    def _add(self, markup: str, box: tuple[float, float, float, float]) -> None:
        part = _Part(markup, *box)
        if self._buffer is None:
            self._parts.append(part)
        else:
            self._buffer.append(part)

    def line(self,
             xy: Sequence[float],
             *,
             fill: tuple[int, int, int],
             width: int = 1,
             joint: str | None = None) -> None:
        """
        Draw a run of connected segments.

        Parameters
        ----------
        xy : collections.abc.Sequence[float]
            Alternating x and y.
        fill : tuple[int, int, int]
            The colour to draw in.
        width : int
            How thick the line is.
        joint : str | None
            How to finish the corners between segments. ``'curve'`` rounds them, which is what the
            raster surface's own curve joint does.
        """
        xs, ys = list(xy[::2]), list(xy[1::2])
        points = ' '.join(f'{x:g},{y:g}' for x, y in zip(xs, ys, strict=True))
        rounded = ' stroke-linejoin="round" stroke-linecap="round"' if joint == 'curve' else ''
        left, right = _span(xs)
        top, bottom = _span(ys)
        self._add(
            f'<polyline points="{points}" fill="none" stroke="{_rgb(fill)}" '
            f'stroke-width="{width}"{rounded}/>',
            (left - width, top - width, right + width, bottom + width))

    def rect(self,
             xy: Sequence[float],
             *,
             fill: tuple[int, int, int] | None = None,
             outline: tuple[int, int, int] | None = None,
             width: int = 1) -> None:
        """
        Draw a rectangle.

        Parameters
        ----------
        xy : collections.abc.Sequence[float]
            Left, top, right, and bottom.
        fill : tuple[int, int, int] | None
            The colour to fill with.
        outline : tuple[int, int, int] | None
            The colour to outline with.
        width : int
            How thick the outline is.
        """
        left, top, right, bottom = xy
        self._add(
            f'<rect x="{left:g}" y="{top:g}" width="{right - left:g}" '
            f'height="{bottom - top:g}" {_paint(fill, outline, width)}/>',
            (left, top, right, bottom))

    def ellipse(self,
                xy: Sequence[float],
                *,
                fill: tuple[int, int, int] | None = None,
                outline: tuple[int, int, int] | None = None,
                width: int = 1) -> None:
        """
        Draw an ellipse within a bounding box.

        Parameters
        ----------
        xy : collections.abc.Sequence[float]
            Left, top, right, and bottom of the box.
        fill : tuple[int, int, int] | None
            The colour to fill with.
        outline : tuple[int, int, int] | None
            The colour to outline with.
        width : int
            How thick the outline is.
        """
        left, top, right, bottom = xy
        self._add(
            f'<ellipse cx="{(left + right) / 2:g}" cy="{(top + bottom) / 2:g}" '
            f'rx="{(right - left) / 2:g}" ry="{(bottom - top) / 2:g}" '
            f'{_paint(fill, outline, width)}/>', (left, top, right, bottom))

    def pieslice(self, xy: Sequence[float], start: float, end: float, *, fill: tuple[int, int,
                                                                                     int]) -> None:
        """
        Draw a slice of an ellipse, closed back through its centre.

        Parameters
        ----------
        xy : collections.abc.Sequence[float]
            Left, top, right, and bottom of the box.
        start : float
            The angle to start at, in degrees clockwise from three o'clock.
        end : float
            The angle to stop at.
        fill : tuple[int, int, int]
            The colour to fill with.
        """
        left, top, right, bottom = xy
        cx, cy = (left + right) / 2, (top + bottom) / 2
        rx, ry = (right - left) / 2, (bottom - top) / 2
        start_x, start_y = _on_ellipse(cx, cy, rx, ry, start)
        end_x, end_y = _on_ellipse(cx, cy, rx, ry, end)
        # The y axis runs down, so a clockwise sweep in the caller's terms is a positive sweep here.
        large = 1 if (end - start) % _FULL_TURN > _HALF_TURN else 0
        self._add(
            f'<path d="M {cx:g} {cy:g} L {start_x:g} {start_y:g} '
            f'A {rx:g} {ry:g} 0 {large} 1 {end_x:g} {end_y:g} Z" fill="{_rgb(fill)}"/>',
            (left, top, right, bottom))

    def text(self, xy: Sequence[float], body: str, *, fill: tuple[int, int, int],
             size: int) -> None:
        """
        Draw a line of text with its top left corner at *xy*.

        Parameters
        ----------
        xy : collections.abc.Sequence[float]
            The top left corner.
        body : str
            The text.
        fill : tuple[int, int, int]
            The colour to draw in.
        size : int
            The font size.
        """
        x, y = xy
        # Pillow anchors a string by the top of its box; text-before-edge is the same rule.
        self._add(
            f'<text x="{x:g}" y="{y:g}" fill="{_rgb(fill)}" font-size="{size}" '
            f'font-family="sans-serif" dominant-baseline="text-before-edge" '
            f'xml:space="preserve">{html.escape(body)}</text>',
            (x, y, x + size * len(body), y + size))

    @contextmanager
    def note(self, details: Mapping[str, Any]) -> Iterator[None]:
        """
        Wrap everything drawn inside the block in a group carrying the note's details.

        Parameters
        ----------
        details : collections.abc.Mapping[str, typing.Any]
            What the note says about itself.

        Yields
        ------
        None
            Control while the note is drawn.
        """
        index = len(self._notes)
        self._notes.append(details)
        with self._collect() as parts:
            yield
        if parts:
            box = _merge(parts)
            inner = ''.join(part.markup for part in parts)
            tie = details.get('Index', '')
            self._add(
                f'<g class="rb-note" tabindex="0" data-note="{index}" data-tie="{tie}">{inner}</g>',
                box)

    @contextmanager
    def marks(self, kind: str) -> Iterator[None]:
        """
        Wrap ruling of one kind, so that a page can offer to leave it out.

        Parameters
        ----------
        kind : str
            What the ruling is.

        Yields
        ------
        None
            Control while the ruling is drawn.
        """
        with self._collect() as parts:
            yield
        if parts:
            inner = ''.join(part.markup for part in parts)
            self._add(f'<g class="rb-rule rb-rule-{kind}">{inner}</g>', _merge(parts))

    @contextmanager
    def tied(self, index: int) -> Iterator[None]:
        """
        Wrap what follows one note's lane, so that laying the chart out again can move it too.

        Parameters
        ----------
        index : int
            The note whose lane the drawing follows.

        Yields
        ------
        None
            Control while the drawing is done.
        """
        with self._collect() as parts:
            yield
        if parts:
            inner = ''.join(part.markup for part in parts)
            self._add(f'<g data-tie="{index}">{inner}</g>', _merge(parts))

    @contextmanager
    def head(self) -> Iterator[None]:
        """
        Wrap a note's own disc, so a page can keep it round while it stretches everything else.

        Yields
        ------
        None
            Control while the disc is drawn.
        """
        with self._collect() as parts:
            yield
        if parts:
            inner = ''.join(part.markup for part in parts)
            self._add(f'<g class="rb-head">{inner}</g>', _merge(parts))

    @contextmanager
    def _collect(self) -> Iterator[list[_Part]]:
        # Gather what is drawn inside the block instead of writing it out, so that it can be
        # wrapped or filed away. Nesting is not needed and is not supported.
        previous, self._buffer = self._buffer, []
        collected = self._buffer
        try:
            yield collected
        finally:
            self._buffer = previous

    def to_svg(self, *, scale: float, supersample: int) -> str:
        """
        Assemble the whole picture as an SVG document.

        Parameters
        ----------
        scale : float
            How large the document asks to be drawn.
        supersample : int
            The multiple the layout's units are of the finished size.

        Returns
        -------
        str
            The document.
        """
        width, height = self.pixel_size(scale=scale, supersample=supersample)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
                f'viewBox="0 0 {self.width} {self.height}">'
                f'<rect width="{self.width}" height="{self.height}" fill="{_rgb(self._background)}"'
                f'/>{"".join(part.markup for part in self._parts)}</svg>')

    def pixel_size(self, *, scale: float, supersample: int) -> tuple[int, int]:
        """
        Work out the size the document asks to be drawn at.

        Parameters
        ----------
        scale : float
            How large to write it.
        supersample : int
            The multiple the layout's units are of the finished size.

        Returns
        -------
        tuple[int, int]
            The width and height in pixels.
        """
        return round(self.width * scale / supersample), round(self.height * scale / supersample)

    @property
    def notes(self) -> tuple[Mapping[str, Any], ...]:
        """Every note's details, in the order they were drawn."""
        return tuple(self._notes)

    def save(self, path: Path, *, scale: float, supersample: int) -> tuple[int, int]:
        """
        Write the document out.

        Parameters
        ----------
        path : pathlib.Path
            Where to write.
        scale : float
            How large to write it.
        supersample : int
            The multiple the layout's units are of the finished size.

        Returns
        -------
        tuple[int, int]
            The width and height in pixels.
        """
        path.write_text(self.to_svg(scale=scale, supersample=supersample) + '\n', encoding='utf-8')
        return self.pixel_size(scale=scale, supersample=supersample)


def _merge(parts: Sequence[_Part]) -> tuple[float, float, float, float]:
    return (min(part.left for part in parts), min(part.top for part in parts),
            max(part.right for part in parts), max(part.bottom for part in parts))


def canvas_for(suffix: str, width: int, height: int, background: tuple[int, int, int]) -> Canvas:
    """
    Choose the surface a file of this kind is drawn on.

    Parameters
    ----------
    suffix : str
        The output file's suffix, with its dot, in any case.
    width : int
        The layout's width in its own units.
    height : int
        The layout's height in its own units.
    background : tuple[int, int, int]
        What to fill before drawing.

    Returns
    -------
    Canvas
        The surface.

    Raises
    ------
    ValueError
        If no surface writes that kind of file.
    """
    match suffix.lower():
        case '.png':
            return PillowCanvas(width, height, background)
        case '.svg':
            return SVGCanvas(width, height, background)
        case '.htm' | '.html':
            # A chart read in a browser is a whole site rather than one picture, since the page
            # lays the chart out for the window it is opened in rather than for a size chosen here.
            msg = ('A chart is not drawn as a page. Use `dade rbplus site` to build one that can '
                   'be read in a browser.')
            raise ValueError(msg)
        case _:
            msg = f'No surface writes `{suffix}`; expected .png or .svg.'
            raise ValueError(msg)
