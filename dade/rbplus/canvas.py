"""
The surfaces a chart is drawn on.

:py:mod:`dade.rbplus.render` lays a chart out once and draws it through one of these, so the same
geometry comes out as a raster image, as a vector one, or as a page that can be clicked through.
The drawing calls follow Pillow's, since that is where they started.

Coordinates are always in the layout's own units, which are a whole multiple of the finished size
so that the raster surface can be reduced once at the end and smoothed by it. A vector surface has
no such need, and carries the same numbers as its view box instead.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Protocol
import html
import json
import math

from PIL import Image, ImageDraw

from dade.common.fonts import load_font

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path

__all__ = ('BOOTSTRAP_CSS', 'BOOTSTRAP_JS', 'Canvas', 'HTMLCanvas', 'PillowCanvas', 'SVGCanvas',
           'canvas_for')

BOOTSTRAP_CSS = 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css'
"""Where the page fetches Bootstrap's stylesheet from.

:meta hide-value:
"""
BOOTSTRAP_JS = 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js'
"""Where the page fetches Bootstrap's bundle from, which carries Popper.

:meta hide-value:
"""

_FONT_STACK = ("'Noto Sans CJK JP', 'Noto Sans JP', 'Hiragino Sans', 'Yu Gothic', "
               'sans-serif')
_FULL_TURN = 360.0
_HALF_TURN = 180.0


def _rgb(color: tuple[int, int, int]) -> str:
    return '#{:02x}{:02x}{:02x}'.format(*color)


def _on_ellipse(cx: float, cy: float, rx: float, ry: float, degrees: float) -> tuple[float, float]:
    # Where an angle lands on an ellipse, measured the way the raster surface measures it: clockwise
    # from three o'clock, with the y axis running down the image.
    radians = math.radians(degrees)
    return cx + rx * math.cos(radians), cy + ry * math.sin(radians)


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

        A surface that can be clicked through carries *details* so the note can report itself. One
        that cannot ignores them.

        Parameters
        ----------
        details : collections.abc.Mapping[str, typing.Any]
            What the note would say about itself.

        Yields
        ------
        None
            Control while the note is drawn.
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
        Draw one note. A raster image cannot be clicked through, so the details are dropped.

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
    numbers, so the picture is identical to the raster one and scales without loss.
    """
    def __init__(self, width: int, height: int, background: tuple[int, int, int]) -> None:
        self.width = width
        """The view box's width, in the layout's own units."""
        self.height = height
        """The view box's height, in the layout's own units."""
        self._background = background
        self._parts: list[str] = []
        self._notes: list[Mapping[str, Any]] = []
        self._open = False

    def _add(self, markup: str) -> None:
        self._parts.append(markup)

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
        points = ' '.join(f'{x:g},{y:g}' for x, y in zip(xy[::2], xy[1::2], strict=True))
        rounded = ' stroke-linejoin="round" stroke-linecap="round"' if joint == 'curve' else ''
        self._add(f'<polyline points="{points}" fill="none" stroke="{_rgb(fill)}" '
                  f'stroke-width="{width}"{rounded}/>')

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
        self._add(f'<rect x="{left:g}" y="{top:g}" width="{right - left:g}" '
                  f'height="{bottom - top:g}" {_paint(fill, outline, width)}/>')

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
        self._add(f'<ellipse cx="{(left + right) / 2:g}" cy="{(top + bottom) / 2:g}" '
                  f'rx="{(right - left) / 2:g}" ry="{(bottom - top) / 2:g}" '
                  f'{_paint(fill, outline, width)}/>')

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
        self._add(f'<path d="M {cx:g} {cy:g} L {start_x:g} {start_y:g} '
                  f'A {rx:g} {ry:g} 0 {large} 1 {end_x:g} {end_y:g} Z" fill="{_rgb(fill)}"/>')

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
        self._add(f'<text x="{x:g}" y="{y:g}" fill="{_rgb(fill)}" font-size="{size}" '
                  f'font-family="{_FONT_STACK}" dominant-baseline="text-before-edge" '
                  f'xml:space="preserve">{html.escape(body)}</text>')

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
        self._add(f'<g class="rb-note" tabindex="0" role="button" data-note="{index}">')
        self._open = True
        try:
            yield
        finally:
            self._open = False
            self._add('</g>')

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
                f'/>{"".join(self._parts)}</svg>')

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


