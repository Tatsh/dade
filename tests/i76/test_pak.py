"""Tests for :py:mod:`destin.i76.pak`."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from destin.i76.pak import (
    build_bundle_index,
    extract,
    iter_members,
    load_member,
    parse_index,
    read_index,
)

if TYPE_CHECKING:
    from pathlib import Path

_BUNDLE = b'first second! act'


def test_parse_index_skips_count_line_and_short_lines(pix_text: str) -> None:
    entries = parse_index(pix_text)
    assert [(e.name, e.offset, e.length) for e in entries] == [('a.geo', 0, 5), ('b.map', 6, 7),
                                                               ('c.act', 14, 3)]


def test_parse_index_lowercases_names(pix_text: str) -> None:
    assert all(entry.name == entry.name.lower() for entry in parse_index(pix_text))


def test_parse_index_empty() -> None:
    assert parse_index('0\n') == ()


def test_read_index(tmp_path: Path, pix_text: str) -> None:
    (pix := tmp_path / 'b.pix').write_text(pix_text)
    assert read_index(pix) == parse_index(pix_text)


def test_iter_members_slices_bundle(pix_text: str) -> None:
    assert [payload for _, payload in iter_members(_BUNDLE, parse_index(pix_text))] == [
        b'first', b'second!', b'act'
    ]


def test_build_bundle_index(tmp_path: Path, pix_text: str) -> None:
    (tmp_path / 'b.pix').write_text(pix_text)
    (tmp_path / 'b.pak').write_bytes(_BUNDLE)
    index = build_bundle_index(tmp_path)
    assert set(index) == {'a.geo', 'b.map', 'c.act'}


def test_build_bundle_index_ignores_bundles_without_indices(tmp_path: Path, pix_text: str) -> None:
    (tmp_path / 'orphan.pix').write_text(pix_text)
    assert build_bundle_index(tmp_path) == {}


def test_load_member(tmp_path: Path, pix_text: str) -> None:
    (tmp_path / 'b.pix').write_text(pix_text)
    (tmp_path / 'b.pak').write_bytes(_BUNDLE)
    index = build_bundle_index(tmp_path)
    assert load_member(index, 'B.MAP') == b'second!'


def test_load_member_absent(tmp_path: Path) -> None:
    assert load_member(build_bundle_index(tmp_path), 'nope.geo') is None


def test_extract(tmp_path: Path, pix_text: str) -> None:
    (tmp_path / 'b.pix').write_text(pix_text)
    (pak := tmp_path / 'b.pak').write_bytes(_BUNDLE)
    assert extract(pak, tmp_path / 'out') == 3
    assert (tmp_path / 'out' / 'b.map').read_bytes() == b'second!'


def test_extract_without_index(tmp_path: Path) -> None:
    (pak := tmp_path / 'b.pak').write_bytes(_BUNDLE)
    with pytest.raises(FileNotFoundError):
        extract(pak, tmp_path / 'out')
