"""
Reader for Neversoft ``PKR2`` resource packs (Tony Hawk's Pro Skater 2 PC, ``THawk2.exe``).

On-disk format (little-endian), reverse-engineered from ``THawk2.exe``::

    PKR_Header (16 bytes) @ 0x00
      +0x00  char[4]  magic      = "PKR2"
      +0x04  uint32   alignment  = data-region byte alignment (4 in All.pkr)
      +0x08  uint32   dirCount   = number of directory records (table A)
      +0x0C  uint32   fileCount  = number of file records (table B)

    PKR_DirEntry (40 bytes, table A), packed right after the header
      +0x00  char[32] name        = directory path including its trailing '/'
      +0x20  uint32   childOffset = absolute file offset of the first file record
      +0x24  uint32   childCount  = number of files in this directory

    PKR_FileEntry (48 bytes, table B), packed right after table A
      +0x00  char[32] name        = file name within its directory
      +0x20  int32    method      = compression method; -2 means stored
      +0x24  uint32   dataOffset  = absolute file offset of the resource bytes
      +0x28  uint32   uncompSize  = uncompressed size in bytes
      +0x2C  uint32   compSize    = stored size in bytes

A file's full path is its directory's name followed by its own. Each directory owns a contiguous
run of file records, so the run starts at ``(childOffset - tableBStart) / 48``.

The game's loader (``FUN_004e9840``) reads the header then both tables; its reader
(``FUN_004e9a00``) seeks to ``dataOffset`` and reads ``compSize`` bytes, decompressing via the
dispatch table in ``FUN_004e97f0``. ``All.pkr`` stores everything uncompressed, so only
:py:data:`METHOD_STORED` is exercised against real data; the run-length and zlib paths are
faithful ports of the decompiled codecs kept for completeness.
"""
from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING, NamedTuple
import logging
import struct
import zlib

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = ('DIR_SIZE', 'FILE_SIZE', 'HEADER_SIZE', 'PKR_MAGIC', 'CompressionMethod', 'PkrArchive',
           'PkrDirEntry', 'PkrFileEntry', 'PkrHeader', 'UnsafePathError', 'extract_all',
           'extract_entry', 'iter_entries', 'parse')

log = logging.getLogger(__name__)

PKR_MAGIC = b'PKR2'
"""Magic bytes at the start of every pack.

:meta hide-value:
"""
HEADER_SIZE = 16
"""Size of the pack header in bytes.

:meta hide-value:
"""
DIR_SIZE = 40
"""Size of one directory record in bytes.

:meta hide-value:
"""
FILE_SIZE = 48
"""Size of one file record in bytes.

:meta hide-value:
"""
_HEADER_FMT = '<4sIII'
_DIR_FMT = '<32sII'
_FILE_FMT = '<32siIII'


class CompressionMethod(IntEnum):
    """Compression methods dispatched by ``k_apfnPkrDecompressors`` at ``0x0054bdb4``."""

    STORED = -2
    """The resource is stored verbatim."""
    RLE8 = 0
    """The resource uses the run-length codec with 8-bit counts."""
    RLE16 = 1
    """The resource uses the run-length codec with 16-bit counts."""
    ZLIB = 2
    """The resource is deflated."""


class UnsafePathError(Exception):
    """Raised when a pack entry names a path that would escape the destination directory."""


class PkrHeader(NamedTuple):
    """Header of a ``PKR2`` pack together with the derived table offsets."""

    alignment: int
    """Byte alignment of the data region."""
    dir_count: int
    """Number of directory records."""
    file_count: int
    """Number of file records."""
    table_b_start: int
    """Absolute offset of the first file record."""
    data_region_start: int
    """Absolute offset of the first resource byte."""


class PkrDirEntry(NamedTuple):
    """One directory record from table A."""

    name: str
    """Directory path including its trailing separator."""
    child_offset: int
    """Absolute offset of this directory's first file record."""
    child_count: int
    """Number of files in this directory."""


class PkrFileEntry(NamedTuple):
    """One file record from table B."""

    name: str
    """File name within its directory."""
    method: int
    """Compression method applied to the stored bytes."""
    data_offset: int
    """Absolute offset of the resource bytes."""
    uncompressed_size: int
    """Size of the resource once decompressed."""
    compressed_size: int
    """Number of bytes to read from the pack."""


class PkrArchive(NamedTuple):
    """A parsed pack: its header and both record tables."""

    header: PkrHeader
    """The pack header."""
    dirs: tuple[PkrDirEntry, ...]
    """Every directory record, in file order."""
    files: tuple[PkrFileEntry, ...]
    """Every file record, in file order."""


def _cstr(raw: bytes) -> str:
    return raw.split(b'\x00', 1)[0].decode('latin1')


