from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

from dade.common.exceptions import InvalidFormatError
from dade.sopranos.audio import (
    VOICE_RATE,
    convert_bank,
    convert_stream,
    convert_voice,
    decode_stream,
    read_sound_bank,
    read_stream_header,
    read_voice_adpcm,
)

if TYPE_CHECKING:
    from pathlib import Path

_FRAME = bytes([0x00, 0x00, *([0x11] * 14)])
"""One PS-ADPCM frame: shift and filter nibble, a flag byte, then fourteen sample bytes."""


def build_bank_header(entries: list[tuple[int, int, int, int]]) -> bytes:
    """
    Build a ``.MSH`` sound bank header.

    Parameters
    ----------
    entries : list[tuple[int, int, int, int]]
        Each as ``(size, identifier, offset, rate)``.

    Returns
    -------
    bytes
        The whole header.
    """
    return bytes(8) + struct.pack('<I', len(entries)) + b''.join(
        struct.pack('<4I', *entry) for entry in entries)


def build_voice(blocks: list[bytes], *, tag: bytes = b'AUDO') -> bytes:
    """
    Build a ``.VO2`` dialogue file.

    Parameters
    ----------
    blocks : list[bytes]
        The PS-ADPCM payload of each block.
    tag : bytes
        Chunk tag, so a test may write a block the reader should ignore.

    Returns
    -------
    bytes
        The whole file.
    """
    out = bytearray()
    for payload in blocks:
        total = 64 + len(payload)
        out += tag + bytes(4) + struct.pack('<I', total) + bytes(4) + bytes(48) + payload
    return bytes(out)


def test_read_sound_bank_keeps_only_playable_entries() -> None:
    header = build_bank_header([(0, 0, 0, 22050), (16, 7, 0, 22050), (16, 8, 16, 0)])
    entries = read_sound_bank(header)
    assert [(e.number, e.identifier, e.rate) for e in entries] == [(0, 7, 22050)]


def test_read_sound_bank_rejects_a_tiny_header() -> None:
    with pytest.raises(InvalidFormatError, match='too small'):
        read_sound_bank(b'abc')


def test_read_sound_bank_rejects_a_count_it_cannot_hold() -> None:
    with pytest.raises(InvalidFormatError, match='declares 99 entries'):
        read_sound_bank(bytes(8) + struct.pack('<I', 99))


def test_convert_bank_writes_a_wav_per_sound(tmp_path: Path) -> None:
    header = tmp_path / 'bank.msh'
    body = tmp_path / 'bank.msb'
    header.write_bytes(build_bank_header([(len(_FRAME), 1, 0, 22050)]))
    body.write_bytes(_FRAME)
    written = convert_bank(header, body, tmp_path / 'out')
    assert [path.name for path in written] == ['bank_000.wav']
    assert written[0].read_bytes().startswith(b'RIFF')


def test_convert_bank_warns_about_a_sound_past_the_end(tmp_path: Path,
                                                       caplog: pytest.LogCaptureFixture) -> None:
    header = tmp_path / 'bank.msh'
    body = tmp_path / 'bank.msb'
    header.write_bytes(build_bank_header([(16, 1, 999, 22050)]))
    body.write_bytes(_FRAME)
    with caplog.at_level('WARNING'):
        assert convert_bank(header, body, tmp_path / 'out') == ()
    assert 'past the end of the body' in caplog.text


def test_read_voice_adpcm_keeps_only_audio_payloads() -> None:
    assert read_voice_adpcm(build_voice([_FRAME, _FRAME])) == _FRAME * 2


def test_read_voice_adpcm_skips_blocks_that_are_not_audio() -> None:
    assert read_voice_adpcm(build_voice([_FRAME], tag=b'LSYN')) == b''


def test_read_voice_adpcm_ignores_a_block_that_overruns() -> None:
    raw = bytearray(build_voice([_FRAME]))
    struct.pack_into('<I', raw, 8, 0xFFFF)
    assert read_voice_adpcm(bytes(raw)) == b''


def test_read_voice_adpcm_ignores_a_block_with_no_payload() -> None:
    raw = bytearray(build_voice([_FRAME]))
    struct.pack_into('<I', raw, 8, 8)
    assert read_voice_adpcm(bytes(raw)) == b''


def test_convert_voice_writes_a_wav(tmp_path: Path) -> None:
    source = tmp_path / 'line.vo2'
    source.write_bytes(build_voice([_FRAME]))
    written = convert_voice(source, tmp_path / 'out' / 'line.wav')
    assert written is not None
    assert written.read_bytes().startswith(b'RIFF')


def test_convert_voice_writes_nothing_without_audio(tmp_path: Path) -> None:
    source = tmp_path / 'line.vo2'
    source.write_bytes(build_voice([_FRAME], tag=b'LSYN'))
    assert convert_voice(source, tmp_path / 'out' / 'line.wav') is None


def test_voice_rate_is_the_discs_rate() -> None:
    assert VOICE_RATE == 48000


def test_read_stream_header_reads_the_layout() -> None:
    header = bytes(8) + struct.pack('<4I', 2, 44100, 0x4000, 12)
    assert read_stream_header(header) == (2, 44100, 0x4000, 12)


def test_read_stream_header_rejects_a_tiny_header() -> None:
    with pytest.raises(InvalidFormatError, match='too small'):
        read_stream_header(b'abc')


@pytest.mark.parametrize(('channels', 'interleave'), [(0, 0x4000), (9, 0x4000), (2, 0)])
def test_read_stream_header_rejects_an_unusable_layout(*, channels: int, interleave: int) -> None:
    header = bytes(8) + struct.pack('<4I', channels, 44100, interleave, 1)
    with pytest.raises(InvalidFormatError, match='declares'):
        read_stream_header(header)


def test_decode_stream_passes_a_single_channel_through() -> None:
    assert decode_stream(_FRAME, 1, 16) == decode_stream(_FRAME, 1, 16)
    assert len(decode_stream(_FRAME, 1, 16)) == 28 * 2


def test_decode_stream_interleaves_two_channels() -> None:
    pcm = decode_stream(_FRAME + _FRAME, 2, 16)
    # Twenty-eight frames per channel, two channels, two bytes a sample.
    assert len(pcm) == 28 * 2 * 2


def test_convert_stream_writes_a_wav(tmp_path: Path) -> None:
    header = tmp_path / 'song.mih'
    body = tmp_path / 'song.mib'
    header.write_bytes(bytes(8) + struct.pack('<4I', 1, 44100, 16, 1))
    body.write_bytes(_FRAME)
    written = convert_stream(header, body, tmp_path / 'out' / 'song.wav')
    assert written.read_bytes().startswith(b'RIFF')
