from __future__ import annotations

from typing import TYPE_CHECKING

from dade.incoming.converters.text import txt_to_utf8

if TYPE_CHECKING:
    from pathlib import Path


def test_ascii(tmp_path: Path) -> None:
    source = tmp_path / 'a.txt'
    source.write_bytes(b'num_of_levels 5')
    assert txt_to_utf8(source, tmp_path).read_text('utf-8') == 'num_of_levels 5'


def test_utf8(tmp_path: Path) -> None:
    source = tmp_path / 'u.txt'
    source.write_bytes('café'.encode())
    assert txt_to_utf8(source, tmp_path).read_text('utf-8') == 'café'


def test_shift_jis(tmp_path: Path) -> None:
    source = tmp_path / 'j.txt'
    source.write_bytes('空きブロック'.encode('shift-jis'))
    assert txt_to_utf8(source, tmp_path).read_text('utf-8') == '空きブロック'


def test_iso8859_15(tmp_path: Path) -> None:
    source = tmp_path / 'f.txt'
    source.write_bytes(b'caf\xe9 bar')  # 0xe9 + space is invalid Shift-JIS, valid Latin-9.
    assert txt_to_utf8(source, tmp_path).read_text('utf-8') == 'café bar'
