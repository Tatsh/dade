"""Tests for :py:mod:`destin.jubeatplus.cipher`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import hashlib

from destin.jubeatplus.cipher import (
    BGM_PASSPHRASE,
    LAB_URL_PASSPHRASE,
    MISSION_DATA_PASSPHRASE,
    RESOURCE_DATA_PASSPHRASE,
    SAVE_DATA_PASSPHRASE,
    TEXTURE_PASSPHRASE,
    TUNE_INFO_PASSPHRASE,
    bgm_key,
    key_for_passphrase,
    lab_url_key,
    mission_data_key,
    resource_data_key,
    save_data_key,
    texture_key,
    tune_info_key,
)
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

_KEYS = (
    (bgm_key, BGM_PASSPHRASE),
    (lab_url_key, LAB_URL_PASSPHRASE),
    (mission_data_key, MISSION_DATA_PASSPHRASE),
    (resource_data_key, RESOURCE_DATA_PASSPHRASE),
    (save_data_key, SAVE_DATA_PASSPHRASE),
    (texture_key, TEXTURE_PASSPHRASE),
    (tune_info_key, TUNE_INFO_PASSPHRASE),
)
# The digests the game's own files were encrypted with. Every other test here derives its key from
# the passphrase beside it, so only these literals notice a passphrase that has drifted from the
# one in the binary.
_DIGESTS = (
    (bgm_key, 'f9a142c70b07d9a8093b56b8c2eeb698'),
    (lab_url_key, 'a619ba3290e96865e4771561b602205c'),
    (mission_data_key, '4abf0f353007098d4d93fd8a544858ab'),
    (resource_data_key, '07e25140cde192e5358becab00ae2e7f'),
    (save_data_key, 'b3ba718ed53a836b09599dff362dc7dd'),
    (texture_key, 'c8cfc58275563289f141c277db4d16af'),
    (tune_info_key, '68c840101cd8324f31263ac693cb5b62'),
)


@pytest.mark.parametrize(('factory', 'passphrase'), _KEYS)
def test_every_key_is_the_digest_of_its_passphrase(factory: Callable[[], bytes],
                                                   passphrase: bytes) -> None:
    assert factory() == hashlib.md5(passphrase, usedforsecurity=False).digest()


@pytest.mark.parametrize(('factory', 'passphrase'), _KEYS)
def test_every_key_is_sixteen_bytes(factory: Callable[[], bytes], passphrase: bytes) -> None:
    assert len(factory()) == 16


@pytest.mark.parametrize(('factory', 'digest'), _DIGESTS)
def test_every_key_is_the_one_the_game_ships(factory: Callable[[], bytes], digest: str) -> None:
    assert factory().hex() == digest


def test_the_seven_keys_are_all_different() -> None:
    assert len({factory() for factory, _ in _KEYS}) == len(_KEYS)


def test_the_bgm_and_tune_info_passphrases_differ_only_in_their_tail() -> None:
    assert BGM_PASSPHRASE[:-4] == TUNE_INFO_PASSPHRASE[:-3]
    assert bgm_key() != tune_info_key()


def test_key_for_passphrase_is_cached() -> None:
    assert key_for_passphrase(b'example') is key_for_passphrase(b'example')
