"""Tests for :mod:`dade.bit192.save`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import hashlib

import pytest

from dade.bit192.save import (
    DLC_OFFSETS,
    SAVE_SIZE,
    UNLOCK_FLAGS_COUNT,
    UNLOCK_FLAGS_OFFSET,
    SaveFile,
    dlc_token,
)

if TYPE_CHECKING:
    from pathlib import Path

_DEVICE_ID_OFFSET = 0x3CA38
_INTEGRITY_OFFSET = 0x3C488


def _blank_save(device_id: str = 'test-device') -> bytearray:
    buf = bytearray(SAVE_SIZE)
    encoded = device_id.encode()
    buf[_DEVICE_ID_OFFSET:_DEVICE_ID_OFFSET + len(encoded)] = encoded
    return buf


def test_device_id() -> None:
    assert SaveFile(_blank_save('pixel-7')).device_id == 'pixel-7'


def test_dlc_token_matches_md5() -> None:
    assert dlc_token('abc', 'vvv') == hashlib.md5(b'abcvvv').hexdigest().encode()  # noqa: S324


def test_unlock_dlc_writes_token() -> None:
    sf = SaveFile(_blank_save('dev1'))
    sf.unlock_dlc('darksphere')
    off = DLC_OFFSETS['darksphere']
    token = dlc_token('dev1', 'darksphere')
    assert sf.data[off:off + len(token)] == token
    assert sf.data[off + len(token)] == 0  # NUL terminator


def test_unlock_all_dlc() -> None:
    sf = SaveFile(_blank_save())
    assert sorted(sf.unlock_all_dlc()) == sorted(DLC_OFFSETS)
    for name, off in DLC_OFFSETS.items():
        assert sf.data[off:off + 32] == dlc_token(sf.device_id, name)


def test_unlock_song_sets_flag() -> None:
    sf = SaveFile(_blank_save())
    sf.unlock_song(271)
    assert sf.data[UNLOCK_FLAGS_OFFSET + 271] == 1
    assert sf.data[UNLOCK_FLAGS_OFFSET + 270] == 0  # only the requested flag


@pytest.mark.parametrize('bad', [0, UNLOCK_FLAGS_COUNT, UNLOCK_FLAGS_COUNT + 1])
def test_unlock_song_rejects_out_of_range(bad: int) -> None:
    with pytest.raises(ValueError, match=r'out of range'):
        SaveFile(_blank_save()).unlock_song(bad)


def test_unlock_all_songs_sets_array_only() -> None:
    sf = SaveFile(_blank_save())
    count = sf.unlock_all_songs()
    assert count == UNLOCK_FLAGS_COUNT - 1
    # Every flag from 1 to the array end is set...
    assert all(sf.data[UNLOCK_FLAGS_OFFSET + n] == 1 for n in range(1, UNLOCK_FLAGS_COUNT))
    # ...and the array stops exactly at the integrity hash (which is left untouched).
    assert UNLOCK_FLAGS_OFFSET + UNLOCK_FLAGS_COUNT == _INTEGRITY_OFFSET
    assert sf.data[_INTEGRITY_OFFSET] == 0
    # DLC token region is not touched by song unlocking.
    assert sf.data[DLC_OFFSETS['darksphere']] == 0


def test_load_rejects_wrong_size(tmp_path: Path) -> None:
    bad = tmp_path / 'save.bin'
    bad.write_bytes(b'\x00' * 16)
    with pytest.raises(ValueError, match=r'Unexpected save size'):
        SaveFile.load(bad)


def test_load_and_save_roundtrip(tmp_path: Path) -> None:
    src = tmp_path / 'save.bin'
    src.write_bytes(bytes(_blank_save('dev2')))
    sf = SaveFile.load(src)
    sf.unlock_dlc('vvv')
    dst = tmp_path / 'save.new'
    sf.save(dst)
    assert len(dst.read_bytes()) == SAVE_SIZE


def test_blank_is_zeroed_and_sized() -> None:
    sf = SaveFile.blank()
    assert len(sf.data) == SAVE_SIZE
    assert not any(sf.data)


def test_set_device_id_roundtrips() -> None:
    sf = SaveFile.blank()
    sf.set_device_id('a1b2c3d4e5f6a7b8')
    assert sf.device_id == 'a1b2c3d4e5f6a7b8'


def test_set_device_id_rejects_overlong() -> None:
    with pytest.raises(ValueError, match=r'too long'):
        SaveFile.blank().set_device_id('x' * 200)


def test_unlock_everything_sets_songs_and_dlc() -> None:
    sf = SaveFile.blank()
    sf.set_device_id('iOS')
    sf.unlock_everything()
    assert sf.data[UNLOCK_FLAGS_OFFSET + 271] == 1
    for name, off in DLC_OFFSETS.items():
        assert sf.data[off:off + 32] == dlc_token('iOS', name)


def test_generate_full_save_from_scratch() -> None:
    # The whole point: a fresh save with every song and every (device-bound) DLC pack unlocked.
    sf = SaveFile.blank()
    sf.set_device_id('deadbeefdeadbeef')
    sf.unlock_everything()
    assert sf.device_id == 'deadbeefdeadbeef'
    assert all(sf.data[UNLOCK_FLAGS_OFFSET + n] == 1 for n in range(1, UNLOCK_FLAGS_COUNT))
    vvv = DLC_OFFSETS['vvv']
    assert sf.data[vvv:vvv + 32] == dlc_token('deadbeefdeadbeef', 'vvv')
    assert sf.data[_INTEGRITY_OFFSET] == 0  # array stops before the (unverified) integrity hash
