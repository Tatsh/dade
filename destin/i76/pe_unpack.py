"""
Static unpacker for DLLs packed with the Interstate '82 custom compressor.

``i82sim.dll`` and its siblings ship with a ``.text`` section holding only a small decompressor
stub and a zero-filled hole; the real code lives in an appended overlay that the stub inflates at
load time. Reproducing that statically lets the result be loaded into a disassembler.

Reverse-engineered from the stub at image base ``0x10000000``:

- ``FUN_100011e0`` maps the module, reads the overlay header, decompresses each listed section into
  its relative virtual address, applies base relocations, and jumps to the original entry point.
- ``FUN_10001828`` is the decompressor. Each block is an output size dword, a header dword, and
  then a bit stream. When the header's low byte is zero the block is a run of ``(header >> 8) &
  0xff`` repeated to fill the output. Otherwise the low byte is the number of Huffman internal
  nodes, each holding two 9-bit child entries; a child below ``0x100`` is a leaf byte and one at or
  above ``0x100`` is an internal node index plus ``0x100``. Bits are read least-significant first,
  the header dword doubles as the first accumulator word, and refills read little-endian dwords.
- The overlay begins at file offset ``0x1be00`` and holds the magic, the number of compressed
  sections, the original entry point's relative virtual address, the decompressed size of the
  relocation stream, one section index and characteristics pair per compressed section, and then
  one compressed block per section followed by the relocation block.

The unpacked image is emitted at its preferred base, so base relocations are a no-op and are
skipped. Imports live in the uncompressed ``.rdata`` and survive intact.
"""
from __future__ import annotations

import logging
import struct

from destin.common.io import u16, u32

from .typing import PeSection

__all__ = ('OVERLAY_MAGIC', 'OVERLAY_OFFSET', 'InvalidImageError', 'decompress_block',
           'parse_sections', 'unpack')

log = logging.getLogger(__name__)

OVERLAY_OFFSET = 0x1BE00
"""File offset of the overlay, taken from ``DAT_10001011`` in the stub.

:meta hide-value:
"""
OVERLAY_MAGIC = 0x04181996
"""Magic checked by ``FUN_100011e0`` at the start of the overlay.

:meta hide-value:
"""

_LEAF_LIMIT = 0x100
"""Child values below this are leaf bytes; the rest are internal node indices plus this value.

:meta hide-value:
"""
_SECTION_HEADER_SIZE = 40
"""Size in bytes of one PE section header.

:meta hide-value:
"""


class InvalidImageError(ValueError):
    """Raised when a file is not a PE image or carries no recognised overlay."""


def _align_up(value: int, alignment: int) -> int:
    """
    Round a value up to a multiple of an alignment.

    Parameters
    ----------
    value : int
        The value to round.
    alignment : int
        The alignment, which must be a power of two.

    Returns
    -------
    int
        The rounded value.
    """
    return (value + alignment - 1) & ~(alignment - 1)


def decompress_block(data: bytes, position: int) -> tuple[bytes, int]:
    """
    Decode one compressed block.

    Parameters
    ----------
    data : bytes
        The packed file's contents.
    position : int
        Byte offset of the block.

    Returns
    -------
    tuple[bytes, int]
        The block's output and the offset just past the block.
    """
    out_size = u32(data, position)
    position += 4
    accumulator = u32(data, position)
    position += 4
    node_count = accumulator & 0xFF
    mask = 0x80

    def read_bit() -> int:
        nonlocal accumulator, mask, position
        mask = (mask * 2) & 0xFFFFFFFF
        if mask == 0:  # Thirty-two bits consumed, so refill.
            accumulator = u32(data, position)
            position += 4
            mask = 1
        return 1 if (accumulator & mask) else 0

    if node_count == 0:  # A run-length block.
        return bytes([(accumulator >> 8) & 0xFF]) * out_size, position

    table = [0] * (node_count * 2)
    for node in range(node_count):
        for child in range(2):
            value = 0
            for bit in range(9):
                if read_bit():
                    value |= 1 << bit
            table[node * 2 + child] = value

    out = bytearray()
    root = node_count - 1
    while len(out) < out_size:
        index = root
        while True:
            value = table[index * 2 + read_bit()]
            if value >= _LEAF_LIMIT:
                index = value - _LEAF_LIMIT
            else:
                out.append(value)
                break
    return bytes(out), position


