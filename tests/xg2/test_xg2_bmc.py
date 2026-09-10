"""Tests for :mod:`dade.xg2.bmc`."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import runpy
import struct

import pytest

from dade.common.exceptions import SelfCheckFailed
from dade.xg2 import bmc
from dade.xg2.bmc import BMC_HEADER_SIZE, BMC_MAGIC, CHANNEL_HEADER_SIZE, BmcClip, demo, parse_bmc

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

_MODULE_PATH = str(Path(bmc.__file__))
_NAME_SIZE = 12
_GOOD_CLIP = BmcClip('walk.asf', 4, [[0.0, 85.0, 170.0, 255.0], [-100.0, 0.0, 100.0, 0.0]])


def _header(frames: int, channels: int, name: str = 'walk.asf') -> bytes:
    head = BMC_MAGIC + name.encode().ljust(_NAME_SIZE, b'\x00')
    head += struct.pack('>4H', frames, frames, 0x7800, channels)
    return head.ljust(BMC_HEADER_SIZE, b'\x00')


def test_demo_holds() -> None:
    demo()


def test_module_entry_point_runs(capsys: pytest.CaptureFixture[str]) -> None:
    runpy.run_path(_MODULE_PATH, run_name='__main__')
    assert 'both channel encodings decode' in capsys.readouterr().out


@pytest.mark.parametrize(
    ('clip', 'match'),
    [(None, 'did not parse'), (_GOOD_CLIP._replace(name='bad'), 'expected walk.asf'),
     (_GOOD_CLIP._replace(frames=3), 'expected 4'),
     (_GOOD_CLIP._replace(channels=[[0.0, 85.0, 170.0, 255.0]]), 'expected 2'),
     (_GOOD_CLIP._replace(channels=[[1.0, 2.0, 3.0, 4.0], [-100.0, 0.0, 100.0, 0.0]]),
      'expected 0, 85, 170, 255'),
     (_GOOD_CLIP._replace(channels=[[0.0, 85.0, 170.0, 255.0], [0.0, 0.0, 100.0, 0.0]]),
      'expected -100'),
     (_GOOD_CLIP._replace(channels=[[0.0, 85.0, 170.0, 255.0], [-100.0, 0.0, 0.0, 0.0]]),
      'expected 100'), (_GOOD_CLIP, 'wrong magic parsed')])
def test_demo_reports_a_broken_clip(mocker: MockerFixture, clip: BmcClip | None,
                                    match: str) -> None:
    mocker.patch('dade.xg2.bmc.parse_bmc', return_value=clip)
    with pytest.raises(SelfCheckFailed, match=match):
        demo()


def test_parse_bmc_reads_quantised_channels() -> None:
    frames = 4
    first = struct.pack('>H2h', CHANNEL_HEADER_SIZE + frames, 0, 255) + bytes((0, 85, 170, 255))
    # The last record has a zero length and runs to the end.
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
