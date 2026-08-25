"""Tests for :py:mod:`dade.jubeatplus.plists`."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
import plistlib

from dade.common.bfcodec import BFCodec
from dade.jubeatplus.cipher import lab_url_key, texture_key
from dade.jubeatplus.plists import json_safe, read_plist

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path


def test_json_safe_leaves_plain_values_alone() -> None:
    assert json_safe({
        'a': 1,
        'b': [True, 'text', 2.5],
        'c': None
    }) == {
        'a': 1,
        'b': [True, 'text', 2.5],
        'c': None
    }


def test_json_safe_converts_a_date() -> None:
    when = datetime(2014, 11, 11, 17, 45, tzinfo=timezone.utc)
    assert json_safe({'when': when}) == {'when': '2014-11-11T17:45:00+00:00'}


def test_json_safe_converts_a_uid() -> None:
    assert json_safe(plistlib.UID(7)) == 7


def test_json_safe_converts_a_tuple() -> None:
    assert json_safe((1, 2)) == [1, 2]


def test_json_safe_reports_opaque_data_as_hex() -> None:
    assert json_safe(b'\x01\x02') == {'hex': '0102', 'length': 2}


def test_json_safe_deciphers_a_lab_url() -> None:
    blob = BFCodec(lab_url_key()).encipher(b'https://example.invalid/path')
    assert json_safe(blob)['deciphered'] == 'https://example.invalid/path'


def test_json_safe_leaves_data_under_another_key_opaque() -> None:
    blob = BFCodec(texture_key()).encipher(b'https://example.invalid/path')
    assert 'deciphered' not in json_safe(blob)


def test_json_safe_leaves_undecodable_plaintext_opaque() -> None:
    blob = BFCodec(lab_url_key()).encipher(b'\xff\xfe\xfd\xfc')
    assert 'deciphered' not in json_safe(blob)


def test_json_safe_leaves_unprintable_plaintext_opaque() -> None:
    blob = BFCodec(lab_url_key()).encipher(b'line one\nline two')
    assert 'deciphered' not in json_safe(blob)


def test_read_plist(make_lab_plist: Callable[[Mapping[str, object]], Path]) -> None:
    blob = BFCodec(lab_url_key()).encipher(b'https://example.invalid/')
    path = make_lab_plist({'Theme': 2, 'URL': blob})
    assert read_plist(path) == {
        'Theme': 2,
        'URL': {
            'deciphered': 'https://example.invalid/',
            'hex': blob.hex(),
            'length': len(blob)
        }
    }
