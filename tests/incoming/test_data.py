from __future__ import annotations

from typing import TYPE_CHECKING
import json

import pytest

from dade.incoming.converters import ConversionError, UnsupportedFormatError
from dade.incoming.converters.data import bin_to_json, ctl_to_json
from dade.incoming.test_utils import ctl_records

if TYPE_CHECKING:
    from pathlib import Path


def test_heightfield(tmp_path: Path) -> None:
    source = tmp_path / 'h.bin'
    source.write_bytes(bytes(526338))
    obj = json.loads(bin_to_json(source, tmp_path).read_text('utf-8'))
    assert obj['type'] == 'heightfield'
    assert len(obj['heights']) == 513 * 513


def test_tile_flags(tmp_path: Path) -> None:
    source = tmp_path / 't.bin'
    source.write_bytes(bytes(32768))
    obj = json.loads(bin_to_json(source, tmp_path).read_text('utf-8'))
    assert obj['type'] == 'tile_flags'
    assert obj['water_bit'] == 0x2000


def test_bin_unknown_size(tmp_path: Path) -> None:
    source = tmp_path / 'x.bin'
    source.write_bytes(bytes(100))
    with pytest.raises(UnsupportedFormatError, match='terrain'):
        bin_to_json(source, tmp_path)


def test_ctl(tmp_path: Path) -> None:
    source = tmp_path / 'p.ctl'
    source.write_bytes(ctl_records(3))
    obj = json.loads(ctl_to_json(source, tmp_path).read_text('utf-8'))
    assert obj['frame_count'] == 2
    assert len(obj['frames']) == 2
    assert obj['header'] == {'axis_x': 0, 'axis_y': 0, 'flags': 0, 'mode': 0}


def test_ctl_not_multiple(tmp_path: Path) -> None:
    source = tmp_path / 'b.ctl'
    source.write_bytes(bytes(20))
    with pytest.raises(ConversionError, match='16-byte'):
        ctl_to_json(source, tmp_path)
