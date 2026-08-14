"""Tests for :py:mod:`destin.rhythmin.aep`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from destin.rhythmin.aep import AepIndex, entry_to_json, index_to_json, read_aep_index
import pytest

if TYPE_CHECKING:
    from pathlib import Path


def test_header(aep_index_bytes: bytes) -> None:
    index = AepIndex(aep_index_bytes)
    assert index.header.group_id == 7
    assert index.frame_names == ('TONE_00_1', 'TONE_L1_2_LIGHT', 'OVERFLOWING')
    assert index.layer_names == ('ROOT', 'STAR')
    assert index.user_names == ('JACKET00', 'JACKET01')


def test_sprite_records(aep_index_bytes: bytes) -> None:
    records = AepIndex(aep_index_bytes).sprite_records
    assert [tuple(record) for record in records] == [(252, 252, 10, 20), (170, 178, 0, 2048),
                                                     (300, 10, 2000, 0)]
    assert records[0].page == 0
    assert records[1].page == 1
    assert records[0].fits is True
    # The third record runs past the 2048-wide page, which is how a mis-based table shows up.
    assert records[2].fits is False


def test_layer_numbers_and_entries(aep_index_bytes: bytes) -> None:
    index = AepIndex(aep_index_bytes)
    assert index.layer_numbers == (0, 2)
    assert [entry.entry_type for entry in index.frame_entries] == [0, -1, 3, -1]
    assert [entry.type_name
            for entry in index.frame_entries] == ['sprite', 'terminator', 'group', 'terminator']


def test_layer_chain(aep_index_bytes: bytes) -> None:
    index = AepIndex(aep_index_bytes)
    assert [entry.entry_type for entry in index.layer_chain('ROOT')] == [0, -1]
    star = index.layer_chain('STAR')
    assert [entry.entry_type for entry in star] == [3, -1]
    assert star[0].anchor_x == 3
    assert star[0].anchor_y == 4


def test_layer_chain_rejects_an_unknown_layer(aep_index_bytes: bytes) -> None:
    with pytest.raises(KeyError, match='is not a layer name'):
        AepIndex(aep_index_bytes).layer_chain('NOPE')


def test_position_channel(aep_index_bytes: bytes) -> None:
    index = AepIndex(aep_index_bytes)
    keys = index.position_channel(index.frame_entries[0].position_channel)
    assert [tuple(key) for key in keys] == [(0, 10, 20), (5, 30, 40)]


def test_color_channel_reads_its_components_signed(aep_index_bytes: bytes) -> None:
    index = AepIndex(aep_index_bytes)
    keys = index.color_channel(index.frame_entries[2].color_channel)
    assert [tuple(key) for key in keys] == [(0, 10, 20), (3, -1, -2)]


def test_absent_channels_yield_no_keys(aep_index_bytes: bytes) -> None:
    index = AepIndex(aep_index_bytes)
    assert index.position_channel(0) == ()
    assert index.color_channel(0) == ()


def test_find(aep_index_bytes: bytes) -> None:
    index = AepIndex(aep_index_bytes)
    frame = index.find('TONE_00_1')
    assert len(frame) == 1
    assert frame[0].block == 'frame'
    assert frame[0].ordinal == 0
    assert frame[0].sprite is not None
    user = index.find('JACKET01')
    assert user[0].block == 'user'
    assert user[0].ordinal == 1
    assert user[0].sprite is None
    assert index.find('NOPE') == ()


def test_index_to_json(aep_index_bytes: bytes) -> None:
    rendered = index_to_json(AepIndex(aep_index_bytes))
    assert rendered['groupId'] == 7
    assert [record['name'] for record in rendered['spriteRecords']] == list(rendered['frameNames'])
    assert rendered['spriteRecords'][2]['fits'] is False
    assert len(rendered['frameEntries']) == 4


def test_index_to_json_names_only(aep_index_bytes: bytes) -> None:
    rendered = index_to_json(AepIndex(aep_index_bytes), names_only=True)
    assert 'frameEntries' not in rendered
    assert 'spriteRecords' not in rendered
    assert rendered['layerNames'] == ['ROOT', 'STAR']


def test_entry_to_json_decodes_channels(aep_index_bytes: bytes) -> None:
    index = AepIndex(aep_index_bytes)
    rendered = entry_to_json(index, index.frame_entries[2])
    assert rendered['typeName'] == 'group'
    assert rendered['positionKeys'] == [{
        'frame': 0,
        'x': 10,
        'y': 20
    }, {
        'frame': 5,
        'x': 30,
        'y': 40
    }]
    assert rendered['colorKeys'][1] == {'frame': 3, 'color': -1, 'alpha': -2}


def test_read_aep_index(aep_index_file: Path) -> None:
    assert read_aep_index(aep_index_file).header.group_id == 7


def test_rejects_a_short_file() -> None:
    with pytest.raises(ValueError, match='Too short for an AEP index header'):
        AepIndex(b'\0' * 8)


def _index_with_frame_names(tail: bytes) -> AepIndex:
    """Build an index whose frame-name block is the given bytes, valid or not."""
    data = bytearray(b'\0' * 28)
    struct.pack_into('<hhiiiii', data, 4, 0, 0, 24, 0, 0, 24, 24)
    return AepIndex(bytes(data) + tail)


def test_rejects_a_name_block_with_no_terminating_byte() -> None:
    with pytest.raises(ValueError, match='Unterminated name block'):
        _ = _index_with_frame_names(b'name-with-no-NUL').frame_names


def test_rejects_a_name_block_with_no_terminating_empty_string() -> None:
    with pytest.raises(ValueError, match='runs past the end of the file'):
        _ = _index_with_frame_names(b'name\0').frame_names
