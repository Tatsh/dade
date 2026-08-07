"""
Decoder for the textures embedded in a ``.PSX`` lighting companion file (``*_L.PSX``).

After the chunk list a lighting file carries, in order: a texture checksum table, a table of
16-colour palettes, a table of 256-colour palettes, and finally a table of texture instances.
Every table is preceded by its own 32-bit count::

    u32 numChecksums, u32 checksum[numChecksums]
    u32 numCluts16,  { u32 id, u16 entry[16], ... }   (9 dwords per record)
    u32 numCluts256, { u32 id, u16 entry[256], ... }  (0x81 dwords per record)
    u32 numInstances, u32 instanceOffset[numInstances]

    Instance (at instanceOffset[i]):
      +0x04 u32 numColors   (0x10 selects a 16-colour palette, otherwise 256)
      +0x08 u32 clutId
      +0x0C u32 page        (index into the checksum table)
      +0x10 u16 width
      +0x12 u16 height
      +0x14 pixels          (4 bits per pixel when numColors is 0x10, otherwise 8)

Palette entries are 16-bit ``BGR555``. Two values are treated as fully transparent and decode to
magenta so they stand out: zero and ``0x7C1F``.

The level and object scenes place their checksum table after a per-sector array instead, so they
are read by :py:meth:`destin.thps2pc.psx.Scene.texture_checksums`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import logging

from destin.common.io import i32, u16, u32
from destin.common.ppm import ppm

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from .typing import Rgb

__all__ = ('TRANSPARENT_COLOR', 'LightingTextures', 'TextureInstance', 'bgr555_to_rgb',
           'decode_instance', 'iter_decoded', 'parse_lighting', 'to_ppm')

log = logging.getLogger(__name__)

TRANSPARENT_COLOR: Rgb = (255, 0, 255)
"""Colour substituted for the two palette values the game treats as fully transparent.

:meta hide-value:
"""

_CLUT16_COLORS = 0x10
_CLUT16_STRIDE = 9 * 4
_CLUT256_STRIDE = 0x81 * 4
_TRANSPARENT_VALUES = frozenset({0, 0x7C1F})


class TextureInstance(NamedTuple):
    """One texture instance record."""

    checksum: int
    """Texture checksum resolved through the file's checksum table, or zero when out of range."""
    clut_id: int
    """Identifier of the palette this texture uses."""
    height: int
    """Height in pixels."""
    num_colors: int
    """Number of palette entries: ``0x10`` for 4 bits per pixel, otherwise 8 bits per pixel."""
    offset: int
    """Absolute offset of the instance record."""
    page: int
    """Index into the file's checksum table."""
    pixels_offset: int
    """Absolute offset of the first pixel byte."""
    width: int
    """Width in pixels."""
    @property
    def is_4bpp(self) -> bool:
        """Whether pixels are packed two per byte."""
        return self.num_colors == _CLUT16_COLORS


class LightingTextures(NamedTuple):
    """Every table decoded from a lighting file."""

    checksums: tuple[int, ...]
    """Texture checksums, in table order."""
    cluts_16: Mapping[int, int]
    """Palette identifier to the absolute offset of its first 16-colour entry."""
    cluts_256: Mapping[int, int]
    """Palette identifier to the absolute offset of its first 256-colour entry."""
    instances: tuple[TextureInstance, ...]
    """Texture instances, in table order."""


def bgr555_to_rgb(value: int) -> Rgb:
    """
    Expand a 16-bit ``BGR555`` palette entry to 8 bits per channel.

    Parameters
    ----------
    value : int
        The palette entry.

    Returns
    -------
    Rgb
        The expanded colour, or :py:data:`TRANSPARENT_COLOR` for a transparent entry.
    """
    if value in _TRANSPARENT_VALUES:
        return TRANSPARENT_COLOR
    red = value & 0x1F
    green = (value >> 5) & 0x1F
    blue = (value >> 10) & 0x1F
    return ((red << 3) | (red >> 2), (green << 3) | (green >> 2), (blue << 3) | (blue >> 2))


