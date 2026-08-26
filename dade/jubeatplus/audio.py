"""
The game's audio.

Sound effects ship as Core Audio Format (``.caf``) files holding uncompressed PCM, which is a
container almost nothing outside Apple's frameworks reads even though its contents are ordinary
samples. ``ffmpeg`` rewraps them as WAV without touching the samples.

Music ships as ``.m4a``, both loose in the bundle and, enciphered, inside every tune package. That
is already a portable container, so it is written out as it is rather than transcoded.

The rewrap itself is :py:mod:`dade.common.audio`, shared with the other iOS titles.
"""
from __future__ import annotations

from dade.common.audio import M4A_MAGIC, to_wav as caf_to_wav

__all__ = ('M4A_MAGIC', 'caf_to_wav')
