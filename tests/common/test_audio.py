"""Tests for :py:mod:`dade.common.audio`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import subprocess as sp

import pytest

from dade.common.audio import CAF_MAGIC, M4A_MAGIC, is_m4a, to_wav

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture


def test_the_magics_are_the_documented_ones() -> None:
    assert M4A_MAGIC == b'ftyp'
    assert CAF_MAGIC == b'caff'


def test_an_mpeg_four_container_is_recognised() -> None:
    assert is_m4a(bytes(4) + b'ftypM4A ' + bytes(8))


def test_a_core_audio_file_is_not_mpeg_four() -> None:
    assert not is_m4a(CAF_MAGIC + bytes(16))


def test_a_short_buffer_is_not_mpeg_four() -> None:
    assert not is_m4a(b'')
    assert not is_m4a(b'ftyp')


def test_to_wav_calls_ffmpeg_with_both_paths(tmp_path: Path, mocker: MockerFixture) -> None:
    run = mocker.patch('dade.common.audio.sp.run')
    source = tmp_path / 'in.caf'
    destination = tmp_path / 'out.wav'
    assert to_wav(source, destination, tmp_path / 'ffmpeg') == destination
    args = run.call_args[0][0]
    assert str(source) in args
    assert str(destination) in args
    assert '-i' in args


def test_to_wav_lets_a_failure_through(tmp_path: Path, mocker: MockerFixture) -> None:
    mocker.patch('dade.common.audio.sp.run', side_effect=sp.CalledProcessError(1, 'ffmpeg'))
    with pytest.raises(sp.CalledProcessError):
        to_wav(tmp_path / 'in.caf', tmp_path / 'out.wav', tmp_path / 'ffmpeg')
