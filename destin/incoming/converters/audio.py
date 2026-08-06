"""Audio converters: Dreamcast CDDA ``.raw`` tracks to WAV."""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import wave

from ._base import ConversionError

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('raw_to_wav',)

log = logging.getLogger(__name__)

_CDDA_CHANNELS = 2
_CDDA_SAMPLE_WIDTH = 2
_CDDA_FRAME_RATE = 44100
_CDDA_SECTOR_SIZE = 2352
_READ_CHUNK = _CDDA_SECTOR_SIZE * 512


def _write_wav(source: Path, destination: Path) -> None:
    with source.open('rb') as raw, wave.open(str(destination), 'wb') as wav:
        wav.setnchannels(_CDDA_CHANNELS)
        wav.setsampwidth(_CDDA_SAMPLE_WIDTH)
        wav.setframerate(_CDDA_FRAME_RATE)
        while chunk := raw.read(_READ_CHUNK):
            wav.writeframesraw(chunk)


def raw_to_wav(source: Path, dest_dir: Path) -> Path:
    """
    Wrap a Dreamcast CDDA ``.raw`` track in a RIFF/WAVE header.

    The track is raw Red Book audio: signed 16-bit, 44100 Hz, stereo, interleaved, native
    little-endian. No sample manipulation is performed.

    Parameters
    ----------
    source : Path
        The source ``.raw`` track.
    dest_dir : Path
        The directory the WAV is written to.

    Returns
    -------
    Path
        The written WAV path.

    Raises
    ------
    ConversionError
        If the track size is not a whole number of CDDA sectors, or an I/O error occurs.
    """
    size = source.stat().st_size
    if size % _CDDA_SECTOR_SIZE:
        msg = (f'`{source}` is {size} bytes, not a whole number of {_CDDA_SECTOR_SIZE}-byte CDDA '
               f'sectors; it may not be a raw audio track.')
        raise ConversionError(msg)
    destination = dest_dir / f'{source.stem}.wav'
    try:
        _write_wav(source, destination)
    except OSError as e:
        msg = f'Failed to convert `{source}`: {e}'
        raise ConversionError(msg) from e
    return destination
