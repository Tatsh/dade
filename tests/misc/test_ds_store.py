"""Tests for the ``.DS_Store`` reader."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import plistlib
import struct

import pytest

from dade.common.exceptions import InvalidFormatError
from dade.misc.ds_store import read_ds_store

if TYPE_CHECKING:
    from pathlib import Path

    from .conftest import DSStoreBuilder


def test_read_ds_store_groups_records_by_name(ds_store_path: Path) -> None:
    entries = read_ds_store(ds_store_path)['entries']
    assert sorted(entries) == ['.', 'Photos', 'Readme.txt']
    assert sorted(entries['Readme.txt']) == ['cmmt', 'logS', 'modD', 'pBBk', 'ptbL']


def test_read_ds_store_reads_every_data_type(ds_store_path: Path) -> None:
    entries = read_ds_store(ds_store_path)['entries']
    assert entries['.']['vSrn'] == 1
    assert entries['Photos']['dscl'] is True
    assert entries['Photos']['icsp'] == 16
    assert entries['Readme.txt']['cmmt'] == 'メモ'
    assert entries['Readme.txt']['logS'] == 8192
    assert entries['Readme.txt']['modD'] == '2021-01-01T00:00:00+00:00'
    assert entries['Readme.txt']['ptbL'] == 'icnv'


def test_read_ds_store_decodes_a_property_list_blob(ds_store_path: Path) -> None:
    assert read_ds_store(ds_store_path)['entries']['.']['bwsp'] == {
        'ShowSidebar': True,
        'WindowBounds': '{{0, 0}, {770, 435}}'
    }


def test_read_ds_store_decodes_an_icon_position(ds_store_path: Path) -> None:
    assert read_ds_store(ds_store_path)['entries']['Photos']['Iloc'] == {
        'trailer': 'ffffffffffff0000',
        'x': 132,
        'y': 64
    }


def test_read_ds_store_decodes_a_window_frame(ds_store_path: Path) -> None:
    assert read_ds_store(ds_store_path)['entries']['.']['fwi0'] == {
        'bottom': 471,
        'left': 0,
        'right': 770,
        'top': 36,
        'trailer': '00000000',
        'view': 'icnv'
    }


def test_read_ds_store_reports_an_unrecognised_blob_as_hex(ds_store_path: Path) -> None:
    assert read_ds_store(ds_store_path)['entries']['Readme.txt']['pBBk'] == {
        'hex': '626f6f6b',
        'length': 4
    }


def test_read_ds_store_reports_the_structure(ds_store_path: Path) -> None:
    structure = read_ds_store(ds_store_path)['structure']
    assert structure['header']['alignment'] == 1
    assert structure['header']['magic'] == 'Bud1'
    # The allocator is written after the blocks, and its offset therefore clears the header.
    assert structure['header']['allocator_offset'] > 32
    assert structure['header']['allocator_size'] == 4 + 4 + 256 * 4 + 4 + 9 + 32 * 4
    assert len(structure['blocks']) == 3
    assert all(block['size'] & (block['size'] - 1) == 0 for block in structure['blocks'])
    assert structure['directories']['DSDB']['page_size'] == 0x1000
    assert structure['directories']['DSDB']['records'] == 11
    assert len(structure['free_list']) == 32


def test_read_ds_store_walks_an_internal_node_in_order(ds_store_branching: Path) -> None:
    entries = read_ds_store(ds_store_branching)['entries']
    assert list(entries) == ['Alpha', 'Beta', 'Gamma', 'Delta', 'Echo']
    assert [entry['vSrn'] for entry in entries.values()] == [1, 2, 3, 4, 5]


def test_read_ds_store_reports_an_unreadable_timestamp_as_stored(
        ds_store_builder: type[DSStoreBuilder], tmp_path: Path) -> None:
    builder = ds_store_builder()
    node = builder.add(
        ds_store_builder.leaf((ds_store_builder.record('Far', 'modD', 'dutc',
                                                       struct.pack('>q', 2 ** 62)),)))
    path = tmp_path / '.DS_Store'
    path.write_bytes(builder.build((('DSDB', builder.add(ds_store_builder.master(node))),)))
    assert read_ds_store(path)['entries']['Far']['modD'] == 2 ** 62


def test_read_ds_store_decodes_a_core_foundation_date_blob(ds_store_builder: type[DSStoreBuilder],
                                                           tmp_path: Path) -> None:
    builder = ds_store_builder()
    node = builder.add(
        ds_store_builder.leaf((ds_store_builder.record(
            'Far', 'modD', 'blob',
            struct.pack('>I', 8) + struct.pack('<d', 600000000.0)),)))
    path = tmp_path / '.DS_Store'
    path.write_bytes(builder.build((('DSDB', builder.add(ds_store_builder.master(node))),)))
    assert read_ds_store(path)['entries']['Far']['modD'] == '2020-01-06T10:40:00+00:00'


def test_read_ds_store_reports_an_unreadable_core_foundation_date_as_stored(
        ds_store_builder: type[DSStoreBuilder], tmp_path: Path) -> None:
    builder = ds_store_builder()
    node = builder.add(
        ds_store_builder.leaf((ds_store_builder.record(
            'Far', 'moDD', 'blob',
            struct.pack('>I', 8) + struct.pack('<d', 1e20)),)))
    path = tmp_path / '.DS_Store'
    path.write_bytes(builder.build((('DSDB', builder.add(ds_store_builder.master(node))),)))
    assert read_ds_store(path)['entries']['Far']['moDD'] == pytest.approx(1e20)


def test_read_ds_store_converts_nested_property_list_values(ds_store_builder: type[DSStoreBuilder],
                                                            tmp_path: Path) -> None:
    builder = ds_store_builder()
    plist = plistlib.dumps(
        {
            'arrangeBy': ['name', 'kind'],
            'backgroundColor': b'\xff\x00\xff',
            'installDate': datetime(2020, 1, 1),  # ruff: ignore[call-datetime-without-tzinfo]
            'reference': plistlib.UID(5)
        },
        fmt=plistlib.FMT_BINARY)
    node = builder.add(
        ds_store_builder.leaf((ds_store_builder.record('Far', 'icvp', 'blob',
                                                       struct.pack('>I', len(plist)) + plist),)))
    path = tmp_path / '.DS_Store'
    path.write_bytes(builder.build((('DSDB', builder.add(ds_store_builder.master(node))),)))
    assert read_ds_store(path)['entries']['Far']['icvp'] == {
        'arrangeBy': ['name', 'kind'],
        'backgroundColor': {
            'hex': 'ff00ff',
            'length': 3
        },
        'installDate': '2020-01-01T00:00:00',
        'reference': 5
    }


def test_read_ds_store_reports_a_malformed_property_list_as_hex(
        ds_store_builder: type[DSStoreBuilder], tmp_path: Path) -> None:
    data = b'bplist00' + bytes(8)
    builder = ds_store_builder()
    node = builder.add(
        ds_store_builder.leaf((ds_store_builder.record('Far', 'icvp', 'blob',
                                                       struct.pack('>I', len(data)) + data),)))
    path = tmp_path / '.DS_Store'
    path.write_bytes(builder.build((('DSDB', builder.add(ds_store_builder.master(node))),)))
    assert read_ds_store(path)['entries']['Far']['icvp'] == {'hex': data.hex(), 'length': len(data)}


def test_read_ds_store_rejects_a_file_that_is_not_a_database(tmp_path: Path) -> None:
    path = tmp_path / '.DS_Store'
    path.write_bytes(struct.pack('>I4sIII', 1, b'Bud0', 0x2000, 8, 0x2000))
    with pytest.raises(InvalidFormatError, match='Not a Buddy allocator file'):
        read_ds_store(path)


@pytest.mark.parametrize(('offset', 'size', 'offset_copy', 'message'),
                         [(0x2000, 8, 0x3000, 'does not match its copy'),
                          (0, 8, 0, 'does not match its copy'), (0x2000, 0, 0x2000, 'has no size')])
def test_read_ds_store_rejects_a_broken_header(offset: int, size: int, offset_copy: int,
                                               message: str, tmp_path: Path) -> None:
    path = tmp_path / '.DS_Store'
    path.write_bytes(struct.pack('>I4sIII', 1, b'Bud1', offset, size, offset_copy))
    with pytest.raises(InvalidFormatError, match=message):
        read_ds_store(path)


def test_read_ds_store_rejects_a_truncated_file(ds_store_path: Path, tmp_path: Path) -> None:
    path = tmp_path / 'Truncated'
    path.write_bytes(ds_store_path.read_bytes()[:64])
    with pytest.raises(InvalidFormatError, match='Truncated at offset'):
        read_ds_store(path)


def test_read_ds_store_rejects_an_unknown_data_type(ds_store_builder: type[DSStoreBuilder],
                                                    tmp_path: Path) -> None:
    builder = ds_store_builder()
    node = builder.add(
        ds_store_builder.leaf((ds_store_builder.record('Odd', 'vSrn', 'zzzz', bytes(4)),)))
    path = tmp_path / '.DS_Store'
    path.write_bytes(builder.build((('DSDB', builder.add(ds_store_builder.master(node))),)))
    with pytest.raises(InvalidFormatError, match='Unknown record data type'):
        read_ds_store(path)


def test_read_ds_store_rejects_a_block_outside_the_table(ds_store_builder: type[DSStoreBuilder],
                                                         tmp_path: Path) -> None:
    builder = ds_store_builder()
    path = tmp_path / '.DS_Store'
    path.write_bytes(builder.build((('DSDB', builder.add(ds_store_builder.master(99))),)))
    with pytest.raises(InvalidFormatError, match='outside the table'):
        read_ds_store(path)


def test_read_ds_store_rejects_a_cycle(ds_store_builder: type[DSStoreBuilder],
                                       tmp_path: Path) -> None:
    builder = ds_store_builder()
    # Block zero is the sentinel a leaf opens with, and a node therefore never sits there.
    builder.add(bytes(8))
    root = len(builder.blocks)
    builder.add(
        ds_store_builder.branch(
            ((root, ds_store_builder.record('Loop', 'vSrn', 'long', struct.pack('>i', 1))),), root))
    path = tmp_path / '.DS_Store'
    path.write_bytes(builder.build((('DSDB', builder.add(ds_store_builder.master(root))),)))
    with pytest.raises(InvalidFormatError, match='part of a cycle'):
        read_ds_store(path)
