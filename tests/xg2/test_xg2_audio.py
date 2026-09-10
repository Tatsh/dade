"""Tests for :mod:`dade.xg2.vadpcm`, :mod:`dade.xg2.bmc`, and :mod:`dade.xg2.wav`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from dade.xg2.bmc import BMC_HEADER_SIZE, BMC_MAGIC, parse_bmc
from dade.xg2.vadpcm import FRAME_SIZE, decode_vadpcm, find_table_base, read_codebook
from dade.xg2.wav import pcm_to_bytes, wrap_wav, write_wav, write_wav16

if TYPE_CHECKING:
    from pathlib import Path


def test_decode_vadpcm_frame_length() -> None:
    coefficients = [0] * (2 * 4 * 8)
    assert len(decode_vadpcm(b'\x00' * (FRAME_SIZE * 3), coefficients, 2, 4)) == 48


def test_decode_vadpcm_ignores_a_partial_frame() -> None:
    coefficients = [0] * (2 * 4 * 8)
    assert decode_vadpcm(b'\x00' * (FRAME_SIZE - 1), coefficients, 2, 4) == []


def test_decode_vadpcm_zero_codebook_gives_silence() -> None:
    coefficients = [0] * (2 * 4 * 8)
    assert decode_vadpcm(b'\x00' * FRAME_SIZE, coefficients, 2, 4) == [0] * 16


def test_decode_vadpcm_scales_the_residual() -> None:
    coefficients = [0] * (2 * 4 * 8)
    # A scaling shift of zero yields a residual of one at unity after the Q11 shift back.
    frame = bytes([0x00, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    assert decode_vadpcm(frame, coefficients, 2, 4)[0] == 1


def test_decode_vadpcm_applies_the_scaling_shift() -> None:
    coefficients = [0] * (2 * 4 * 8)
    frame = bytes([0x30, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    assert decode_vadpcm(frame, coefficients, 2, 4)[0] == 8


def test_decode_vadpcm_clamps_out_of_range_predictor() -> None:
    coefficients = [0] * (2 * 4 * 8)
    assert decode_vadpcm(bytes([0x0F, *([0] * 8)]), coefficients, 2, 4) == [0] * 16


def test_read_codebook() -> None:
    rom = b'\x00' * 8 + struct.pack('>8h', 1, -2, 3, -4, 5, -6, 7, -8)
    assert read_codebook(rom, 0, 1, 1) == [1, -2, 3, -4, 5, -6, 7, -8]


def test_read_codebook_honours_the_base() -> None:
    rom = b'\xff' * 4 + b'\x00' * 8 + struct.pack('>8h', *range(8))
    assert read_codebook(rom, 4, 1, 1) == list(range(8))


def test_find_table_base_locates_valid_frames() -> None:
    rom = bytearray(b'\xff' * 0x100)
    rom[0x40:0x40 + FRAME_SIZE * 3] = b'\x00' * (FRAME_SIZE * 3)
    assert find_table_base(bytes(rom), 0, [(0, FRAME_SIZE * 3)], 4) == 0x40


def test_find_table_base_gives_up() -> None:
    assert find_table_base(b'\xff' * 0x100, 0, [(0, FRAME_SIZE * 2)], 4) is None


def _clip(frames: int, *channels: bytes) -> bytes:
    """
    Build a ``BMC`` clip around ready-made channel records.

    Returns
    -------
    bytes
        The blob.
    """
    header = BMC_MAGIC + b'walk.asf'.ljust(12, b'\x00')
    return header + struct.pack('>4H', frames, frames, 0x7800, len(channels)) + b''.join(channels)


def test_parse_bmc_reads_the_name_and_frame_count() -> None:
    clip = parse_bmc(_clip(2, struct.pack('>H2h', 0, 0, 255) + b'\x00\xff'))
    assert clip is not None
    assert clip.name == 'walk.asf'
    assert clip.frames == 2


def test_parse_bmc_rescales_a_quantised_channel() -> None:
    # An eight-bit channel spans its two bounds; 0 and 255 land on them exactly.
    clip = parse_bmc(_clip(2, struct.pack('>H2h', 0, -100, 100) + b'\x00\xff'))
    assert clip is not None
    assert [round(v) for v in clip.channels[0]] == [-100, 100]


def test_parse_bmc_reads_a_raw_channel() -> None:
    # A record whose length is frames * 2 + 2 has signed halfwords instead.
    raw = struct.pack('>H3h', 2 + 3 * 2, 1000, -1000, 7)
    quantised = struct.pack('>H2h', 0, 0, 0) + b'\x00\x00\x00'
    clip = parse_bmc(_clip(3, raw, quantised))
    assert clip is not None
    assert clip.channels[0] == [1000.0, -1000.0, 7.0]


def test_parse_bmc_takes_a_zero_length_as_the_last_channel() -> None:
    first = struct.pack('>H2h', BMC_HEADER_SIZE // 4 + 2, 0, 255) + b'\x00\xff'
    clip = parse_bmc(_clip(2, first, struct.pack('>H2h', 0, 0, 255) + b'\xff\x00'))
    assert clip is not None
    assert len(clip.channels) == 2
    assert [round(v) for v in clip.channels[1]] == [255, 0]


def test_parse_bmc_rejects_other_data() -> None:
    assert parse_bmc(b'shaw' + b'\x00' * 32) is None


def test_pcm_to_bytes_clamps() -> None:
    assert pcm_to_bytes([40000, -40000]) == struct.pack('<2h', 32767, -32768)


def test_wrap_wav_header() -> None:
    wav = wrap_wav(b'\x01\x02\x03\x04', rate=8000)
    assert wav[:4] == b'RIFF'
    assert wav[8:12] == b'WAVE'
    size, tag, channels, rate, _, _, bits = struct.unpack_from('<IHHIIHH', wav, 16)
    assert (size, tag, channels, rate, bits) == (16, 1, 1, 8000, 16)
    assert wav[36:40] == b'data'
    assert wav.endswith(b'\x01\x02\x03\x04')


def test_wrap_wav_reports_its_sizes() -> None:
    wav = wrap_wav(b'\x00' * 10)
    assert struct.unpack_from('<I', wav, 4)[0] == 36 + 10
    assert struct.unpack_from('<I', wav, 40)[0] == 10


def test_write_wav(tmp_path: Path) -> None:
    path = tmp_path / 'out.wav'
    write_wav(path, b'\x01\x02')
    assert path.read_bytes() == wrap_wav(b'\x01\x02')


def test_write_wav16(tmp_path: Path) -> None:
    path = tmp_path / 'out.wav'
    write_wav16(path, [1, -1], 22050)
    assert path.read_bytes().endswith(struct.pack('<2h', 1, -1))
