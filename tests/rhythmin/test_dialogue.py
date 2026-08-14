"""Tests for :py:mod:`destin.rhythmin.dialogue`."""
from __future__ import annotations

import struct

from destin.rhythmin.dialogue import (
    POOLS,
    PoolSpec,
    empty_pools,
    extract_pools,
    render_binary,
    render_c_header,
)
import pytest

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
