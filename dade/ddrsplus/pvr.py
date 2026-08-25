"""
Reader for the legacy PowerVR (PVR v2) textures *DDR S+* stores its banners as.

The 52-byte header is thirteen little-endian words::

    headerSize height width mipMapCount flags dataSize bitCount
    rMask gMask bMask aMask 'PVR!' numSurfs

``flags`` holds the pixel type in its low byte and feature bits above it. Rather than carry a table
of pixel types, the decoder reads each channel out with the four bit masks the header itself
supplies, which covers RGBA4444, RGBA5551, RGB565, RGB888, and RGBA8888 without special cases.
Compressed and mipmapped textures are rejected up front, because for those the masks and the bit
count do not describe the payload.

Every banner is a 256x64 texture because the hardware wanted power-of-two dimensions, but the
artwork occupies only :py:data:`BANNER_SIZE` in the top left. On each banner checked, every pixel
outside that region is the single fully transparent colour ``(255, 255, 255, 0)`` and the
non-transparent bounding box is exactly 196x61, so :py:func:`crop` trims the padding away.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import struct

from dade.common.exceptions import InvalidFormatError

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ('BANNER_SIZE', 'HEADER_SIZE', 'PVRHeader', 'Texture', 'crop', 'decode_pvr',
           'read_header')

HEADER_SIZE = 52
"""Bytes the PVR v2 header spans.

:meta hide-value:
"""
BANNER_SIZE = (196, 61)
"""Size of the artwork inside a banner texture, the rest being transparent padding.

