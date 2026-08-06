"""Tests for :mod:`destin.xg2.mfs`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from destin.xg2.mfs import MfsCalibrationError, calibrate_base, iter_files, read_table
from destin.xg2.offsets import XG1_MFS_COUNT, XG1_MFS_TABLE
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

_RECORD_SIZE = 0x10
_FIRST = 0x100


def _build_rom(payloads: list[bytes],
               make_lzss: Callable[[bytes], bytes],
               *,
               slack: int = 0) -> bytes:
    """Build a ROM whose mfs directory is consistent with its file data."""
    streams = [make_lzss(p) for p in payloads]
    table_end = XG1_MFS_TABLE + len(payloads) * _RECORD_SIZE
    base = table_end - _FIRST
    rom = bytearray(base + _FIRST + sum(len(s) + slack for s in streams) + 0x100)
    struct.pack_into('>III', rom, XG1_MFS_COUNT, len(payloads), 0, _FIRST)
    start = _FIRST
    for i, (payload, stream) in enumerate(zip(payloads, streams, strict=True)):
        offset = XG1_MFS_TABLE + i * _RECORD_SIZE
        rom[offset:offset + 4] = b'LZSS'
        end = start + len(stream) + slack
        struct.pack_into('>III', rom, offset + 4, len(payload), len(stream), end)
        rom[base + start:base + start + len(stream)] = stream
        start = end
    return bytes(rom)


def test_read_table(make_lzss: Callable[[bytes], bytes]) -> None:
    rom = _build_rom([b'alpha', b'beta'], make_lzss)
    first, entries = read_table(rom)
    assert first == _FIRST
    assert len(entries) == 2
    assert entries[0].decompressed_size == 5
    assert entries[1].decompressed_size == 4


def test_read_table_rejects_a_missing_magic(make_lzss: Callable[[bytes], bytes]) -> None:
    rom = bytearray(_build_rom([b'alpha'], make_lzss))
    rom[XG1_MFS_TABLE:XG1_MFS_TABLE + 4] = b'ZZZZ'
    with pytest.raises(ValueError, match='missing its LZSS magic'):
        read_table(bytes(rom))


def test_calibrate_base_finds_the_archive(make_lzss: Callable[[bytes], bytes]) -> None:
    rom = _build_rom([b'alpha', b'beta'], make_lzss)
    first, entries = read_table(rom)
    base, starts = calibrate_base(rom, first, entries)
    assert base == XG1_MFS_TABLE + len(entries) * _RECORD_SIZE - _FIRST
    assert starts[0] == _FIRST


def test_calibrate_base_gives_up_on_rubbish(make_lzss: Callable[[bytes], bytes]) -> None:
    rom = bytearray(_build_rom([b'alpha', b'beta'], make_lzss))
    # Demand far more output than the ROM can supply, so every candidate base runs off the end.
    struct.pack_into('>I', rom, XG1_MFS_TABLE + 4, 0xFFFFFF)
    first, entries = read_table(bytes(rom))
    with pytest.raises(MfsCalibrationError):
        calibrate_base(bytes(rom), first, entries)


def test_iter_files_round_trips(make_lzss: Callable[[bytes], bytes]) -> None:
    payloads = [b'alpha', b'beta', b'gamma!!']
    rom = _build_rom(payloads, make_lzss)
    assert [data for _, _, _, data in iter_files(rom)] == payloads


def test_iter_files_reports_offsets(make_lzss: Callable[[bytes], bytes]) -> None:
    rom = _build_rom([b'alpha', b'beta'], make_lzss)
    indices = [index for index, _, _, _ in iter_files(rom)]
    offsets = [offset for _, offset, _, _ in iter_files(rom)]
    assert indices == [0, 1]
    assert offsets[1] > offsets[0]


def test_iter_files_tolerates_padding(make_lzss: Callable[[bytes], bytes]) -> None:
    payloads = [b'alpha', b'beta']
    assert [data
            for _, _, _, data in iter_files(_build_rom(payloads, make_lzss, slack=3))] == payloads