def decode_instance(data: bytes, instance: TextureInstance,
                    tables: LightingTextures) -> bytes | None:
    """
    Decode one texture instance to packed 24-bit RGB pixels.

    Parameters
    ----------
    data : bytes
        The whole lighting file.
    instance : TextureInstance
        The instance to decode.
    tables : LightingTextures
        The tables the instance's palette is resolved against.

    Returns
    -------
    bytes | None
        Row-major RGB triples, or ``None`` when the instance names a palette that is absent.
    """
    cluts = tables.cluts_16 if instance.is_4bpp else tables.cluts_256
    clut_offset = cluts.get(instance.clut_id)
    if clut_offset is None:
        log.debug('Instance at %#x names missing palette %d.', instance.offset, instance.clut_id)
        return None
    out = bytearray()
    for pixel in range(instance.width * instance.height):
        if instance.is_4bpp:
            packed = data[instance.pixels_offset + (pixel >> 1)]
            index = (packed >> ((pixel & 1) * 4)) & 0xF
        else:
            index = data[instance.pixels_offset + pixel]
        out += bytes(bgr555_to_rgb(u16(data, clut_offset + index * 2)))
    return bytes(out)


def iter_decoded(data: bytes, tables: LightingTextures) -> Iterator[tuple[TextureInstance, bytes]]:
    """
    Decode every instance in a lighting file, skipping those with a missing palette.

    Parameters
    ----------
    data : bytes
        The whole lighting file.
    tables : LightingTextures
        The tables produced by :py:func:`parse_lighting`.

    Yields
    ------
    tuple[TextureInstance, bytes]
        Each instance and its packed RGB pixels.
    """
    for instance in tables.instances:
        if (pixels := decode_instance(data, instance, tables)) is not None:
            yield instance, pixels


def parse_lighting(data: bytes) -> LightingTextures:
    """
    Decode every table that follows the chunk list of a lighting file.

    Parameters
    ----------
    data : bytes
        The whole lighting file.

    Returns
    -------
    LightingTextures
        The checksum table, both palette tables, and the instance table.
    """
    offset = u32(data, 4)
    while i32(data, offset) != -1:
        offset = offset + 8 + u32(data, offset + 4)
    base = offset + 4
    num_checksums = u32(data, base)
    checksums = tuple(u32(data, base + 4 + i * 4) for i in range(num_checksums))
    position = base + 4 + num_checksums * 4
    cluts_16, position = _read_cluts(data, position, _CLUT16_STRIDE)
    cluts_256, position = _read_cluts(data, position, _CLUT256_STRIDE)
    num_instances = u32(data, position)
    position += 4
    instances = tuple(
        _read_instance(data, u32(data, position + i * 4), checksums) for i in range(num_instances))
    log.debug(
        'Parsed lighting file: %d checksums, %d 16-colour and %d 256-colour palettes, '
        '%d instances.', num_checksums, len(cluts_16), len(cluts_256), len(instances))
    return LightingTextures(checksums=checksums,
                            cluts_16=cluts_16,
                            cluts_256=cluts_256,
                            instances=instances)


def to_ppm(pixels: bytes, width: int, height: int) -> bytes:
    """
    Wrap packed RGB pixels in a binary PPM header.

    Parameters
    ----------
    pixels : bytes
        Row-major RGB triples.
    width : int
        Image width in pixels.
    height : int
        Image height in pixels.

    Returns
    -------
    bytes
        A complete binary PPM image.
    """
    return ppm(pixels, width, height)


def _read_cluts(data: bytes, offset: int, stride: int) -> tuple[dict[int, int], int]:
    count = u32(data, offset)
    offset += 4
    cluts = {}
    for _ in range(count):
        cluts[u32(data, offset)] = offset + 4
        offset += stride
    return cluts, offset


def _read_instance(data: bytes, offset: int, checksums: tuple[int, ...]) -> TextureInstance:
    page = u32(data, offset + 0x0C)
    return TextureInstance(checksum=checksums[page] if page < len(checksums) else 0,
                           clut_id=u32(data, offset + 8),
                           height=u16(data, offset + 0x12),
                           num_colors=u32(data, offset + 4),
                           offset=offset,
                           page=page,
                           pixels_offset=offset + 0x14,
                           width=u16(data, offset + 0x10))
