"""Tests for :py:mod:`destin.i76.pe_unpack`."""
from __future__ import annotations

import struct

from destin.i76.pe_unpack import (
    OVERLAY_MAGIC,
    OVERLAY_OFFSET,
    InvalidImageError,
    decompress_block,
    parse_sections,
    unpack,
)
import pytest

_PE_OFFSET = 0x80
_OPTIONAL_SIZE = 0xE0


def _build_pe(sections: tuple[tuple[str, int, int, int, int], ...],
              *,
              size_of_image: int = 0x8000,
              overlay: bytes = b'') -> bytes:
    """
    Build a minimal PE image.

    Parameters
    ----------
    sections : tuple[tuple[str, int, int, int, int], ...]
        Name, virtual size, virtual address, raw size, and raw pointer per section.
    size_of_image : int
        Value for the optional header's SizeOfImage field.
    overlay : bytes
        Bytes placed at :py:data:`destin.i76.pe_unpack.OVERLAY_OFFSET`.

    Returns
    -------
    bytes
        The image.
    """
    data = bytearray(OVERLAY_OFFSET + max(len(overlay), 0x400))
    data[0:2] = b'MZ'
    struct.pack_into('<I', data, 0x3C, _PE_OFFSET)
    data[_PE_OFFSET:_PE_OFFSET + 4] = b'PE\0\0'
    struct.pack_into('<H', data, _PE_OFFSET + 6, len(sections))
    struct.pack_into('<H', data, _PE_OFFSET + 20, _OPTIONAL_SIZE)
    optional = _PE_OFFSET + 24
    struct.pack_into('<I', data, optional + 28, 0x10000000)  # ImageBase.
    struct.pack_into('<I', data, optional + 32, 0x1000)  # SectionAlignment.
    struct.pack_into('<I', data, optional + 56, size_of_image)  # SizeOfImage.
    struct.pack_into('<I', data, optional + 60, 0x400)  # SizeOfHeaders.
    base = optional + _OPTIONAL_SIZE
    for index, (name, vsize, vaddr, rawsize, rawptr) in enumerate(sections):
        header = base + index * 40
        data[header:header + 8] = name.encode().ljust(8, b'\0')
        struct.pack_into('<I', data, header + 8, vsize)
        struct.pack_into('<I', data, header + 12, vaddr)
        struct.pack_into('<I', data, header + 16, rawsize)
        struct.pack_into('<I', data, header + 20, rawptr)
    if overlay:
        data[OVERLAY_OFFSET:OVERLAY_OFFSET + len(overlay)] = overlay
    return bytes(data)


def test_decompress_block_run_length() -> None:
    payload, position = decompress_block(struct.pack('<II', 12, 0x00AB00), 0)
    assert payload == b'\xab' * 12
    assert position == 8


def test_decompress_block_reports_next_position() -> None:
    data = b'\x00' * 4 + struct.pack('<II', 3, 0x00FF00)
    _, position = decompress_block(data, 4)
    assert position == 12


def test_decompress_block_huffman_single_leaf() -> None:
    # One internal node whose children are both the leaf byte 0x41, so every bit decodes to 'A'.
    bits = [0] * 18
    for offset in (0, 9):
        for bit in range(9):
            bits[offset + bit] = (0x41 >> bit) & 1
    accumulator = 1  # node_count == 1.
    for index, bit in enumerate(bits[:23]):
        if bit:
            accumulator |= 1 << (8 + index)
    payload, _ = decompress_block(struct.pack('<II', 4, accumulator) + b'\x00' * 32, 0)
    assert payload == b'AAAA'


def test_parse_sections() -> None:
    image = _build_pe(
        (('.text', 0x2000, 0x1000, 0x400, 0x400), ('.rdata', 0x1000, 0x3000, 0x200, 0x800)))
    sections = parse_sections(image)
    assert [s.name for s in sections] == ['.text', '.rdata']
    assert sections[0].virtual_address == 0x1000
    assert sections[1].raw_size == 0x200


def test_parse_sections_rejects_non_pe() -> None:
    data = bytearray(0x200)
    struct.pack_into('<I', data, 0x3C, 0x80)
    with pytest.raises(InvalidImageError, match='Not a PE image'):
        parse_sections(bytes(data))


def test_unpack_rejects_bad_overlay_magic() -> None:
    image = _build_pe((('.text', 0x2000, 0x1000, 0x400, 0x400),))
    with pytest.raises(InvalidImageError, match='Overlay magic'):
        unpack(image)


