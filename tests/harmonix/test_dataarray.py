from __future__ import annotations

from typing import TYPE_CHECKING
import json
import math

import pytest

from destin.harmonix import dataarray

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def test_dtb_to_obj_all_element_types(make_dtb: Callable[..., bytes]) -> None:
    root, clean = dataarray.dtb_to_obj(
        make_dtb([1, 'two', 3.5, [4, 'five', [6]]], symbols=('src.dta', 'other.dta')))
    assert clean
    assert root == [1, 'two', 3.5, [4, 'five', [6]]]


def test_dtb_to_obj_empty_array(make_dtb: Callable[..., bytes]) -> None:
    assert dataarray.dtb_to_obj(make_dtb([])) == ([], True)


def test_dtb_to_obj_rounds_floats(make_dtb: Callable[..., bytes]) -> None:
    root, _ = dataarray.dtb_to_obj(make_dtb([0.7]))
    assert isinstance(root[0], float)
    assert math.isclose(root[0], 0.7, abs_tol=1e-6)


def test_dtb_to_obj_more_than_sixteen_elements(make_dtb: Callable[..., bytes]) -> None:
    # More than sixteen elements need a second tag word.
    items = list(range(20))
    assert dataarray.dtb_to_obj(make_dtb(items)) == (items, True)


@pytest.mark.parametrize('data', [b'', b'\x01\x00\x00\x00\x00'])
def test_dtb_to_obj_not_version_two(data: bytes) -> None:
    with pytest.raises(ValueError, match='Not a version-2 DataArray'):
        dataarray.dtb_to_obj(data)


def test_convert_writes_json(make_dtb: Callable[..., bytes], tmp_path: Path) -> None:
    source = tmp_path / 'config.txt.bin'
    source.write_bytes(make_dtb([['name', 'value']]))
    out = dataarray.convert(source)
    assert out == tmp_path / 'config.txt.json'
    assert source.exists()  # The original is left in place.
    assert json.loads(out.read_text(encoding='utf-8')) == [['name', 'value']]


def test_convert_rejects_trailing_bytes(make_dtb: Callable[..., bytes], tmp_path: Path) -> None:
    source = tmp_path / 'config.ui.bin'
    source.write_bytes(make_dtb([1]) + b'trailing')
    assert dataarray.convert(source) is None
    assert source.exists()


@pytest.mark.parametrize('data', [b'JUNK', b'\x02\x01\x00\x00\x00', b'\x02\x00\x00\x00\x00\x05'])
def test_convert_rejects_unparseable(data: bytes, tmp_path: Path) -> None:
    source = tmp_path / 'config.txt.bin'
    source.write_bytes(data)
    assert dataarray.convert(source) is None
