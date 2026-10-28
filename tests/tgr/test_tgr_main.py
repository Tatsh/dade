from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import runpy

import pytest

from dade.common.exceptions import InvalidFormatError
from dade.common.tools import ToolNotFoundError
from dade.tgr.main import tgr

if TYPE_CHECKING:
    from click.testing import CliRunner
    from pytest_mock import MockerFixture

_FFMPEG = Path('/usr/bin/ffmpeg')


@pytest.mark.parametrize('suffix', ['.z64', '.V64', '.n64'])
def test_extract_routes_cartridges(runner: CliRunner, mocker: MockerFixture, tmp_path: Path,
                                   suffix: str) -> None:
    rom = tmp_path / f'game{suffix}'
    rom.write_bytes(b'rom')
    mocker.patch('dade.tgr.main.locate_tool', return_value=_FFMPEG)
    extract_rom = mocker.patch('dade.tgr.main.extract_rom')
    extract_disc = mocker.patch('dade.tgr.main.extract_disc')
    result = runner.invoke(tgr, ['extract', str(rom), '-o', str(tmp_path / 'out')])
    assert result.exit_code == 0
    extract_rom.assert_called_once_with(rom, tmp_path / 'out' / 'n64', _FFMPEG)
    extract_disc.assert_not_called()


def test_extract_routes_discs(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    image = tmp_path / 'disc.iso'
    image.write_bytes(b'iso')
    locate_tool = mocker.patch('dade.tgr.main.locate_tool', return_value=_FFMPEG)
    extract_disc = mocker.patch('dade.tgr.main.extract_disc')
    result = runner.invoke(tgr, [
        'extract',
        str(tmp_path),
        str(image), '-o',
        str(tmp_path / 'out'), '--ffmpeg-path',
        str(image)
    ])
    assert result.exit_code == 0
    locate_tool.assert_called_once_with('ffmpeg', image)
    assert [c.args
            for c in extract_disc.call_args_list] == [(tmp_path, tmp_path / 'out' / 'pc', _FFMPEG),
                                                      (image, tmp_path / 'out' / 'pc', _FFMPEG)]


def test_extract_no_audio(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    locate_tool = mocker.patch('dade.tgr.main.locate_tool')
    extract_disc = mocker.patch('dade.tgr.main.extract_disc')
    result = runner.invoke(tgr, ['extract', str(tmp_path), '--no-audio'])
    assert result.exit_code == 0
    locate_tool.assert_not_called()
    extract_disc.assert_called_once_with(tmp_path, Path('pc'), None)


def test_extract_without_ffmpeg_warns(runner: CliRunner, mocker: MockerFixture, tmp_path: Path,
                                      caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch('dade.tgr.main.locate_tool', side_effect=ToolNotFoundError('No ffmpeg.'))
    extract_disc = mocker.patch('dade.tgr.main.extract_disc')
    result = runner.invoke(tgr, ['extract', str(tmp_path)])
    assert result.exit_code == 0
    extract_disc.assert_called_once_with(tmp_path, Path('pc'), None)
    assert 'No ffmpeg. The audio is skipped.' in caplog.text


def test_extract_invalid_format_aborts(runner: CliRunner, mocker: MockerFixture,
                                       tmp_path: Path) -> None:
    rom = tmp_path / 'game.z64'
    rom.write_bytes(b'rom')
    mocker.patch('dade.tgr.main.locate_tool', return_value=_FFMPEG)
    mocker.patch('dade.tgr.main.extract_rom', side_effect=InvalidFormatError('Bad image.'))
    result = runner.invoke(tgr, ['extract', str(rom)])
    assert result.exit_code == 1
    assert f'{rom}: Bad image.' in result.output


def test_module_entry_point(mocker: MockerFixture) -> None:
    group = mocker.patch('dade.tgr.main.tgr')
    runpy.run_module('dade.tgr', run_name='__main__')
    group.assert_called_once_with()
