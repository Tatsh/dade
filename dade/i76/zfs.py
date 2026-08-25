"""
Reader for the ZFSF and ZFS3 archives shipped with Interstate '76 and Interstate '82.

Both formats share a byte-compatible directory: a ``0x20``-byte header followed by a linked list
of blocks of up to 100 thirty-six-byte entries. The header is little-endian and holds the magic
(4), a version (4), an entries-per-block hint (4), the block capacity (4) which is always 100, the
entry count (4), two reserved dwords, and the offset of the second block (4). Block zero's entries
start at ``0x20`` and its next pointer is the header field at ``0x1c``; every later block is a next
pointer followed by its entries. Each entry is a 16-byte NUL-padded name, then the data offset,
directory index, stored size, DOS timestamp, and flags as dwords.

The formats differ only in their payloads: ZFSF records are LZO-compressed per their flags, while
every member of every shipped ZFS3 archive is stored uncompressed.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal
import logging
import struct

from dade.common.io import read_cstring

from .lzo import decompress_record
from .typing import ZfsEntry

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path

__all__ = ('InvalidArchiveError', 'archive_format', 'extract', 'iter_members', 'read_directory')

log = logging.getLogger(__name__)

MAGIC_ZFSF = b'ZFSF'
"""Magic identifying an Interstate '76 archive, whose records are LZO-compressed.

:meta hide-value:
"""
MAGIC_ZFS3 = b'ZFS3'
"""Magic identifying an Interstate '82 archive, whose records are stored uncompressed.

:meta hide-value:
"""

_BLOCK_CAPACITY = 100
"""Maximum number of directory entries stored in one block.

:meta hide-value:
"""
_ENTRY_SIZE = 36
"""Size of one directory entry in bytes.

:meta hide-value:
"""
_COUNT_OFFSET = 0x10
"""Header offset of the directory entry count.

:meta hide-value:
"""
_NEXT_BLOCK_OFFSET = 0x1C
"""Header offset of the pointer to the second directory block.

:meta hide-value:
"""
_FIRST_BLOCK_OFFSET = 0x20
"""Offset at which block zero's entries begin.

:meta hide-value:
"""
_FORMATS: Mapping[bytes, Literal['zfsf', 'zfs3']] = {MAGIC_ZFSF: 'zfsf', MAGIC_ZFS3: 'zfs3'}
"""Mapping of archive magic to format name.

:meta hide-value:
"""


class InvalidArchiveError(ValueError):
    """Raised when a file does not carry a recognised ZFS magic."""


def archive_format(data: bytes) -> Literal['zfsf', 'zfs3']:
    """
    Identify an archive from its magic.

    Parameters
    ----------
    data : bytes
        The archive's contents, or at least its first four bytes.

    Returns
    -------
    Literal['zfsf', 'zfs3']
        ``'zfsf'`` for an LZO-compressed Interstate '76 archive and ``'zfs3'`` for an
        uncompressed Interstate '82 archive.

    Raises
    ------
    InvalidArchiveError
        If the magic is neither ``ZFSF`` nor ``ZFS3``.
    """
    if (name := _FORMATS.get(bytes(data[:4]))) is None:
        msg = f'Not a ZFS archive (magic {data[:4]!r}).'
        raise InvalidArchiveError(msg)
    return name


def read_directory(data: bytes) -> tuple[ZfsEntry, ...]:
    """
    Parse the directory of a ZFSF or ZFS3 archive.

    Parameters
    ----------
    data : bytes
        The archive's contents.

    Returns
    -------
    tuple[ZfsEntry, ...]
        Every directory entry, in directory order.
    """
    count = struct.unpack_from('<I', data, _COUNT_OFFSET)[0]
    next_offset = struct.unpack_from('<I', data, _NEXT_BLOCK_OFFSET)[0]
    entries: list[ZfsEntry] = []
    first = True
    while len(entries) < count:
        if first:
            block_position = _FIRST_BLOCK_OFFSET
            first = False
        else:
            block_position = next_offset + 4
            next_offset = struct.unpack_from('<I', data, next_offset)[0]
        for index in range(_BLOCK_CAPACITY):
            if len(entries) >= count:
                break
            offset = block_position + index * _ENTRY_SIZE
            name = read_cstring(data[offset:offset + 16])
            data_offset, _, size, _, flags = struct.unpack_from('<5I', data, offset + 16)
            entries.append(ZfsEntry(name, data_offset, size, flags))
    return tuple(entries)


def iter_members(data: bytes) -> Iterator[tuple[ZfsEntry, bytes]]:
    """
    Yield every named member of an archive together with its decoded contents.

    ZFSF records are decompressed per their flags. ZFS3 records are yielded verbatim, since no
    shipped Interstate '82 archive compresses its members; a member that does carry compression
    flags is logged and still yielded verbatim rather than being decoded as garbage. Entries with
    an empty name are skipped. An unrecognised magic raises :py:class:`InvalidArchiveError`.

    Parameters
    ----------
    data : bytes
        The archive's contents.

    Yields
    ------
    tuple[ZfsEntry, bytes]
        The directory entry and its decoded payload.
    """
    compressed = archive_format(data) == 'zfsf'
    for entry in read_directory(data):
        if not entry.name:
            continue
        stored = data[entry.offset:entry.offset + entry.size]
        if compressed:
            yield entry, decompress_record(stored, entry.flags)
        else:
            if entry.flags:
                log.warning('Member `%s` has non-zero flags %d; writing bytes verbatim.',
                            entry.name, entry.flags)
            yield entry, bytes(stored)


def extract(data: bytes, outdir: Path) -> int:
    """
    Write every member of an archive into ``outdir`` under its lowercased name.

    An unrecognised magic raises :py:class:`InvalidArchiveError`.

    Parameters
    ----------
    data : bytes
        The archive's contents.
    outdir : pathlib.Path
        Directory to write members into. It is created if it does not exist.

    Returns
    -------
    int
        The number of members written.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    count = 0
    for entry, payload in iter_members(data):
        (outdir / entry.name.lower()).write_bytes(payload)
        log.debug('Extracted `%s` (%d bytes).', entry.name, len(payload))
        count += 1
    return count
