"""Tests for :mod:`dade.thps2pc.imagemagick`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import subprocess as sp

import pytest

from dade.thps2pc import imagemagick

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from pytest_mock import MockerFixture


def test_resolve_prefers_the_named_binary(mocker: MockerFixture) -> None:
    mocker.patch('dade.thps2pc.imagemagick.which', side_effect=lambda name: f'/usr/bin/{name}')
    assert imagemagick.resolve('convert') == ('/usr/bin/convert',)


def test_resolve_falls_back_to_magick_for_convert(mocker: MockerFixture) -> None:
    mocker.patch('dade.thps2pc.imagemagick.which',
                 side_effect=lambda name: '/usr/bin/magick' if name == 'magick' else None)
    assert imagemagick.resolve('convert') == ('/usr/bin/magick',)


def test_resolve_uses_a_magick_subcommand_for_montage(mocker: MockerFixture) -> None:
    mocker.patch('dade.thps2pc.imagemagick.which',
                 side_effect=lambda name: '/usr/bin/magick' if name == 'magick' else None)
    assert imagemagick.resolve('montage') == ('/usr/bin/magick', 'montage')


def test_resolve_accepts_an_override(tmp_path: Path) -> None:
    binary = tmp_path / 'convert'
    binary.write_text('')
    assert imagemagick.resolve('convert', binary) == (str(binary),)


def test_resolve_rejects_a_missing_override(tmp_path: Path) -> None:
    with pytest.raises(imagemagick.ImageMagickNotFoundError, match=r'does not exist'):
        imagemagick.resolve('convert', tmp_path / 'absent')


def test_resolve_raises_when_nothing_is_installed(mocker: MockerFixture) -> None:
    mocker.patch('dade.thps2pc.imagemagick.which', return_value=None)
    with pytest.raises(imagemagick.ImageMagickNotFoundError, match=r'Could not find `montage`'):
        imagemagick.resolve('montage')


@pytest.mark.parametrize(('function', 'tool'), [(imagemagick.convert, 'convert'),
                                                (imagemagick.montage, 'montage')])
def test_commands_run_with_check(function: Callable[[Sequence[str]], None], tool: str,
                                 mocker: MockerFixture) -> None:
    mocker.patch('dade.thps2pc.imagemagick.which', side_effect=lambda name: f'/usr/bin/{name}')
    run = mocker.patch('dade.thps2pc.imagemagick.sp.run')
    function(['a', 'b'])
    run.assert_called_once_with([f'/usr/bin/{tool}', 'a', 'b'], check=True)


def test_write_image_skips_conversion_for_ppm(tmp_path: Path, mocker: MockerFixture) -> None:
    run = mocker.patch('dade.thps2pc.imagemagick.sp.run')
    dest = tmp_path / 'nested' / 'out.ppm'
    imagemagick.write_image(b'P6\n1 1\n255\n\x00\x00\x00', dest)
    assert dest.read_bytes() == b'P6\n1 1\n255\n\x00\x00\x00'
    run.assert_not_called()


def test_write_image_converts_other_formats(tmp_path: Path, mocker: MockerFixture) -> None:
    mocker.patch('dade.thps2pc.imagemagick.which', side_effect=lambda name: f'/usr/bin/{name}')
    run = mocker.patch('dade.thps2pc.imagemagick.sp.run')
    imagemagick.write_image(b'P6\n1 1\n255\n\x00\x00\x00', tmp_path / 'out.png')
    command = run.call_args.args[0]
    assert command[0] == '/usr/bin/convert'
    assert command[-1] == str(tmp_path / 'out.png')


def test_write_image_passes_extra_arguments(tmp_path: Path, mocker: MockerFixture) -> None:
    mocker.patch('dade.thps2pc.imagemagick.which', side_effect=lambda name: f'/usr/bin/{name}')
    run = mocker.patch('dade.thps2pc.imagemagick.sp.run')
    imagemagick.write_image(b'P6\n1 1\n255\n\x00\x00\x00',
                            tmp_path / 'out.png',
                            extra_args=['-scale', '2x2'])
    assert '-scale' in run.call_args.args[0]


def test_write_image_removes_its_temporary_file(tmp_path: Path, mocker: MockerFixture) -> None:
    mocker.patch('dade.thps2pc.imagemagick.which', side_effect=lambda name: f'/usr/bin/{name}')
    mocker.patch('dade.thps2pc.imagemagick.sp.run')
    imagemagick.write_image(b'P6\n1 1\n255\n\x00\x00\x00', tmp_path / 'out.png')
    assert list(tmp_path.glob('*.ppm')) == []


def test_write_image_cleans_up_after_a_failure(tmp_path: Path, mocker: MockerFixture) -> None:
    mocker.patch('dade.thps2pc.imagemagick.which', side_effect=lambda name: f'/usr/bin/{name}')
    mocker.patch('dade.thps2pc.imagemagick.sp.run', side_effect=sp.CalledProcessError(1, 'convert'))
    with pytest.raises(sp.CalledProcessError):
        imagemagick.write_image(b'P6\n1 1\n255\n\x00\x00\x00', tmp_path / 'out.png')
    assert list(tmp_path.glob('*.ppm')) == []
