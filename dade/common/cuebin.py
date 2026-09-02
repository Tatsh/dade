"""
Convert a cue/bin disc image into a plain ISO 9660 image.

Parse a ``.cue`` sheet far enough to find the binary and its data track, then turn the raw ``.bin``
sectors into the 2048-byte-per-sector user-data stream that an ISO 9660 reader expects. A ``.bin``
handed over without its sheet is read too, by looking at its sectors rather than being told.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import re

from dade.common.exceptions import InvalidFormatError

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('bin_to_iso', 'cuebin_to_iso')

_USER_DATA_SIZE = 2048
"""User-data bytes per sector in every supported track mode.

:meta hide-value:
"""
_FILE_RE = re.compile(r'^\s*FILE\s+"([^"]+)"\s+BINARY', re.IGNORECASE)
"""Match a ``FILE "name.bin" BINARY`` line and capture the file name."""
_TRACK_RE = re.compile(r'^\s*TRACK\s+\d+\s+(\S+)', re.IGNORECASE)
"""Match a ``TRACK nn MODE`` line and capture the track mode."""

_SYNC = b'\x00' + b'\xff' * 10 + b'\x00'
"""The twelve bytes every raw 2352-byte sector opens with.

A track written with its sync, header and error correction starts each sector this way. A track
written as user data alone does not, which is how the two are told apart without a cue sheet.

:meta hide-value:
"""

_RAW_SECTOR_SIZE = 2352
"""Bytes per sector in a track that kept its sync and error correction."""

_MODE_OFFSETS = {1: 16, 2: 24}
"""Where the user data starts inside a raw sector, by the mode byte at offset 15."""


def _unwrap_sectors(data: bytes, offset: int) -> bytes:
    """
    Take the user data out of every raw sector.

    Parameters
    ----------
    data : bytes
        The whole track.
    offset : int
        Where the user data starts inside a sector.

    Returns
    -------
    bytes
        The user-data stream.
    """
    return b''.join(data[start + offset:start + offset + _USER_DATA_SIZE]
                    for start in range(0, len(data), _RAW_SECTOR_SIZE))


def bin_to_iso(bin_path: Path) -> bytes:
    """
    Read a ``.bin`` that came without its cue sheet.

    The sector layout is taken from the file rather than from a sheet: a track that kept its sync
    and error correction opens each 2352-byte sector with a fixed twelve-byte pattern and names its
    mode in the byte after the address, while a track holding user data alone is already what an
    ISO 9660 reader wants and is returned unchanged.

    Parameters
    ----------
    bin_path : pathlib.Path
        Path to the ``.bin``.

    Returns
    -------
    bytes
        The ISO 9660 image.

    Raises
    ------
    dade.common.exceptions.InvalidFormatError
        If the sectors carry a sync pattern but a mode this cannot read.
    """
    data = bin_path.read_bytes()
    if data[:len(_SYNC)] != _SYNC:
        return data
    mode = data[15]
    if (offset := _MODE_OFFSETS.get(mode)) is None:
        msg = f'Unsupported sector mode {mode} in `{bin_path.name}`.'
        raise InvalidFormatError(msg)
    return _unwrap_sectors(data, offset)


def cuebin_to_iso(cue_path: Path) -> bytes:
    """
    Assemble the ISO 9660 image described by a cue sheet.

    The ``.bin`` is located relative to the cue sheet's directory using the name from its ``FILE``
    line. Only the first track is read, which is the data track on the disc images this handles.

    Parameters
    ----------
    cue_path : pathlib.Path
        Path to the ``.cue`` sheet.

    Returns
    -------
    bytes
        The assembled ISO 9660 image.

    Raises
    ------
    dade.common.exceptions.InvalidFormatError
        If the cue sheet has no ``FILE`` or ``TRACK`` line, or the track uses an unsupported mode.
    """
    bin_name: str | None = None
    mode: str | None = None
    for line in cue_path.read_text(encoding='utf-8').splitlines():
        if (match := _FILE_RE.match(line)):
            bin_name = match.group(1)
        elif (match := _TRACK_RE.match(line)):
            mode = match.group(1)
            break
    if bin_name is None or mode is None:
        msg = 'Unparseable cue sheet: missing FILE or TRACK line.'
        raise InvalidFormatError(msg)
    match mode.upper():
        case 'MODE1/2352':
            sector, offset = _RAW_SECTOR_SIZE, _MODE_OFFSETS[1]
        case 'MODE2/2352':
            sector, offset = _RAW_SECTOR_SIZE, _MODE_OFFSETS[2]
        case 'MODE1/2048':
            sector, offset = _USER_DATA_SIZE, 0
        case _:
            msg = f'Unsupported track mode `{mode}`.'
            raise InvalidFormatError(msg)
    data = (cue_path.parent / bin_name).read_bytes()
    if sector == _USER_DATA_SIZE:
        return data
    return _unwrap_sectors(data, offset)