:meta hide-value:
"""

_FIELDS = 13
_PVR_TAG = 0x21525650
_ALPHA_FLAG = 1 << 15
_MIPMAP_FLAG = 1 << 8
_TWIDDLE_FLAG = 1 << 9
_BITS_PER_BYTE = 8
_MAX_8_BIT = 0xFF
_CHANNELS = 4


class PVRHeader(NamedTuple):
    """A parsed PVR v2 header."""

    header_size: int
    """Bytes the header spans."""
    height: int
    """Image height in pixels."""
    width: int
    """Image width in pixels."""
    mipmap_count: int
    """How many mipmap levels follow the top level."""
    flags: int
    """The pixel type in the low byte and feature bits above it."""
    data_size: int
    """Bytes of pixel data following the header."""
    bit_count: int
    """Bits one pixel spans."""
    r_mask: int
    """Bit mask selecting the red channel."""
    g_mask: int
    """Bit mask selecting the green channel."""
    b_mask: int
    """Bit mask selecting the blue channel."""
    a_mask: int
    """Bit mask selecting the alpha channel."""
    tag: int
    """The ``PVR!`` magic."""
    num_surfaces: int
    """How many surfaces the file holds."""
    @property
    def has_alpha(self) -> bool:
        """
        Whether the texture declares an alpha channel.

        Returns
        -------
        bool
            ``True`` when the alpha flag is set.
        """
        return bool(self.flags & _ALPHA_FLAG)

    @property
    def pixel_type(self) -> int:
        """
        The pixel type, the low byte of the flags.

        Returns
        -------
        int
            The pixel type.
        """
        return self.flags & 0xFF


class Texture(NamedTuple):
    """A decoded texture."""

    width: int
    """Image width in pixels."""
    height: int
    """Image height in pixels."""
    pixels: bytes
    """Row-major RGBA quads, four bytes per pixel."""


def read_header(data: bytes) -> PVRHeader:
    """
    Parse and validate a PVR v2 header.

    Parameters
    ----------
    data : bytes
        The whole texture file.

    Returns
    -------
    PVRHeader
        The parsed header.

    Raises
    ------
    InvalidFormatError
        If the file is too short, lacks the ``PVR!`` tag, or describes a texture this reader
        cannot decode.
    """
    if len(data) < HEADER_SIZE:
        msg = f'Too short for a {HEADER_SIZE}-byte PVR header: {len(data)} bytes.'
        raise InvalidFormatError(msg)
    header = PVRHeader(*struct.unpack_from(f'<{_FIELDS}I', data, 0))
    if header.tag != _PVR_TAG:
        msg = f'Not a PVR v2 texture, the tag is {header.tag:#010x}.'
        raise InvalidFormatError(msg)
    if header.header_size != HEADER_SIZE:
        msg = f'Unexpected header size {header.header_size}, expected {HEADER_SIZE}.'
        raise InvalidFormatError(msg)
    for flag, name in ((_MIPMAP_FLAG, 'mipmapped'), (_TWIDDLE_FLAG, 'twiddled')):
        if header.flags & flag:
            msg = f'Cannot decode a {name} texture, flags {header.flags:#x}.'
            raise InvalidFormatError(msg)
    if header.bit_count % _BITS_PER_BYTE:
        msg = f'Cannot decode a {header.bit_count}-bit pixel that is not a whole byte count.'
        raise InvalidFormatError(msg)
    expected = header.width * header.height * header.bit_count // _BITS_PER_BYTE
    if header.data_size != expected:
        msg = (f'Data size {header.data_size} does not match {header.width}x{header.height} at '
               f'{header.bit_count} bpp, which needs {expected} bytes; pixel type '
               f'{header.pixel_type:#04x} is probably compressed.')
        raise InvalidFormatError(msg)
    if len(data) < HEADER_SIZE + header.data_size:
        msg = (f'The header claims {header.data_size} pixel bytes but only '
               f'{len(data) - HEADER_SIZE} follow it.')
        raise InvalidFormatError(msg)
    if not header.r_mask | header.g_mask | header.b_mask:
        msg = 'The header carries no colour bit masks, so the pixel layout is unknown.'
        raise InvalidFormatError(msg)
    return header


def _channel_reader(mask: int) -> Callable[[int], int]:
    """
    Build a function lifting one masked channel to a full 8-bit value.

    A channel narrower than eight bits is scaled by bit replication so an all-ones field becomes
    255 exactly rather than falling short of white.

    Parameters
    ----------
    mask : int
        The channel's bit mask, possibly zero.

    Returns
    -------
    collections.abc.Callable[[int], int]
        A function mapping a raw pixel to that channel's value. A zero mask yields a function
        returning 255, the right default for a missing alpha channel.
    """
    if not mask:
        return lambda _: _MAX_8_BIT
    shift = (mask & -mask).bit_length() - 1
    width = (mask).bit_count()
    if width >= _BITS_PER_BYTE:
        drop = width - _BITS_PER_BYTE
        return lambda pixel: ((pixel & mask) >> shift) >> drop
    if 2 * width >= _BITS_PER_BYTE:
        return lambda pixel: (((pixel & mask) >> shift) << (_BITS_PER_BYTE - width) | (
            (pixel & mask) >> shift) >> (2 * width - _BITS_PER_BYTE))
    scale = _MAX_8_BIT // ((1 << width) - 1)
    return lambda pixel: ((pixel & mask) >> shift) * scale


def decode_pvr(data: bytes) -> Texture:
    """
    Decode a PVR v2 texture to 8-bit RGBA.

    Parameters
    ----------
    data : bytes
        The whole texture file.

    Returns
    -------
    Texture
        The dimensions and ``width * height * 4`` bytes of RGBA.

    """
    header = read_header(data)
    stride = header.bit_count // _BITS_PER_BYTE
    body = data[HEADER_SIZE:HEADER_SIZE + header.data_size]
    readers = (_channel_reader(header.r_mask), _channel_reader(
        header.g_mask), _channel_reader(
            header.b_mask), _channel_reader(header.a_mask if header.has_alpha else 0))
    out = bytearray(header.width * header.height * _CHANNELS)
    for index in range(header.width * header.height):
        pixel = int.from_bytes(body[index * stride:(index + 1) * stride], 'little')
        out[index * _CHANNELS:(index + 1) * _CHANNELS] = bytes(read(pixel) for read in readers)
    return Texture(header.width, header.height, bytes(out))


def crop(texture: Texture, size: tuple[int, int] = BANNER_SIZE) -> Texture:
    """
    Trim a texture to a region anchored at its top left corner.

    A texture smaller than the requested region in either axis is returned unchanged rather than
    padded.

    Parameters
    ----------
    texture : Texture
        The decoded texture.
    size : tuple[int, int]
        The width and height to keep.

    Returns
    -------
    Texture
        The cropped texture, or the original when it is already no larger.
    """
    width, height = size
    if texture.width <= width and texture.height <= height:
        return texture
    width, height = min(width, texture.width), min(height, texture.height)
    row = texture.width * _CHANNELS
    return Texture(
        width, height,
        b''.join(texture.pixels[y * row:y * row + width * _CHANNELS] for y in range(height)))
