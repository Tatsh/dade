"""
Raw PCM helper for Tone Sphere.

Tone Sphere ships some sounds as headerless little-endian 16-bit PCM (``.raw``) played through
Marmalade's ``s3eSound`` at 44100 Hz stereo (the rate/channel count are this game's choice, not a
Marmalade constant). This module wraps such data in a canonical WAV container so it plays anywhere.
"""
from __future__ import annotations

from pathlib import Path

from dade.common.wav import wrap_pcm

__all__ = ('DEFAULT_CHANNELS', 'DEFAULT_RATE', 'wrap_raw_file', 'wrap_wav')

DEFAULT_RATE = 44100
"""Tone Sphere's ``s3eSound`` sample rate (Hz).

:meta hide-value:
"""
DEFAULT_CHANNELS = 2
"""Tone Sphere's channel count (stereo).

:meta hide-value:
"""
_BITS = 16


def wrap_wav(pcm: bytes, rate: int = DEFAULT_RATE, channels: int = DEFAULT_CHANNELS) -> bytes:
    """
    Wrap headerless 16-bit PCM in a WAV container.

    Parameters
    ----------
    pcm : bytes
        Little-endian signed 16-bit PCM samples (interleaved if stereo).
    rate : int
        Sample rate in Hz.
    channels : int
        Channel count (1 = mono, 2 = stereo).

    Returns
    -------
    bytes
        A complete RIFF/WAVE file.
    """
    block = channels * (_BITS // 8)
    data = pcm[:len(pcm) - (len(pcm) % block)] if block else pcm
    return wrap_pcm(data, rate=rate, channels=channels, bits=_BITS)


def wrap_raw_file(raw_path: str | Path,
                  rate: int = DEFAULT_RATE,
                  channels: int = DEFAULT_CHANNELS) -> Path:
    """
    Write a ``.wav`` next to a headerless ``.raw`` file.

    Parameters
    ----------
    raw_path : str or pathlib.Path
        Path to the ``.raw`` PCM file.
    rate : int
        Sample rate in Hz.
    channels : int
        Channel count.

    Returns
    -------
    pathlib.Path
        The written ``.wav`` path.
    """
    src = Path(raw_path)
    dst = src.with_suffix('.wav')
    dst.write_bytes(wrap_wav(src.read_bytes(), rate=rate, channels=channels))
    return dst