def parse_sections(data: bytes) -> tuple[PeSection, ...]:
    """
    Read every section header out of a PE image.

    Parameters
    ----------
    data : bytes
        The image's contents.

    Returns
    -------
    tuple[PeSection, ...]
        The section headers, in file order.

    Raises
    ------
    InvalidImageError
        If the file carries no PE signature.
    """
    pe_offset = u32(data, 0x3C)
    if data[pe_offset:pe_offset + 4] != b'PE\0\0':
        msg = 'Not a PE image.'
        raise InvalidImageError(msg)
    section_offset = pe_offset + 24 + u16(data, pe_offset + 20)
    sections: list[PeSection] = []
    for index in range(u16(data, pe_offset + 6)):
        header = section_offset + index * _SECTION_HEADER_SIZE
        sections.append(
            PeSection(data[header:header + 8].rstrip(b'\0').decode('latin1'), u32(data, header + 8),
                      u32(data, header + 12), u32(data, header + 16), u32(data, header + 20),
                      u32(data, header + 36), header))
    return tuple(sections)


def unpack(data: bytes) -> bytes:
    """
    Statically unpack a packed image into a memory-aligned dump.

    The result has its file offsets equal to its relative virtual addresses and its entry point
    restored, so a disassembler can load it directly at the image's preferred base.

    Parameters
    ----------
    data : bytes
        The packed image's contents.

    Returns
    -------
    bytes
        The unpacked image.

    Raises
    ------
    InvalidImageError
        If the file carries no PE signature or no recognised overlay.
    """
    pe_offset = u32(data, 0x3C)
    sections = parse_sections(data)
    optional_offset = pe_offset + 24
    image_base = u32(data, optional_offset + 28)
    section_alignment = u32(data, optional_offset + 32)
    size_of_image = u32(data, optional_offset + 56)
    size_of_headers = u32(data, optional_offset + 60)
    log.debug('Image base %#010x with %d sections and image size %#010x.', image_base,
              len(sections), size_of_image)

    image = bytearray(size_of_image)
    image[0:size_of_headers] = data[0:size_of_headers]
    for section in sections:
        if section.raw_pointer and section.raw_size:
            raw = data[section.raw_pointer:section.raw_pointer + section.raw_size]
            image[section.virtual_address:section.virtual_address + len(raw)] = raw

    if u32(data, OVERLAY_OFFSET) != OVERLAY_MAGIC:
        msg = 'Overlay magic mismatch.'
        raise InvalidImageError(msg)
    packed_count = u32(data, OVERLAY_OFFSET + 4)
    entry_point = u32(data, OVERLAY_OFFSET + 8)
    log.debug(
        'Overlay lists %d packed sections with entry point %#010x and a %#x-byte '
        'relocation stream.', packed_count, entry_point, u32(data, OVERLAY_OFFSET + 12))

    position = OVERLAY_OFFSET + 16
    descriptors = [u32(data, position + index * 8) for index in range(packed_count)]
    position += packed_count * 8
    for section_index in descriptors:
        section = sections[section_index]
        out, position = decompress_block(data, position)
        image[section.virtual_address:section.virtual_address + len(out)] = out
        log.debug('Decompressed section `%s` at %#010x to %d bytes.', section.name,
                  section.virtual_address, len(out))

    # Rewrite the headers so the file is a memory-aligned dump: raw sizes and offsets match the
    # virtual layout, and the entry point points at the recovered original.
    struct.pack_into('<I', image, optional_offset + 36, section_alignment)
    struct.pack_into('<I', image, optional_offset + 16, entry_point)
    out_size = size_of_headers
    for section in sections:
        aligned = _align_up(max(section.virtual_size, section.raw_size), section_alignment)
        struct.pack_into('<I', image, section.header_offset + 16, aligned)
        struct.pack_into('<I', image, section.header_offset + 20, section.virtual_address)
        out_size = max(out_size, section.virtual_address + aligned)
    return bytes(image[:out_size])
