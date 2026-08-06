"""Tests for :func:`destin.marmalade.hashstring.iw_hash_string`."""
from __future__ import annotations

from destin.marmalade.hashstring import iw_hash_string


def test_empty_string_is_seed() -> None:
    assert iw_hash_string('') == 0x1505


def test_case_insensitive() -> None:
    assert iw_hash_string('CIwModel') == iw_hash_string('ciwmodel')


def test_distinct_names_differ() -> None:
    assert iw_hash_string('CIwModel') != iw_hash_string('CIwTexture')


def test_result_is_32_bit() -> None:
    assert 0 <= iw_hash_string('ResGroupResources' * 8) <= 0xFFFFFFFF