def test_unpack_restores_entry_point() -> None:
    block = struct.pack('<II', 16, 0x00CD00)  # Run-length block of 0xcd.
    overlay = struct.pack('<IIII', OVERLAY_MAGIC, 1, 0x1234, 0) + struct.pack('<II', 0, 0) + block
    image = _build_pe((('.text', 0x2000, 0x1000, 0x400, 0x400),), overlay=overlay)
    out = unpack(image)
    optional = _PE_OFFSET + 24
    assert struct.unpack_from('<I', out, optional + 16)[0] == 0x1234


def test_unpack_writes_decompressed_section() -> None:
    block = struct.pack('<II', 16, 0x00CD00)
    overlay = struct.pack('<IIII', OVERLAY_MAGIC, 1, 0x1234, 0) + struct.pack('<II', 0, 0) + block
    image = _build_pe((('.text', 0x2000, 0x1000, 0x400, 0x400),), overlay=overlay)
    out = unpack(image)
    assert out[0x1000:0x1010] == b'\xcd' * 16


def test_unpack_skips_section_without_raw_data() -> None:
    block = struct.pack('<II', 16, 0x00CD00)
    overlay = struct.pack('<IIII', OVERLAY_MAGIC, 1, 0x1234, 0) + struct.pack('<II', 0, 0) + block
    image = _build_pe((('.text', 0x2000, 0x1000, 0x400, 0x400), ('.bss', 0x1000, 0x3000, 0, 0)),
                      overlay=overlay)
    out = unpack(image)
    assert out[0x1000:0x1010] == b'\xcd' * 16
    assert out[0x3000:0x3010] == b'\x00' * 16


def test_unpack_sets_file_alignment_to_section_alignment() -> None:
    block = struct.pack('<II', 4, 0x00CD00)
    overlay = struct.pack('<IIII', OVERLAY_MAGIC, 1, 0x20, 0) + struct.pack('<II', 0, 0) + block
    image = _build_pe((('.text', 0x2000, 0x1000, 0x400, 0x400),), overlay=overlay)
    out = unpack(image)
    optional = _PE_OFFSET + 24
    assert struct.unpack_from('<I', out, optional + 36)[0] == 0x1000


def test_unpack_makes_raw_pointers_match_virtual_addresses() -> None:
    block = struct.pack('<II', 4, 0x00CD00)
    overlay = struct.pack('<IIII', OVERLAY_MAGIC, 1, 0x20, 0) + struct.pack('<II', 0, 0) + block
    image = _build_pe((('.text', 0x2000, 0x1000, 0x400, 0x400),), overlay=overlay)
    out = unpack(image)
    header = _PE_OFFSET + 24 + _OPTIONAL_SIZE
    assert struct.unpack_from('<I', out, header + 20)[0] == 0x1000
    assert struct.unpack_from('<I', out, header + 16)[0] == 0x2000


def _pack_bits(node_count: int, bits: list[int]) -> bytes:
    """
    Encode a Huffman bit stream the way ``FUN_10001828`` reads it.

    Parameters
    ----------
    node_count : int
        Number of internal nodes, stored in the header dword's low byte.
    bits : list[int]
        The bits to emit, least-significant first.

    Returns
    -------
    bytes
        The header dword followed by any refill dwords.
    """
    header = node_count & 0xFF
    for index, bit in enumerate(bits[:24]):  # The header dword carries the first 24 bits.
        if bit:
            header |= 1 << (8 + index)
    words = [header]
    rest = bits[24:]
    while rest:
        word = 0
        for index, bit in enumerate(rest[:32]):
            if bit:
                word |= 1 << index
        words.append(word)
        rest = rest[32:]
    return b''.join(struct.pack('<I', word) for word in words)


def _value_bits(value: int) -> list[int]:
    return [(value >> bit) & 1 for bit in range(9)]


def test_decompress_block_traverses_internal_nodes() -> None:
    # Node 0 holds leaves 'A' and 'B'; node 1 (the root) points at node 0 on a zero bit and at
    # leaf 'B' on a one bit. Decoding [1] then [0, 0] therefore yields b'BA'.
    table = _value_bits(0x41) + _value_bits(0x42) + _value_bits(0x100) + _value_bits(0x42)
    data = struct.pack('<I', 2) + _pack_bits(2, [*table, 1, 0, 0])
    payload, _ = decompress_block(data, 0)
    assert payload == b'BA'
