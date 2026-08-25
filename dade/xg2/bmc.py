r"""
The ``BMC`` named sound effect container used by the Extreme-G XG2 ``mfs`` archive.

Layout: the magic ``BMC\\x80``, a twelve-byte NUL-padded name, then a 0x18-byte header followed by
the samples. The audio is 8-bit differential PCM where each byte is a signed delta added to an
accumulator that saturates at the 8-bit signed bounds; the clamp is what keeps the signal bounded
rather than wrapping into noise.

The playback rate is not stored and has not been confirmed against the game, so callers supply it.
"""
from __future__ import annotations

from typing import NamedTuple

__all__ = ('BMC_HEADER_SIZE', 'BMC_MAGIC', 'DEFAULT_SAMPLE_RATE', 'BmcSound', 'decode_bmc_dpcm',
           'parse_bmc')

BMC_MAGIC = b'BMC\x80'
"""Magic introducing a ``BMC`` sound.

:meta hide-value:
"""
BMC_HEADER_SIZE = 0x18
"""Size of the header preceding the samples.

:meta hide-value:
"""
_MAX_POSITIVE = 127
_MIN_SAMPLE = -128

DEFAULT_SAMPLE_RATE = 22050
"""Assumed playback rate in Hz. This has not been confirmed against the game.

:meta hide-value:
"""


class BmcSound(NamedTuple):
    """A parsed ``BMC`` sound effect."""

    name: str
    """Name stored in the header, which may be empty."""
    data: bytes
    """The differential PCM payload."""


def parse_bmc(blob: bytes) -> BmcSound | None:
    """
    Parse a ``BMC`` container.

    Parameters
    ----------
    blob : bytes
        A decoded archive entry.

    Returns
    -------
    BmcSound | None
        The parsed sound, or ``None`` when *blob* is not a ``BMC`` container.
    """
    if blob[:4] != BMC_MAGIC:
        return None
    name = blob[4:16].split(b'\x00')[0].decode('ascii', 'replace')
    return BmcSound(name, bytes(blob[BMC_HEADER_SIZE:]))


def decode_bmc_dpcm(data: bytes) -> list[int]:
    """
    Decode clamped 8-bit differential PCM to 16-bit samples.

    Parameters
    ----------
    data : bytes
        The differential payload, one signed delta per byte.

    Returns
    -------
    list[int]
        Signed 16-bit samples, one per input byte.
    """
    out = []
    accumulator = 0
    for byte in data:
        accumulator += byte - 256 if byte > _MAX_POSITIVE else byte
        accumulator = (_MIN_SAMPLE if accumulator < _MIN_SAMPLE else min(
            accumulator, _MAX_POSITIVE))
        out.append(accumulator * 256)
    return out
