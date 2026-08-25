from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dade.common.wav import pcm16_to_bytes, wrap_pcm, write_pcm

if TYPE_CHECKING:
    from pathlib import Path


def test_pcm16_to_bytes_clamps() -> None:
    assert pcm16_to_bytes([0, 40000, -40000, 100]) == b'\x00\x00\xff\x7f\x00\x80d\x00'


def test_wrap_pcm_header() -> None:
    out = wrap_pcm(b'\x01\x02\x03\x04', rate=22050, channels=1, bits=16)
    assert out[:4] == b'RIFF'
    assert out[8:12] == b'WAVE'
    assert out[12:16] == b'fmt '
    assert out.endswith(b'\x01\x02\x03\x04')
    assert len(out) == 44 + 4


@pytest.mark.parametrize(('channels', 'bits'), [(1, 16), (2, 16), (2, 8)])
def test_wrap_pcm_block_align(channels: int, bits: int) -> None:
    out = wrap_pcm(b'\x00' * 16, rate=44100, channels=channels, bits=bits)
    block_align = int.from_bytes(out[32:34], 'little')
    assert block_align == channels * bits // 8


def test_write_pcm(tmp_path: Path) -> None:
    dest = tmp_path / 'out.wav'
    write_pcm(dest, b'\x05\x06', rate=8000, channels=1, bits=16)
    assert dest.read_bytes() == wrap_pcm(b'\x05\x06', rate=8000, channels=1, bits=16)
