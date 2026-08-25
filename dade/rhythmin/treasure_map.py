"""
Reading of the sugoroku ``map_%03d.map`` board files.

The 27 boards in ``PopnRhythmin.app`` are the sugoroku treasure maps: nine main maps with three
sub-maps each, the file number being ``mainMapId * 10 + subMapId``. They are plain, unencrypted
little-endian binaries read by ``TreasureMap::load``:

* the header is 0x50 bytes: two ``uint8`` of head bytes, then an ``int16`` square count at +0x02.
  The game ignores +0x04 onwards, but the files carry structure there, and this reads it: a 24-byte
  Shift-JIS main-map title at +0x04, a 40-byte sub-map title at +0x1c, and an ``int32`` of
  unconfirmed meaning at +0x44 (1 to 6 across the shipped files; it is not the sub-map ordinal);
* square records start at +0x50 with a stride of 0xaa: ``int16`` identifier, x, y, kind, and slot,
  then a back link at +0x0a and three forward links at +0x0c, +0x0e, and +0x10, where a negative
  value means no link, then 0x98 bytes of Shift-JIS message text at +0x12 using ``<br>`` as the
  line break.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple
import itertools
import math
import struct

from PIL import Image, ImageDraw

from .render import load_font

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

__all__ = (
    'GRID_GLYPHS',
    'HEADER_SIZE',
    'RECORD_SIZE',
    'SQUARE_KINDS',
    'SQUARE_KIND_COLORS',
    'Square',
    'TreasureMap',
    'map_to_json',
    'parse_treasure_map',
    'read_treasure_map',
    'render_ascii',
    'render_image',
)

HEADER_SIZE = 0x50
"""Size of the file header.

:meta hide-value:
"""
RECORD_SIZE = 0xAA
"""Stride of one square record.

:meta hide-value:
"""
SQUARE_KINDS: Mapping[int, str] = {
    -1: 'invalid',
    0: 'start',
    1: 'player-start',
    2: 'story-message',
    3: 'bonus',
    4: 'treasure',
    5: 'sub-map-flag',
    6: 'wallpaper-piece',
    7: 'music-piece',
    8: 'warp',
    9: 'goal-lock',
    10: 'bonus-treasure',
}
"""``TreasureMap::SquareKind`` to its readable name.

:meta hide-value:
"""
GRID_GLYPHS: Mapping[int, str] = {
    0: 'S',
    1: 'P',
    2: 'm',
    3: 'B',
    4: 'T',
    5: 'F',
    6: 'w',
    7: 'n',
    8: 'W',
    9: 'G',
    10: 'X',
}
"""Square kind to the glyph the text and image boards draw it with.

:meta hide-value:
"""
SQUARE_KIND_COLORS: Mapping[int, tuple[int, int, int]] = {
    0: (90, 200, 90),
    1: (80, 220, 255),
    2: (145, 145, 158),
    3: (250, 200, 30),
    4: (255, 150, 40),
    5: (110, 116, 190),
    6: (190, 110, 220),
    7: (255, 120, 180),
    8: (70, 130, 250),
    9: (170, 60, 60),
    10: (240, 60, 60),
}
"""Square kind to the tile colour the image board draws it with.

:meta hide-value:
"""

_TEXT_OFFSET = 0x12
_TEXT_SIZE = 0x98
_MAIN_TITLE = slice(0x04, 0x1C)
_SUB_TITLE = slice(0x1C, 0x44)
_HEADER_VALUE_OFFSET = 0x44
_WARP_KIND = 8
_BACKGROUND = (24, 24, 32)
_TILE_OUTLINE = (15, 15, 20)
_EDGE_COLOR = (95, 95, 112)
_TITLE_COLOR = (235, 235, 245)
_STATS_COLOR = (180, 180, 195)
_LEGEND_COLOR = (150, 150, 165)
_UNKNOWN_COLOR = (200, 200, 200)


class Square(NamedTuple):
    """One square of a board."""

    identifier: int
    """The square's own identifier, which the links refer to."""
    x: int
    """Horizontal board coordinate, in the file's own units."""
    y: int
    """Vertical board coordinate, in the file's own units."""
    kind: int
    """The square's :data:`SQUARE_KINDS` value."""
    slot: int
    """Kind-specific slot, which pairs the two ends of a warp."""
    back: int | None
    """Identifier of the square this one leads back to, or ``None``."""
    links: tuple[int, ...]
    """Identifiers of the squares this one leads forward to."""
    text: str
    """The square's message, with ``<br>`` resolved to a newline."""
    @property
    def kind_name(self) -> str:
        """
        Readable name of the square's kind.

        Returns
        -------
        str
            The :data:`SQUARE_KINDS` name, or a description of the raw value.
        """
        return SQUARE_KINDS.get(self.kind, f'unknown({self.kind})')


