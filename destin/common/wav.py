"""
Canonical RIFF/WAVE (PCM) writer shared by the game submodules.

Several games decode proprietary audio into raw PCM and then wrap it in a WAVE header. The header is
always the canonical 44-byte layout with an integer-PCM ``fmt `` chunk (format tag ``1``); the games
differ only in their sample rate, channel count, and bit depth, which are parameters here.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__ = ('pcm16_to_bytes', 'wrap_pcm', 'write_pcm')

_INT16_MIN = -32768
"""Minimum value of a signed 16-bit PCM sample.

:meta hide-value:
"""
_INT16_MAX = 32767
"""Maximum value of a signed 16-bit PCM sample.

:meta hide-value:
"""


def pcm16_to_bytes(samples: Iterable[int]) -> bytes:
    """
    Pack an iterable of integer samples into little-endian signed 16-bit PCM.

    Each sample is clamped to the signed 16-bit range before packing.

    Parameters
    ----------
    samples : Iterable[int]
        The decoded samples.

    Returns
    -------
    bytes
        The little-endian signed 16-bit PCM data.
    """
    return b''.join(struct.pack('<h', max(_INT16_MIN, min(_INT16_MAX, s))) for s in samples)


def wrap_pcm(pcm: bytes, *, rate: int, channels: int = 1, bits: int = 16) -> bytes:
    """
    Prepend a canonical RIFF/WAVE header to integer-PCM data.

    Parameters
    ----------
    pcm : bytes
        The raw PCM sample data.
    rate : int
        The sample rate in hertz.
    channels : int
        The number of interleaved channels.
    bits : int
        The bit depth of each sample.

    Returns
    -------
    bytes
        A complete RIFF/WAVE file.
    """
    block_align = channels * bits // 8
    byte_rate = rate * block_align
    fmt = struct.pack('<IHHIIHH', 16, 1, channels, rate, byte_rate, block_align, bits)
    return (b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVE' + b'fmt ' + fmt + b'data' +
            struct.pack('<I', len(pcm)) + pcm)


def write_pcm(path: Path, pcm: bytes, *, rate: int, channels: int = 1, bits: int = 16) -> None:
    """
    Write integer-PCM data to *path* as a canonical RIFF/WAVE file.

    Parameters
    ----------
    path : pathlib.Path
        The destination ``.wav`` path.
    pcm : bytes
        The raw PCM sample data.
    rate : int
        The sample rate in hertz.
    channels : int
        The number of interleaved channels.
    bits : int
        The bit depth of each sample.
    """
    path.write_bytes(wrap_pcm(pcm, rate=rate, channels=channels, bits=bits))
