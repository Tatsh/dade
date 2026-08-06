from __future__ import annotations

from typing import TYPE_CHECKING

from destin.common.io import BytesReader, MmapReader, Reader, resolve_reader
import pytest

if TYPE_CHECKING:
    from pathlib import Path


def test_bytes_reader_size_and_read() -> None:
    reader = BytesReader(b'0123456789')
    assert reader.size == 10
    assert reader.read(2, 3) == b'234'


def test_bytes_reader_is_reader() -> None:
    assert isinstance(BytesReader(b''), Reader)


def test_mmap_reader_reads_file(tmp_path: Path) -> None:
    path = tmp_path / 'data.bin'
    path.write_bytes(b'abcdefgh')
    with MmapReader(path) as reader:
        assert reader.size == 8
        assert reader.read(2, 3) == b'cde'


def test_mmap_reader_rejects_empty_file(tmp_path: Path) -> None:
    empty = tmp_path / 'empty.bin'
    empty.touch()
    with pytest.raises(ValueError, match='mmap'):
        MmapReader(empty)


def test_resolve_reader_bytes_owns_nothing() -> None:
    reader, owned = resolve_reader(b'payload')
    assert isinstance(reader, BytesReader)
    assert owned is None


def test_resolve_reader_path_owns_mmap(tmp_path: Path) -> None:
    path = tmp_path / 'data.bin'
    path.write_bytes(b'payload')
    reader, owned = resolve_reader(path)
    assert isinstance(reader, MmapReader)
    assert owned is reader
    owned.close()


def test_resolve_reader_passes_through_existing_reader() -> None:
    existing = BytesReader(b'x')
    reader, owned = resolve_reader(existing)
    assert reader is existing
    assert owned is None
