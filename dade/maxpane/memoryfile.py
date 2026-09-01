"""
Decoder for the tagged ``R_MemoryFile`` streams carrying every custom Max Payne asset.

``R_MemoryFile::writeTagged`` prefixes each value with a one-byte ``BasicType`` tag and then writes
a byte count the caller chooses, so a tag does not encode its own length in general. In practice
each tag is used with one width, which :py:data:`TAG_SIZES` records.

Integers are stored in a narrowest-signed-fit form: ``operator<<`` measures the magnitude and picks
a one-, two-, three-, or four-byte encoding, with the tag identifying the width. That is why the
same logical field is two bytes in one level and three in another.

Chunked assets place a :py:data:`BasicType.CHUNK` tag before a 12-byte header giving an identifier,
a version, and a size that counts the 13-byte header itself. Levels and movement networks are flat
tagged streams and use no chunks.
"""
from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING
import struct

from .typing import TaggedValue

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

__all__ = ('CHUNK_HEADER_SIZE', 'TAG_SIZES', 'BasicType', 'iter_values', 'read_chunk_header',
           'read_int', 'read_string', 'read_vector3')


class BasicType(IntEnum):
    """
    Tag values written by ``R_MemoryFile::writeTag``.

    The scalar entries were read from the ``operator<<`` overloads exported by ``rl.dll``; the
    compact integer entries come from the width selection inside those overloads.
    """

    LONG = 0x00
    """Signed long, four bytes."""
    ULONG = 0x01
    """Unsigned long, four bytes."""
    INT32 = 0x02
    """Signed integer needing the full four bytes."""
    UINT32 = 0x03
    """Unsigned integer needing the full four bytes."""
    SHORT = 0x04
    """Signed short, two bytes."""
    USHORT = 0x05
    """Unsigned short, two bytes."""
    CHAR = 0x06
    """Character, one byte."""
    SCHAR = 0x07
    """Signed character, one byte."""
    UCHAR = 0x08
    """Unsigned character, one byte."""
    FLOAT = 0x09
    """Single-precision float, four bytes."""
    DOUBLE = 0x0A
    """Double-precision float, eight bytes."""
    CHUNK = 0x0C
    """Chunk header of twelve bytes."""
    STRING = 0x0D
    """String. The payload length is not implied by the tag."""
    BOOL = 0x0E
    """Boolean, one byte."""
    UINT24 = 0x0F
    """Unsigned integer compacted to three bytes."""
    UINT16 = 0x10
    """Unsigned integer compacted to two bytes."""
    UINT8 = 0x11
    """Unsigned integer compacted to one byte."""
    INT24 = 0x12
    """Signed integer compacted to three bytes."""
    INT16 = 0x13
    """Signed integer compacted to two bytes."""
    INT8 = 0x14
    """Signed integer compacted to one byte."""
    VECTOR2 = 0x15
    """Two floats."""
    VECTOR3 = 0x16
    """Three floats."""
    VECTOR4 = 0x17
    """Four floats."""
    MATRIX2 = 0x18
    """Two-by-two matrix of floats."""
    MATRIX3 = 0x19
    """Three-by-three matrix of floats."""
    MATRIX4X3 = 0x1A
    """Four-by-three matrix of floats."""
    MATRIX4 = 0x1B
    """Four-by-four matrix of floats."""
    ARRAY = 0x1C
    """Marker introducing a counted array. Carries no payload of its own."""
    MAP = 0x1F
    """Marker introducing a counted map. Carries no payload of its own; a count follows, then that
    many entries of a key and a :py:attr:`PAIR`."""
    PAIR = 0x25
    """Marker introducing the two halves of a map entry. Carries no payload of its own."""
    FLOAT16 = 0x26
    """Half-precision float, two bytes."""


CHUNK_HEADER_SIZE = 13
"""Size of a chunk tag plus its twelve-byte header.

:meta hide-value:
"""

TAG_SIZES: Mapping[int, int] = {
    BasicType.ARRAY: 0,
    BasicType.BOOL: 1,
    BasicType.CHAR: 1,
    BasicType.CHUNK: 12,
    BasicType.DOUBLE: 8,
    BasicType.FLOAT: 4,
    BasicType.FLOAT16: 2,
    BasicType.INT8: 1,
    BasicType.INT16: 2,
    BasicType.INT24: 3,
    BasicType.INT32: 4,
    BasicType.LONG: 4,
    BasicType.MATRIX2: 16,
    BasicType.MATRIX3: 36,
    BasicType.MATRIX4: 64,
    BasicType.MAP: 0,
    BasicType.MATRIX4X3: 48,
    BasicType.PAIR: 0,
    BasicType.SCHAR: 1,
    BasicType.SHORT: 2,
    BasicType.UCHAR: 1,
    BasicType.UINT8: 1,
    BasicType.UINT16: 2,
    BasicType.UINT24: 3,
    BasicType.UINT32: 4,
    BasicType.ULONG: 4,
    BasicType.USHORT: 2,
    BasicType.VECTOR2: 8,
    BasicType.VECTOR3: 12,
    BasicType.VECTOR4: 16
}
"""Payload width in bytes for every tag whose width is fixed.

:py:attr:`BasicType.STRING` is absent because its length is chosen by the caller.

:meta hide-value:
"""

