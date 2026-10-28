"""
Decoding of Nintendo 64 texels to RGBA.

The game loads every texture with ``G_LOADBLOCK`` and a ``dxt`` of 0. The load then copies the
texels into texture memory as they are, while the sampler reads each odd row with its 32-bit words
swapped. The cartridge therefore stores every odd row with its words already swapped, and a decoder
reading the cartridge undoes the swap.
"""
from __future__ import annotations

from typing import NamedTuple

__all__ = ('FMT_CI', 'FMT_I', 'FMT_IA', 'FMT_RGBA', 'SIZ_4B', 'SIZ_8B', 'SIZ_16B', 'SIZ_32B',
           'TextureKey', 'decode', 'decode_tlut', 'rgba5551')

FMT_RGBA = 0
"""``G_IM_FMT_RGBA``.

:meta hide-value:
"""
FMT_CI = 2
"""``G_IM_FMT_CI``.

:meta hide-value:
"""
FMT_IA = 3
"""``G_IM_FMT_IA``.

:meta hide-value:
"""
FMT_I = 4
"""``G_IM_FMT_I``.

:meta hide-value:
"""
SIZ_4B = 0
"""``G_IM_SIZ_4b``.

:meta hide-value:
"""
SIZ_8B = 1
"""``G_IM_SIZ_8b``.

:meta hide-value:
"""
SIZ_16B = 2
"""``G_IM_SIZ_16b``.

:meta hide-value:
"""
SIZ_32B = 3
"""``G_IM_SIZ_32b``.

:meta hide-value:
"""


class TextureKey(NamedTuple):
    """Everything that decides the pixels of one texture."""

    address: int
    """Offset of the texels in the memory the display list addresses."""
    palette: int
    """Offset of the palette, or -1 for a format without one."""
    fmt: int
    """The ``G_IM_FMT_*`` value."""
    siz: int
    """The ``G_IM_SIZ_*`` value."""
    width: int
    """Width in texels."""
    height: int
    """Height in texels."""
    line: int
    """Row stride in 64-bit words, or 0 for rows packed without padding."""


def rgba5551(value: int) -> tuple[int, int, int, int]:
    """
    Expand an RGBA 5551 colour to 8 bits a channel.

    Parameters
    ----------
    value : int
        The 16-bit colour.

    Returns
    -------
    tuple[int, int, int, int]
        Red, green, blue, and alpha.
    """
    return (((value >> 11) & 0x1F) * 255 // 31, ((value >> 6) & 0x1F) * 255 // 31,
            ((value >> 1) & 0x1F) * 255 // 31, 255 if value & 1 else 0)


def decode_tlut(memory: bytes | bytearray, offset: int,
                count: int) -> list[tuple[int, int, int, int]]:
    """
    Read a palette of big-endian RGBA 5551 colours.

    Colours past the end of ``memory`` read as transparent black.

    Parameters
    ----------
    memory : bytes | bytearray
        The memory the palette is in.
    offset : int
        Offset of the first colour.
    count : int
        The number of colours.

    Returns
    -------
    list[tuple[int, int, int, int]]
        The colours.
    """
    return [
        rgba5551(int.from_bytes(memory[o:o + 2], 'big')) if o >= 0 and o + 2 <= len(memory) else
        (0, 0, 0, 0) for o in range(offset, offset + count * 2, 2)
    ]


def _texel(memory: bytes | bytearray, key: TextureKey, x: int, y: int, stride: int,
           swap: int) -> int:
    bits = 4 << key.siz
    position = x * bits
    byte = key.address + y * stride * 8 + ((position >> 3) ^ (swap if y & 1 else 0))
    if byte < 0 or byte + max(bits // 8, 1) > len(memory):
        return 0
    match bits:
        case 4:
            return (memory[byte] >> (0 if position & 4 else 4)) & 0xF
        case 8:
            return memory[byte]
        case 16:
            return (memory[byte] << 8) | memory[byte + 1]
        case _:
            return int.from_bytes(memory[byte:byte + 4], 'big')


def _colour(key: TextureKey, value: int, palette: list[tuple[int, int, int, int]]) -> bytes:
    match (key.fmt, key.siz):
        case (2, _):
            return bytes(palette[value] if value < len(palette) else (0, 0, 0, 0))
        case (3, 0):
            intensity = ((value >> 1) & 7) * 255 // 7
            return bytes((intensity, intensity, intensity, 255 if value & 1 else 0))
        case (3, 1):
            intensity = (value >> 4) * 17
            return bytes((intensity, intensity, intensity, (value & 0xF) * 17))
        case (3, _):
            return bytes((value >> 8, value >> 8, value >> 8, value & 0xFF))
        case (4, 0):
            return bytes((value * 17,) * 4)
        case (4, _):
            return bytes(((value & 0xFF),) * 4)
        case (_, 3):
            return value.to_bytes(4, 'big')
        case _:
            return bytes(rgba5551(value))


def decode(memory: bytes | bytearray, key: TextureKey, *, swapped_rows: bool = True) -> bytes:
    """
    Decode a texture to 8-bit RGBA.

    Parameters
    ----------
    memory : bytes | bytearray
        The memory the texture and its palette are in.
    key : TextureKey
        The texture.
    swapped_rows : bool
        Whether the odd rows have their words swapped, as for a texture the game loads with
        ``G_LOADBLOCK``. An image the game draws a row at a time does not.

    Returns
    -------
    bytes
        ``width * height * 4`` bytes, row by row from the top.
    """
    stride = key.line or (key.width * (4 << key.siz) + 63) // 64
    palette = (decode_tlut(memory, key.palette, 16 if key.siz == SIZ_4B else 256)
               if key.fmt == FMT_CI else [])
    return b''.join(
        _colour(key, _texel(memory, key, x, y, stride, 4 if swapped_rows else 0), palette)
        for y in range(key.height) for x in range(key.width))
