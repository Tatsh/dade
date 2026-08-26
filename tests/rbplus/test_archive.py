"""Tests for :py:mod:`dade.rbplus.archive`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import zipfile

import pytest

from dade.rbplus.archive import (
    ARCHIVE_PASSWORD,
    ArchiveError,
    archive_root,
    entry_names,
    open_archive,
    read_manifest,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def test_the_password_is_the_one_the_binary_carries() -> None:
    assert ARCHIVE_PASSWORD == b'mt972'


def test_open_archive_lists_its_entries(make_asset_archive: Callable[..., Path]) -> None:
    with open_archive(make_asset_archive(entries={'a.png': b'x', 'b.png': b'y'})) as archive:
        assert {info.filename for info in entry_names(archive)} == {'iPad/a.png', 'iPad/b.png'}


def test_directories_are_left_out(tmp_path: Path) -> None:
    path = tmp_path / 'dirs.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('iPad/', b'')
        archive.writestr('iPad/a.png', b'x')
    with open_archive(path) as archive:
        assert [info.filename for info in entry_names(archive)] == ['iPad/a.png']


def test_a_file_that_is_not_a_zip_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / 'broken.zip'
    path.write_bytes(b'not a zip at all')
    with pytest.raises(ArchiveError, match='not a ZIP archive'):
        open_archive(path)


@pytest.mark.parametrize('root', ['iPad', 'iPad2x', 'iPhone@2x'])
def test_archive_root_names_the_one_top_level_directory(make_asset_archive: Callable[..., Path],
                                                        root: str) -> None:
    with open_archive(make_asset_archive(entries={'a.png': b'x'}, root=root)) as archive:
        assert archive_root(archive) == root


def test_archive_root_is_empty_when_there_is_no_common_one(tmp_path: Path) -> None:
    path = tmp_path / 'mixed.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('one/a.png', b'x')
        archive.writestr('two/b.png', b'y')
    with open_archive(path) as archive:
        assert not archive_root(archive)


def test_read_manifest_lists_the_asset_paths(make_asset_archive: Callable[..., Path]) -> None:
    paths = ('00_Share/a.png', '01_Colette/b.png')
    with open_archive(make_asset_archive(entries={'a.png': b'x'}, manifest=paths)) as archive:
        assert read_manifest(archive) == paths


def test_read_manifest_drops_blank_lines(make_asset_archive: Callable[..., Path]) -> None:
    with open_archive(make_asset_archive(manifest=('a.png', '', 'b.png', ''))) as archive:
        assert read_manifest(archive) == ('a.png', 'b.png')


def test_read_manifest_is_empty_without_one(make_asset_archive: Callable[..., Path]) -> None:
    with open_archive(make_asset_archive(entries={'a.png': b'x'})) as archive:
        assert read_manifest(archive) == ()


def test_read_manifest_works_without_a_root(tmp_path: Path,
                                            make_asset_archive: Callable[..., Path]) -> None:
    with open_archive(make_asset_archive(manifest=('a.png',), root='')) as archive:
        assert read_manifest(archive) == ('a.png',)


def test_a_manifest_that_is_not_an_archive_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / 'bad-manifest.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('iPad/list', b'not a nested zip')
    with open_archive(path) as archive, pytest.raises(ArchiveError, match='readable manifest'):
        read_manifest(archive)


def test_a_manifest_archive_without_its_entry_is_rejected(tmp_path: Path) -> None:
    nested = tmp_path / 'nested.zip'
    with zipfile.ZipFile(nested, 'w') as inner:
        inner.writestr('wrong-name', b'a.png')
    path = tmp_path / 'wrong-inner.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('iPad/list', nested.read_bytes())
    with open_archive(path) as archive, pytest.raises(ArchiveError, match='readable manifest'):
        read_manifest(archive)
