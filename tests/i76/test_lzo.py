"""Tests for :py:mod:`destin.i76.lzo`."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from destin.i76.lzo import decompress_record, lzo1x_decompress, lzo1y_decompress

if TYPE_CHECKING:
    from collections.abc import Callable

_EOF_MARKER = b'\x11\x00\x00'
"""Token 17 with a zero 16-bit operand, giving offset 0, which ends a stream."""

_DECODERS = [lzo1x_decompress, lzo1y_decompress]

_PREFIX = b'\x06ABCDEFGHI'
"""A literal-run token of 6, giving nine literal bytes."""


def _literal_run(payload: bytes) -> bytes:
    """
    Encode ``payload`` as a long literal run using the 0x00 continuation form.

    Parameters
    ----------
    payload : bytes
        The literal bytes to emit. Must be at least 18 bytes long.

    Returns
    -------
    bytes
        The encoded run header followed by ``payload``.
    """
    remaining = len(payload) - 3 - 15
    zeros, rest = divmod(remaining, 255)
    if rest == 0:
        zeros, rest = zeros - 1, 255
    return bytes([0]) + b'\x00' * zeros + bytes([rest]) + payload


@pytest.mark.parametrize('flags', [0, 1, 8, 0x100])
def test_decompress_record_stored(flags: int) -> None:
    assert decompress_record(b'\x01\x02\x03', flags) == b'\x01\x02\x03'


@pytest.mark.parametrize('flags', [2, 4])
def test_decompress_record_literal_run(lzo_stream: bytes, flags: int) -> None:
    assert decompress_record(lzo_stream, flags | (4096 << 8)) == b'ABCDEF'


@pytest.mark.parametrize('decompress', _DECODERS)
def test_long_literal_token(decompress: Callable[[bytes, int], bytes]) -> None:
    assert decompress(b'\x1a' + b'123456789' + _EOF_MARKER, 4096) == b'123456789'


@pytest.mark.parametrize('decompress', _DECODERS)
def test_literal_run_continuation(decompress: Callable[[bytes, int], bytes]) -> None:
    # A leading zero token takes the 0x00 continuation path: 15 + 5 + 3 literal bytes.
    assert decompress(b'\x00\x05' + b'x' * 23 + _EOF_MARKER, 4096) == b'x' * 23


def test_variants_differ_on_the_same_stream() -> None:
    # Token 0x60 yields an M2 match of (t >> 5) + 1 == 4 bytes under LZO1X but (t >> 4) - 1 == 5
    # under LZO1Y, which is the whole reason both decoders exist.
    stream = _PREFIX + b'\x60\x00' + _EOF_MARKER
    assert lzo1x_decompress(stream, 4096) == b'ABCDEFGHI' + b'I' * 4
    assert lzo1y_decompress(stream, 4096) == b'ABCDEFGHI' + b'I' * 5


@pytest.mark.parametrize('decompress', _DECODERS)
def test_m3_match(decompress: Callable[[bytes, int], bytes]) -> None:
    # Token 0x21 is M3 with length (0x21 & 31) + 2 == 3 and a zero operand, so the match runs
    # back one byte and repeats the final 'I'.
    assert decompress(_PREFIX + b'\x21\x00\x00' + _EOF_MARKER, 4096) == b'ABCDEFGHI' + b'I' * 3


@pytest.mark.parametrize('decompress', _DECODERS)
def test_m3_long_length(decompress: Callable[[bytes, int], bytes]) -> None:
    # Token 0x20 has a zero length field, taking the 31 + 255 + 5 + 2 continuation path.
    stream = _PREFIX + b'\x20\x00\x05\x00\x00' + _EOF_MARKER
    assert decompress(stream, 4096) == b'ABCDEFGH' + b'I' * 294


@pytest.mark.parametrize('decompress', _DECODERS)
def test_inline_m1_after_trailing_literals(decompress: Callable[[bytes, int], bytes]) -> None:
    # The M3 operand's low two bits are 1, so one trailing literal ('Z') is copied and the next
    # token is taken as an inline M1 match of two bytes.
    stream = _PREFIX + b'\x21\x01\x00Z\x04\x00' + _EOF_MARKER
    assert decompress(stream, 4096) == b'ABCDEFGHI' + b'I' * 3 + b'Z' + b'I' + b'Z'


@pytest.mark.parametrize('decompress', _DECODERS)
def test_literal_run_from_match_state(decompress: Callable[[bytes, int], bytes]) -> None:
    # After the M3 match the operand's low bits are 0, so the next token re-enters the
    # literal-or-match state, where a value below 16 starts another literal run.
    stream = _PREFIX + b'\x21\x00\x00' + b'\x02' + b'12345' + _EOF_MARKER
    assert decompress(stream, 4096) == b'ABCDEFGHI' + b'I' * 3 + b'12345'


def test_post_literal_run_m1_uses_large_base() -> None:
    # The post-literal-run M1 match reaches back past the variant's base, so it needs an output
    # longer than LZO1Y's 0x400.
    payload = bytes(index % 256 for index in range(1100))
    stream = _literal_run(payload) + b'\x04\x00' + _EOF_MARKER
    assert lzo1y_decompress(stream, 8192) == payload + payload[74:77]


def test_m4_match_copies() -> None:
    # An M4 match reaches back 0x4000 plus its operand, so it needs an output past 16 KiB.
    payload = bytes(index % 256 for index in range(16398))
    stream = _literal_run(payload) + b'\x17\x08\x00' + _EOF_MARKER
    assert lzo1x_decompress(stream, 65536) == payload + payload[12:21]


def test_m4_long_length() -> None:
    # Token 0x10 has a zero length field, taking the 7 + 255 + 3 + 2 continuation path.
    payload = bytes(index % 256 for index in range(16398))
    stream = _literal_run(payload) + b'\x10\x00\x03\x08\x00' + _EOF_MARKER
    assert lzo1x_decompress(stream, 65536) == payload + payload[12:12 + 267]


def test_truncated_stream_raises() -> None:
    with pytest.raises(IndexError):
        lzo1x_decompress(b'\x03AB', 4096)


@pytest.mark.parametrize('decompress', _DECODERS)
def test_stream_starting_at_the_end_marker(decompress: Callable[[bytes, int], bytes]) -> None:
    # A leading token of 16 or 17 skips the literal states and goes straight to a match.
    assert decompress(_EOF_MARKER, 4096) == b''
