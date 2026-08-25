from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dade.bitrock.archive import InstallBuilderFile
from dade.bitrock.exceptions import CorruptArchiveError
from dade.bitrock.io import MmapReader
from dade.bitrock.sansio import BytesReader

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def test_from_bytes(build_cookfs: Callable[..., bytes]) -> None:
    with InstallBuilderFile(build_cookfs({'a': b'x'})) as archive:
        assert archive.namelist == ('a',)
        assert archive.read('a') == b'x'
        assert archive.get_size('a') == 1
        assert tuple(archive) == ('a',)


def test_from_reader(build_cookfs: Callable[..., bytes]) -> None:
    reader = BytesReader(build_cookfs({'a': b'y'}))
    with InstallBuilderFile(reader) as archive:
        assert archive.read('a') == b'y'


def test_from_path(tmp_path: Path, build_cookfs: Callable[..., bytes]) -> None:
    installer = tmp_path / 'demo.run'
    installer.write_bytes(build_cookfs({'a': b'z'}))
    with InstallBuilderFile(installer) as archive:
        assert archive.read('a') == b'z'


def test_from_path_string(tmp_path: Path, build_cookfs: Callable[..., bytes]) -> None:
    installer = tmp_path / 'demo.run'
    installer.write_bytes(build_cookfs({'a': b'z'}))
    with InstallBuilderFile(str(installer)) as archive:
        assert archive.read('a') == b'z'


def test_cookfs_attribute(build_cookfs: Callable[..., bytes]) -> None:
    with InstallBuilderFile(build_cookfs({'a': b'x'})) as archive:
        assert archive.cookfs.read('a') == b'x'


def test_close_is_idempotent_for_bytes(build_cookfs: Callable[..., bytes]) -> None:
    archive = InstallBuilderFile(build_cookfs({'a': b'x'}))
    archive.close()
    archive.close()


def test_construction_failure_closes_path(tmp_path: Path) -> None:
    installer = tmp_path / 'bad.run'
    installer.write_bytes(b'not a cookfs archive at all, no signature present')
    with pytest.raises(CorruptArchiveError):
        InstallBuilderFile(installer, end_offset=16)


def test_mmap_reader_context_manager(tmp_path: Path, build_cookfs: Callable[..., bytes]) -> None:
    installer = tmp_path / 'demo.run'
    installer.write_bytes(build_cookfs({'a': b'x'}))
    with MmapReader(installer) as reader:
        assert reader.size == installer.stat().st_size
        assert reader.read(0, 4) == b'STUB'


def test_mmap_reader_rejects_empty_file(tmp_path: Path) -> None:
    empty = tmp_path / 'empty.run'
    empty.write_bytes(b'')
    with pytest.raises(ValueError, match='mmap'):
        MmapReader(empty)


def test_is_encrypted_false(build_cookfs: Callable[..., bytes]) -> None:
    with InstallBuilderFile(build_cookfs({'a': b'x'})) as archive:
        assert archive.is_encrypted is False


def test_is_encrypted_true(build_encrypted_cookfs: Callable[..., bytes]) -> None:
    with InstallBuilderFile(build_encrypted_cookfs({'a': b'secret'}, b'pw')) as archive:
        assert archive.is_encrypted is True


def test_unlock(build_encrypted_cookfs: Callable[..., bytes]) -> None:
    with InstallBuilderFile(build_encrypted_cookfs({'a': b'secret'}, b'pw')) as archive:
        archive.unlock('pw')
        assert archive.read('a') == b'secret'
