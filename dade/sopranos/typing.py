"""Typing helpers for the Sopranos submodule."""
from __future__ import annotations

from typing import Literal, NamedTuple, TypeAlias

__all__ = ('FSEntry', 'LevelEntry', 'PixelFormat', 'Primitive', 'SoundEntry', 'TextureInfo')

Primitive: TypeAlias = Literal[3, 4]
"""GS primitive type: ``3`` is an independent triangle list, ``4`` a triangle strip.

:meta hide-value:
"""

PixelFormat: TypeAlias = Literal[2, 4, 5]
"""Stored pixel format: ``2`` is 8-bit paletted, ``4`` is 24-bit RGB, ``5`` is 32-bit RGBA.

:meta hide-value:
"""


class FSEntry(NamedTuple):
    """One file inside a ``.FS`` archive."""

    name: str
    """Slash-separated path recorded in the archive's string table."""
    offset: int
    """Absolute byte offset of the file's data, always a multiple of 2048."""
    size: int
    """Length of the file's data in bytes."""
    name_hash: int
    """CRC-32 of the lowercased name, as stored in the directory chunk."""


class LevelEntry(NamedTuple):
    """One sub-asset stored inside a ``.LVL`` container."""

    name: str
    """Name recorded in the index, such as ``p_bcasino1.SGP2``."""
    offset: int
    """Byte offset of the sub-asset within the ``.LVL`` file."""
    size: int
    """Length of the sub-asset in bytes."""


class TextureInfo(NamedTuple):
    """One image inside a ``.TEX2`` texture bank."""

    name: str
    """Original source path, such as ``data/interface/hud/simpleshadow.tga``."""
    width: int
    """Width in pixels."""
    height: int
    """Height in pixels."""
    pixel_format: PixelFormat
    """Stored pixel format."""
    data_offset: int
    """Absolute byte offset of the pixel data."""
    palette_offset: int
    """Absolute byte offset of the 256-entry palette, or ``0`` when there is none."""
    name_hash: int
    """CRC-32 of the lowercased name, as stored in the bank."""


class SoundEntry(NamedTuple):
    """One sound described by a ``.MSH`` header and stored in the matching ``.MSB`` body."""

    number: int
    """Position among the header's playable entries, used to name the extracted file."""
    offset: int
    """Byte offset of the sound's PS-ADPCM data within the ``.MSB`` body."""
    size: int
    """Length of the sound's PS-ADPCM data in bytes."""
    rate: int
    """Sample rate in Hz."""
    identifier: int
    """Raw second word of the entry: a sequential index in some banks, a name hash in others."""
