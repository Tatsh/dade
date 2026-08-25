"""
Generic Tcl CookFS container reader.

The container format is a cookfs archive: an opaque prefix, a run of compressed pages, a page
directory, and a 16-byte suffix ending in the ``CFS0002`` signature. The decompressed index (magic
``CFS2.200``) encodes the directory tree, each file listing the blocks that make up its contents.
The format is reproduced from the pure-Tcl cookfs reference implementation (``pages.tcl`` and
``fsindex.tcl``, ``(c) 2010-2014 Wojciech Kocjan``).

This module parses only the generic container: locating the signature, reading the page directory,
decompressing pages, and parsing the index tree. Any application-specific layer on top (encryption,
custom page decompressors, logical-member reassembly) is left to the caller.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import bz2
import struct
import zlib

from dade.bitrock.exceptions import (
    CorruptArchiveError,
    SignatureNotFoundError,
    UnsupportedCompressionError,
)

if TYPE_CHECKING:
    from collections.abc import MutableMapping

    from dade.common.io import Reader

__all__ = ('DEFAULT_SEARCH_WINDOW', 'Block', 'decompress_page', 'locate_end_offset',
           'parse_fs_index', 'parse_index', 'read_page_directory')

_SIGNATURE = b'CFS0002'
_INDEX_MAGIC = b'CFS2.200'
_SUFFIX_LENGTH = 16
"""Trailing record: ``idxsize`` (4) + ``numpages`` (4) + cid (1) + signature (7).

:meta hide-value:
"""
_MD5_LENGTH = 16
"""Length of each page's MD5 digest in the page directory.

:meta hide-value:
"""
_DIRECTORY_MARKER = -1
"""``numblocks`` value marking a directory rather than a file.

:meta hide-value:
"""
_COMPRESSION_NONE = 0
_COMPRESSION_ZLIB = 1
_COMPRESSION_BZ2 = 2
_BZ2_LENGTH_PREFIX = 4
"""Bytes cookfs writes before the bz2 stream for the uncompressed size (unused when reading).

:meta hide-value:
"""
DEFAULT_SEARCH_WINDOW = 16 << 20
"""
Bytes read from the end of the source when auto-locating the cookfs signature.

Some producers append a trailer after the cookfs archive, so the signature is not at the very end
of the file; the window must be larger than that trailer. Pass an explicit ``end_offset`` to
:py:func:`locate_end_offset` to skip the scan entirely.

