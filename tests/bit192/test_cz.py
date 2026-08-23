"""Tests for :mod:`destin.bit192.cz`."""
from __future__ import annotations

import pytest

from destin.bit192 import cz
from destin.marmalade.test_utils import build_derbh


def test_decrypt_is_involution() -> None:
    payload = bytes(range(256)) * 4
    assert cz.decrypt(cz.decrypt(payload)) == payload


def test_roundtrip_dtrz() -> None:
    dtrz = build_derbh([('a.bin', b'hello')])
    encrypted = cz.decrypt(dtrz)  # XOR is symmetric, so this "encrypts"
    assert cz.looks_like_cz(encrypted)
    assert cz.decrypt(encrypted) == dtrz


def test_plain_dtrz_is_not_cz() -> None:
    assert not cz.looks_like_cz(build_derbh([('a.bin', b'x')]))


def test_empty_key_rejected() -> None:
    with pytest.raises(ValueError, match=r'non-empty\.$'):
        cz.decrypt(b'abc', key1=b'')
