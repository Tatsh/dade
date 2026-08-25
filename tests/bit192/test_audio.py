"""Tests for :mod:`dade.bit192.audio`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from dade.bit192 import audio

if TYPE_CHECKING:
    from pathlib import Path


def test_wrap_wav_header() -> None:
    wav = audio.wrap_wav(b'\x01\x02\x03\x04', rate=8000, channels=1)
    assert wav[:4] == b'RIFF'
    assert wav[8:12] == b'WAVE'
    assert wav[12:16] == b'fmt '
    fmt_size, fmt_tag, channels, rate, _byte_rate, _block, bits = struct.unpack_from(
        '<IHHIIHH', wav, 16)
    assert (fmt_size, fmt_tag, channels, rate, bits) == (16, 1, 1, 8000, 16)
    assert wav[36:40] == b'data'
    assert struct.unpack_from('<I', wav, 40)[0] == 4  # data chunk size
    assert wav.endswith(b'\x01\x02\x03\x04')  # the PCM follows the size field


def test_wrap_wav_truncates_to_block() -> None:
    # 3 bytes of stereo 16-bit (block = 4) -> truncated to 0 frames.
    wav = audio.wrap_wav(b'\x01\x02\x03', channels=2)
    assert struct.unpack_from('<I', wav, 40)[0] == 0  # data chunk truncated away


def test_wrap_raw_file(tmp_path: Path) -> None:
    raw = tmp_path / 'sound.raw'
    raw.write_bytes(b'\x00\x01' * 8)
    out = audio.wrap_raw_file(raw)
    assert out == tmp_path / 'sound.wav'
    assert out.read_bytes()[:4] == b'RIFF'
