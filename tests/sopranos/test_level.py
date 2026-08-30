from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

from dade.common.exceptions import InvalidFormatError
from dade.sopranos.level import INDEX_OFFSET, RECORD_SIZE, extract, read_index

from .conftest import build_level

if TYPE_CHECKING:
    from pathlib import Path


def test_read_index_lists_sub_assets() -> None:
    entries = read_index(build_level({'a.TEX2': b'aaa', 'b.EGP2': b'bbbb'}))
    assert [(entry.name, entry.size) for entry in entries] == [('a.TEX2', 3), ('b.EGP2', 4)]


def test_read_index_ignores_leftover_bytes_after_the_name() -> None:
    raw = bytearray(build_level({'a.TEX2': b'aaa'}))
    # The cooker leaves whatever was in memory past the terminating NUL.
    raw[INDEX_OFFSET + 8 + 7:INDEX_OFFSET + 8 + 12] = b'\0junk'
    assert read_index(bytes(raw))[0].name == 'a.TEX2'


def test_read_index_skips_unused_slots() -> None:
    header = struct.pack('<I', 2) + bytes(12)
    used = struct.pack('<2I', INDEX_OFFSET + 2 * RECORD_SIZE, 2) + b'used'.ljust(0x20, b'\0')
    blank = struct.pack('<2I', 0, 0) + bytes(0x20)
    assert [e.name for e in read_index(header + used + blank + b'hi')] == ['used']


def test_read_index_skips_an_entry_running_past_the_end(caplog: pytest.LogCaptureFixture) -> None:
    header = struct.pack('<I', 1) + bytes(12)
    record = struct.pack('<2I', INDEX_OFFSET + RECORD_SIZE, 99) + b'far'.ljust(0x20, b'\0')
    with caplog.at_level('WARNING'):
        assert read_index(header + record + b'hi') == ()
    assert 'past the end' in caplog.text


def test_read_index_rejects_a_tiny_file() -> None:
    with pytest.raises(InvalidFormatError, match='too small'):
        read_index(b'abc')


def test_read_index_rejects_a_truncated_index() -> None:
    with pytest.raises(InvalidFormatError, match='runs past the end'):
        read_index(struct.pack('<I', 40) + bytes(12))


def test_extract_writes_each_sub_asset(tmp_path: Path) -> None:
    container = tmp_path / 'level.lvl'
    container.write_bytes(build_level({'a.TEX2': b'aaa', 'b.EGP2': b'bbbb'}))
    written = extract(container, tmp_path / 'out')
    assert [path.name for path in written] == ['a.TEX2', 'b.EGP2']
    assert (tmp_path / 'out' / 'b.EGP2').read_bytes() == b'bbbb'


def test_extract_skips_empty_sub_assets(tmp_path: Path) -> None:
    container = tmp_path / 'level.lvl'
    container.write_bytes(build_level({'a.TEX2': b'aaa', 'empty.SCR2': b''}))
    assert [path.name for path in extract(container, tmp_path / 'out')] == ['a.TEX2']


def test_extract_makes_no_directory_when_nothing_has_content(tmp_path: Path) -> None:
    container = tmp_path / 'level.lvl'
    container.write_bytes(build_level({'empty.SCR2': b''}))
    assert extract(container, tmp_path / 'out') == ()
    assert not (tmp_path / 'out').exists()
