from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from dade.common.exceptions import InvalidFormatError
from dade.common.tools import ToolNotFoundError
from dade.itgps2.main import itgps2

if TYPE_CHECKING:
    from click.testing import CliRunner
    from pytest_mock import MockerFixture

_FFMPEG = Path('/usr/bin/ffmpeg')


def test_extract_reports_each_release(runner: CliRunner, mocker: MockerFixture,
                                      tmp_path: Path) -> None:
    locate_tool = mocker.patch('dade.itgps2.main.locate_tool', return_value=_FFMPEG)
    extract_disc = mocker.patch('dade.itgps2.main.extract_disc',
                                return_value=('itg', {
                                    'copied': 2,
                                    'av': 1
                                }))
    result = runner.invoke(itgps2, ['extract', str(tmp_path), '-o', 'out', '-j', '3'])
    assert result.exit_code == 0, result.output
    locate_tool.assert_called_once_with('ffmpeg', None)
    extract_disc.assert_called_once_with(tmp_path, Path('out'), _FFMPEG, 3)
    assert f'{Path("out") / "itg"}: av: 1, copied: 2' in result.output


def test_extract_without_ffmpeg(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('dade.itgps2.main.locate_tool', side_effect=ToolNotFoundError('missing.'))
    extract_disc = mocker.patch('dade.itgps2.main.extract_disc', return_value=('itg', {}))
    assert runner.invoke(itgps2, ['extract', str(tmp_path), '-j', '1']).exit_code == 0
    assert extract_disc.call_args.args[2] is None


def test_extract_no_video(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    locate_tool = mocker.patch('dade.itgps2.main.locate_tool')
    mocker.patch('dade.itgps2.main.extract_disc', return_value=('itg', {}))
    assert runner.invoke(itgps2, ['extract', str(tmp_path), '--no-video']).exit_code == 0
    locate_tool.assert_not_called()


def test_extract_aborts_on_an_invalid_disc(runner: CliRunner, mocker: MockerFixture,
                                           tmp_path: Path) -> None:
    mocker.patch('dade.itgps2.main.locate_tool', return_value=_FFMPEG)
    mocker.patch('dade.itgps2.main.extract_disc', side_effect=InvalidFormatError('No packs.'))
    result = runner.invoke(itgps2, ['extract', str(tmp_path)])
    assert result.exit_code == 1
    assert 'No packs.' in result.output


def test_extract_accepts_an_ffmpeg_path_and_several_sources(runner: CliRunner,
                                                            mocker: MockerFixture,
                                                            tmp_path: Path) -> None:
    ffmpeg = tmp_path / 'ffmpeg'
    ffmpeg.write_bytes(b'')
    locate_tool = mocker.patch('dade.itgps2.main.locate_tool', return_value=ffmpeg)
    extract_disc = mocker.patch('dade.itgps2.main.extract_disc', return_value=('itg', {}))
    result = runner.invoke(
        itgps2, ['extract', str(tmp_path),
                 str(ffmpeg), '--ffmpeg-path',
                 str(ffmpeg)])
    assert result.exit_code == 0, result.output
    locate_tool.assert_called_once_with('ffmpeg', ffmpeg)
    assert extract_disc.call_count == 2
