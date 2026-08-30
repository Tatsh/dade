"""
Reader for the ``.LVL`` containers that hold each level's cooked assets.

A container starts with a little-endian ``u32`` sub-asset count, twelve unused bytes, and then one
40-byte index record per sub-asset. Each record is an absolute offset, a length, and a 32-byte name
buffer.

The name buffer is not cleared before use, so anything past the terminating NUL is leftover memory
from the machine that built the disc and must be ignored.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import struct

from dade.common.exceptions import InvalidFormatError

from .typing import LevelEntry

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('INDEX_OFFSET', 'RECORD_SIZE', 'extract', 'read_index')

log = logging.getLogger(__name__)

INDEX_OFFSET = 0x10
"""Byte offset of the first index record.

:meta hide-value:
"""
RECORD_SIZE = 0x28
"""Size in bytes of one index record.

:meta hide-value:
"""

_NAME_SIZE = 0x20


def read_index(data: bytes) -> tuple[LevelEntry, ...]:
    """
    Read a ``.LVL`` container's index.

    Records with an empty name, or with both a zero offset and a zero length, are unused slots and
    are skipped.

    Parameters
    ----------
    data : bytes
        The whole ``.LVL`` file.

    Returns
    -------
    tuple[LevelEntry, ...]
        One entry per stored sub-asset, in index order.

    Raises
    ------
    InvalidFormatError
        If the file is too small or its index runs past the end of the file.
    """
    if len(data) < INDEX_OFFSET:
        msg = 'Level container is too small.'
        raise InvalidFormatError(msg)
    count = struct.unpack_from('<I', data)[0]
    if INDEX_OFFSET + count * RECORD_SIZE > len(data):
        msg = f'Level container declares {count} sub-assets but its index runs past the end.'
        raise InvalidFormatError(msg)
    entries = []
    for i in range(count):
        record = INDEX_OFFSET + i * RECORD_SIZE
        offset, size = struct.unpack_from('<2I', data, record)
        name = data[record + 8:record + _NAME_SIZE + 8].split(b'\0')[0].decode('ascii', 'replace')
        if not name or not (offset or size):
            continue
        if offset + size > len(data):
            log.warning('Sub-asset `%s` runs past the end of its container.', name)
            continue
        entries.append(LevelEntry(name, offset, size))
    return tuple(entries)


def extract(path: Path, output_dir: Path) -> tuple[Path, ...]:
    """
    Write every sub-asset of a ``.LVL`` container to its own file.

    Zero-length sub-assets are skipped: they mark an asset kind the level does not use.

    Parameters
    ----------
    path : Path
        The ``.LVL`` file to read.
    output_dir : Path
        Directory to write into. It is created if missing.

    Returns
    -------
    tuple[Path, ...]
        The files written, named after each sub-asset.
    """
    data = path.read_bytes()
    entries = read_index(data)
    written = []
    if any(entry.size for entry in entries):
        output_dir.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        if not entry.size:
            continue
        destination = output_dir / entry.name
        destination.write_bytes(data[entry.offset:entry.offset + entry.size])
        written.append(destination)
    return tuple(written)