class HTMLCanvas(SVGCanvas):
    """
    A page holding the vector picture, with every note answering to a click.

    The page is Bootstrap's, fetched from its content delivery network, and the picture is the same
    SVG written inline so that a note's group can be clicked.
    """
    def __init__(self,
                 width: int,
                 height: int,
                 background: tuple[int, int, int],
                 *,
                 title: str = 'Chart') -> None:
        super().__init__(width, height, background)
        self.title = title
        """What the page calls itself."""

    def to_html(self, *, scale: float, supersample: int) -> str:
        """
        Assemble the whole page.

        Parameters
        ----------
        scale : float
            How large the picture asks to be drawn.
        supersample : int
            The multiple the layout's units are of the finished size.

        Returns
        -------
        str
            The page.
        """
        return _PAGE.format(background=_rgb(self._background),
                            bootstrap_css=BOOTSTRAP_CSS,
                            bootstrap_js=BOOTSTRAP_JS,
                            notes=json.dumps(list(self._notes), ensure_ascii=False),
                            svg=self.to_svg(scale=scale, supersample=supersample),
                            title=html.escape(self.title))

    def save(self, path: Path, *, scale: float, supersample: int) -> tuple[int, int]:
        """
        Write the page out.

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
            The picture's width and height in pixels.
        """
        path.write_text(self.to_html(scale=scale, supersample=supersample) + '\n', encoding='utf-8')
        return self.pixel_size(scale=scale, supersample=supersample)


def _paint(fill: tuple[int, int, int] | None, outline: tuple[int, int, int] | None,
           width: int) -> str:
    parts = [f'fill="{_rgb(fill)}"' if fill is not None else 'fill="none"']
    if outline is not None:
        parts.extend((f'stroke="{_rgb(outline)}"', f'stroke-width="{width}"'))
    return ' '.join(parts)


def canvas_for(suffix: str, width: int, height: int, background: tuple[int, int, int], *,
               title: str) -> Canvas:
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
    title : str
        What a page should call itself, ignored by the other surfaces.

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
        case '.html' | '.htm':
            return HTMLCanvas(width, height, background, title=title)
        case _:
            msg = (f'No surface writes `{suffix}`; expected one of .png, .svg, .html.')
            raise ValueError(msg)


_PAGE = """<!doctype html>
<html lang="en" data-bs-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link href="{bootstrap_css}" rel="stylesheet">
<style>
body {{ background: {background}; }}
.rb-chart {{ overflow-x: auto; }}
.rb-note {{ cursor: pointer; }}
.rb-note:hover, .rb-note:focus {{ outline: none; filter: brightness(1.6); }}
.rb-note.rb-picked {{ filter: brightness(2); }}
.rb-panel {{ position: sticky; top: 1rem; }}
</style>
</head>
<body>
<div class="container-fluid py-3">
  <div class="row g-3">
    <div class="col-12 col-xl-9">
      <div class="rb-chart">{svg}</div>
    </div>
    <div class="col-12 col-xl-3">
      <div class="card rb-panel">
        <div class="card-header">Note</div>
        <div class="card-body">
          <p class="text-body-secondary mb-0" id="rb-empty">Select a note to see its details.</p>
          <dl class="row mb-0 d-none" id="rb-details"></dl>
        </div>
      </div>
    </div>
  </div>
</div>
<script src="{bootstrap_js}"></script>
<script>
const notes = {notes};
const details = document.getElementById('rb-details');
const empty = document.getElementById('rb-empty');
let picked = null;
function show(index) {{
  const note = notes[index];
  if (!note) return;
  details.innerHTML = Object.entries(note).map(([key, value]) =>
    `<dt class="col-5 text-truncate">${{key}}</dt><dd class="col-7">${{value}}</dd>`).join('');
  details.classList.remove('d-none');
  empty.classList.add('d-none');
}}
for (const group of document.querySelectorAll('.rb-note')) {{
  const select = () => {{
    if (picked) picked.classList.remove('rb-picked');
    picked = group;
    group.classList.add('rb-picked');
    show(group.dataset.note);
  }};
  group.addEventListener('click', select);
  group.addEventListener('keydown', (event) => {{
    if (event.key === 'Enter' || event.key === ' ') {{ event.preventDefault(); select(); }}
  }});
}}
</script>
</body>
</html>"""
