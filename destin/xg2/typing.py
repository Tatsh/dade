"""Shared typing helpers for :py:mod:`destin.xg2`."""
from __future__ import annotations

from typing import Literal, NamedTuple, TypeAlias, TypedDict

__all__ = ('ArchEntry', 'Endian', 'MfsEntry', 'ParsedBank', 'SampleMeta', 'Sf2Preset', 'Sf2Zone',
           'SoundZone', 'Texture', 'TextureFormat')

Endian: TypeAlias = Literal['<', '>']
""":py:mod:`struct` byte-order character: little-endian (PC) or big-endian (N64).

:meta hide-value:
"""

TextureFormat: TypeAlias = Literal['ci4', 'ci8', 'i8', 'rgba16']
"""Name of the source pixel format a :py:class:`Texture` was decoded from.

:meta hide-value:
"""


class ArchEntry(TypedDict):
    """One 16-byte record in an ``XG2Arch`` container directory."""

    index: int
    """Position of the record within the container."""
    offset: int
    """Data offset relative to the container base."""
    absolute: int
    """Data offset relative to the start of the enclosing buffer."""
    codec: str
    """Codec tag, normalised to upper case (``LZSS``, ``LHUF``, ``COPY``)."""
    decompressed_size: int
    """Size of the entry once decoded."""
    compressed_size: int
    """Size of the entry as stored."""


class MfsEntry(NamedTuple):
    """One 16-byte record in the Extreme-G 1 ``mfs`` directory."""

    decompressed_size: int
    """Size of the file once decompressed."""
    compressed_size: int
    """Size of the file as stored."""
    end_offset: int
    """Cumulative end offset, which doubles as the next file's start offset."""


class Texture(NamedTuple):
    """A decoded texture image in RGBA8 order."""

    pixel_format: TextureFormat
    """Source pixel format the image was decoded from."""
    offset: int
    """Offset of the pixel data within its source blob."""
    width: int
    """Width in pixels."""
    height: int
    """Height in pixels."""
    rgba: bytes
    """Pixel data, four bytes per pixel."""


class SoundZone(TypedDict):
    """One ``ALSound`` mapped to a SoundFont instrument zone."""

    sample: int
    """Index into the bank's decoded sample list."""
    key_min: int
    """Lowest MIDI key the zone responds to."""
    key_max: int
    """Highest MIDI key the zone responds to."""
    velocity_min: int
    """Lowest velocity the zone responds to."""
    velocity_max: int
    """Highest velocity the zone responds to."""
    key_base: int
    """Root key the sample was recorded at."""
    detune: int
    """Fine tuning in cents."""
    loop_start: int
    """Loop start in samples, or zero when the sound does not loop."""
    loop_end: int
    """Loop end in samples, or zero when the sound does not loop."""
    loop: bool
    """Whether the sound loops."""
    pan: int
    """Pan position, 0 to 127 with 64 centred."""
    volume: int
    """Volume, 0 to 127."""
    attack: int
    """Envelope attack time in microseconds."""
    decay: int
    """Envelope decay time in microseconds."""
    release: int
    """Envelope release time in microseconds."""


class ParsedBank(TypedDict):
    """An ``ALBankFile`` control bank with every sound decoded to PCM."""

    sample_rate: int
    """Playback rate in Hz declared by the bank."""
    instruments: list[list[SoundZone]]
    """Melodic instruments, each a list of zones, indexed by program number."""
    percussion: list[SoundZone]
    """Zones of the channel-9 drum kit, which may be empty."""
    samples: list[list[int]]
    """Decoded 16-bit PCM for every sound referenced by the bank."""


class SampleMeta(TypedDict):
    """PCM plus loop points for one SoundFont sample."""

    pcm: list[int]
    """Decoded 16-bit PCM."""
    loop_start: int
    """Loop start in samples."""
    loop_end: int
    """Loop end in samples."""


class Sf2Zone(TypedDict):
    """One SoundFont instrument zone."""

    sample: int
    """Index into the SoundFont sample list."""
    key_min: int
    """Lowest MIDI key the zone responds to."""
    key_max: int
    """Highest MIDI key the zone responds to."""
    velocity_min: int
    """Lowest velocity the zone responds to."""
    velocity_max: int
    """Highest velocity the zone responds to."""
    root: int
    """Overriding root key."""
    detune: int
    """Fine tuning in cents."""
    pan: int
    """Pan position, 0 to 127 with 64 centred."""
    volume: int
    """Volume, 0 to 127."""
    attack: int
    """Envelope attack time in microseconds."""
    decay: int
    """Envelope decay time in microseconds."""
    release: int
    """Envelope release time in microseconds."""
    loop: bool
    """Whether the zone loops its sample."""


class Sf2Preset(TypedDict):
    """One SoundFont preset."""

    bank: int
    """MIDI bank number."""
    program: int
    """MIDI program number."""
    name: str
    """Preset name, truncated to twenty characters when written."""
    instrument: int
    """Index into the SoundFont instrument list."""
