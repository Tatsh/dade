"""
Texture extraction from model display lists.

The N64 builds store models as F3DEX display lists in which segment 5 addresses point back into
the model file itself. Textures are found by walking the command stream for the load idiom
``G_SETTIMG(palette)`` then ``G_LOADTLUT`` then ``G_SETTIMG(pixels)`` then ``G_SETTILESIZE``.

The PC port replaced the display list with a flat four-word descriptor introduced by the marker
``0xAC000000``. Every PC texture is 8-bit colour-indexed against a shared 256-colour palette with
tightly packed rows, which is far simpler than the N64 side.

Both walkers are heuristic: they infer image dimensions the hardware never had to store. The
sanity gate in :py:func:`parse_dl_textures` rejects results outside 2 to 512 pixels a side, since
anything outside that is a mis-parse rather than a game texture. Use the montage commands to
review the results visually.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from .images import TLUT_SIZE, decode_ci, decode_rgba16, read_tlut
from .typing import Texture

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ('MAX_TEXTURE_SIDE', 'MIN_TEXTURE_SIDE', 'parse_dl_textures', 'parse_pc_descriptors',
           'parse_pc_textures')

MIN_TEXTURE_SIDE = 2
"""Smallest plausible texture dimension.

:meta hide-value:
"""
MAX_TEXTURE_SIDE = 512
"""Largest plausible texture dimension.

