from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from destin.common.context import using_input_root
from destin.incoming.converters import ConversionError
from destin.incoming.converters.models import ian_to_obj, parse_ian
from destin.incoming.test_utils import ian_model
import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture

_VERTEX = (1.0, 2.0, 3.0, 0.0, 1.0, 0.0, 0.25, 0.75)


def test_parse_ian() -> None:
    model = parse_ian(ian_model([_VERTEX], [(0, 0, 0)], name='Line01'))
    assert model.name == 'Line01'
    assert model.vertices[0].position == (1.0, 2.0, 3.0)
    assert model.triangles == ((0, 0, 0),)


def test_parse_ian_too_small() -> None:
    with pytest.raises(ConversionError, match='too small'):
        parse_ian(bytes(8))


def test_parse_ian_offsets_past_end() -> None:
    data = bytearray(ian_model([_VERTEX], [(0, 0, 0)]))
    struct.pack_into('<H', data, 0x18, 9999)  # vertex count overflows the file
    with pytest.raises(ConversionError, match='past the end'):
        parse_ian(bytes(data))


def test_ian_to_obj_no_texture(tmp_path: Path) -> None:
    source = tmp_path / 'arrow.ian'
    source.write_bytes(ian_model([_VERTEX], [(0, 0, 0)]))
    outputs = ian_to_obj(source, tmp_path)
    assert len(outputs) == 2
    obj = (tmp_path / 'arrow.obj').read_text('utf-8')
    assert 'v 1.0 -2.0 3.0' in obj  # Y negated
    assert 'vt 0.25 0.25' in obj  # V flipped (1 - 0.75)
    assert 'map_Kd' not in (tmp_path / 'arrow.mtl').read_text('utf-8')


def test_ian_to_obj_with_texture(tmp_path: Path, mocker: MockerFixture) -> None:
    source = tmp_path / 'arrow.ian'
    source.write_bytes(ian_model([_VERTEX], [(0, 0, 0)]))
    mocker.patch('destin.incoming.converters.models.place_ian_texture', return_value='arrow.png')
    with using_input_root(tmp_path):
        outputs = ian_to_obj(source, tmp_path)
    assert len(outputs) == 3
    assert 'map_Kd arrow.png' in (tmp_path / 'arrow.mtl').read_text('utf-8')


def test_ian_to_obj_context_without_texture(tmp_path: Path, mocker: MockerFixture) -> None:
    source = tmp_path / 'arrow.ian'
    source.write_bytes(ian_model([_VERTEX], [(0, 0, 0)]))
    mocker.patch('destin.incoming.converters.models.place_ian_texture', return_value=None)
    with using_input_root(tmp_path):
        outputs = ian_to_obj(source, tmp_path)
    assert len(outputs) == 2
