"""Tests for :py:mod:`destin.rhythmin.dialogue`."""
from __future__ import annotations

import struct

import pytest

from destin.rhythmin.dialogue import (
    POOLS,
    PoolSpec,
    empty_pools,
    extract_pools,
    render_binary,
    render_c_header,
)

from .conftest import MACHO_STRINGS, MACHO_TABLE_ADDRESS

_SPEC = PoolSpec('kTestPool', MACHO_TABLE_ADDRESS, len(MACHO_STRINGS))
_FAT_HEADER_SIZE = 28


def test_extract_pools(macho_image: bytes) -> None:
    pools = extract_pools(macho_image, (_SPEC,))
    assert len(pools) == 1
    assert pools[0].name == 'kTestPool'
    assert pools[0].strings == MACHO_STRINGS


def _fat(image: bytes, cpu_type: int) -> bytes:
    """Wrap an image in a fat header holding one slice of the given CPU type."""
    # The magic, one architecture, then that architecture's CPU type, subtype, offset, size, and
    # alignment, which is 28 bytes, so the slice starts there.
    return struct.pack('>IIiIIII', 0xCAFEBABE, 1, cpu_type, 0, _FAT_HEADER_SIZE, len(image),
                       0) + image


def test_extract_pools_unwraps_a_fat_binary(macho_image: bytes) -> None:
    assert extract_pools(_fat(macho_image, 12), (_SPEC,))[0].strings == MACHO_STRINGS


def test_extract_pools_rejects_a_fat_binary_with_no_arm_slice(macho_image: bytes) -> None:
    with pytest.raises(ValueError, match='No 32-bit ARM slice'):
        extract_pools(_fat(macho_image, 7), (_SPEC,))


def test_extract_pools_rejects_a_64_bit_image() -> None:
    with pytest.raises(ValueError, match='Not a 32-bit Mach-O image'):
        extract_pools(struct.pack('<I', 0xFEEDFACF) + b'\0' * 64, (_SPEC,))


def test_extract_pools_rejects_an_address_outside_every_segment(macho_image: bytes) -> None:
    with pytest.raises(ValueError, match='is in no segment'):
        extract_pools(macho_image, (PoolSpec('kNope', 0xDEAD0000, 1),))


def test_extract_pools_rejects_a_pointer_outside_the_file(macho_image: bytes) -> None:
    # The pointer table's own address, read as if it were a pointer array of the wrong length,
    # eventually walks into the string data and off the end of the mapped range.
    with pytest.raises(ValueError, match='is not in the file'):
        extract_pools(macho_image, (PoolSpec('kTooLong', MACHO_TABLE_ADDRESS, 64),))


def test_extract_pools_stops_reading_commands_at_a_zero_length_one(macho_image: bytes) -> None:
    data = bytearray(macho_image)
    # Claim a second load command; the zero padding after the segment reads as a zero-length one.
    struct.pack_into('<I', data, 16, 2)
    assert extract_pools(bytes(data), (_SPEC,))[0].strings == MACHO_STRINGS


def _image_with_unterminated_string() -> bytes:
    vm_base = 0x4000
    table_offset = 128
    tail = b'abcdef'  # No NUL, so the string runs off the end of the file.
    file_size = table_offset + 4 + len(tail)
    segment = struct.pack('<II16sIIIIIIII', 0x1, 56, b'__TEXT', vm_base, file_size, 0, file_size, 7,
                          5, 0, 0)
    image = bytearray(struct.pack('<IIIIIII', 0xFEEDFACE, 12, 9, 2, 1, len(segment), 0) + segment)
    image += b'\0' * (table_offset - len(image))
    image += struct.pack('<I', vm_base + table_offset + 4)
    image += tail
    return bytes(image)


def test_extract_pools_rejects_a_string_that_is_not_terminated() -> None:
    with pytest.raises(ValueError, match='not NUL-terminated'):
        extract_pools(_image_with_unterminated_string(), (PoolSpec('kUnterminated', 0x4080, 1),))


def test_empty_pools() -> None:
    pools = empty_pools()
    assert [pool.name for pool in pools] == [spec.name for spec in POOLS]
    assert [pool.entry_count for pool in pools] == [spec.entry_count for spec in POOLS]
    assert all(pool.strings == () for pool in pools)


def test_render_c_header_escapes(macho_image: bytes) -> None:
    header = render_c_header(extract_pools(macho_image, (_SPEC,)))
    assert 'static const char *const kTestPool[4] = {' in header
    assert '"plain ascii",' in header
    assert r'"quotes \" backslash \\ question \?",' in header
    # High bytes become three-digit octal so the literal stays plain ASCII.
    assert '\\343\\201\\262' in header


def test_render_c_header_for_empty_pools() -> None:
    header = render_c_header(empty_pools())
    assert 'static const char *const kCharGroup6Slot0[41] = {0};' in header


def test_render_binary(macho_image: bytes) -> None:
    pools = extract_pools(macho_image, (_SPEC,))
    rendered = render_binary(pools)
    assert struct.unpack_from('<i', rendered, 0)[0] == len(MACHO_STRINGS)
    offset = 4
    for text in MACHO_STRINGS:
        length = struct.unpack_from('<i', rendered, offset)[0]
        assert length == len(text)
        assert rendered[offset + 4:offset + 4 + length] == text
        offset += 4 + length
    assert offset == len(rendered)