:meta hide-value:
"""

_G_SETTIMG = 0xFD
_G_SETTILE = 0xF5
_G_LOADTLUT = 0xF0
_G_LOADTILE = 0xF4
_G_SETTILESIZE = 0xF2
_SEGMENT_5 = 0x05
_SIZ_CI4 = 0
_SIZ_CI8 = 1
_SIZ_RGBA16 = 2
_PC_MARKER = 0xAC000000
_PC_MAX_SIDE = 256
_PC_DIMENSION_MARKER = 0x04


def _plausible(width: int, height: int) -> bool:
    return (MIN_TEXTURE_SIDE <= width <= MAX_TEXTURE_SIDE
            and MIN_TEXTURE_SIDE <= height <= MAX_TEXTURE_SIDE)


def _scan_load_tiles(data: bytes) -> tuple[list[int], dict[int, int]]:
    """
    Collect segment-5 image addresses and the tallest tile run for each.

    A display list draws an atlas as many sub-rectangles, so the bottom edge of the tallest
    ``G_LOADTILE`` bounds the real image height. Only the first run for an address counts; later
    runs are separate draws of an image already measured.

    Returns
    -------
    tuple[list[int], dict[int, int]]
        The sorted image addresses, and the tallest bottom edge seen for each.
    """
    n = len(data)
    addresses: set[int] = set()
    max_bottom: dict[int, int] = {}
    last: int | None = None
    current: int | None = None
    skip = False
    for offset in range(0, n - 8, 8):
        w0, w1 = struct.unpack_from('>II', data, offset)
        op = w0 >> 24
        if op == _G_SETTIMG and (w1 >> 24) == _SEGMENT_5:
            last = w1 & 0xFFFFFF
            addresses.add(last)
        elif op == _G_LOADTLUT:  # That image was a palette, not pixels.
            last = None
        elif op == _G_LOADTILE and last is not None:
            if last != current:
                current = last
                skip = last in max_bottom
                if not skip:
                    max_bottom[last] = 0
            if not skip:
                max_bottom[last] = max(max_bottom[last], (w1 & 0xFFF) >> 2)
    return sorted(addresses), max_bottom


def parse_dl_textures(data: bytes) -> list[Texture]:
    """
    Decode every texture referenced by an F3DEX display list.

    Parameters
    ----------
    data : bytes
        A flat model blob whose segment-5 addresses index into itself.

    Returns
    -------
    list[dade.xg2.typing.Texture]
        The decoded textures, in the order the display list loads them.
    """
    n = len(data)
    addresses, max_bottom = _scan_load_tiles(data)

    def region_end(address: int) -> int:
        for candidate in addresses:
            if candidate > address:
                return candidate
        return n

    out: list[Texture] = []
    last: tuple[int, int] | None = None
    palette: list[bytes] | None = None
    tile_size: int | None = None
    tile_line = 0
    seen: set[int] = set()
    for offset in range(0, n - 8, 8):
        w0, w1 = struct.unpack_from('>II', data, offset)
        op = w0 >> 24
        if op == _G_SETTIMG:
            last = (w1 & 0xFFFFFF, (w0 & 0x3FF) + 1) if (w1 >> 24) == _SEGMENT_5 else None
        elif op == _G_SETTILE:
            tile_size = (w0 >> 19) & 3
            tile_line = (w0 >> 9) & 0x1FF
        elif op == _G_LOADTLUT:
            count = ((w1 >> 14) & 0x3FF) + 1
            if last is not None and count <= TLUT_SIZE and last[0] + count * 2 <= n:
                palette = read_tlut(data, last[0], count)
            last = None
        elif op == _G_SETTILESIZE:
            if last is None or last[0] in seen:
                continue
            pixels = last[0]
            texture = _decode_tile(
                data, pixels, palette, tile_size,
                (last[1], (((w1 >> 12) & 0xFFF) >> 2) + 1, ((w1 & 0xFFF) >> 2) + 1, tile_line,
                 region_end(pixels) - pixels, max_bottom.get(pixels)))
            if texture is not None:
                out.append(texture)
                seen.add(pixels)
            last = None
    return out


def _decode_tile(data: bytes, pixels: int, palette: list[bytes] | None, tile_size: int | None,
                 geometry: tuple[int, int, int, int, int, int | None]) -> Texture | None:
    """
    Decode one tile once its format and geometry are known.

    Returns
    -------
    dade.xg2.typing.Texture | None
        The texture, or ``None`` when the inferred geometry is not plausible.
    """
    n = len(data)
    header_width, render_width, render_height, tile_line, region, bottom = geometry
    atlas = header_width > 1
    # An atlas is bounded by its tallest sub-rectangle; without one, fall back to the render
    # height so trailing non-texture bytes do not add rubbish rows.
    height = (bottom + 1) if bottom is not None else render_height
    if tile_size == _SIZ_CI8 and palette:
        width, row_bytes = ((header_width, header_width) if atlas else
                            (render_width, max(tile_line * 8, render_width)))
        height = min(height, region // row_bytes) if atlas else height
        if _plausible(width, height) and pixels + (height - 1) * row_bytes + width <= n:
            return Texture('ci8', pixels, width, height,
                           decode_ci(data, pixels, width, height, palette, 8, row_bytes))
    elif tile_size == _SIZ_CI4 and palette:
        width, row_bytes = ((header_width * 2, header_width) if atlas else
                            (render_width, max(tile_line * 8, (render_width + 1) // 2)))
        height = min(height, region // row_bytes) if atlas else height
        if _plausible(width, height) and pixels + (height - 1) * row_bytes + (width + 1) // 2 <= n:
            return Texture('ci4', pixels, width, height,
                           decode_ci(data, pixels, width, height, palette, 4, row_bytes))
    elif tile_size == _SIZ_RGBA16:
        width, row_bytes = ((header_width, header_width * 2) if atlas else
                            (render_width, max(tile_line * 8, render_width * 2)))
        height = min(height, region // row_bytes) if atlas else height
        if _plausible(width, height) and pixels + (height - 1) * row_bytes + width * 2 <= n:
            return Texture('rgba16', pixels, width, height,
                           decode_rgba16(data, pixels, width, height, row_bytes))
    return None


def parse_pc_descriptors(model: bytes) -> Iterator[tuple[int, int, int, int, int]]:
    """
    Yield every valid ``0xAC`` texture descriptor in a PC model blob.

    A descriptor is four little-endian words: the marker, a segment-5 palette pointer, a dimension
    word whose second byte is ``0x04``, and a segment-5 pixel pointer.

    Parameters
    ----------
    model : bytes
        A PC model blob.

    Yields
    ------
    tuple[int, int, int, int, int]
        The descriptor offset, palette offset, pixel offset, width, and height.
    """
    n = len(model)
    for offset in range(0, n - 16, 4):
        if struct.unpack_from('<I', model, offset)[0] != _PC_MARKER:
            continue
        palette_word, dimensions, pixel_word = struct.unpack_from('<3I', model, offset + 4)
        if ((palette_word >> 24) != _SEGMENT_5 or (pixel_word >> 24) != _SEGMENT_5
                or ((dimensions >> 16) & 0xFF) != _PC_DIMENSION_MARKER):
            continue
        width, height = (dimensions >> 8) & 0xFF, dimensions & 0xFF
        if 1 <= width <= _PC_MAX_SIDE and 1 <= height <= _PC_MAX_SIDE:
            yield offset, palette_word & 0xFFFFFF, pixel_word & 0xFFFFFF, width, height


def parse_pc_textures(model: bytes) -> list[Texture]:
    """
    Decode every texture in a PC model blob.

    Every PC texture is 8-bit colour-indexed against a shared 256-colour palette with tightly
    packed rows. Palettes are shared and may sit after the pixels they belong to, so their
    position carries no information about the pixel depth.

    Parameters
    ----------
    model : bytes
        A PC model blob.

    Returns
    -------
    list[dade.xg2.typing.Texture]
        The decoded textures, one per distinct pixel offset.
    """
    n = len(model)
    out: list[Texture] = []
    seen: set[int] = set()
    for _, palette_offset, pixel_offset, width, height in parse_pc_descriptors(model):
        if pixel_offset in seen:
            continue
        if palette_offset + TLUT_SIZE * 2 > n or pixel_offset + width * height > n:
            continue
        palette = read_tlut(model, palette_offset, TLUT_SIZE, '<')
        seen.add(pixel_offset)
        out.append(
            Texture('ci8', pixel_offset, width, height,
                    decode_ci(model, pixel_offset, width, height, palette, 8, width)))
    return out
