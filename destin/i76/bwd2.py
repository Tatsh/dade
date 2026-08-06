"""
Walker for the BWD2 FOURCC containers used by ``.msn`` and ``.sdf`` files.

The grammar is a flat sequence of chunks, each a four-byte tag followed by a little-endian dword
size that counts the eight-byte header itself. Some tags nest further chunks in their payload and
others are leaves; which is which is not encoded in the file, so the container tags are supplied by
the caller and default to the set observed in the shipped missions.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import struct

from .typing import Chunk

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator

__all__ = ('DEFAULT_CONTAINER_TAGS', 'ascii_strings', 'is_tag', 'walk', 'world_refs')

log = logging.getLogger(__name__)

DEFAULT_CONTAINER_TAGS = frozenset({'BWD2', 'GRP ', 'SDFC', 'WDEF', 'WORL', 'WRLDS'})
"""Chunk tags treated as containers when the caller does not specify a set.

:meta hide-value:
"""

_WORLD_TAG = b'WRLD'
"""Tag of the chunk listing a mission's asset references.

:meta hide-value:
"""
_MIN_REF_LENGTH = 5
"""Shortest run of printable bytes accepted as an asset reference.

:meta hide-value:
"""
_PRINTABLE_START = 0x20
"""Lowest byte value treated as printable ASCII.

:meta hide-value:
"""
_PRINTABLE_END = 0x7F
"""One past the highest byte value treated as printable ASCII.

:meta hide-value:
"""
_HEADER_SIZE = 8
"""Size in bytes of a chunk header, being the tag and the size dword.

:meta hide-value:
"""


def is_tag(tag: bytes) -> bool:
    """
    Test whether four bytes look like a FOURCC tag.

    A tag begins with an ASCII letter, and its remaining bytes are printable or NUL padding.

    Parameters
    ----------
    tag : bytes
        The four bytes to test.

    Returns
    -------
    bool
        ``True`` when the bytes look like a tag.
    """
    if not tag[:1].isalpha():
        return False
    return all(byte == 0 or _PRINTABLE_START <= byte < _PRINTABLE_END for byte in tag)


def ascii_strings(data: bytes, min_length: int = 3) -> tuple[str, ...]:
    """
    Pull runs of printable ASCII out of a buffer.

    Parameters
    ----------
    data : bytes
        The buffer to scan.
    min_length : int
        Shortest run to report.

    Returns
    -------
    tuple[str, ...]
        Every printable run of at least ``min_length`` bytes, in order.
    """
    found: list[str] = []
    current = bytearray()
    for byte in data:
        if _PRINTABLE_START <= byte < _PRINTABLE_END:
            current.append(byte)
        else:
            if len(current) >= min_length:
                found.append(current.decode())
            current = bytearray()
    if len(current) >= min_length:
        found.append(current.decode())
    return tuple(found)


def _walk(data: bytes, offset: int, end: int, container_tags: Collection[str]) -> Iterator[Chunk]:
    """
    Yield the chunks between ``offset`` and ``end``.

    Parameters
    ----------
    data : bytes
        The container's contents.
    offset : int
        Byte offset to start at.
    end : int
        Byte offset to stop at.
    container_tags : collections.abc.Collection[str]
        Tags whose payloads hold further chunks.

    Yields
    ------
    Chunk
        Each chunk in order. Iteration stops early at the first malformed header.
    """
    while offset + _HEADER_SIZE <= end:
        tag = data[offset:offset + 4]
        size = struct.unpack_from('<I', data, offset + 4)[0]
        if not is_tag(tag) or size < _HEADER_SIZE or offset + size > end:
            log.debug('Stopping at offset %#x on tag %r with size %d.', offset, tag, size)
            return
        body, chunk_end = offset + _HEADER_SIZE, offset + size
        name = tag.decode('latin1')
        if name in container_tags:
            yield Chunk(name, offset, size, b'', tuple(_walk(data, body, chunk_end,
                                                             container_tags)))
        else:
            yield Chunk(name, offset, size, data[body:chunk_end], ())
        offset = chunk_end


def walk(data: bytes, container_tags: Collection[str] | None = None) -> tuple[Chunk, ...]:
    """
    Parse a BWD2 container into a chunk tree.

    Parameters
    ----------
    data : bytes
        The container's contents.
    container_tags : collections.abc.Collection[str] | None
        Tags whose payloads hold further chunks. Defaults to
        :py:data:`DEFAULT_CONTAINER_TAGS`.

    Returns
    -------
    tuple[Chunk, ...]
        The top-level chunks, each with its children populated.
    """
    tags = DEFAULT_CONTAINER_TAGS if container_tags is None else container_tags
    return tuple(_walk(data, 0, len(data), tags))


def world_refs(data: bytes) -> tuple[str, ...]:
    """
    Read the asset references out of a mission's ``WRLD`` chunk.

    Parameters
    ----------
    data : bytes
        Contents of the ``.msn`` file.

    Returns
    -------
    tuple[str, ...]
        Every referenced asset name, in order. Empty when the file has no ``WRLD`` chunk.
    """
    if (found := data.find(_WORLD_TAG)) < 0:
        return ()
    size = struct.unpack_from('<I', data, found + 4)[0]
    refs: list[str] = []
    current = bytearray()
    for byte in data[found + _HEADER_SIZE:found + size]:
        if _PRINTABLE_START <= byte < _PRINTABLE_END:
            current.append(byte)
        else:
            if len(current) >= _MIN_REF_LENGTH and b'.' in current:
                refs.append(current.decode('latin1'))
            current = bytearray()
    return tuple(refs)
