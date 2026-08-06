"""
Minimal RIFF WAVE writer for the decoded audio.

The header layout and sample packing are the canonical ones from :py:mod:`destin.common.wav`; this
module only fixes the defaults the Extreme-G decoders use.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from destin.common.wav import pcm16_to_bytes, wrap_pcm

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__ = ('DEFAULT_RATE', 'pcm_to_bytes', 'wrap_wav', 'write_wav', 'write_wav16')

DEFAULT_RATE = 22050
"""Sample rate assumed when a caller does not give one.

:meta hide-value:
"""


def pcm_to_bytes(samples: Iterable[int]) -> bytes:
    """
    Pack 16-bit samples as little-endian bytes, clamping out-of-range values.

    Parameters
    ----------
    samples : collections.abc.Iterable[int]
        Signed sample values.

    Returns
    -------
    bytes
        Two bytes per sample.
    """
    return pcm16_to_bytes(samples)


def wrap_wav(data: bytes, rate: int = DEFAULT_RATE, channels: int = 1, bits: int = 16) -> bytes:
    """
    Prepend a canonical 44-byte RIFF WAVE header to PCM data.

    Parameters
    ----------
    data : bytes
        Raw little-endian PCM.
    rate : int
        Sample rate in Hz.
    channels : int
        Channel count.
    bits : int
        Bits per sample.

    Returns
    -------
    bytes
        The complete WAV file.
    """
    return wrap_pcm(data, rate=rate, channels=channels, bits=bits)


def write_wav(path: Path,
              data: bytes,
              rate: int = DEFAULT_RATE,
              channels: int = 1,
              bits: int = 16) -> None:
    """
    Write raw PCM to a WAV file.

    Parameters
    ----------
    path : pathlib.Path
        Destination file, whose parent must already exist.
    data : bytes
        Raw little-endian PCM.
    rate : int
        Sample rate in Hz.
    channels : int
        Channel count.
    bits : int
        Bits per sample.
    """
    path.write_bytes(wrap_wav(data, rate, channels, bits))


def write_wav16(path: Path, samples: Iterable[int], rate: int) -> None:
    """
    Write 16-bit mono samples to a WAV file.

    Parameters
    ----------
    path : pathlib.Path
        Destination file, whose parent must already exist.
    samples : collections.abc.Iterable[int]
        Signed sample values, clamped to the 16-bit range.
    rate : int
        Sample rate in Hz.
    """
    write_wav(path, pcm_to_bytes(samples), rate)
