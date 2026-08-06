"""Tests for :mod:`destin.xg2.soundfont` and :mod:`destin.xg2.albank`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from destin.xg2.albank import BANK_MAGIC, parse_bank
from destin.xg2.soundfont import (
    DRUM_BANK,
    bank_to_sf2,
    build_combined,
    build_sf2,
    make_zone,
    sample_meta,
)
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

    from destin.xg2.typing import ParsedBank, SampleMeta, Sf2Preset, Sf2Zone, SoundZone


def _sound_zone(sample: int = 0, key_min: int = 36) -> SoundZone:
    return {
        'sample': sample,
        'key_min': key_min,
        'key_max': key_min,
        'velocity_min': 0,
        'velocity_max': 127,
        'key_base': 60,
        'detune': 0,
        'loop_start': 0,
        'loop_end': 8,
        'loop': True,
        'pan': 64,
        'volume': 127,
        'attack': 1000,
        'decay': 2000,
        'release': 3000
    }


def _bank(*, percussion: bool = False) -> ParsedBank:
    return {
        'sample_rate': 22050,
        'instruments': [[_sound_zone()], []],
        'percussion': [_sound_zone(1, 38)] if percussion else [],
        'samples': [[1, 2, 3], [4, 5, 6]]
    }


def test_build_sf2_structure(sf2_sample: SampleMeta, sf2_zone: Sf2Zone,
                             sf2_preset: Sf2Preset) -> None:
    data = build_sf2([sf2_sample], [[sf2_zone]], [sf2_preset], 22050, 'Test')
    assert data[:4] == b'RIFF'
    assert data[8:12] == b'sfbk'
    for chunk in (b'INFO', b'sdta', b'pdta', b'phdr', b'pbag', b'pgen', b'inst', b'ibag', b'igen',
                  b'shdr'):
        assert chunk in data


def test_build_sf2_records_the_name(sf2_sample: SampleMeta, sf2_zone: Sf2Zone,
                                    sf2_preset: Sf2Preset) -> None:
    assert b'MyBank' in build_sf2([sf2_sample], [[sf2_zone]], [sf2_preset], 22050, 'MyBank')


def test_build_sf2_riff_size_matches(sf2_sample: SampleMeta, sf2_zone: Sf2Zone,
                                     sf2_preset: Sf2Preset) -> None:
    data = build_sf2([sf2_sample], [[sf2_zone]], [sf2_preset], 22050, 'Test')
    assert struct.unpack_from('<I', data, 4)[0] == len(data) - 8


def test_build_sf2_with_no_presets(sf2_sample: SampleMeta) -> None:
    data = build_sf2([sf2_sample], [], [], 22050, 'Empty')
    assert b'EOP' in data
    assert b'EOI' in data


def test_build_sf2_sorts_presets(sf2_sample: SampleMeta, sf2_zone: Sf2Zone) -> None:
    presets: list[Sf2Preset] = [{
        'bank': DRUM_BANK,
        'program': 0,
        'name': 'Drums',
        'instrument': 0
    }, {
        'bank': 0,
        'program': 1,
        'name': 'First',
        'instrument': 0
    }]
    data = build_sf2([sf2_sample], [[sf2_zone]], presets, 22050, 'Test')
    assert data.index(b'First') < data.index(b'Drums')


def test_make_zone_maps_fields() -> None:
    zone = make_zone(_sound_zone())
    assert zone['root'] == 60
    assert zone['key_min'] == 36
    assert zone['sample'] == 0


def test_make_zone_applies_the_sample_offset() -> None:
    assert make_zone(_sound_zone(), 5)['sample'] == 5


def test_make_zone_applies_overrides() -> None:
    zone = make_zone(_sound_zone(), loop=False, key_min=10)
    assert zone['loop'] is False
    assert zone['key_min'] == 10


def test_sample_meta_carries_loop_points() -> None:
    meta = sample_meta(_bank())
    assert meta[0]['loop_start'] == 0
    assert meta[0]['loop_end'] == 8
    assert meta[0]['pcm'] == [1, 2, 3]


def test_sample_meta_covers_unused_samples() -> None:
    meta = sample_meta(_bank())
    assert len(meta) == 2
    assert meta[1]['loop_end'] == 0


def test_sample_meta_includes_percussion() -> None:
    assert sample_meta(_bank(percussion=True))[1]['loop_end'] == 8


def test_bank_to_sf2_skips_empty_instruments() -> None:
    data = bank_to_sf2(_bank(), 'Bank')
    assert data is not None
    assert b'prog000' in data
    assert b'prog001' not in data


def test_bank_to_sf2_returns_none_without_instruments() -> None:
    empty: ParsedBank = {'sample_rate': 22050, 'instruments': [[]], 'percussion': [], 'samples': []}
    assert bank_to_sf2(empty, 'Bank') is None


def test_parse_bank_rejects_a_missing_magic() -> None:
    assert parse_bank(b'\x00' * 64, 0) is None


def test_parse_bank_rejects_an_implausible_rate() -> None:
    rom = bytearray(b'\x00' * 0x100)
    rom[0:2] = BANK_MAGIC
    struct.pack_into('>I', rom, 4, 0x20)
    struct.pack_into('>H', rom, 0x20, 1)  # One instrument.
    struct.pack_into('>I', rom, 0x24, 96000)  # Out of range.
    assert parse_bank(bytes(rom), 0) is None


def test_parse_bank_rejects_a_zero_instrument_count() -> None:
    rom = bytearray(b'\x00' * 0x100)
    rom[0:2] = BANK_MAGIC
    struct.pack_into('>I', rom, 4, 0x20)
    struct.pack_into('>I', rom, 0x24, 22050)
    assert parse_bank(bytes(rom), 0) is None


def test_build_combined_rejects_a_bank_it_cannot_parse() -> None:
    with pytest.raises(ValueError, match='No ALBankFile could be parsed'):
        build_combined(b'\x00' * 64, 0)


def test_build_sf2_omits_optional_generators(sf2_sample: SampleMeta, sf2_zone: Sf2Zone,
                                             sf2_preset: Sf2Preset) -> None:
    zone: Sf2Zone = {**sf2_zone, 'attack': 0, 'decay': 0, 'release': 0, 'loop': False}
    assert build_sf2([sf2_sample], [[zone]], [sf2_preset], 22050, 'Test')[:4] == b'RIFF'


def test_build_sf2_falls_back_to_the_whole_sample(sf2_zone: Sf2Zone, sf2_preset: Sf2Preset) -> None:
    sample: SampleMeta = {'pcm': [1, 2, 3, 4], 'loop_start': 3, 'loop_end': 1}
    data = build_sf2([sample], [[sf2_zone]], [sf2_preset], 22050, 'Test')
    assert struct.unpack_from('<II', data, data.index(b's000') + 20) == (0, 4)


def test_build_combined_writes_the_percussion_kit(make_albank: Callable[..., bytes]) -> None:
    assert b'Drums' in build_combined(make_albank(percussion=True), 0)


def test_build_combined_borrows_a_fallback_kit(make_albank: Callable[..., bytes]) -> None:
    bank = make_albank()
    assert b'Drums' in build_combined(bank + bank, 0, len(bank))


def test_build_combined_ignores_a_fallback_it_cannot_parse(
        make_albank: Callable[..., bytes]) -> None:
    bank = make_albank()
    assert b'Drums' not in build_combined(bank + b'\x00' * 0x40, 0, len(bank))


def test_build_combined_drops_a_kit_key_off_the_keyboard(make_albank: Callable[..., bytes]) -> None:
    bank = make_albank()
    assert b'Drums' not in build_combined(bank + bank, 0, len(bank), 'ExtremeG', 1)
