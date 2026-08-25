"""
Decoders for the Interstate '76 texture formats.

Reverse-engineered from the texture loader at ``FUN_004474b0`` and the vector-quantisation decoder
at ``FUN_0044b430``:

- ``.act`` is a 256-entry RGB palette, three bytes per entry.
- ``.map`` is a width and height dword pair followed by one palette index per pixel.
- ``.vqm`` is a width and height dword pair, a NUL-terminated codebook name, and then one unsigned
  16-bit codebook index per 4x4 block. An index with the top bit set encodes a solid-colour block
  in its low byte instead of referencing the codebook.
- ``.cbk`` is a count dword followed by that many 16-byte entries, each a 4x4 block of palette
  indices.

Every format resolves to 8-bit palette indices, which :py:func:`to_rgb` expands through a palette.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import struct

from .typing import IndexedImage, VqmImage

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ('PALETTE_SIZE', 'decode_map', 'decode_vqm', 'load_codebook', 'load_palette', 'to_rgb',
           'vqm_codebook_name')

log = logging.getLogger(__name__)

PALETTE_SIZE = 768
"""Length of an ``.act`` palette in bytes, being 256 RGB triples.

:meta hide-value:
"""

_BLOCK_SIZE = 4
"""Edge length in pixels of one vector-quantised block.

:meta hide-value:
"""
_CODEBOOK_ENTRY_SIZE = 16
"""Size in bytes of one codebook entry, being a 4x4 block of palette indices.

:meta hide-value:
"""
_SOLID_BLOCK_FLAG = 0x8000
"""Set on a ``.vqm`` index whose low byte is a solid colour rather than a codebook reference.

:meta hide-value:
"""
_VQM_INDEX_OFFSET = 24
"""Offset at which a ``.vqm``'s block indices begin.

:meta hide-value:
"""


def load_palette(data: bytes) -> bytes:
    """
    Take the palette out of an ``.act`` file.

    Parameters
    ----------
    data : bytes
        Contents of the ``.act`` file.

    Returns
    -------
    bytes
        The first 768 bytes, being 256 RGB triples.
    """
    return data[:PALETTE_SIZE]


def load_codebook(data: bytes) -> tuple[bytes, ...]:
    """
    Parse a ``.cbk`` codebook.

    Parameters
    ----------
    data : bytes
        Contents of the ``.cbk`` file.

    Returns
    -------
    tuple[bytes, ...]
        One 16-byte 4x4 block of palette indices per codebook entry.
    """
    count = struct.unpack_from('<I', data, 0)[0]
    return tuple(data[4 + index * _CODEBOOK_ENTRY_SIZE:4 + (index + 1) * _CODEBOOK_ENTRY_SIZE]
                 for index in range(count))


def decode_map(data: bytes) -> IndexedImage:
    """
    Decode a ``.map`` palette-indexed image.

    Parameters
    ----------
    data : bytes
        Contents of the ``.map`` file.

    Returns
    -------
    IndexedImage
        The image dimensions and its palette indices.
    """
    width, height = struct.unpack_from('<II', data, 0)
    return IndexedImage(width, height, data[8:8 + width * height])


def vqm_codebook_name(data: bytes) -> str:
    """
    Read the codebook name a ``.vqm`` references.

    Parameters
    ----------
    data : bytes
        Contents of the ``.vqm`` file.

    Returns
    -------
    str
        The NUL-terminated codebook file name stored in the header.
    """
    return data[8:data.index(b'\x00', 8)].decode('latin1')


def decode_vqm(data: bytes, codebook: Sequence[bytes]) -> VqmImage:
    """
    Decode a ``.vqm`` vector-quantised image.

    Parameters
    ----------
    data : bytes
        Contents of the ``.vqm`` file.
    codebook : collections.abc.Sequence[bytes]
        The codebook named by :py:func:`vqm_codebook_name`, as returned by
        :py:func:`load_codebook`.

    Returns
    -------
    VqmImage
        The image dimensions, its palette indices, and the codebook name from the header.
    """
    width, height = struct.unpack_from('<II', data, 0)
    name = vqm_codebook_name(data)
    blocks_wide, blocks_high = width // _BLOCK_SIZE, height // _BLOCK_SIZE
    indices = struct.unpack_from(f'<{blocks_wide * blocks_high}H', data, _VQM_INDEX_OFFSET)
    out = bytearray(width * height)
    for block_y in range(blocks_high):
        for block_x in range(blocks_wide):
            value = indices[block_y * blocks_wide + block_x]
            for row in range(_BLOCK_SIZE):
                for column in range(_BLOCK_SIZE):
                    if value & _SOLID_BLOCK_FLAG:
                        pixel = value & 0xFF
                    else:
                        pixel = codebook[value][row * _BLOCK_SIZE + column]
                    out[(block_y * _BLOCK_SIZE + row) * width +
                        (block_x * _BLOCK_SIZE + column)] = pixel
    return VqmImage(width, height, bytes(out), name)


def to_rgb(indices: bytes, width: int, height: int, palette: bytes) -> bytes:
    """
    Expand palette indices to RGB triples.

    Parameters
    ----------
    indices : bytes
        Row-major palette indices, one byte per pixel.
    width : int
        Image width in pixels.
    height : int
        Image height in pixels.
    palette : bytes
        A 768-byte palette of 256 RGB triples.

    Returns
    -------
    bytes
        Row-major RGB triples, three bytes per pixel.
    """
    out = bytearray(width * height * 3)
    for position, index in enumerate(indices[:width * height]):
        out[position * 3 + 0] = palette[index * 3 + 0]
        out[position * 3 + 1] = palette[index * 3 + 1]
        out[position * 3 + 2] = palette[index * 3 + 2]
    return bytes(out)
