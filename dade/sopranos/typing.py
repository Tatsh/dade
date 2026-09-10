"""Typing helpers for the Sopranos submodule."""
from __future__ import annotations

from enum import IntEnum
from typing import Literal, NamedTuple, TypeAlias

__all__ = ('BlendMode', 'FSEntry', 'LevelEntry', 'PixelFormat', 'Primitive', 'SoundEntry',
           'TextureInfo')

Primitive: TypeAlias = Literal[3, 4]
"""GS primitive type: ``3`` is an independent triangle list, ``4`` a triangle strip.

:meta hide-value:
"""

PixelFormat: TypeAlias = Literal[2, 4, 5]
"""Stored pixel format: ``2`` is 8-bit paletted, ``4`` is 24-bit RGB, ``5`` is 32-bit RGBA.

:meta hide-value:
"""


class BlendMode(IntEnum):
    """How the engine draws a surface using a texture, cooked into byte ``0x1B`` of its record.

    The engine passes a texture's handle to the texture manager, takes the flags back, and turns
    them into a GS ``TEST_1`` and ``ALPHA_1`` pair per material in ``FUN_001E8810``. Reading the
    byte gives the same result without having to recognise a texture by name or by content. Across
    all 133 levels, :py:attr:`ADDITIVE` is exactly the 171 ``add_`` textures and
    :py:attr:`SUBTRACTIVE` exactly the 262 ``sub_`` ones, with nothing else in either group.
    """

    DEFAULT = 0
    """No override; the render pass decides, and for a level that means opaque."""
    CUTOUT = 1
    """``TEST_1`` with ATE set, ATST ``GEQUAL`` and AREF 8 on the PS2's 0..128 alpha scale."""
    BLEND = 2
    """``ALPHA_1`` 0x44: ``(Cs - Cd) * As + Cd``."""
    ADDITIVE = 3
    """``ALPHA_1`` 0x68 with FIX 0x80: ``Cs + Cd``. Drawn without depth writes."""
    SUBTRACTIVE = 4
    """``ALPHA_1`` 0xA1 with FIX 0x80: ``Cd - Cs``. Drawn without depth writes."""


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
    blend_mode: BlendMode
    """How the engine blends a surface drawn with this texture."""
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
