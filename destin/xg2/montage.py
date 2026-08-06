"""
Contact sheets for reviewing decoded textures.

The display-list and descriptor walkers infer dimensions the hardware never stored, so a mis-parse
shows up as a striped or skewed image rather than an error. Tiling every texture into one sheet
makes those obvious at a glance, which is what these sheets are for.

Each texture is fitted into a fixed cell with nearest-neighbour sampling, never enlarged, and
composited over a checkerboard so transparent regions stay visible.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .typing import Texture

__all__ = ('DEFAULT_CELL', 'DEFAULT_COLUMNS', 'build_index', 'build_montage')

DEFAULT_CELL = 64
"""Side of one cell in pixels.

:meta hide-value:
"""
DEFAULT_COLUMNS = 16
"""Number of cells per row.

:meta hide-value:
"""
_CHECK_DARK = 90
_CHECK_LIGHT = 130
_CHECK_SIZE = 8


def _checkerboard(width: int, height: int) -> bytearray:
    canvas = bytearray(width * height * 4)
    for y in range(height):
        for x in range(width):
            shade = (_CHECK_DARK if ((x >> 3) + (y >> 3)) & 1 else _CHECK_LIGHT)
            i = (y * width + x) * 4
            canvas[i:i + 4] = bytes((shade, shade, shade, 255))
    return canvas


def build_montage(textures: Sequence[Texture],
                  cell: int = DEFAULT_CELL,
                  columns: int = DEFAULT_COLUMNS) -> tuple[int, int, bytes]:
    """
    Tile textures into a single contact sheet.

    Parameters
    ----------
    textures : collections.abc.Sequence[destin.xg2.typing.Texture]
        The textures to tile, in order.
    cell : int
        Side of one cell in pixels.
    columns : int
        Number of cells per row.

    Returns
    -------
    tuple[int, int, bytes]
        The sheet's width, height, and RGBA8 pixel data.
    """
    rows = (len(textures) + columns - 1) // columns
    width, height = columns * cell, max(rows, 1) * cell
    canvas = _checkerboard(width, height)
    for index, texture in enumerate(textures):
        origin_x, origin_y = (index % columns) * cell, (index // columns) * cell
        scale = min(cell / texture.width, cell / texture.height, 1.0)
        draw_width = max(1, int(texture.width * scale))
        draw_height = max(1, int(texture.height * scale))
        offset_x = origin_x + (cell - draw_width) // 2
        offset_y = origin_y + (cell - draw_height) // 2
        for y in range(draw_height):
            source_y = int(y / scale)
            for x in range(draw_width):
                source = (source_y * texture.width + int(x / scale)) * 4
                if texture.rgba[source + 3] == 0:
                    continue
                i = ((offset_y + y) * width + (offset_x + x)) * 4
                canvas[i:i + 4] = bytes(
                    (texture.rgba[source], texture.rgba[source + 1], texture.rgba[source + 2], 255))
    return width, height, bytes(canvas)


def build_index(textures: Sequence[Texture],
                labels: Sequence[str],
                columns: int = DEFAULT_COLUMNS) -> str:
    """
    Build a text index mapping each cell of a contact sheet back to its source.

    Parameters
    ----------
    textures : collections.abc.Sequence[destin.xg2.typing.Texture]
        The textures the sheet was built from.
    labels : collections.abc.Sequence[str]
        A source label per texture.
    columns : int
        Number of cells per row, which must match the sheet.

    Returns
    -------
    str
        One line per texture, giving its index, cell, dimensions, and label.
    """
    return ''.join(f'{i:3d}  r{i // columns:02d}c{i % columns:02d}  '
                   f'{texture.width}x{texture.height}  {label}\n'
                   for i, (texture, label) in enumerate(zip(textures, labels, strict=True)))