class TreasureMap(NamedTuple):
    """One parsed board."""

    name: str
    """The file's name."""
    head: tuple[int, int]
    """The two header bytes preceding the square count."""
    main_title: str
    """The main map's title."""
    sub_title: str
    """The sub-map's title."""
    header_value: int
    """The ``int32`` at +0x44, whose meaning is unconfirmed."""
    squares: tuple[Square, ...]
    """Every square, in file order."""
    edges: tuple[tuple[int, int], ...]
    """The deduplicated forward-link edge list."""
    trailing_bytes: int
    """Bytes past the last square record, which is normally zero."""
    @property
    def kind_counts(self) -> dict[str, int]:
        """
        How many squares there are of each kind.

        Returns
        -------
        dict[str, int]
            Readable kind name to its count.
        """
        counts: dict[str, int] = {}
        for square in self.squares:
            counts[square.kind_name] = counts.get(square.kind_name, 0) + 1
        return counts

    @property
    def title(self) -> str:
        """
        The board's two titles joined, falling back to the file name.

        Returns
        -------
        str
            A display title.
        """
        joined = ' - '.join(part for part in (self.main_title, self.sub_title) if part.strip())
        return joined or self.name


def _decode_sjis(raw: bytes) -> str:
    """
    Decode a NUL-terminated Shift-JIS run, resolving the format's line break.

    Parameters
    ----------
    raw : bytes
        The field's bytes, NUL-padded.

    Returns
    -------
    str
        The decoded text, with ``<br>`` replaced by a newline.
    """
    return raw.split(b'\0', 1)[0].decode('shift_jis', errors='replace').replace('<br>', '\n')


def _deduplicate_edges(squares: Sequence[Square]) -> tuple[tuple[int, int], ...]:
    """
    Build the forward-link edge list the way ``TreasureMap::load`` builds it.

    A link is skipped when the reverse edge has already been recorded, so a two-way corridor
    appears once.

    Parameters
    ----------
    squares : Sequence[Square]
        The board's squares.

    Returns
    -------
    tuple[tuple[int, int], ...]
        The edges, in the order the game records them.
    """
    known: set[tuple[int, int]] = set()
    identifiers = {square.identifier for square in squares}
    edges: list[tuple[int, int]] = []
    for square in squares:
        for link in square.links:
            if link not in identifiers or (link, square.identifier) in known:
                continue
            known.add((square.identifier, link))
            edges.append((square.identifier, link))
    return tuple(edges)


def parse_treasure_map(data: bytes, name: str = '') -> TreasureMap:
    """
    Parse a board file.

    Parameters
    ----------
    data : bytes
        The file's contents.
    name : str
        The file's name, carried through to the parsed board for display.

    Returns
    -------
    TreasureMap
        The parsed board.

    Raises
    ------
    ValueError
        If the file is too short for a board, or its square count disagrees with its size.
    """
    if len(data) < HEADER_SIZE + RECORD_SIZE:
        msg = f'Too short for a map file: {len(data)} bytes.'
        raise ValueError(msg)
    head0, head1, count = struct.unpack_from('<BBh', data, 0)
    expected = HEADER_SIZE + count * RECORD_SIZE
    if count <= 0 or len(data) < expected:
        msg = f'Bad square count {count} for a file of {len(data)} bytes; {expected} are needed.'
        raise ValueError(msg)
    squares: list[Square] = []
    for index in range(count):
        record = data[HEADER_SIZE + index * RECORD_SIZE:HEADER_SIZE + (index + 1) * RECORD_SIZE]
        identifier, x, y, kind, slot, back, *links = struct.unpack_from('<9h', record, 0)
        squares.append(
            Square(identifier, x, y, kind, slot, back if back >= 0 else None,
                   tuple(link for link in links if link >= 0),
                   _decode_sjis(record[_TEXT_OFFSET:_TEXT_OFFSET + _TEXT_SIZE])))
    return TreasureMap(name, (head0, head1), _decode_sjis(data[_MAIN_TITLE]),
                       _decode_sjis(data[_SUB_TITLE]),
                       struct.unpack_from('<i', data, _HEADER_VALUE_OFFSET)[0], tuple(squares),
                       _deduplicate_edges(squares),
                       len(data) - expected)


