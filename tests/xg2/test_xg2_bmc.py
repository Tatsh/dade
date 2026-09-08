"""Tests for :mod:`dade.xg2.bmc`."""
from __future__ import annotations

import struct

from dade.xg2.bmc import BMC_HEADER_SIZE, BMC_MAGIC, CHANNEL_HEADER_SIZE, demo, parse_bmc

_NAME_SIZE = 12


def _header(frames: int, channels: int, name: str = 'walk.asf') -> bytes:
    head = BMC_MAGIC + name.encode().ljust(_NAME_SIZE, b'\x00')
    head += struct.pack('>4H', frames, frames, 0x7800, channels)
    return head.ljust(BMC_HEADER_SIZE, b'\x00')


def test_demo_holds() -> None:
    demo()


def test_parse_bmc_reads_quantised_channels() -> None:
    frames = 4
    first = struct.pack('>H2h', CHANNEL_HEADER_SIZE + frames, 0, 255) + bytes((0, 85, 170, 255))
    # The last record carries a zero length and runs to the end.
    last = struct.pack('>H2h', 0, -100, 100) + bytes((0, 128, 255, 0))
    clip = parse_bmc(_header(frames, 2) + first + last)
    assert clip is not None
    assert clip.name == 'walk.asf'
    assert clip.frames == frames
    assert [round(v) for v in clip.channels[0]] == [0, 85, 170, 255]
    assert round(clip.channels[1][0]) == -100
    assert round(clip.channels[1][2]) == 100


def test_parse_bmc_rejects_the_wrong_magic() -> None:
    assert parse_bmc(b'JUNK' + b'\x00' * 0x40) is None


def test_parse_bmc_of_zero_frames() -> None:
    clip = parse_bmc(_header(0, 0))
    assert clip is not None
    assert clip.frames == 0
    assert clip.channels == []


def test_parse_bmc_rejects_an_undersized_record() -> None:
    assert parse_bmc(_header(4, 1) + struct.pack('>H', 3)) is None


def test_parse_bmc_rejects_a_truncated_stored_record() -> None:
    assert parse_bmc(_header(4, 1) + struct.pack('>H', 6) + b'\x00' * 4) is None