def _decompress_rle(src: bytes, out_size: int, count_width: int) -> bytes:
    """
    Expand a run-length stream of ``[count][value]`` tokens.

    This is a port of the game's ``PkrDecompressRle8`` and ``PkrDecompressRle16``. Any shortfall
    is padded with the last value seen, matching the codec's post-loop fill.

    Parameters
    ----------
    src : bytes
        The compressed bytes.
    out_size : int
        Expected size of the decompressed output.
    count_width : int
        Width of a token's count field in bytes: 1 for the 8-bit codec, 2 for the 16-bit one.

    Returns
    -------
    bytes
        The decompressed bytes, truncated or padded to ``out_size``.
    """
    out = bytearray()
    pos = 0
    last_value = 0
    token = count_width + 1
    while pos + token <= len(src) and len(out) < out_size:
        count = int.from_bytes(src[pos:pos + count_width], 'little')
        value = src[pos + count_width]
        if len(out) + count > out_size:
            break
        out.extend(bytes([value]) * count)
        last_value = value
        pos += token
    if len(out) < out_size:
        out.extend(bytes([last_value]) * (out_size - len(out)))
    return bytes(out[:out_size])


def parse(data: bytes) -> PkrArchive:
    """
    Parse a pack's header and both record tables.

    Parameters
    ----------
    data : bytes
        The whole pack file.

    Returns
    -------
    PkrArchive
        The parsed header and tables.

    Raises
    ------
    ValueError
        If the data is too small, does not carry the ``PKR2`` magic, or its tables run past the
        end of the file.
    """
    if len(data) < HEADER_SIZE:
        msg = 'File is too small to be a PKR.'
        raise ValueError(msg)
    magic, alignment, dir_count, file_count = struct.unpack_from(_HEADER_FMT, data, 0)
    if magic != PKR_MAGIC:
        msg = f'Bad magic {magic!r}, expected {PKR_MAGIC!r}. This is not a PKR2 file.'
        raise ValueError(msg)
    table_a_start = HEADER_SIZE
    table_b_start = table_a_start + dir_count * DIR_SIZE
    data_region_start = table_b_start + file_count * FILE_SIZE
    if len(data) < data_region_start:
        msg = 'Truncated PKR: the directory tables run past the end of the file.'
        raise ValueError(msg)
    dirs = []
    for i in range(dir_count):
        name, child_offset, child_count = struct.unpack_from(_DIR_FMT, data,
                                                             table_a_start + i * DIR_SIZE)
        dirs.append(PkrDirEntry(_cstr(name), child_offset, child_count))
    files = []
    for i in range(file_count):
        record = struct.unpack_from(_FILE_FMT, data, table_b_start + i * FILE_SIZE)
        files.append(PkrFileEntry(_cstr(record[0]), *record[1:]))
    header = PkrHeader(alignment=alignment,
                       dir_count=dir_count,
                       file_count=file_count,
                       table_b_start=table_b_start,
                       data_region_start=data_region_start)
    log.debug('Parsed PKR2 with %d directories and %d files.', dir_count, file_count)
    return PkrArchive(header, tuple(dirs), tuple(files))


def iter_entries(archive: PkrArchive) -> Iterator[tuple[str, PkrFileEntry]]:
    """
    Yield every file in the pack as its full path paired with its record.

    Parameters
    ----------
    archive : PkrArchive
        A parsed pack.

    Yields
    ------
    tuple[str, PkrFileEntry]
        The file's full path and its record.
    """
    for entry in archive.dirs:
        start = (entry.child_offset - archive.header.table_b_start) // FILE_SIZE
        for index in range(start, start + entry.child_count):
            yield entry.name + archive.files[index].name, archive.files[index]


def extract_entry(data: bytes, entry: PkrFileEntry) -> bytes:
    """
    Decode one file's resource bytes according to its compression method.

    Parameters
    ----------
    data : bytes
        The whole pack file.
    entry : PkrFileEntry
        The record to decode.

    Returns
    -------
    bytes
        The decoded resource.

    Raises
    ------
    ValueError
        If the resource runs past the end of the pack.
    NotImplementedError
        If the record names a compression method this reader does not know.
    """
    offset, count = entry.data_offset, entry.compressed_size
    if offset + count > len(data):
        msg = f'Resource {entry.name!r} runs past the end of the file.'
        raise ValueError(msg)
    raw = data[offset:offset + count]
    match entry.method:
        case CompressionMethod.STORED:
            return raw
        case CompressionMethod.RLE8:
            return _decompress_rle(raw, entry.uncompressed_size, 1)
        case CompressionMethod.RLE16:
            return _decompress_rle(raw, entry.uncompressed_size, 2)
        case CompressionMethod.ZLIB:
            return zlib.decompress(raw)
        case _:
            msg = f'Unknown compression method {entry.method} for {entry.name!r}.'
            raise NotImplementedError(msg)


def extract_all(data: bytes, dest: Path) -> tuple[int, int]:
    """
    Extract every file in a pack into a destination directory.

    Parameters
    ----------
    data : bytes
        The whole pack file.
    dest : Path
        Directory to write the mirrored tree into. It is created if missing.

    Returns
    -------
    tuple[int, int]
        The number of files written and the total number of bytes written.

    Raises
    ------
    UnsafePathError
        If an entry names an absolute path or one containing a parent reference.
    """
    archive = parse(data)
    count = 0
    total = 0
    for path, entry in iter_entries(archive):
        relative = path.replace('\\', '/')
        if relative.startswith('/') or '..' in relative.split('/'):
            msg = f'Unsafe path in archive: {path!r}.'
            raise UnsafePathError(msg)
        out_path = dest.joinpath(*relative.split('/'))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        blob = extract_entry(data, entry)
        out_path.write_bytes(blob)
        count += 1
        total += len(blob)
    log.debug('Extracted %d files totalling %d bytes.', count, total)
    return count, total
