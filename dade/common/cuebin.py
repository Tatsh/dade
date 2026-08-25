"""
Convert a cue/bin disc image into a plain ISO 9660 image.

Parse a ``.cue`` sheet far enough to find the binary and its data track, then turn the raw ``.bin``
sectors into the 2048-byte-per-sector user-data stream that an ISO 9660 reader expects.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import re

from dade.common.exceptions import InvalidFormatError

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('cuebin_to_iso',)

_USER_DATA_SIZE = 2048
"""User-data bytes per sector in every supported track mode.

:meta hide-value:
"""
_FILE_RE = re.compile(r'^\s*FILE\s+"([^"]+)"\s+BINARY', re.IGNORECASE)
"""Match a ``FILE "name.bin" BINARY`` line and capture the file name."""
_TRACK_RE = re.compile(r'^\s*TRACK\s+\d+\s+(\S+)', re.IGNORECASE)
"""Match a ``TRACK nn MODE`` line and capture the track mode."""


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
            sector, offset = 2352, 16
        case 'MODE2/2352':
            sector, offset = 2352, 24
        case 'MODE1/2048':
            sector, offset = 2048, 0
        case _:
            msg = f'Unsupported track mode `{mode}`.'
            raise InvalidFormatError(msg)
    data = (cue_path.parent / bin_name).read_bytes()
    return b''.join(data[start + offset:start + offset + _USER_DATA_SIZE]
                    for start in range(0, len(data), sector))
