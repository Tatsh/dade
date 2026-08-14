"""Tests for :py:mod:`destin.misc.strings`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import plistlib

from destin.misc import read_strings
import pytest

if TYPE_CHECKING:
    from pathlib import Path


def test_read_strings_compiled(compiled_strings: Path) -> None:
    assert read_strings(compiled_strings) == {'ok': 'OK', 'cancel': 'キャンセル'}


def test_read_strings_text(text_strings: Path) -> None:
    assert read_strings(text_strings) == {
        'ok': 'OK',
        'quote': 'say "hi"',
        'lines': 'one\ntwo',
        'odd key': 'kept',
    }


@pytest.mark.parametrize('encoding', ['utf-16-le', 'utf-16-be'])
def test_read_strings_utf16(tmp_path: Path, encoding: str) -> None:
    path = tmp_path / 'Wide.strings'
    mark = b'\xff\xfe' if encoding == 'utf-16-le' else b'\xfe\xff'
    path.write_bytes(mark + '"ok" = "OK";'.encode(encoding))
    assert read_strings(path) == {'ok': 'OK'}


def test_read_strings_plist_root_not_a_dictionary(tmp_path: Path) -> None:
    path = tmp_path / 'List.strings'
    path.write_bytes(plistlib.dumps(['not', 'a', 'table'], fmt=plistlib.FMT_BINARY))
    with pytest.raises(ValueError, match='root is not a dictionary'):
        read_strings(path)


def test_read_strings_undecodable(tmp_path: Path) -> None:
    path = tmp_path / 'Bad.strings'
    path.write_bytes(b'\xc3\x28"ok" = "OK";')
    with pytest.raises(UnicodeDecodeError):
        read_strings(path)
