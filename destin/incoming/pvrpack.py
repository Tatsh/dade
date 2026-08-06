"""
Reader for the Incoming ``*_T.PVR`` Dreamcast texture-pack container.

A pack begins with a table of contents made of ``(absolute offset, size)`` pairs of unsigned 32-bit
little-endian integers, terminated by a zero entry. The byte length of the table equals the offset
of its first entry. Each entry points at a standard Dreamcast PVRT chunk.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import logging
import struct

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ('PackTexture', 'iter_pack_textures')

log = logging.getLogger(__name__)

_PVRT_MAGIC = b'PVRT'
_TOC_ENTRY = struct.Struct('<II')
_PVRT_SUBHEADER = struct.Struct('<BBHHH')
_U32 = struct.Struct('<I')


class PackTexture(NamedTuple):
    """A single PVRT texture extracted from a pack."""

    position: int
    """Zero-based position of the texture within the pack."""
    width: int
    """Texture width in pixels."""
    height: int
    """Texture height in pixels."""
    data: bytes
    """The complete standalone PVRT chunk, ready to be written as a ``.pvr`` file."""


def _read_chunk(data: bytes, offset: int, size: int, position: int) -> PackTexture:
    if data[offset:offset + 4] != _PVRT_MAGIC:
        msg = f'Entry {position} at offset 0x{offset:x} does not start with a PVRT magic.'
        raise ValueError(msg)
    _, _, _, width, height = _PVRT_SUBHEADER.unpack_from(data, offset + 8)
    end = min(offset + size, len(data))
    if end < offset + size:
        log.warning('Entry %d is truncated by %d bytes; clamping to end of file.', position,
                    offset + size - end)
    return PackTexture(position, width, height, data[offset:end])


def iter_pack_textures(data: bytes) -> Iterator[PackTexture]:
    """
    Iterate over the textures contained in an Incoming PVR pack.

    A plain PVRT file (one that begins with the ``PVRT`` magic) is yielded as a single texture.

    Parameters
    ----------
    data : bytes
        The complete contents of a ``*_T.PVR`` file.

    Yields
    ------
    PackTexture
        One entry for every texture in the pack, in storage order.

    Raises
    ------
    ValueError
        If the data is too short or its table of contents is not self-consistent.
    """
    if data[:4] == _PVRT_MAGIC:
        yield _read_chunk(data, 0, len(data), 0)
        return
    if len(data) < _TOC_ENTRY.size:
        msg = 'File is too small to be an Incoming PVR pack.'
        raise ValueError(msg)
    toc_length = _U32.unpack_from(data, 0)[0]
    if toc_length < _TOC_ENTRY.size or toc_length % _TOC_ENTRY.size or toc_length > len(data):
        msg = f'Invalid table-of-contents length {toc_length}; not an Incoming PVR pack.'
        raise ValueError(msg)
    for position in range(toc_length // _TOC_ENTRY.size):
        offset, size = _TOC_ENTRY.unpack_from(data, position * _TOC_ENTRY.size)
        if offset == 0 and size == 0:
            break
        yield _read_chunk(data, offset, size, position)