_SIGNED_TAGS = frozenset({
    BasicType.INT8, BasicType.INT16, BasicType.INT24, BasicType.INT32, BasicType.LONG,
    BasicType.SHORT, BasicType.SCHAR
})


def read_chunk_header(data: bytes, offset: int = 0) -> tuple[int, int, int]:
    """
    Read a chunk tag and its header.

    Parameters
    ----------
    data : bytes
        The stream.
    offset : int
        Byte offset of the :py:attr:`BasicType.CHUNK` tag.

    Returns
    -------
    tuple[int, int, int]
        The chunk identifier, its version, and its size. The size counts the
        :py:data:`CHUNK_HEADER_SIZE` header bytes, so the payload is that many bytes shorter.

    Raises
    ------
    ValueError
        If the tag at *offset* is not :py:attr:`BasicType.CHUNK`.
    """
    if data[offset] != BasicType.CHUNK:
        msg = f'Not a chunk tag at offset {offset}: 0x{data[offset]:02x}.'
        raise ValueError(msg)
    return struct.unpack_from('<3I', data, offset + 1)


def read_int(data: bytes, offset: int) -> tuple[int, int]:
    """
    Read one tagged integer, whatever width it was compacted to.

    Parameters
    ----------
    data : bytes
        The stream.
    offset : int
        Byte offset of the tag.

    Returns
    -------
    tuple[int, int]
        The value and the offset just past it.

    Raises
    ------
    ValueError
        If the tag at *offset* is not an integer tag.
    """
    tag = data[offset]
    if tag not in TAG_SIZES or tag in {BasicType.ARRAY, BasicType.CHUNK}:
        msg = f'Not an integer tag at offset {offset}: 0x{tag:02x}.'
        raise ValueError(msg)
    width = TAG_SIZES[tag]
    end = offset + 1 + width
    return int.from_bytes(data[offset + 1:end], 'little', signed=tag in _SIGNED_TAGS), end


def read_string(data: bytes, offset: int) -> tuple[str, int]:
    """
    Read one tagged string.

    A string is the :py:attr:`BasicType.STRING` tag, then a tagged integer giving its length, then
    that many raw bytes. The length is compacted like any other integer, so it is one to four bytes
    wide and carries its own tag.

    Parameters
    ----------
    data : bytes
        The stream.
    offset : int
        Byte offset of the tag.

    Returns
    -------
    tuple[str, int]
        The string and the offset just past it.

    Raises
    ------
    ValueError
        If the tag at *offset* is not :py:attr:`BasicType.STRING`.
    """
    if data[offset] != BasicType.STRING:
        msg = f'Not a string tag at offset {offset}: 0x{data[offset]:02x}.'
        raise ValueError(msg)
    length, start = read_int(data, offset + 1)
    return data[start:start + length].decode('latin-1'), start + length


def read_vector3(data: bytes, offset: int) -> tuple[tuple[float, float, float], int]:
    """
    Read one tagged three-component vector.

    Parameters
    ----------
    data : bytes
        The stream.
    offset : int
        Byte offset of the tag.

    Returns
    -------
    tuple[tuple[float, float, float], int]
        The vector and the offset just past it.

    Raises
    ------
    ValueError
        If the tag at *offset* is not :py:attr:`BasicType.VECTOR3`.
    """
    if data[offset] != BasicType.VECTOR3:
        msg = f'Not a vector tag at offset {offset}: 0x{data[offset]:02x}.'
        raise ValueError(msg)
    return struct.unpack_from('<3f', data, offset + 1), offset + 13


def iter_values(data: bytes, offset: int = 0) -> Iterator[TaggedValue]:
    """
    Walk a tagged stream until an unknown tag or the end of the buffer.

    Bulk data such as lightmap pixels is written untagged, so a walk stops wherever the stream
    leaves tagged territory. The caller can resume by passing a later offset. Strings are followed
    correctly because they carry their own length.

    Parameters
    ----------
    data : bytes
        The stream.
    offset : int
        Byte offset to start at.

    Yields
    ------
    TaggedValue
        Each tag and its payload, in order. A string's payload is its bytes without the length.
    """
    while offset < len(data):
        tag = data[offset]
        if tag == BasicType.STRING:
            try:
                text, end = read_string(data, offset)
            except (IndexError, ValueError):
                return
            if end > len(data):
                return
            yield TaggedValue(end=end, offset=offset, payload=text.encode('latin-1'), tag=tag)
            offset = end
            continue
        if (width := TAG_SIZES.get(tag)) is None or offset + 1 + width > len(data):
            return
        yield TaggedValue(end=offset + 1 + width,
                          offset=offset,
                          payload=bytes(data[offset + 1:offset + 1 + width]),
                          tag=tag)
        offset += 1 + width