def read_treasure_map(path: Path) -> TreasureMap:
    """
    Read and parse one board file.

    A file that is not a board raises the :py:class:`ValueError` :func:`parse_treasure_map` raises.

    Parameters
    ----------
    path : pathlib.Path
        The ``map_XXX.map`` to read.

    Returns
    -------
    TreasureMap
        The parsed board.
    """
    return parse_treasure_map(path.read_bytes(), path.name)


def map_to_json(board: TreasureMap) -> dict[str, Any]:
    """
    Render a parsed board as JSON-ready values.

    Parameters
    ----------
    board : TreasureMap
        The board to render.

    Returns
    -------
    dict[str, Any]
        The rendered board.
    """
    return {
        'edges': [list(edge) for edge in board.edges],
        'file': board.name,
        'head': list(board.head),
        'header_value': board.header_value,
        'main_title': board.main_title,
        'square_count': len(board.squares),
        'squares': [{
            'back': square.back,
            'id': square.identifier,
            'links': list(square.links),
            'slot': square.slot,
            'text': square.text,
            'type': square.kind,
            'type_name': square.kind_name,
            'x': square.x,
            'y': square.y,
        } for square in board.squares],
        'sub_title': board.sub_title,
        'trailing_bytes': board.trailing_bytes,
        'type_counts': board.kind_counts,
    }


def _coordinate_step(values: Sequence[int]) -> int:
    """
    Find the grid pitch of a sorted coordinate list.

    Parameters
    ----------
    values : Sequence[int]
        The sorted unique coordinates along one axis.

    Returns
    -------
    int
        The greatest common divisor of the gaps between them, or 1 when there is only one.
    """
    step = 0
    for first, second in itertools.pairwise(values):
        step = math.gcd(step, second - first)
    return step or 1


