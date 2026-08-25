from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import subprocess as sp

import pytest

from dade.incoming.sources import PreparedSource, SourceError, prepare_source

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest_mock import MockerFixture


def _which(mapping: dict[str, str]) -> Callable[[str], str | None]:
    return mapping.get


def _seven_zip_writes_cab(args: tuple[str, ...]) -> None:
    out_dir = next(a[2:] for a in args if a.startswith('-o'))
    (Path(out_dir) / 'data1.cab').write_bytes(b'CAB')


def test_prepare_nonexistent(tmp_path: Path) -> None:
    with pytest.raises(SourceError, match='does not exist'):
        prepare_source(tmp_path / 'nope', tmp_path / 'work')


def test_prepare_single_asset(tmp_path: Path) -> None:
    asset = tmp_path / 'a.png'
    asset.write_text('x')
    assert prepare_source(asset, tmp_path / 'work') == PreparedSource(None, (asset,))


def test_prepare_gdi_file(tmp_path: Path, mocker: MockerFixture) -> None:
    gdi = tmp_path / 'x.gdi'
    gdi.write_text('x')
    (tmp_path / 'track02.raw').write_text('a')
    run = mocker.patch('dade.incoming.sources.run_gdiextract')
    work = tmp_path / 'work'
    result = prepare_source(gdi, work)
    run.assert_called_once()
    assert result.root == work
    assert tmp_path / 'track02.raw' in result.files


def test_prepare_cab_file(tmp_path: Path, mocker: MockerFixture) -> None:
    cab = tmp_path / 'DATA1.CAB'
    cab.write_text('x')
    run = mocker.patch('dade.incoming.sources.run_unshield')
    work = tmp_path / 'work'
    assert prepare_source(cab, work) == PreparedSource(work, ())
    run.assert_called_once()


def test_prepare_dir_with_cab(tmp_path: Path, mocker: MockerFixture) -> None:
    (tmp_path / 'DATA1.CAB').write_text('x')
    mocker.patch('dade.incoming.sources.run_unshield')
    work = tmp_path / 'work'
    assert prepare_source(tmp_path, work).root == work


def test_prepare_dir_with_gdi(tmp_path: Path, mocker: MockerFixture) -> None:
    (tmp_path / 'g.gdi').write_text('x')
    (tmp_path / 'track01.raw').write_text('a')
    mocker.patch('dade.incoming.sources.run_gdiextract')
    work = tmp_path / 'work'
    assert prepare_source(tmp_path, work).root == work


def test_prepare_extracted_dir(tmp_path: Path) -> None:
    (tmp_path / 'TEXTURES').mkdir()
    assert prepare_source(tmp_path, tmp_path / 'work') == PreparedSource(tmp_path, ())


def test_iso_isodump_success(tmp_path: Path, mocker: MockerFixture) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_text('x')
    mocker.patch('dade.incoming.sources.which', side_effect=_which({'isodump': '/isodump'}))

    def run(args: tuple[str, ...], **kwargs: object) -> object:
        kwargs['stdout'].write(  # type: ignore[attr-defined] # ty: ignore[unresolved-attribute]
            b'CABDATA')
        return mocker.Mock()

    mocker.patch('dade.incoming.sources.sp.run', side_effect=run)
    unshield = mocker.patch('dade.incoming.sources.run_unshield')
    assert prepare_source(iso, tmp_path / 'work').root == tmp_path / 'work'
    unshield.assert_called_once()


def test_iso_isodump_empty_then_7z(tmp_path: Path, mocker: MockerFixture) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_text('x')
    mocker.patch('dade.incoming.sources.which',
                 side_effect=_which({
                     'isodump': '/isodump',
                     '7z': '/7z'
                 }))

    def run(args: tuple[str, ...], **kwargs: object) -> object:
        if args[0] == '/7z':  # isodump wrote nothing, so 7z is the fallback
            _seven_zip_writes_cab(args)
        return mocker.Mock()

    mocker.patch('dade.incoming.sources.sp.run', side_effect=run)
    unshield = mocker.patch('dade.incoming.sources.run_unshield')
    assert prepare_source(iso, tmp_path / 'work').root == tmp_path / 'work'
    unshield.assert_called_once()


def test_iso_isodump_error_then_7z(tmp_path: Path, mocker: MockerFixture) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_text('x')
    mocker.patch('dade.incoming.sources.which',
                 side_effect=_which({
                     'isodump': '/isodump',
                     '7z': '/7z'
                 }))

    def run(args: tuple[str, ...], **kwargs: object) -> object:
        if args[0] == '/isodump':
            raise sp.CalledProcessError(1, args)
        _seven_zip_writes_cab(args)
        return mocker.Mock()

    mocker.patch('dade.incoming.sources.sp.run', side_effect=run)
    mocker.patch('dade.incoming.sources.run_unshield')
    assert prepare_source(iso, tmp_path / 'work').root == tmp_path / 'work'


def test_iso_no_isodump_uses_7z(tmp_path: Path, mocker: MockerFixture) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_text('x')
    mocker.patch('dade.incoming.sources.which', side_effect=_which({'7z': '/7z'}))
    mocker.patch('dade.incoming.sources.sp.run',
                 side_effect=lambda args, **_: _seven_zip_writes_cab(args))
    mocker.patch('dade.incoming.sources.run_unshield')
    assert prepare_source(iso, tmp_path / 'work').root == tmp_path / 'work'


def test_iso_7z_finds_nothing(tmp_path: Path, mocker: MockerFixture) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_text('x')
    mocker.patch('dade.incoming.sources.which', side_effect=_which({'7z': '/7z'}))
    mocker.patch('dade.incoming.sources.sp.run', return_value=mocker.Mock())
    with pytest.raises(SourceError, match='Could not extract'):
        prepare_source(iso, tmp_path / 'work')


def test_iso_no_tools(tmp_path: Path, mocker: MockerFixture) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_text('x')
    mocker.patch('dade.incoming.sources.which', return_value=None)
    with pytest.raises(SourceError, match='Could not extract'):
        prepare_source(iso, tmp_path / 'work')
