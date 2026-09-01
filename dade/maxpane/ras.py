"""
Reader for RAS (Remedy Archive System) archives.

``.ras`` archives and the ``.mpm`` mod packages share one layout.

The 44-byte header starts with the magic and a signed cipher seed in the clear; the remaining 36
bytes are encrypted with that seed and give the file and directory counts, the size of each table,
the format version, a CRC32 of the header with its own CRC field zeroed, and the writer identity.
The file table follows, then the directory table, each encrypted with the same seed restarting its
keystream at index zero.

Both tables are sequences of a NUL-terminated name followed by fixed-width fields: 40 bytes for a
file (two sizes, two reserved dwords, the owning directory index, another reserved dword, and a
``SYSTEMTIME``) and 16 bytes for a directory (a ``SYSTEMTIME`` alone). Members carry no offset
field because payloads are stored back to back in file-table order, which makes
``header + tables + sum of stored sizes == archive size`` an exact integrity check.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import struct

from .blocks import unwrap
from .crypto import decrypt
from .typing import ArchiveHeader, RASContents, RASDirectory, RASEntry

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ('ARCHIVE_VERSION', 'HEADER_SIZE', 'MAGIC', 'InvalidArchiveError', 'is_intact',
           'iter_members', 'member_bytes', 'read_directory', 'read_header')

log = logging.getLogger(__name__)

MAGIC = b'RAS\x00'
"""Magic at the start of every archive.

:meta hide-value:
"""
ARCHIVE_VERSION = 1.2
"""The only format version known to exist, from ``R_File::RAS_ARCHIVE_VERSION``.

:meta hide-value:
"""
HEADER_SIZE = 0x2C
"""Size of the archive header in bytes.

:meta hide-value:
"""

_FILE_FIELDS_SIZE = 40
_SYSTEMTIME_SIZE = 16
_VERSION_TOLERANCE = 1e-6


class InvalidArchiveError(ValueError):
    """Raised when a buffer is not a readable RAS archive."""


def _system_time(data: bytes, offset: int) -> str | None:
    year, month, _, day, hour, minute, second, millisecond = struct.unpack_from('<8H', data, offset)
    if not year:
        return None
    return (f'{year:04d}-{month:02d}-{day:02d} '
            f'{hour:02d}:{minute:02d}:{second:02d}.{millisecond:03d}')


def _read_name(data: bytes, offset: int) -> tuple[str, int]:
    end = data.index(b'\x00', offset)
    return data[offset:end].decode('latin-1'), end + 1


def read_header(data: bytes) -> ArchiveHeader:
    """
    Decode and decrypt the archive header.

    Parameters
    ----------
    data : bytes
        At least the first :py:data:`HEADER_SIZE` bytes of an archive.

    Returns
    -------
    ArchiveHeader
        The decrypted header.

    Raises
    ------
    InvalidArchiveError
        If the magic is wrong or the version is not :py:data:`ARCHIVE_VERSION`.
    """
    if data[:4] != MAGIC:
        msg = f'Not a RAS archive: {data[:4]!r}.'
        raise InvalidArchiveError(msg)
    if len(data) < HEADER_SIZE:
        msg = f'A RAS archive is at least {HEADER_SIZE} bytes; this one is {len(data)}.'
        raise InvalidArchiveError(msg)
    seed = struct.unpack_from('<i', data, 4)[0]
    raw = decrypt(bytes(data[8:HEADER_SIZE]), seed)
    file_count, directory_count, file_table_size, directory_table_size = struct.unpack_from(
        '<4I', raw, 0)
    version = struct.unpack_from('<f', raw, 16)[0]
    if abs(version - ARCHIVE_VERSION) > _VERSION_TOLERANCE:
        msg = f'Unsupported RAS archive version {version:.2f}.'
        raise InvalidArchiveError(msg)
    return ArchiveHeader(archiver_id=struct.unpack_from('<I', raw, 32)[0],
                         crc=struct.unpack_from('<I', raw, 20)[0],
                         directory_count=directory_count,
                         directory_crc=struct.unpack_from('<I', raw, 28)[0],
                         directory_table_size=directory_table_size,
                         file_count=file_count,
                         file_crc=struct.unpack_from('<I', raw, 24)[0],
                         file_table_size=file_table_size,
                         seed=seed,
                         version=version)


def read_directory(data: bytes) -> RASContents:
    """
    Decode the header and both tables.

    Parameters
    ----------
    data : bytes
        At least the header and both tables. The payload itself is not touched.

    Returns
    -------
    RASContents
        The header, the directory table, the file table, and the computed end of the payload.

    Raises
    ------
    InvalidArchiveError
        If the header will not read, or an entry names a directory the archive does not hold.
    """
    header = read_header(data)
    table_start = HEADER_SIZE + header.file_table_size
    file_table = decrypt(bytes(data[HEADER_SIZE:table_start]), header.seed)
    directory_table = decrypt(bytes(data[table_start:table_start + header.directory_table_size]),
                              header.seed)
    directories: list[RASDirectory] = []
    offset = 0
    for _ in range(header.directory_count):
        name, offset = _read_name(directory_table, offset)
        directories.append(RASDirectory(modified=_system_time(directory_table, offset), name=name))
        offset += _SYSTEMTIME_SIZE
    entries: list[RASEntry] = []
    offset = 0
    cursor = table_start + header.directory_table_size
    for _ in range(header.file_count):
        name, offset = _read_name(file_table, offset)
        size, stored_size, _, directory, _, _ = struct.unpack_from('<6I', file_table, offset)
        if directory >= len(directories):
            msg = (f'`{name}` names directory {directory} of {len(directories)}.')
            raise InvalidArchiveError(msg)
        modified = _system_time(file_table, offset + 24)
        offset += _FILE_FIELDS_SIZE
        entries.append(
            RASEntry(directory=directory,
                     modified=modified,
                     name=name,
                     offset=cursor,
                     path=(directories[directory].name + name).replace('\\', '/').lstrip('/'),
                     size=size,
                     stored_size=stored_size))
        cursor += stored_size
    return RASContents(data_end=cursor,
                       directories=tuple(directories),
                       entries=tuple(entries),
                       header=header)


def member_bytes(data: bytes, entry: RASEntry, *, raw: bool = False) -> bytes:
    """
    Slice one member out of an archive.

    Parameters
    ----------
    data : bytes
        The whole archive.
    entry : RASEntry
        Member to read, from :py:func:`read_directory` over the same buffer.
    raw : bool
        Return the stored bytes without removing ``RA->`` or ``RC->`` wrappers.

    Returns
    -------
    bytes
        The member's contents.
    """
    stored = bytes(data[entry.offset:entry.offset + entry.stored_size])
    return stored if raw else unwrap(stored)[0]


def iter_members(data: bytes, *, raw: bool = False) -> Iterator[tuple[RASEntry, bytes]]:
    """
    Yield every member of an archive with its contents.

    Parameters
    ----------
    data : bytes
        The whole archive.
    raw : bool
        Return stored bytes without removing ``RA->`` or ``RC->`` wrappers.

    Yields
    ------
    tuple[RASEntry, bytes]
        Each member and its contents, in stored order.
    """
    for entry in read_directory(data).entries:
        yield entry, member_bytes(data, entry, raw=raw)


def is_intact(data: bytes) -> bool:
    """
    Check that the tables account for every byte of the archive.

    Parameters
    ----------
    data : bytes
        The whole archive.

    Returns
    -------
    bool
        :py:obj:`True` when the computed end of the payload matches the buffer length.
    """
    return read_directory(data).data_end == len(data)
