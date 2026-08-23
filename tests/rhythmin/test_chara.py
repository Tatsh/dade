"""Tests for :py:mod:`destin.rhythmin.chara`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json

import pytest

from destin.rhythmin.bfcodec import encipher
from destin.rhythmin.chara import decrypt_chara, parse_chara, read_chara

if TYPE_CHECKING:
    from pathlib import Path


def test_read_chara(chara_file: Path, chara_json: dict[str, object]) -> None:
    assert read_chara(chara_file) == chara_json


def test_parse_chara_strips_trailing_commas() -> None:
    assert parse_chara(b'{"a": [1, 2,], "b": {"c": 3,},}') == {'a': [1, 2], 'b': {'c': 3}}


def test_decrypt_chara_round_trip() -> None:
    assert decrypt_chara(encipher(b'{"ok": true}')) == b'{"ok": true}'


def test_decrypt_chara_rejects_a_bad_trailer() -> None:
    with pytest.raises(ValueError, match='Bad length trailer'):
        decrypt_chara(b'\0' * 16)


def test_parse_chara_rejects_a_payload_that_is_not_json() -> None:
    with pytest.raises(json.JSONDecodeError):
        parse_chara(b'not json at all')
