"""Tests for :mod:`dade.xg2.fluidsynth`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import subprocess as sp

from dade.xg2.fluidsynth import find_fluidsynth, render_directory

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture


def test_find_fluidsynth_prefers_the_override(mocker: MockerFixture, tmp_path: Path) -> None:
    which = mocker.patch('dade.xg2.fluidsynth.shutil.which')
    assert find_fluidsynth(tmp_path / 'fs') == str(tmp_path / 'fs')
    which.assert_not_called()


def test_find_fluidsynth_searches_the_path(mocker: MockerFixture) -> None:
    mocker.patch('dade.xg2.fluidsynth.shutil.which', return_value='/usr/bin/fluidsynth')
    assert find_fluidsynth() == '/usr/bin/fluidsynth'


def test_find_fluidsynth_returns_none_when_absent(mocker: MockerFixture) -> None:
    mocker.patch('dade.xg2.fluidsynth.shutil.which', return_value=None)
    assert find_fluidsynth() is None


def test_render_directory_skips_without_fluidsynth(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('dade.xg2.fluidsynth.shutil.which', return_value=None)
    run = mocker.patch('dade.xg2.fluidsynth.sp.run')
    assert render_directory(tmp_path, tmp_path / 'bank.sf2') == 0
    run.assert_not_called()


def test_render_directory_skips_without_a_soundfont(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('dade.xg2.fluidsynth.shutil.which', return_value='/usr/bin/fluidsynth')
    run = mocker.patch('dade.xg2.fluidsynth.sp.run')
    assert render_directory(tmp_path, tmp_path / 'missing.sf2') == 0
    run.assert_not_called()


def test_render_directory_renders_each_midi(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('dade.xg2.fluidsynth.shutil.which', return_value='/usr/bin/fluidsynth')
    soundfont = tmp_path / 'bank.sf2'
    soundfont.write_bytes(b'sf2')
    for name in ('a.mid', 'b.mid'):
        (tmp_path / name).write_bytes(b'MThd')

    def fake_run(command: list[str], **_: object) -> object:
        (tmp_path / command[command.index('-F') + 1]).write_bytes(b'RIFF')
        return mocker.Mock(returncode=0)

    run = mocker.patch('dade.xg2.fluidsynth.sp.run', side_effect=fake_run)
    assert render_directory(tmp_path, soundfont) == 2
    assert run.call_count == 2


def test_render_directory_survives_a_failure(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('dade.xg2.fluidsynth.shutil.which', return_value='/usr/bin/fluidsynth')
    soundfont = tmp_path / 'bank.sf2'
    soundfont.write_bytes(b'sf2')
    (tmp_path / 'a.mid').write_bytes(b'MThd')
    mocker.patch('dade.xg2.fluidsynth.sp.run', side_effect=sp.CalledProcessError(1, 'fluidsynth'))
    assert render_directory(tmp_path, soundfont) == 0


def test_render_directory_survives_a_missing_binary(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('dade.xg2.fluidsynth.shutil.which', return_value='/usr/bin/fluidsynth')
    soundfont = tmp_path / 'bank.sf2'
    soundfont.write_bytes(b'sf2')
    (tmp_path / 'a.mid').write_bytes(b'MThd')
    mocker.patch('dade.xg2.fluidsynth.sp.run', side_effect=OSError)
    assert render_directory(tmp_path, soundfont) == 0


def test_render_directory_skips_a_missing_directory(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('dade.xg2.fluidsynth.shutil.which', return_value='/usr/bin/fluidsynth')
    soundfont = tmp_path / 'bank.sf2'
    soundfont.write_bytes(b'sf2')
    assert render_directory(tmp_path / 'missing', soundfont) == 0


def test_render_directory_ignores_a_midi_that_produced_nothing(mocker: MockerFixture,
                                                               tmp_path: Path) -> None:
    mocker.patch('dade.xg2.fluidsynth.shutil.which', return_value='/usr/bin/fluidsynth')
    soundfont = tmp_path / 'bank.sf2'
    soundfont.write_bytes(b'sf2')
    (tmp_path / 'a.mid').write_bytes(b'MThd')
    mocker.patch('dade.xg2.fluidsynth.sp.run')
    assert render_directory(tmp_path, soundfont) == 0
