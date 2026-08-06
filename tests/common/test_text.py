from __future__ import annotations

from typing import TYPE_CHECKING

from destin.common.text import decode_text, recode_to_utf8

if TYPE_CHECKING:
    from pathlib import Path


def test_decode_text_prefers_the_first_candidate() -> None:
    assert decode_text('café'.encode()) == 'café'


def test_decode_text_falls_through_to_a_later_candidate() -> None:
    assert decode_text('空きブロック'.encode('shift-jis')) == '空きブロック'


def test_decode_text_uses_the_fallback_when_no_candidate_decodes() -> None:
    assert decode_text(b'caf\xe9') == 'café'


def test_decode_text_honours_a_custom_candidate_list() -> None:
    assert decode_text(b'caf\xe9', ('iso-8859-15',), 'utf-8') == 'café'


def test_recode_to_utf8_writes_utf8(tmp_path: Path) -> None:
    source = tmp_path / 'in.TXT'
    source.write_bytes('空き'.encode('shift-jis'))
    written = recode_to_utf8(source, tmp_path)
    assert written == tmp_path / 'in.txt'
    assert written.read_text('utf-8') == '空き'


def test_recode_to_utf8_honours_a_custom_suffix(tmp_path: Path) -> None:
    source = tmp_path / 'in.dat'
    source.write_bytes(b'plain')
    assert recode_to_utf8(source, tmp_path, suffix='.out') == tmp_path / 'in.out'
