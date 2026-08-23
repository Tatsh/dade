from __future__ import annotations

from typing import TYPE_CHECKING
import json
import struct

import pytest

from destin.common.context import using_input_root
from destin.incoming.converters import ConversionError
from destin.incoming.converters.models_dc import mbin_to_obj, mlbin_to_json
from destin.incoming.test_utils import mbin_pair

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture

_FACE_I0 = 0x108 + 4  # 0x90 header + 3 * 40-byte vertices, then the first face index.


def _write_pair(directory: Path, m_bin: bytes, ml_bin: bytes) -> Path:
    (directory / 'LEVEL_M.BIN').write_bytes(m_bin)
    (directory / 'LEVEL_ML.BIN').write_bytes(ml_bin)
    return directory / 'LEVEL_M.BIN'


def test_mbin_no_context(tmp_path: Path) -> None:
    m_bin, ml_bin = mbin_pair()
    source = _write_pair(tmp_path, m_bin, ml_bin)
    out = tmp_path / 'out'
    mbin_to_obj(source, out)
    obj = (out / 'LEVEL_M' / 'LEVEL_M_000.obj').read_text('utf-8')
    assert 'v 0.0 -0.0 0.0' in obj  # Y negated
    assert 'vn 0.0 -1.0 0.0' in obj
    assert 'vt 0.25 0.25' in obj  # V flipped
    assert 'f 1/1/1 2/2/2 3/3/3' in obj  # winding kept
    assert 'not resolved' in (out / 'LEVEL_M' / 'LEVEL_M_000.mtl').read_text('utf-8')


def test_mbin_with_textures(tmp_path: Path, mocker: MockerFixture) -> None:
    source = _write_pair(tmp_path, *mbin_pair(texture_index=8))
    out = tmp_path / 'out'
    mocker.patch('destin.incoming.converters.models_dc.find_level_pack',
                 return_value=tmp_path / 'pack.pvr')

    def fake_textures(_pack: Path, _indices: set[int], cache: Path, prefix: str) -> dict[int, str]:
        (cache / f'{prefix}_tex8.png').write_bytes(b'PNG')
        return {8: f'{prefix}_tex8.png'}

    mocker.patch('destin.incoming.converters.models_dc.place_pack_textures',
                 side_effect=fake_textures)
    with using_input_root(tmp_path):
        mbin_to_obj(source, out)
    assert (out / 'LEVEL_M' / 'LEVEL_M_000.png').is_file()
    assert 'map_Kd LEVEL_M_000.png' in (out / 'LEVEL_M' / 'LEVEL_M_000.mtl').read_text('utf-8')


def test_mbin_pack_not_found(tmp_path: Path, mocker: MockerFixture) -> None:
    source = _write_pair(tmp_path, *mbin_pair())
    mocker.patch('destin.incoming.converters.models_dc.find_level_pack', return_value=None)
    with using_input_root(tmp_path):
        mbin_to_obj(source, tmp_path / 'out')
    assert 'not resolved' in (tmp_path / 'out' / 'LEVEL_M' / 'LEVEL_M_000.mtl').read_text('utf-8')


def test_mbin_deduplicates_offsets(tmp_path: Path) -> None:
    source = _write_pair(tmp_path, *mbin_pair(extra_offsets=(0,)))
    out = tmp_path / 'out'
    mbin_to_obj(source, out)
    assert (out / 'LEVEL_M' / 'LEVEL_M_000.obj').is_file()
    assert not (out / 'LEVEL_M' / 'LEVEL_M_001.obj').exists()


def test_mbin_missing_index(tmp_path: Path) -> None:
    (tmp_path / 'X_M.BIN').write_bytes(mbin_pair()[0])
    with pytest.raises(ConversionError, match='No matching'):
        mbin_to_obj(tmp_path / 'X_M.BIN', tmp_path / 'out')


def test_mbin_vertex_pointer_overflow(tmp_path: Path) -> None:
    m_bin, ml_bin = mbin_pair()
    buffer = bytearray(m_bin)
    struct.pack_into('<I', buffer, 0x1c, 0x9999)  # vertices pointer past the end
    source = _write_pair(tmp_path, bytes(buffer), ml_bin)
    with pytest.raises(ConversionError, match='no decodable'):
        mbin_to_obj(source, tmp_path / 'out')


def test_mbin_bad_index(tmp_path: Path) -> None:
    m_bin, ml_bin = mbin_pair()
    buffer = bytearray(m_bin)
    struct.pack_into('<I', buffer, _FACE_I0, 99)  # index out of range -> no triangles
    source = _write_pair(tmp_path, bytes(buffer), ml_bin)
    with pytest.raises(ConversionError, match='no decodable'):
        mbin_to_obj(source, tmp_path / 'out')


def test_mbin_header_past_end(tmp_path: Path) -> None:
    m_bin, _ = mbin_pair()
    ml_bin = struct.pack('<II', 0x9999, 0xffffffff)  # offset beyond the file
    source = _write_pair(tmp_path, m_bin, ml_bin)
    with pytest.raises(ConversionError, match='no decodable'):
        mbin_to_obj(source, tmp_path / 'out')


def test_mlbin_to_json(tmp_path: Path) -> None:
    source = tmp_path / 'LEVEL_ML.BIN'
    source.write_bytes(mbin_pair()[1])
    obj = json.loads(mlbin_to_json(source, tmp_path).read_text('utf-8'))
    assert obj == {'count': 1, 'offsets': [0]}


def test_mlbin_without_sentinel(tmp_path: Path) -> None:
    source = tmp_path / 'A_ML.BIN'
    source.write_bytes(struct.pack('<I', 7))  # no terminator within the data
    obj = json.loads(mlbin_to_json(source, tmp_path).read_text('utf-8'))
    assert obj['offsets'] == [7]