:meta hide-value:
"""


class Block(NamedTuple):
    """
    A single span of file data stored inside a cookfs page.

    A file's contents are the concatenation of its blocks, in order.
    """
    page_index: int
    """Index of the page holding the data."""
    offset: int
    """Byte offset of the span within the decompressed page."""
    size: int
    """Length of the span in bytes."""


def decompress_page(page: bytes) -> bytes:
    """
    Decompress a single stored page.

    Parameters
    ----------
    page : bytes
        Raw page bytes, including the leading compression-id byte.

    Returns
    -------
    bytes
        The decompressed page contents.

    Raises
    ------
    UnsupportedCompressionError
        If the page uses a compression method this reader does not support (custom, id 255).
    """
    if not page:
        return b''
    match page[0]:
        case c if c == _COMPRESSION_NONE:
            return page[1:]
        case c if c == _COMPRESSION_ZLIB:
            return zlib.decompress(page[1:], -zlib.MAX_WBITS)
        case c if c == _COMPRESSION_BZ2:
            return bz2.decompress(page[1 + _BZ2_LENGTH_PREFIX:])
        case c:
            msg = f'Unsupported page compression id {c}.'
            raise UnsupportedCompressionError(msg)


def locate_end_offset(reader: Reader, end_offset: int | None, search_window: int) -> int:
    """
    Determine the offset just past the cookfs signature.

    Parameters
    ----------
    reader : Reader
        The byte source.
    end_offset : int | None
        A caller-supplied offset, or ``None`` to auto-detect.
    search_window : int
        Number of trailing bytes to scan when auto-detecting.

    Returns
    -------
    int
        The resolved end offset.

    Raises
    ------
    SignatureNotFoundError
        If the signature cannot be found within the window.
    """
    if end_offset is not None:
        return end_offset
    window = min(search_window, reader.size)
    base = reader.size - window
    tail = reader.read(base, window)
    if (marker := tail.rfind(_SIGNATURE)) < 0:
        msg = ('cookfs signature not found in the final '
               f'{window} bytes; pass end_offset or a larger search_window.')
        raise SignatureNotFoundError(msg)
    return base + marker + len(_SIGNATURE)


def read_page_directory(reader: Reader,
                        end_offset: int) -> tuple[tuple[int, ...], tuple[int, ...], bytes]:
    """
    Parse the page directory and index blob.

    Parameters
    ----------
    reader : Reader
        The byte source for the whole image.
    end_offset : int
        Offset just past the ``CFS0002`` signature, as returned by :py:func:`locate_end_offset`.

    Returns
    -------
    tuple[tuple[int, ...], tuple[int, ...], bytes]
        Per-page start offsets, per-page stored sizes, and the decompressed index blob.

    Raises
    ------
    CorruptArchiveError
        If the directory is truncated or inconsistent.
    """
    suffix = reader.read(end_offset - _SUFFIX_LENGTH, _SUFFIX_LENGTH)
    if len(suffix) != _SUFFIX_LENGTH or suffix[9:] != _SIGNATURE:
        msg = 'Invalid cookfs suffix.'
        raise CorruptArchiveError(msg)
    index_size, page_count = struct.unpack('>II', suffix[:8])
    directory_offset = end_offset - (_SUFFIX_LENGTH + index_size + page_count * (_MD5_LENGTH + 4))
    if directory_offset < 0:
        msg = 'Corrupt cookfs directory offset.'
        raise CorruptArchiveError(msg)
    sizes_offset = directory_offset + page_count * _MD5_LENGTH
    page_sizes = struct.unpack(f'>{page_count}I', reader.read(sizes_offset, page_count * 4))
    start = directory_offset - sum(page_sizes)
    if start < 0:
        msg = 'Corrupt cookfs page data offset.'
        raise CorruptArchiveError(msg)
    offsets: list[int] = []
    running = start
    for size in page_sizes:
        offsets.append(running)
        running += size
    index_start = sizes_offset + page_count * 4
    index_data = decompress_page(reader.read(index_start, index_size))
    return tuple(offsets), page_sizes, index_data


def parse_fs_index(index_data: bytes) -> dict[str, tuple[Block, ...]]:
    """
    Parse a decompressed cookfs index into a flat mapping of file paths to blocks.

    Directories are not included in the result; only files carry block lists.

    Parameters
    ----------
    index_data : bytes
        The decompressed index blob, starting with the ``CFS2.200`` magic.

    Returns
    -------
    dict[str, tuple[Block, ...]]
        Mapping of each file's forward-slash-separated path to its ordered blocks.
    """
    return parse_index(index_data)[0]


def parse_index(index_data: bytes) -> tuple[dict[str, tuple[Block, ...]], dict[str, bytes]]:
    """
    Parse a decompressed cookfs index into its file tree and metadata.

    Parameters
    ----------
    index_data : bytes
        The decompressed index blob, starting with the ``CFS2.200`` magic.

    Returns
    -------
    tuple[dict[str, tuple[Block, ...]], dict[str, bytes]]
        The file-to-blocks mapping and the archive metadata mapping.

    Raises
    ------
    CorruptArchiveError
        If the magic is missing or the structure is truncated.
    """
    if index_data[:8] != _INDEX_MAGIC:
        msg = 'Invalid cookfs index magic.'
        raise CorruptArchiveError(msg)
    files: dict[str, tuple[Block, ...]] = {}
    try:
        position = _parse_directory(index_data, 8, '', files)
        metadata = _parse_metadata(index_data, position)
    except (IndexError, struct.error) as e:
        msg = 'Truncated cookfs index.'
        raise CorruptArchiveError(msg) from e
    return files, metadata


def _parse_metadata(data: bytes, position: int) -> dict[str, bytes]:
    """
    Parse the key/value metadata that follows the directory tree in a cookfs index.

    Parameters
    ----------
    data : bytes
        The whole index blob.
    position : int
        Offset at which the metadata section begins.

    Returns
    -------
    dict[str, bytes]
        The metadata entries, keyed by name.
    """
    metadata: dict[str, bytes] = {}
    if len(data) - position < 4:  # noqa: PLR2004
        return metadata
    (count,) = struct.unpack_from('>i', data, position)
    position += 4
    for _ in range(count):
        (size,) = struct.unpack_from('>I', data, position)
        position += 4
        blob = data[position:position + size]
        position += size
        if (separator := blob.find(b'\x00')) >= 0:
            metadata[blob[:separator].decode('latin1')] = blob[separator + 1:]
    return metadata


def _parse_directory(data: bytes, position: int, path: str,
                     files: MutableMapping[str, tuple[Block, ...]]) -> int:
    """
    Parse one directory level, recursing into subdirectories.

    Parameters
    ----------
    data : bytes
        The whole index blob.
    position : int
        Offset at which this directory's entries begin.
    path : str
        Path of the directory being parsed (empty for the root).
    files : MutableMapping[str, tuple[Block, ...]]
        Accumulator that collects file entries as they are discovered.

    Returns
    -------
    int
        The offset immediately after this directory's entries.
    """
    (item_count,) = struct.unpack_from('>i', data, position)
    position += 4
    for _ in range(item_count):
        name_length = data[position]
        position += 1
        name = data[position:position + name_length].decode('utf-8')
        position += name_length + 1  # Skip the NUL terminator.
        _mtime, block_count = struct.unpack_from('>qi', data, position)
        position += 12
        child = f'{path}/{name}' if path else name
        if block_count == _DIRECTORY_MARKER:
            position = _parse_directory(data, position, child, files)
        else:
            flat = struct.unpack_from(f'>{block_count * 3}i', data, position)
            position += block_count * 12
            files[child] = tuple(Block(*flat[i:i + 3]) for i in range(0, len(flat), 3))
    return position
