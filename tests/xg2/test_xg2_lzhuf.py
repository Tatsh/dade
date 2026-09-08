"""Tests for :mod:`dade.xg2.lzhuf`."""
from __future__ import annotations

import pytest

from dade.xg2.lzhuf import (
    POSITION_CODES,
    POSITION_LENGTHS,
    LzhufError,
    decompress_lzhuf,
    demo,
)


def test_demo_holds() -> None:
    demo()


def test_position_tables_cover_every_byte() -> None:
    assert len(POSITION_CODES) == 256
    assert len(POSITION_LENGTHS) == 256
    assert POSITION_CODES[0] == 0
    assert POSITION_CODES[-1] == 0x3F
    assert set(POSITION_LENGTHS) == {3, 4, 5, 6, 7, 8}


def test_decompress_produces_the_declared_size() -> None:
    assert len(decompress_lzhuf(b'\x00' * 0x400, 0, 64)) == 64


def test_decompress_honours_the_fill_byte() -> None:
    assert len(decompress_lzhuf(b'\xff' * 0x400, 0, 32, fill=0x20)) == 32


def test_decompress_raises_when_the_stream_runs_out() -> None:
    with pytest.raises(LzhufError, match='short of'):
        decompress_lzhuf(b'', 0, 1)


def test_decompress_of_a_zero_size_is_empty() -> None:
    assert decompress_lzhuf(b'\x00' * 16, 0, 0) == b''
