"""
The ``XG2Arch`` container used by Extreme-G XG2 on both N64 and PC.

Layout, all fields unsigned 32-bit::

    +0x00  entryCount
    +0x04  padding
    +0x08  entryCount x 16-byte records:
               +0x00  offset, relative to the container base
               +0x04  four-character codec tag
               +0x08  decompressed size
               +0x0C  compressed size

The PC port stores the same structure little-endian, which byte-reverses the codec tags
(``SSZL`` for ``LZSS``, ``FUHL`` for ``LHUF``, ``YPOC`` for ``COPY``). Both are handled here by
passing the appropriate :py:data:`~dade.xg2.typing.Endian` character, so the two platforms share
one parser.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import struct

from dade.common.lz import decompress_lzss0

from .lzhuf import LzhufUnavailableError, decompress_lzhuf

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .typing import ArchEntry, Endian

__all__ = ('ARCHIVE_TAGS', 'MAX_ENTRY_COUNT', 'decode_entries', 'decode_entry', 'is_archive',
           'parse_archive', 'try_sized_lzss')

log = logging.getLogger(__name__)

ARCHIVE_TAGS = (b'LZSS', b'LHUF', b'HUFF', b'COPY')
"""Codec tags accepted in an ``XG2Arch`` record, in big-endian order.

:meta hide-value:
"""
MAX_ENTRY_COUNT = 4096
"""Largest entry count treated as a plausible container header.

:meta hide-value:
"""
_COPY_TAGS = frozenset({'COPY', 'COMP', 'BIN', 'NONE'})
_LZHUF_TAGS = frozenset({'LHUF', 'HUFF'})
_RECORD_SIZE = 0x10
_MAX_SIZED_LZSS = 8 * 1024 * 1024
_MIN_CONTAINER_SIZE = 0x18
_HEADER_SIZE = 8


def _read_tag(data: bytes, offset: int, endian: Endian) -> str:
    raw = bytes(data[offset:offset + 4])
    if endian == '<':
        raw = raw[::-1]
    return raw.decode('ascii', 'replace').upper().strip('\x00')


def parse_archive(data: bytes, base: int = 0, endian: Endian = '>') -> list[ArchEntry]:
    """
    Parse an ``XG2Arch`` container directory.

    Parameters
    ----------
    data : bytes
        Buffer holding the container.
    base : int
        Offset of the container header within *data*.
    endian : dade.xg2.typing.Endian
        Byte order: ``>`` for the N64 builds, ``<`` for the PC port.

    Returns
    -------
    list[dade.xg2.typing.ArchEntry]
        One record per entry, in container order. A :py:class:`struct.error` propagates if the
        header or a record runs past the end of *data*.
    """
    count = struct.unpack_from(f'{endian}I', data, base)[0]
    entries: list[ArchEntry] = []
    pos = base + 8
    for index in range(count):
        offset, decompressed, compressed = struct.unpack_from(f'{endian}I4x2I', data, pos)
        entries.append({
            'index': index,
            'offset': offset,
            'absolute': base + offset,
            'codec': _read_tag(data, pos + 4, endian),
            'decompressed_size': decompressed,
            'compressed_size': compressed or decompressed
        })
        pos += _RECORD_SIZE
    return entries


def decode_entry(data: bytes, entry: ArchEntry) -> bytes:
    """
    Decode one ``XG2Arch`` entry.

    Parameters
    ----------
    data : bytes
        Buffer holding the container.
    entry : dade.xg2.typing.ArchEntry
        The record to decode, as returned by :py:func:`parse_archive`.

    Returns
    -------
    bytes
        The decoded entry, truncated to its declared decompressed size. A
        :py:class:`~dade.xg2.lzhuf.LzhufUnavailableError` propagates for an ``LHUF`` entry.

    Raises
    ------
    ValueError
        If the codec tag is not recognised.
    """
    source = entry['absolute']
    codec = entry['codec']
    if codec in _COPY_TAGS:
        return bytes(data[source:source + entry['compressed_size']])
    if codec == 'LZSS':
        return decompress_lzss0(data, source, entry['decompressed_size'])[0]
    if codec in _LZHUF_TAGS:
        return decompress_lzhuf(data, source, entry['decompressed_size'])
    msg = f'Unknown XG2Arch codec {codec!r} at 0x{source:X}.'
    raise ValueError(msg)


def _try_decode(data: bytes, entry: ArchEntry) -> bytes | None:
    """
    Decode one entry, logging and giving up rather than raising.

    Returns
    -------
    bytes | None
        The decoded entry, or ``None`` when it could not be decoded.
    """
    try:
        return decode_entry(data, entry)
    except LzhufUnavailableError:
        log.warning('Skipping entry %d at 0x%X: the LHUF codec is not implemented.', entry['index'],
                    entry['absolute'])
    except (IndexError, ValueError, struct.error):
        log.warning('Skipping undecodable entry %d at 0x%X.', entry['index'], entry['absolute'])
    return None


def decode_entries(data: bytes, entries: list[ArchEntry]) -> Iterator[tuple[ArchEntry, bytes]]:
    """
    Decode every entry that can be decoded, skipping and logging the rest.

    Parameters
    ----------
    data : bytes
        Buffer holding the container.
    entries : list[dade.xg2.typing.ArchEntry]
        Records to decode, as returned by :py:func:`parse_archive`.

    Yields
    ------
    tuple[dade.xg2.typing.ArchEntry, bytes]
        Each record paired with its decoded bytes.
    """
    for entry in entries:
        decoded = _try_decode(data, entry)
        if decoded is not None:
            yield entry, decoded


def is_archive(data: bytes, endian: Endian = '>') -> bool:
    """
    Report whether a buffer starts with a plausible ``XG2Arch`` header.

    Parameters
    ----------
    data : bytes
        Buffer to inspect.
    endian : dade.xg2.typing.Endian
        Byte order to test against.

    Returns
    -------
    bool
        Whether the buffer looks like a container.
    """
    if len(data) < _MIN_CONTAINER_SIZE:
        return False
    count = struct.unpack_from(f'{endian}I', data, 0)[0]
    return 1 <= count <= MAX_ENTRY_COUNT and _read_tag(data, 0xC, endian).encode() in ARCHIVE_TAGS


def try_sized_lzss(data: bytes, endian: Endian = '<') -> bytes | None:
    """
    Decode a bare ``[u32 decompressed size][LZSS stream]`` blob.

    Some PC models, notably ``BIKES/*.cmp``, are not containers but a size word followed directly
    by an LZSS stream. Raw level containers whose leading word happens to be a size no larger than
    the file are rejected, since a real stream must expand.

    Parameters
    ----------
    data : bytes
        Buffer to inspect.
    endian : dade.xg2.typing.Endian
        Byte order of the leading size word.

    Returns
    -------
    bytes | None
        The decompressed bytes, or ``None`` when *data* is not such a blob.
    """
    if len(data) < _HEADER_SIZE:
        return None
    size = struct.unpack_from(f'{endian}I', data, 0)[0]
    if not (len(data) < size < _MAX_SIZED_LZSS):
        return None
    try:
        out, consumed = decompress_lzss0(data, 4, size)
    except IndexError:
        return None
    if len(out) >= size and consumed <= len(data) - 4 + 16:
        return out
    # A stream that decodes without raising always produces exactly *size* bytes and never reads
    # past the end of *data*, so both guards above hold and this is unreachable in practice. It is
    # kept in case the decompressor's contract ever loosens.
    return None  # pragma: no cover
