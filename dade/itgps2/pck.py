"""
Reader for the ``PCKF`` packs the PlayStation 2 releases of In The Groove load their files from.

A pack opens with ``PCKF``, a 128-byte pack name, and an entry count. The entries follow with no
padding, each a fixed record and then the path it stores. In The Groove records a size, an offset,
and the length of the path. In The Groove 2 records the stored size, the unpacked size, the
offset, the length of the path, and a flag that marks a raw deflate stream. The layout is
recognised from the records themselves.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import struct
import zlib

from dade.common.exceptions import InvalidFormatError
from dade.common.io import u32

if TYPE_CHECKING:
    from dade.common.io import Reader

__all__ = ('PCKEntry', 'read_directory', 'read_entry')

_MAGIC = b'PCKF'
_HEADER = 0x88
_ITG2 = struct.Struct('<5I')
_ITG = struct.Struct('<3I')
_PATH_LIMIT = 256
"""The longest path read for an entry when the directory is read ahead of parsing it.

:meta hide-value:
"""


class PCKEntry(NamedTuple):
    """One file of a pack."""

    path: str
    """The path the game mounts the file at, such as ``Songs/In The Groove 2/!/!.sm``."""
    offset: int
    """Where the stored bytes start, from the start of the pack."""
    size: int
    """The number of stored bytes."""
    length: int
    """The number of bytes once inflated."""
    compressed: bool
    """Whether the stored bytes are a raw deflate stream."""


def _entries(directory: bytes, count: int, pack_size: int, record: struct.Struct, *,
             itg2: bool) -> tuple[PCKEntry, ...] | None:
    entries = []
    position = 0
    for _ in range(count):
        if position + record.size > len(directory):
            return None
        fields = record.unpack_from(directory, position)
        if itg2:
            size, length, offset, name_length, flag = fields
        else:
            size, offset, name_length = fields
            length, flag = size, 0
        position += record.size
        if flag > 1 or offset + size > pack_size or position + name_length > len(directory):
            return None
        entries.append(
            PCKEntry(directory[position:position + name_length].decode('latin-1'), offset, size,
                     length, bool(flag)))
        position += name_length
    if any(entry.offset < _HEADER + position for entry in entries):
        return None
    return tuple(entries)


def read_directory(reader: Reader,
                   base: int = 0,
                   size: int | None = None) -> tuple[str, tuple[PCKEntry, ...]]:
    """
    Read the name and the entries of a pack.

    Parameters
    ----------
    reader : dade.common.io.Reader
        The bytes the pack is in.
    base : int
        Where the pack starts in ``reader``.
    size : int | None
        The size of the pack. ``None`` takes the rest of ``reader``.

    Returns
    -------
    tuple[str, tuple[PCKEntry, ...]]
        The pack name and its entries in the order they are stored.

    Raises
    ------
    InvalidFormatError
        If the pack does not open with ``PCKF`` or its entries fit neither layout.
    """
    pack_size = reader.size - base if size is None else size
    header = reader.read(base, _HEADER)
    if header[:4] != _MAGIC or len(header) < _HEADER:
        msg = 'Not a PCK pack.'
        raise InvalidFormatError(msg)
    name = header[4:0x84].split(b'\0', 1)[0].decode('latin-1')
    count = u32(header, 0x84)
    directory = reader.read(base + _HEADER,
                            min(count * (_ITG2.size + _PATH_LIMIT), pack_size - _HEADER))
    for record, itg2 in ((_ITG2, True), (_ITG, False)):
        if (entries := _entries(directory, count, pack_size, record, itg2=itg2)) is not None:
            return name, entries
    msg = 'The PCK directory fits neither known layout.'
    raise InvalidFormatError(msg)


def read_entry(reader: Reader, entry: PCKEntry, base: int = 0) -> bytes:
    """
    Read a file of a pack, inflating it when it is stored compressed.

    Parameters
    ----------
    reader : dade.common.io.Reader
        The bytes the pack is in.
    entry : PCKEntry
        The file to read.
    base : int
        Where the pack starts in ``reader``.

    Returns
    -------
    bytes
        The file.

    Raises
    ------
    InvalidFormatError
        If the inflated file is not the length the entry records.
    """
    data = reader.read(base + entry.offset, entry.size)
    if not entry.compressed:
        return data
    if len(data := zlib.decompress(data, -15)) != entry.length:
        msg = f'`{entry.path}` inflates to {len(data)} bytes, not {entry.length}.'
        raise InvalidFormatError(msg)
    return data
