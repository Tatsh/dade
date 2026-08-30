"""
Reader for the ``.FS`` archives shipped with The Sopranos: Road to Respect (PS2).

An archive stores its table of contents at the end. The final four bytes hold the absolute offset of
a chunk stream, and each chunk is a four-character tag followed by a little-endian ``u32`` length.
Only three tags occur, each padded to four characters with a trailing space: ``STR`` holds the
NUL-separated file names, ``DIR`` holds fixed 16-byte directory entries, and ``END`` terminates the
stream.

The game itself never reads the names. It resolves files by the CRC-32 of the lowercased name, which
is why directory entries are sorted by that hash rather than by name.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import struct

from dade.common.exceptions import InvalidFormatError
from dade.common.io import MmapReader
from dade.common.iso9660 import Iso9660Image

from .typing import FSEntry

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import IO

__all__ = ('DIR_TAG', 'END_TAG', 'SECTOR_SIZE', 'STR_TAG', 'is_disc_image', 'iter_disc_archives',
           'iter_entries', 'name_hash', 'read_directory')

log = logging.getLogger(__name__)

SECTOR_SIZE = 2048
"""Directory offsets are stored in units of this many bytes, matching the DVD sector size.

:meta hide-value:
"""
DIR_TAG = b'DIR '
"""Chunk tag introducing the fixed-size directory entries.

:meta hide-value:
"""
STR_TAG = b'STR '
"""Chunk tag introducing the NUL-separated name table.

:meta hide-value:
"""
END_TAG = b'END '
"""Chunk tag terminating the table of contents.

