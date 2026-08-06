from __future__ import annotations

from typing import TYPE_CHECKING

from destin.bitrock import unpack
from destin.bitrock.exceptions import MemberNotFoundError
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def test_unpack_all(tmp_path: Path, build_cookfs: Callable[..., bytes]) -> None:
    data = build_cookfs({'dir/a.txt': b'alpha', 'dir/b.txt': b'beta'})
    results = list(unpack(data, tmp_path))
    assert {r.path for r in results} == {'dir/a.txt', 'dir/b.txt'}
    assert (tmp_path / 'dir/a.txt').read_bytes() == b'alpha'
    assert (tmp_path / 'dir/b.txt').read_bytes() == b'beta'


def test_unpack_selected(tmp_path: Path, build_cookfs: Callable[..., bytes]) -> None:
    data = build_cookfs({'a.txt': b'1', 'b.txt': b'2'})
    results = list(unpack(data, tmp_path, ['a.txt']))
    assert [r.path for r in results] == ['a.txt']
    assert (tmp_path / 'a.txt').exists()
    assert not (tmp_path / 'b.txt').exists()


def test_unpack_dry_run(tmp_path: Path, build_cookfs: Callable[..., bytes]) -> None:
    data = build_cookfs({'a.txt': b'1'})
    results = list(unpack(data, tmp_path, dry_run=True))
    assert results[0].written is False
    assert not (tmp_path / 'a.txt').exists()


def test_unpack_missing_member(tmp_path: Path, build_cookfs: Callable[..., bytes]) -> None:
    data = build_cookfs({'a.txt': b'1'})
    with pytest.raises(MemberNotFoundError, match='nope'):
        list(unpack(data, tmp_path, ['nope']))


def test_unpack_marks_elf_executable(tmp_path: Path, build_cookfs: Callable[..., bytes]) -> None:
    data = build_cookfs({'bin/tool': b'\x7fELF\x02\x01\x01', 'docs/readme': b'hello'})
    results = {r.path: r for r in unpack(data, tmp_path)}
    assert results['bin/tool'].executable is True
    assert results['docs/readme'].executable is False
    assert (tmp_path / 'bin/tool').stat().st_mode & 0o111
    assert not (tmp_path / 'docs/readme').stat().st_mode & 0o111


def test_unpack_marks_macho_and_shebang(tmp_path: Path, build_cookfs: Callable[..., bytes]) -> None:
    data = build_cookfs({
        'lib.dylib': b'\xcf\xfa\xed\xfe\x07',
        'run.sh': b'#!/bin/sh\necho hi\n',
        'data.bin': b'\x00\x01\x02\x03',
    })
    results = {r.path: r.executable for r in unpack(data, tmp_path)}
    assert results == {'lib.dylib': True, 'run.sh': True, 'data.bin': False}
