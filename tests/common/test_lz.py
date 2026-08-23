"""Tests for :mod:`destin.common.lz`."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from destin.common.lz import RING_SIZE, RING_START, decompress_lzss0

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.mark.parametrize('payload', [b'\x00', b'abcdefgh', b'abcdefghi', bytes(range(256)) * 2])
def test_decompress_literals(make_lzss: Callable[[bytes], bytes], payload: bytes) -> None:
    out, consumed = decompress_lzss0(make_lzss(payload), 0, len(payload))
    assert out == payload
    assert consumed == len(payload) + (len(payload) + 7) // 8


def test_decompress_stops_at_requested_size(make_lzss: Callable[[bytes], bytes]) -> None:
    stream = make_lzss(b'abcdefghijklmnop')
    assert decompress_lzss0(stream, 0, 4) == (b'abcd', 5)


def test_decompress_back_reference() -> None:
    # One literal 'A', then a match of three bytes taken from the zero-filled ring.
    stream = bytes([0b00000001, ord('A'), 0x00, 0x00])
    out, _ = decompress_lzss0(stream, 0, 4)
    assert out == b'A\x00\x00\x00'


def test_decompress_repeats_recent_output() -> None:
    # Four literals, then a match pointing at the ring position they were written to.
    literals = b'ABCD'
    offset = RING_START
    stream = bytes([0b00001111, *literals, ((offset >> 4) & 0xF0) | 0x01, offset & 0xFF])
    out, _ = decompress_lzss0(stream, 0, 8)
    assert out[:4] == literals


def test_decompress_honours_start_offset(make_lzss: Callable[[bytes], bytes]) -> None:
    stream = b'\xde\xad' + make_lzss(b'xyz')
    out, consumed = decompress_lzss0(stream, 2, 3)
    assert out == b'xyz'
    assert consumed == 4


def test_decompress_raises_when_stream_runs_out() -> None:
    with pytest.raises(IndexError):
        decompress_lzss0(b'\xff\x01', 0, 8)


def test_ring_constants() -> None:
    assert RING_SIZE == 0x1000
    assert RING_START == 0xFEE
