from __future__ import annotations

from typing import TYPE_CHECKING

from destin.common.json import write_json

if TYPE_CHECKING:
    from pathlib import Path


def test_write_json_default(tmp_path: Path) -> None:
    out = tmp_path / 'out.json'
    write_json(out, {'b': 1, 'a': 2})
    assert out.read_text(encoding='utf-8') == '{\n  "b": 1,\n  "a": 2\n}\n'


def test_write_json_sort_keys(tmp_path: Path) -> None:
    out = tmp_path / 'out.json'
    write_json(out, {'b': 1, 'a': 2}, sort_keys=True)
    assert out.read_text(encoding='utf-8') == '{\n  "a": 2,\n  "b": 1\n}\n'


def test_write_json_ensure_ascii_false(tmp_path: Path) -> None:
    out = tmp_path / 'out.json'
    write_json(out, {'name': 'café'}, ensure_ascii=False)
    assert out.read_bytes() == '{\n  "name": "café"\n}\n'.encode()


def test_write_json_ensure_ascii_true(tmp_path: Path) -> None:
    out = tmp_path / 'out.json'
    write_json(out, {'name': 'café'})
    assert out.read_text(encoding='utf-8') == '{\n  "name": "caf\\u00e9"\n}\n'


def test_write_json_no_trailing_newline(tmp_path: Path) -> None:
    out = tmp_path / 'out.json'
    write_json(out, {'a': 1}, trailing_newline=False)
    assert out.read_text(encoding='utf-8') == '{\n  "a": 1\n}'