def _board_cells(squares: Sequence[Square]) -> tuple[dict[int, tuple[int, int]], int, int]:
    """
    Compress the board's coordinates to a dense grid.

    Parameters
    ----------
    squares : Sequence[Square]
        The board's squares.

    Returns
    -------
    tuple[dict[int, tuple[int, int]], int, int]
        Square identifier to its column and row, then the column and row counts.
    """
    xs = sorted({square.x for square in squares})
    ys = sorted({square.y for square in squares})
    step_x, step_y = _coordinate_step(xs), _coordinate_step(ys)
    cells = {
        square.identifier: ((square.x - xs[0]) // step_x, (square.y - ys[0]) // step_y)
        for square in squares
    }
    return cells, (xs[-1] - xs[0]) // step_x + 1, (ys[-1] - ys[0]) // step_y + 1


def render_ascii(board: TreasureMap) -> tuple[str, ...]:
    """
    Render a board as text, with kind glyphs at each tile and edges as dashes and bars.

    Parameters
    ----------
    board : TreasureMap
        The board to render.

    Returns
    -------
    tuple[str, ...]
        The board's non-empty rows.
    """
    cells, columns, lines = _board_cells(board.squares)
    rows = [[' '] * (columns * 4) for _ in range(lines * 2)]
    for square in board.squares:
        column, row = cells[square.identifier]
        rows[row * 2][column * 4] = GRID_GLYPHS.get(square.kind, '?')
    for first, second in board.edges:
        (ax, ay), (bx, by) = cells[first], cells[second]
        if ay == by and ax != bx:
            left, right = sorted((ax, bx))
            for column in range(left * 4 + 1, right * 4):
                rows[ay * 2][column] = '-'
        elif ax == bx and ay != by:
            top, bottom = sorted((ay, by))
            for row in range(top * 2 + 1, bottom * 2):
                rows[row][ax * 4] = '|'
    return tuple(joined.rstrip() for row in rows if (joined := ''.join(row)).strip())


def _legend_lines(width: int, margin: int, font: Any) -> list[str]:
    """
    Wrap the kind legend to the available width.

    Parameters
    ----------
    width : int
        The image width.
    margin : int
        The margin on each side.
    font : Any
        The font the legend is drawn with.

    Returns
    -------
    list[str]
        One string per legend line.
    """
    lines: list[str] = []
    current = ''
    for kind in sorted(GRID_GLYPHS):
        item = f'{GRID_GLYPHS[kind]}={SQUARE_KINDS[kind]}'
        candidate = f'{current}   {item}' if current else item
        if current and font.getlength(candidate) > width - margin * 2:
            lines.append(current)
            current = item
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _draw_tiles(draw: ImageDraw.ImageDraw, board: TreasureMap, centre: Callable[[int],
                                                                                tuple[int, int]], *,
                font: Any, radius: int, outline_width: int, glyph_rise: int) -> None:
    """
    Draw one coloured tile per square, each carrying its kind glyph.

    Parameters
    ----------
    draw : PIL.ImageDraw.ImageDraw
        The drawing context.
    board : TreasureMap
        The board being drawn.
    centre : Callable[[int], tuple[int, int]]
        Square identifier to the centre of its tile.
    font : Any
        The font glyphs are drawn with.
    radius : int
        Tile radius in pixels.
    outline_width : int
        Width of a tile's outline in pixels.
    glyph_rise : int
        How far above the tile's centre the glyph's baseline sits.
    """
    for square in board.squares:
        x, y = centre(square.identifier)
        draw.ellipse([x - radius, y - radius, x + radius, y + radius],
                     fill=SQUARE_KIND_COLORS.get(square.kind, _UNKNOWN_COLOR),
                     outline=_TILE_OUTLINE,
                     width=outline_width)
        glyph = GRID_GLYPHS.get(square.kind, '?')
        if square.kind == _WARP_KIND:  # A warp shows its slot so partners can be matched.
            glyph = f'W{square.slot}'
        draw.text((x - draw.textlength(glyph, font=font) / 2, y - glyph_rise),
                  glyph,
                  fill=_TILE_OUTLINE,
                  font=font)


def render_image(board: TreasureMap, path: Path, scale: float = 2.0) -> tuple[int, int]:
    """
    Render a board as a PNG of coloured tiles joined by their edges.

    Parameters
    ----------
    board : TreasureMap
        The board to render.
    path : pathlib.Path
        Where to write the image.
    scale : float
        Geometry multiplier applied to every distance.

    Returns
    -------
    tuple[int, int]
        The image's width and height in pixels.
    """
    def px(base: int) -> int:
        return max(1, round(base * scale))

    cells, columns, lines = _board_cells(board.squares)
    pitch, radius = px(76), px(24)
    margin, header = px(36), px(64)
    title_font = load_font(px(22))
    tile_font = load_font(px(18))
    small_font = load_font(px(12))
    # The image must be wide enough for the board and for the text: the title and the stats line
    # set a minimum width, and the legend then wraps to however many lines fit it.
    stats = (f'{board.name}   {len(board.squares)} squares   {len(board.edges)} edges')
    board_width = margin * 2 + (columns - 1) * pitch + radius * 2
    width = max(board_width, margin * 2 + round(title_font.getlength(board.title)),
                margin * 2 + round(small_font.getlength(stats)))
    legend = _legend_lines(width, margin, small_font)
    line_height = px(18)
    height = (margin * 2 + header + line_height * len(legend) + px(16) + (lines - 1) * pitch +
              radius * 2)
    image = Image.new('RGB', (width, height), _BACKGROUND)
    draw = ImageDraw.Draw(image)
    board_x = margin + (width - board_width) // 2  # Centre a narrow board under the text.

    def centre(identifier: int) -> tuple[int, int]:
        column, row = cells[identifier]
        return board_x + radius + column * pitch, margin + header + radius + row * pitch

    for first, second in board.edges:
        draw.line([centre(first), centre(second)], fill=_EDGE_COLOR, width=px(4))
    _draw_tiles(draw,
                board,
                centre,
                font=tile_font,
                radius=radius,
                outline_width=px(2),
                glyph_rise=px(11))
    draw.text((margin, margin - px(8)), board.title, fill=_TITLE_COLOR, font=title_font)
    draw.text((margin, margin + px(22)), stats, fill=_STATS_COLOR, font=small_font)
    legend_y = height - margin - line_height * len(legend)
    for index, line in enumerate(legend):
        draw.text((margin, legend_y + index * line_height),
                  line,
                  fill=_LEGEND_COLOR,
                  font=small_font)
    image.save(path)
    return width, height