:meta hide-value:
"""

_CHUNK_HEADER_SIZE = 8
_ENTRY_SIZE = 16
_MIN_ARCHIVE_SIZE = 4
_STANDARD_ID_OFFSET = 0x8001
_CRC_POLYNOMIAL = 0x04C11DB7
_MASK32 = 0xFFFFFFFF


def _build_crc_table() -> tuple[int, ...]:
    table = []
    for i in range(256):
        value = i << 24
        for _ in range(8):
            value = ((value << 1) ^ _CRC_POLYNOMIAL) & _MASK32 if value & 0x80000000 else (
                (value << 1) & _MASK32)
        table.append(value)
    return tuple(table)


_CRC_TABLE = _build_crc_table()


def name_hash(name: str) -> int:
    """
    Compute the archive's lookup hash for a file name.

    This is a most-significant-bit-first CRC-32 with polynomial ``0x04C11DB7``, an initial and final
    value of ``0xFFFFFFFF``, and no reflection. The name is lowercased first, which makes lookups
    case-insensitive.

    Parameters
    ----------
    name : str
        The slash-separated path as recorded in the archive.

    Returns
    -------
    int
        The 32-bit hash.
    """
    crc = _MASK32
    for byte in name.lower().encode():
        crc = ((crc << 8) & _MASK32) ^ _CRC_TABLE[((crc >> 24) ^ byte) & 0xFF]
    return (~crc) & _MASK32


def is_disc_image(path: Path) -> bool:
    """
    Report whether a file looks like an ISO 9660 disc image.

    Parameters
    ----------
    path : Path
        The file to test.

    Returns
    -------
    bool
        ``True`` when the standard identifier is present at the usual place.
    """
    try:
        with path.open('rb') as fp:
            fp.seek(_STANDARD_ID_OFFSET)
            return fp.read(5) == b'CD001'
    except OSError:
        return False


def iter_disc_archives(path: Path) -> Iterator[tuple[str, int, int]]:
    """
    Yield each ``.FS`` archive stored in a disc image.

    Reading the archives in place avoids copying multi-gigabyte files out of the image first, and
    sidesteps the ISO mounters that hand back blank data for PlayStation 2 discs.

    Parameters
    ----------
    path : Path
        The disc image.

    Yields
    ------
    tuple[str, int, int]
        The archive's name, its byte offset within the image, and its length.
    """
    with MmapReader(path) as reader:
        image = Iso9660Image(reader)
        for name, _size in image.iter_files():
            if name.lower().endswith('.fs'):
                offset, length = image.locate(name)
                yield name.rsplit('/', 1)[-1], offset, length


def _looks_blank(fp: IO[bytes], base: int, size: int, probes: int = 8) -> bool:
    """
    Report whether an archive appears to be nothing but zero bytes.

    Parameters
    ----------
    fp : IO[bytes]
        The open archive.
    base : int
        Byte offset of the archive within *fp*.
    size : int
        Length of the archive in bytes.
    probes : int
        How many places to sample.

    Returns
    -------
    bool
        ``True`` when every sampled block is entirely zero.
    """
    for i in range(probes):
        fp.seek(base + (size // probes) * i)
        if fp.read(2048).strip(b'\0'):
            return False
    return True


def _read_chunks(
        path: Path,
        base: int = 0,
        length: int | None = None) -> tuple[tuple[str, ...], tuple[tuple[int, int, int], ...]]:
    size = path.stat().st_size - base if length is None else length
    if size < _MIN_ARCHIVE_SIZE:
        msg = f'`{path.name}` is too small to be an FS archive.'
        raise InvalidFormatError(msg)
    names: tuple[str, ...] = ()
    rows: tuple[tuple[int, int, int], ...] = ()
    with path.open('rb') as fp:
        fp.seek(base + size - 4)
        toc = struct.unpack('<I', fp.read(4))[0]
        if not toc and _looks_blank(fp, base, size):
            msg = (f'`{path.name}` contains only zero bytes. Some ISO mounters misread PlayStation '
                   f'2 discs and hand back a blank file; read the archive from the disc image '
                   f'itself instead.')
            raise InvalidFormatError(msg)
        if toc >= size:
            msg = f'`{path.name}` has a table of contents offset beyond the end of the file.'
            raise InvalidFormatError(msg)
        fp.seek(base + toc)
        while (header := fp.read(_CHUNK_HEADER_SIZE)) and len(header) == _CHUNK_HEADER_SIZE:
            tag, length = struct.unpack('<4sI', header)
            if tag == END_TAG:
                break
            payload = fp.read(length)
            if tag == STR_TAG:
                names = tuple(part.decode() for part in payload.split(b'\0') if part)
            elif tag == DIR_TAG:
                if length % _ENTRY_SIZE:
                    msg = f'`{path.name}` has a directory chunk that is not a multiple of 16 bytes.'
                    raise InvalidFormatError(msg)
                rows = tuple((sector, entry_size, entry_hash)
                             for _flags, sector, entry_size, entry_hash in (
                                 struct.unpack_from('<4I', payload, at)
                                 for at in range(0, length, _ENTRY_SIZE)))
    if not rows:
        msg = f'`{path.name}` has no directory chunk.'
        raise InvalidFormatError(msg)
    return names, rows


def read_directory(path: Path, base: int = 0, length: int | None = None) -> tuple[FSEntry, ...]:
    """
    Read an archive's table of contents.

    Entries whose hash matches no name in the string table are returned with a synthesised
    ``unnamed/<hash>.bin`` name so that nothing is silently dropped.

    Parameters
    ----------
    path : Path
        The ``.FS`` archive to read, or a disc image containing one.
    base : int
        Byte offset of the archive within *path*, for reading one out of a disc image in place.
    length : int | None
        Length of the archive in bytes; ``None`` means everything after *base*.

    Returns
    -------
    tuple[FSEntry, ...]
        One entry per file, in name order.

    Raises
    ------
    InvalidFormatError
        If the file is too short, holds only zero bytes, has a table of contents offset out of
        range, or has no directory chunk.
    """  # noqa: DOC502
    names, rows = _read_chunks(path, base, length)
    by_hash = {entry_hash: (sector, size) for sector, size, entry_hash in rows}
    entries = []
    seen = set()
    for name in sorted(names):
        if (found := by_hash.get(digest := name_hash(name))) is None:
            log.warning('No directory entry matches `%s`.', name)
            continue
        seen.add(digest)
        entries.append(FSEntry(name, found[0] * SECTOR_SIZE, found[1], digest))
    entries.extend(
        FSEntry(f'unnamed/{entry_hash:08x}.bin', sector * SECTOR_SIZE, size, entry_hash)
        for sector, size, entry_hash in rows if entry_hash not in seen)
    return tuple(entries)


def iter_entries(path: Path,
                 base: int = 0,
                 length: int | None = None) -> Iterator[tuple[FSEntry, bytes]]:
    """
    Yield every file in an archive together with its contents.

    Parameters
    ----------
    path : Path
        The ``.FS`` archive to read, or a disc image containing one.
    base : int
        Byte offset of the archive within *path*, for reading one out of a disc image in place.
    length : int | None
        Length of the archive in bytes; ``None`` means everything after *base*.

    Yields
    ------
    tuple[FSEntry, bytes]
        The directory entry and the bytes it points at.
    """
    entries = read_directory(path, base, length)
    with path.open('rb') as fp:
        for entry in entries:
            fp.seek(base + entry.offset)
            yield entry, fp.read(entry.size)
