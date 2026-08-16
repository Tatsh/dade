"""
The game's audio.

Sound effects ship as Core Audio Format (``.caf``) files holding uncompressed PCM, which is a
container almost nothing outside Apple's frameworks reads even though its contents are ordinary
samples. ``ffmpeg`` rewraps them as WAV without touching the samples.

Music ships as ``.m4a``, both loose in the bundle and, enciphered, inside every tune package. That
is already a portable container, so it is written out as it is rather than transcoded.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Final
import subprocess as sp

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('M4A_MAGIC', 'caf_to_wav')

M4A_MAGIC: Final = b'ftyp'
"""The tag at offset four of an MPEG-4 container, used to recognise a tune's audio entries.

:meta hide-value:
"""


def caf_to_wav(source: Path, destination: Path, ffmpeg: Path) -> Path:
    """
    Rewrap a Core Audio Format file as a WAV.

    The samples are copied rather than re-encoded wherever the codec allows it, so a PCM ``.caf``
    comes out bit-identical.

    Parameters
    ----------
    source : pathlib.Path
        The ``.caf`` to convert.
    destination : pathlib.Path
        The ``.wav`` to write. Its parent directory must already exist.
    ffmpeg : pathlib.Path
        The ``ffmpeg`` binary.

    Returns
    -------
    pathlib.Path
        The written file. ``ffmpeg`` failing raises
        :py:class:`subprocess.CalledProcessError`.
    """
    sp.run((str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-y', '-i', str(source),
            str(destination)),
           capture_output=True,
           check=True,
           text=True)
    return destination
