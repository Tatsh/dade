"""Tests for :mod:`destin.xg2.albank`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from destin.xg2.albank import parse_bank
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

    from destin.xg2.typing import ParsedBank

_SOUND = 0x80
_WAVE_TABLE = 0xA0
_BOOK = 0xC0


def _parsed(blob: bytes, control: int = 0) -> ParsedBank:
    bank = parse_bank(b'\x00' * control + blob, control)
    assert bank is not None
    return bank


def test_parse_bank_reads_the_sample_rate(make_albank: Callable[..., bytes]) -> None:
    assert _parsed(make_albank(32000))['sample_rate'] == 32000


def test_parse_bank_decodes_the_sample(make_albank: Callable[..., bytes]) -> None:
    bank = _parsed(make_albank())
    assert len(bank['samples']) == 1
    assert bank['samples'][0] == [0] * 48


def test_parse_bank_honours_the_control_offset(make_albank: Callable[..., bytes]) -> None:
    assert _parsed(make_albank(), 0x1000)['sample_rate'] == 22050


def test_parse_bank_skips_an_absent_instrument(make_albank: Callable[..., bytes]) -> None:
    assert _parsed(make_albank())['instruments'] == [[{
        'sample': 0,
        'key_min': 36,
        'key_max': 96,
        'velocity_min': 0,
        'velocity_max': 127,
        'key_base': 60,
        'detune': 0,
        'loop_start': 0,
        'loop_end': 16,
        'loop': True,
        'pan': 64,
        'volume': 127,
        'attack': 1000,
        'decay': 2000,
        'release': 3000
    }], []]


def test_parse_bank_without_percussion(make_albank: Callable[..., bytes]) -> None:
    assert _parsed(make_albank())['percussion'] == []


def test_parse_bank_reads_percussion(make_albank: Callable[..., bytes]) -> None:
    bank = _parsed(make_albank(percussion=True))
    assert len(bank['percussion']) == 1
    assert bank['percussion'][0]['sample'] == 1
    assert len(bank['samples']) == 2


def test_parse_bank_falls_back_without_a_key_map(make_albank: Callable[..., bytes]) -> None:
    blob = bytearray(make_albank())
    struct.pack_into('>I', blob, _SOUND + 4, 0)
    zone = _parsed(bytes(blob))['instruments'][0][0]
    assert (zone['key_min'], zone['key_max'], zone['key_base']) == (0, 127, 60)


def test_parse_bank_falls_back_without_an_envelope(make_albank: Callable[..., bytes]) -> None:
    blob = bytearray(make_albank())
    struct.pack_into('>I', blob, _SOUND, 0)
    zone = _parsed(bytes(blob))['instruments'][0][0]
    assert (zone['attack'], zone['decay'], zone['release']) == (0, 0, 0)


def test_parse_bank_falls_back_without_a_loop(make_albank: Callable[..., bytes]) -> None:
    blob = bytearray(make_albank())
    struct.pack_into('>I', blob, _WAVE_TABLE + 0x0C, 0)
    assert _parsed(bytes(blob))['instruments'][0][0]['loop'] is False


@pytest.mark.parametrize(('offset', 'value'), [(_SOUND + 8, 0), (_WAVE_TABLE + 0x10, 0), (_BOOK, 3),
                                               (0x50, 0), (_SOUND + 8, 0x60000)])
def test_parse_bank_drops_a_malformed_sound(make_albank: Callable[..., bytes], offset: int,
                                            value: int) -> None:
    blob = bytearray(make_albank())
    struct.pack_into('>I', blob, offset, value)
    assert _parsed(bytes(blob))['instruments'][0] == []


def test_parse_bank_drops_a_sound_that_is_not_adpcm(make_albank: Callable[..., bytes]) -> None:
    blob = bytearray(make_albank())
    blob[_WAVE_TABLE + 8] = 1
    assert _parsed(bytes(blob))['instruments'][0] == []


def test_parse_bank_treats_a_negative_zone_count_as_none(make_albank: Callable[..., bytes]) -> None:
    blob = bytearray(make_albank())
    struct.pack_into('>h', blob, 0x4E, -1)
    assert _parsed(bytes(blob))['instruments'][0] == []


def test_parse_bank_returns_none_without_a_sample_table(make_albank: Callable[..., bytes]) -> None:
    blob = bytearray(make_albank())
    struct.pack_into('>I', blob, _WAVE_TABLE + 4, 0x100000)  # Longer than the image.
    assert parse_bank(bytes(blob), 0) is None
