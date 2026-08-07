"""
Texture and image decoders shared by the N64 and PC builds.

Both platforms use the same three pixel formats -- 4- and 8-bit colour-indexed against a shared
RGBA5551 palette, and direct RGBA5551 -- and differ only in the byte order of their 16-bit values.
Every decoder here therefore takes a :py:data:`~destin.xg2.typing.Endian` character, so one
implementation serves both.

Rows may be padded: the N64 pads each row of a tile to a 64-bit boundary, so the stride can exceed
the visible width. Callers pass the stride in bytes explicitly.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from destin.common.image import expand5
from destin.common.png import write_rgba

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from .typing import Endian

__all__ = ('TLUT_SIZE', 'bmp_to_png', 'decode_ci', 'decode_i8', 'decode_rgba16', 'read_tlut',
           'rgba5551', 'write_png')

TLUT_SIZE = 256
"""Number of entries in a full colour lookup table.

:meta hide-value:
"""
_TRANSPARENT = b'\x00\x00\x00\x00'
_BPP_8 = 8


def rgba5551(value: int) -> bytes:
    """
    Expand one RGBA5551 texel to RGBA8.

    The five-bit channels are expanded by replicating their top three bits, and the single alpha
    bit becomes fully opaque or fully transparent.

    Parameters
    ----------
    value : int
        The 16-bit texel.

    Returns
    -------
    bytes
        Four bytes in RGBA order.
    """
    r, g, b = (value >> 11) & 0x1F, (value >> 6) & 0x1F, (value >> 1) & 0x1F
    return bytes((expand5(r), expand5(g), expand5(b), 255 if value & 1 else 0))


def read_tlut(data: bytes, offset: int, count: int, endian: Endian = '>') -> list[bytes]:
    """
    Read a colour lookup table of RGBA5551 entries.

    Parameters
    ----------
    data : bytes
        Buffer holding the palette.
    offset : int
        Offset of the first entry.
    count : int
        Number of entries to read.
    endian : destin.xg2.typing.Endian
        Byte order of the 16-bit entries.

    Returns
    -------
    list[bytes]
        One four-byte RGBA quad per entry, stopping early if the buffer ends.
    """
    return [
        rgba5551(struct.unpack_from(f'{endian}H', data, offset + 2 * i)[0]) for i in range(count)
        if offset + 2 * i + 2 <= len(data)
    ]


def decode_ci(data: bytes, offset: int, width: int, height: int, tlut: Sequence[bytes], bpp: int,
              stride: int) -> bytes:
    """
    Decode a colour-indexed image to RGBA8.

    Parameters
    ----------
    data : bytes
        Buffer holding the pixel data.
    offset : int
        Offset of the first row.
    width : int
        Width in pixels.
    height : int
        Height in pixels.
    tlut : collections.abc.Sequence[bytes]
        Palette, as returned by :py:func:`read_tlut`. Indices beyond it become transparent.
    bpp : int
        Bits per pixel, either 4 or 8. At 4bpp the high nibble is the left-hand pixel.
    stride : int
        Bytes per source row, which may exceed the visible width.

    Returns
    -------
    bytes
        Pixel data, four bytes per pixel.
    """
    rgba = bytearray(width * height * 4)
    for y in range(height):
        row = offset + y * stride
        for x in range(width):
            if bpp == _BPP_8:
                position = row + x
                index = data[position] if position < len(data) else 0
            else:
                position = row + (x >> 1)
                if position >= len(data):
                    index = 0
                else:
                    index = (data[position] >> 4) if (x & 1) == 0 else (data[position] & 0xF)
            i = (y * width + x) * 4
            rgba[i:i + 4] = tlut[index] if index < len(tlut) else _TRANSPARENT
    return bytes(rgba)


def decode_rgba16(data: bytes,
                  offset: int,
                  width: int,
                  height: int,
                  stride: int,
                  endian: Endian = '>') -> bytes:
    """
    Decode a direct-colour RGBA5551 image to RGBA8.

    Parameters
    ----------
    data : bytes
        Buffer holding the pixel data.
    offset : int
        Offset of the first row.
    width : int
        Width in pixels.
    height : int
        Height in pixels.
    stride : int
        Bytes per source row, which may exceed twice the visible width.
    endian : destin.xg2.typing.Endian
        Byte order of the 16-bit texels.

    Returns
    -------
    bytes
        Pixel data, four bytes per pixel. Texels past the end of *data* are left transparent.
    """
    out = bytearray(width * height * 4)
    for y in range(height):
        row = offset + y * stride
        for x in range(width):
            position = row + x * 2
            if position + 2 <= len(data):
                i = (y * width + x) * 4
                out[i:i + 4] = rgba5551(struct.unpack_from(f'{endian}H', data, position)[0])
    return bytes(out)


def decode_i8(data: bytes, width: int, height: int) -> bytes:
    """
    Decode an 8-bit greyscale image to opaque RGBA8.

    Parameters
    ----------
    data : bytes
        Buffer holding exactly the pixel data.
    width : int
        Width in pixels.
    height : int
        Height in pixels.

    Returns
    -------
    bytes
        Pixel data, four bytes per pixel.
    """
    out = bytearray(width * height * 4)
    for i in range(width * height):
        value = data[i]
        out[i * 4:i * 4 + 4] = bytes((value, value, value, 255))
    return bytes(out)


def write_png(path: Path, width: int, height: int, rgba: bytes) -> None:
    """
    Write RGBA8 pixel data to a PNG file.

    Parameters
    ----------
    path : pathlib.Path
        Destination file, whose parent must already exist.
    width : int
        Width in pixels.
    height : int
        Height in pixels.
    rgba : bytes
        Pixel data, four bytes per pixel.
    """
    write_rgba(path, width, height, rgba)


def bmp_to_png(source: Path, destination: Path) -> bool:
    """
    Convert an 8-bit palettised Windows bitmap to PNG.

    Only the 8-bit colour-indexed bitmaps the PC port ships are handled; anything else is left
    alone so the caller can copy it verbatim.

    Parameters
    ----------
    source : pathlib.Path
        The bitmap to read.
    destination : pathlib.Path
        The PNG to write, whose parent must already exist.

    Returns
    -------
    bool
        Whether the file was converted.
    """
    data = source.read_bytes()
    if data[:2] != b'BM' or struct.unpack_from('<H', data, 28)[0] != _BPP_8:
        return False
    pixels = struct.unpack_from('<I', data, 10)[0]
    width, height = struct.unpack_from('<ii', data, 18)
    palette_offset = 14 + struct.unpack_from('<I', data, 14)[0]
    palette = [
        bytes((data[palette_offset + i * 4 + 2], data[palette_offset + i * 4 + 1],
               data[palette_offset + i * 4], 255)) for i in range(TLUT_SIZE)
    ]
    bottom_up = height > 0
    height = abs(height)
    stride = (width + 3) & ~3  # Bitmap rows are padded to a four-byte boundary.
    rgba = bytearray(width * height * 4)
    for y in range(height):
        source_y = (height - 1 - y) if bottom_up else y
        for x in range(width):
            i = (y * width + x) * 4
            rgba[i:i + 4] = palette[data[pixels + source_y * stride + x]]
    write_png(destination, width, height, bytes(rgba))
    return True
