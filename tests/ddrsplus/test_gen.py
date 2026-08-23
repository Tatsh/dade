"""Tests for :py:mod:`destin.ddrsplus.gen`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

from destin.common.exceptions import InvalidFormatError
from destin.ddrsplus.gen import (
    DIFFICULTY_SLOTS,
    SHAKE_SLOTS,
    parse_chart_table,
    parse_metadata,
    read_gen,
    split_gen,
)

from .conftest import ARTIST, LEVELS, MAX_COMBOS, MUSIC_ID, NAME_ENGLISH

if TYPE_CHECKING:
    from collections.abc import Callable


def test_the_directory_yields_every_populated_section(make_gen: Callable[..., bytes]) -> None:
    assert [section.slot for section in split_gen(make_gen())] == list(range(8))


def test_sections_get_the_extension_their_slot_implies(make_gen: Callable[..., bytes]) -> None:
    assert [s.extension for s in split_gen(make_gen())] == [
        'mp3', 'mp3', 'pvr', 'ssq', 'ssq', 'info', 'tbl', 'tbl'
    ]


def test_an_empty_slot_is_skipped(make_gen: Callable[..., bytes]) -> None:
    data = bytearray(make_gen())
    struct.pack_into('<II', data, 7 * 8, 0, 0)
    assert 7 not in {section.slot for section in split_gen(bytes(data))}


def test_the_enciphered_sections_are_flagged(make_gen: Callable[..., bytes]) -> None:
    flagged = {s.slot for s in split_gen(make_gen()) if s.is_enciphered}
    assert flagged == {0, 1, 3, 4}


def test_reading_deciphers_the_enciphered_sections(make_gen: Callable[..., bytes]) -> None:
    assert read_gen(make_gen())[0][1].startswith(b'\xff\xfb')


def test_a_short_file_is_rejected() -> None:
    with pytest.raises(InvalidFormatError, match='Too short'):
        split_gen(b'')


def test_a_section_running_past_the_end_is_rejected() -> None:
    data = bytearray(64)
    struct.pack_into('<II', data, 0, 64, 999)
    with pytest.raises(InvalidFormatError, match='past the'):
        split_gen(bytes(data))


def test_the_metadata_carries_the_identity(make_metadata: Callable[..., bytes]) -> None:
    metadata = parse_metadata(make_metadata())
    assert metadata.music_id == MUSIC_ID
    assert metadata.title_english == NAME_ENGLISH
    assert metadata.artist == ARTIST


def test_the_music_id_is_big_endian(make_metadata: Callable[..., bytes]) -> None:
    assert parse_metadata(make_metadata(music_id=0x0103)).music_id == 0x0103


def test_the_name_prefers_english(make_metadata: Callable[..., bytes]) -> None:
    assert parse_metadata(make_metadata()).name == NAME_ENGLISH


def test_the_levels_are_four_standard_then_two_shake(make_metadata: Callable[..., bytes]) -> None:
    assert parse_metadata(make_metadata()).levels == LEVELS


def test_an_unset_groove_override_reads_as_none(make_metadata: Callable[..., bytes]) -> None:
    assert parse_metadata(make_metadata()).overrides[0] == (None,) * 5


def test_a_set_groove_override_is_kept(make_metadata: Callable[..., bytes]) -> None:
    data = make_metadata(overrides=((1, 2, 3, 4, 5),) * 6)
    assert parse_metadata(data).overrides[0] == (1, 2, 3, 4, 5)


def test_the_metadata_json_names_the_shake_slots(make_metadata: Callable[..., bytes]) -> None:
    rendered = parse_metadata(make_metadata()).to_json()
    assert [entry['difficulty'] for entry in rendered['shake']] == list(SHAKE_SLOTS)


def test_the_metadata_json_names_the_standard_slots(make_metadata: Callable[..., bytes]) -> None:
    rendered = parse_metadata(make_metadata()).to_json()
    assert [entry['difficulty'] for entry in rendered['standard']] == list(DIFFICULTY_SLOTS)


def test_a_short_metadata_section_is_rejected() -> None:
    with pytest.raises(InvalidFormatError, match='short of'):
        parse_metadata(b'')


def test_the_chart_table_carries_the_header(make_chart_table: Callable[..., bytes]) -> None:
    table = parse_chart_table(make_chart_table())
    assert (table.music_time, table.measures, table.max_bpm, table.min_bpm) == (98, 65, 159, 158)


def test_the_chart_table_carries_a_combo_per_slot(make_chart_table: Callable[..., bytes]) -> None:
    assert parse_chart_table(make_chart_table()).max_combos == MAX_COMBOS


def test_a_zero_combo_marks_a_missing_chart(make_chart_table: Callable[..., bytes]) -> None:
    rendered = parse_chart_table(make_chart_table(combos=(0, 74, 155, 0))).to_json()
    assert [entry['present'] for entry in rendered['charts']] == [False, True, True, False]


def test_each_slot_has_five_groove_values(make_chart_table: Callable[..., bytes]) -> None:
    assert all(len(groove) == 5 for groove in parse_chart_table(make_chart_table()).grooves)


def test_a_short_chart_table_is_rejected() -> None:
    with pytest.raises(InvalidFormatError, match='short of'):
        parse_chart_table(b'')
