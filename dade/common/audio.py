"""
Container conversions that ``ffmpeg`` performs.

Apple's mobile titles ship audio in two containers. Core Audio Format (``.caf``) usually holds
uncompressed PCM but is read by almost nothing outside Apple's frameworks. MPEG-4 audio (``.m4a``)
is portable but holds AAC, which not every consumer wants to decode itself.

``ffmpeg`` rewraps both. Where the codec allows it the samples are copied rather than re-encoded,
so a PCM ``.caf`` comes out of :py:func:`to_wav` bit-identical.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import subprocess as sp

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('CAF_MAGIC', 'M4A_BRAND_OFFSET', 'M4A_MAGIC', 'is_m4a', 'to_wav')

M4A_MAGIC = b'ftyp'
"""The tag at offset four of an MPEG-4 container.

:meta hide-value:
"""
M4A_BRAND_OFFSET = 4
"""Where :py:data:`M4A_MAGIC` sits, past the leading box length.

:meta hide-value:
"""
CAF_MAGIC = b'caff'
"""The four bytes a Core Audio Format file opens with.

:meta hide-value:
"""


def is_m4a(data: bytes) -> bool:
    """
    Report whether a buffer opens with an MPEG-4 container header.

    Parameters
    ----------
    data : bytes
        The start of the file. A short buffer is not an error.

    Returns
    -------
    bool
        Whether the buffer is an MPEG-4 container.
    """
    return data[M4A_BRAND_OFFSET:M4A_BRAND_OFFSET + len(M4A_MAGIC)] == M4A_MAGIC


def to_wav(source: Path, destination: Path, ffmpeg: Path) -> Path:
    """
    Rewrap an audio file as a WAV.

    Parameters
    ----------
    source : pathlib.Path
        The file to convert. Any container ``ffmpeg`` reads is accepted.
    destination : pathlib.Path
        The ``.wav`` to write. Its parent directory must already exist.
    ffmpeg : pathlib.Path
        The ``ffmpeg`` binary.

    Returns
    -------
    pathlib.Path
        The written file. ``ffmpeg`` failing raises :py:class:`subprocess.CalledProcessError`.
    """
    sp.run((str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-y', '-i', str(source),
            str(destination)),
           capture_output=True,
           check=True,
           text=True)
    return destination
