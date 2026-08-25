"""Tests for :mod:`dade.xg2.archive`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

from dade.xg2.archive import (
    decode_entries,
    decode_entry,
    is_archive,
    parse_archive,
    try_sized_lzss,
)
from dade.xg2.lzhuf import LzhufUnavailableError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


def test_parse_archive_reads_records(make_archive: Callable[..., bytes]) -> None:
    blob = make_archive([(b'COPY', b'first'), (b'COPY', b'second')])
    entries = parse_archive(blob)
    assert [e['index'] for e in entries] == [0, 1]
    assert [e['codec'] for e in entries] == ['COPY', 'COPY']
    assert [e['decompressed_size'] for e in entries] == [5, 6]
    assert blob[entries[0]['absolute']:entries[0]['absolute'] + 5] == b'first'


def test_parse_archive_little_endian_reverses_tags(make_archive: Callable[..., bytes]) -> None:
    blob = make_archive([(b'COPY', b'data')], '<')
    assert parse_archive(blob, 0, '<')[0]['codec'] == 'COPY'


def test_parse_archive_falls_back_to_decompressed_size(make_archive: Callable[..., bytes]) -> None:
    blob = bytearray(make_archive([(b'COPY', b'abcd')]))
    struct.pack_into('>I', blob, 8 + 12, 0)  # Zero the compressed size.
    assert parse_archive(bytes(blob))[0]['compressed_size'] == 4


def test_parse_archive_honours_base(make_archive: Callable[..., bytes]) -> None:
    blob = b'\x00' * 16 + make_archive([(b'COPY', b'xyz')])
    entry = parse_archive(blob, 16)[0]
    assert blob[entry['absolute']:entry['absolute'] + 3] == b'xyz'


@pytest.mark.parametrize('tag', [b'COPY', b'BIN\x00', b'NONE'])
def test_decode_entry_copies(make_archive: Callable[..., bytes], tag: bytes) -> None:
    blob = make_archive([(tag, b'payload')])
    assert decode_entry(blob, parse_archive(blob)[0]) == b'payload'


def test_decode_entry_lzss(make_archive: Callable[..., bytes], make_lzss: Callable[[bytes],
                                                                                   bytes]) -> None:
    blob = make_archive([(b'LZSS', make_lzss(b'hello world'))])
    entry = parse_archive(blob)[0]
    entry['decompressed_size'] = 11
    assert decode_entry(blob, entry) == b'hello world'


def test_decode_entry_lzhuf_raises(make_archive: Callable[..., bytes]) -> None:
    blob = make_archive([(b'LHUF', b'payload')])
    with pytest.raises(LzhufUnavailableError):
        decode_entry(blob, parse_archive(blob)[0])


def test_decode_entry_rejects_unknown_codec(make_archive: Callable[..., bytes]) -> None:
    blob = make_archive([(b'ZZZZ', b'payload')])
    with pytest.raises(ValueError, match='Unknown XG2Arch codec'):
        decode_entry(blob, parse_archive(blob)[0])


def test_decode_entries_skips_lzhuf(make_archive: Callable[..., bytes]) -> None:
    blob = make_archive([(b'COPY', b'kept'), (b'LHUF', b'lost'), (b'COPY', b'also')])
    decoded = [(e['index'], b) for e, b in decode_entries(blob, parse_archive(blob))]
    assert decoded == [(0, b'kept'), (2, b'also')]


def test_decode_entries_logs_the_skip(make_archive: Callable[..., bytes],
                                      caplog: pytest.LogCaptureFixture) -> None:
    blob = make_archive([(b'LHUF', b'lost')])
    with caplog.at_level('WARNING'):
        assert list(decode_entries(blob, parse_archive(blob))) == []
    assert 'LHUF codec is not implemented' in caplog.text


def test_decode_entries_skips_undecodable(make_archive: Callable[..., bytes]) -> None:
    blob = make_archive([(b'ZZZZ', b'bad')])
    assert list(decode_entries(blob, parse_archive(blob))) == []


def test_is_archive_accepts_a_container(make_archive: Callable[..., bytes]) -> None:
    assert is_archive(make_archive([(b'LZSS', b'0123456789')]))


@pytest.mark.parametrize('data', [b'', b'\x00' * 8, b'\x01' + b'\x00' * 32])
def test_is_archive_rejects_other_data(data: bytes) -> None:
    assert not is_archive(data)


def test_is_archive_rejects_wrong_endianness(make_archive: Callable[..., bytes]) -> None:
    assert not is_archive(make_archive([(b'LZSS', b'0123456789')]), '<')


def test_try_sized_lzss_round_trip() -> None:
    # Eight maximum-length matches against the zero-filled ring: 17 bytes in, 144 out.
    stream = bytes([0x00]) + bytes([0x00, 0x0F]) * 8
    assert try_sized_lzss(struct.pack('<I', 144) + stream) == b'\x00' * 144


def test_try_sized_lzss_rejects_a_stream_that_does_not_expand(
        make_lzss: Callable[[bytes], bytes]) -> None:
    payload = bytes(range(64))
    assert try_sized_lzss(struct.pack('<I', len(payload)) + make_lzss(payload)) is None


@pytest.mark.parametrize('data', [b'', b'\x04\x00\x00\x00', b'\x02\x00\x00\x00abcdefgh'])
def test_try_sized_lzss_rejects_other_data(data: bytes) -> None:
    assert try_sized_lzss(data) is None


def test_try_sized_lzss_rejects_a_truncated_stream() -> None:
    assert try_sized_lzss(struct.pack('<I', 4096) + b'\xff\x01\x02') is None


def test_round_trip_through_both_byte_orders(make_archive: Callable[..., bytes]) -> None:
    payloads: Sequence[tuple[bytes, bytes]] = [(b'COPY', b'one'), (b'COPY', b'two')]
    for endian in ('>', '<'):
        blob = make_archive(payloads, endian)
        decoded = [b for _, b in decode_entries(blob, parse_archive(blob, 0, endian))]
        assert decoded == [b'one', b'two']


def test_try_sized_lzss_rejects_a_stream_running_past_the_end() -> None:
    # Eight literal flags with only three literals behind them.
    assert try_sized_lzss(struct.pack('<I', 4096) + b'\xff\x01\x02\x03') is None
