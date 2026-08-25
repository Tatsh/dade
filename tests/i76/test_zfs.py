"""Tests for :py:mod:`dade.i76.zfs`."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dade.i76.zfs import (
    InvalidArchiveError,
    archive_format,
    extract,
    iter_members,
    read_directory,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_archive_format_zfsf(zfsf_archive: bytes) -> None:
    assert archive_format(zfsf_archive) == 'zfsf'


def test_archive_format_zfs3(zfs3_archive: bytes) -> None:
    assert archive_format(zfs3_archive) == 'zfs3'


@pytest.mark.parametrize('data', [b'', b'NOPE', b'ZFS4rest'])
def test_archive_format_rejects_unknown(data: bytes) -> None:
    with pytest.raises(InvalidArchiveError):
        archive_format(data)


def test_read_directory_names_and_sizes(zfsf_archive: bytes) -> None:
    entries = read_directory(zfsf_archive)
    assert [(e.name, e.size) for e in entries] == [('A.GEO', 5), ('b.map', 7), ('', 4)]


def test_read_directory_spans_blocks(multi_block_archive: bytes) -> None:
    entries = read_directory(multi_block_archive)
    assert len(entries) == 150
    assert entries[0].name == 'f0.geo'
    assert entries[99].name == 'f99.geo'
    assert entries[100].name == 'f100.geo'
    assert entries[149].name == 'f149.geo'


def test_iter_members_skips_unnamed(zfsf_archive: bytes) -> None:
    assert [(e.name, payload)
            for e, payload in iter_members(zfsf_archive)] == [('A.GEO', b'first'),
                                                              ('b.map', b'second!')]


def test_iter_members_zfs3_is_verbatim(zfs3_archive: bytes) -> None:
    assert [payload for _, payload in iter_members(zfs3_archive)] == [b'world', b'verbatim']


def test_iter_members_warns_on_zfs3_flags(zfs3_archive: bytes,
                                          caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level('WARNING', logger='dade.i76.zfs'):
        list(iter_members(zfs3_archive))
    assert 'ODD.BIN' in caplog.text


def test_extract_writes_lowercased_names(zfsf_archive: bytes, tmp_path: Path) -> None:
    assert extract(zfsf_archive, tmp_path / 'out') == 2
    assert (tmp_path / 'out' / 'a.geo').read_bytes() == b'first'
    assert (tmp_path / 'out' / 'b.map').read_bytes() == b'second!'


def test_extract_rejects_unknown(tmp_path: Path) -> None:
    with pytest.raises(InvalidArchiveError):
        extract(b'NOPE' + bytes(64), tmp_path)
