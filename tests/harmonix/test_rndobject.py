from __future__ import annotations

from typing import TYPE_CHECKING
import json
import math
import struct

import pytest

from dade.common.exceptions import InvalidFormatError
from dade.harmonix import rndobject

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

_IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 5.0, 6.0, 7.0)


def _matrix(values: tuple[float, ...] = _IDENTITY) -> bytes:
    return struct.pack('<12f', *values)


def _name(name: str) -> bytes:
    return name.encode() + b'\x00'


def _with_matrix(head: bytes) -> bytes:
    return head + bytes(-len(head) % 4) + _matrix()  # Keep the transform 4-byte aligned.


def _view(version: int = 3) -> bytes:
    return _with_matrix(struct.pack('<I', version) + _name('floor.mesh') + _name('floor.tex'))


def _tnm(version: int = 2) -> bytes:
    return _with_matrix(struct.pack('<I', version) + _name('spin.mesh') + _name('child.tnm'))


def _mmesh(version: int = 0) -> bytes:
    return _with_matrix(struct.pack('<I', version) + _name('cube.mesh'))


def _lnm(version: int = 0) -> bytes:
    return _with_matrix(struct.pack('<I', version) + _name('lamp.lit') + _name('self.lnm'))


def _arena(version: int = 4) -> bytes:
    return struct.pack('<I', version) + _name('sleeve_01.view') + _name('sleeve_02.view')


def _mat(version: int = 7, blend_mode: int = 3, *, texture: str | None = 'screen01.tex') -> bytes:
    body = struct.pack('<III', version, 0, blend_mode)
    if texture is not None:
        body += struct.pack('<I', 1) + _name(texture)
    return body


def _lit(version: int = 1, light_type: int = 2) -> bytes:
    data = bytearray(200)
    struct.pack_into('<I', data, 0, version)
    struct.pack_into('<12f', data, 0x08, *_IDENTITY)
    struct.pack_into('<12f', data, 0x38, *_IDENTITY)
    struct.pack_into('<3f', data, 0x7C, 0.5, 0.25, 0.75)
    struct.pack_into('<f', data, 0xAC, 1.0)
    struct.pack_into('<f', data, 0xB0, 0.5)
    struct.pack_into('<f', data, 0xB4, 50.0)
    struct.pack_into('<f', data, 0xB8, 2.0)
    struct.pack_into('<I', data, 0xC4, light_type)
    return bytes(data)


def _env(version: int = 0, *, with_fog: bool = True) -> bytes:
    head = struct.pack('<I', version) + bytes(9) + struct.pack('<I', 1) + _name('Omni01.lit')
    if not with_fog:
        return head
    fog = (struct.pack('<4f', 0.1, 0.2, 0.3, 1.0) + struct.pack('<f', 0.0) +
           struct.pack('<f', 1.0) + struct.pack('<f', 1.0) +
           struct.pack('<4f', 0.0, 0.0, 0.2, 1.0) + struct.pack('<I', 3))
    return head + fog


def _tmov(version: int = 2, *, timed: bool = False) -> bytes:
    if timed:
        head = struct.pack('<III', version, 0, 1) + struct.pack('<I', 0) + struct.pack('<f', 1.0)
        head += struct.pack('<f', 12.0) + struct.pack('<I', 0)
    else:
        head = struct.pack('<III', version, 0, 0) + struct.pack('<I', 0)
    return (head + _name('tutorial1.gif') + struct.pack('<II', 1, 0) + _name('screen01.tex'))


def test_view_to_json() -> None:
    meta = rndobject.view_to_json(_view())
    assert meta['version'] == 3
    assert meta['mesh'] == 'floor.mesh'
    assert meta['references'] == ['floor.mesh', 'floor.tex']
    assert meta['transform'] == list(_IDENTITY)


def test_tnm_to_json() -> None:
    meta = rndobject.tnm_to_json(_tnm())
    assert meta['version'] == 2
    assert meta['mesh_refs'] == ['spin.mesh']
    assert meta['tnm_refs'] == ['child.tnm']
    assert meta['transforms'] == [list(_IDENTITY)]


def test_mmesh_to_json() -> None:
    meta = rndobject.mmesh_to_json(_mmesh())
    assert meta['mesh'] == 'cube.mesh'
    assert meta['instance_transforms'] == [list(_IDENTITY)]


def test_lnm_to_json() -> None:
    meta = rndobject.lnm_to_json(_lnm())
    assert meta['lit_refs'] == ['lamp.lit']
    assert meta['transforms'] == [list(_IDENTITY)]


def test_arena_to_json() -> None:
    meta = rndobject.arena_to_json(_arena())
    assert meta['version'] == 4
    assert meta['view_refs'] == ['sleeve_01.view', 'sleeve_02.view']


def test_mat_to_json() -> None:
    meta = rndobject.mat_to_json(_mat())
    assert meta['version'] == 7
    assert meta['blend_mode'] == 3
    assert meta['textures'] == ['screen01.tex']


def test_mat_to_json_no_texture() -> None:
    assert rndobject.mat_to_json(_mat(texture=None))['textures'] is None


def test_lit_to_json() -> None:
    meta = rndobject.lit_to_json(_lit())
    assert meta['type'] == 2
    assert meta['color'] == [0.5, 0.25, 0.75]
    assert math.isclose(meta['range'], 50.0)
    assert math.isclose(meta['intensity'], 2.0)
    assert meta['local_xfm'] == list(_IDENTITY)


def test_env_to_json() -> None:
    meta = rndobject.env_to_json(_env())
    assert meta['lights'] == ['Omni01.lit']
    assert meta['fog_mode'] == 'vert_linear'
    assert math.isclose(meta['fog_end'], 1.0)


def test_env_to_json_partial() -> None:
    meta = rndobject.env_to_json(_env(with_fog=False))
    assert meta['lights'] == ['Omni01.lit']
    assert 'fog_mode' not in meta


def test_tmov_to_json() -> None:
    meta = rndobject.tmov_to_json(_tmov())
    assert meta['movie'] == 'tutorial1.gif'
    assert meta['tex'] == 'screen01.tex'
    assert meta['frames'] == 1
    assert meta['fps'] is None


def test_tmov_to_json_timed() -> None:
    fps = rndobject.tmov_to_json(_tmov(timed=True))['fps']
    assert fps is not None
    assert math.isclose(fps, 12.0)


def test_convert_writes_sidecar(tmp_path: Path) -> None:
    source = tmp_path / 'floor.view'
    source.write_bytes(_view())
    out = rndobject.convert(source)
    assert out == tmp_path / 'floor.view.json'
    assert out is not None
    assert source.exists()
    assert json.loads(out.read_text(encoding='utf-8'))['mesh'] == 'floor.mesh'


def test_convert_returns_none_on_junk(tmp_path: Path) -> None:
    source = tmp_path / 'bad.lit'
    source.write_bytes(b'\xff' * 16)
    assert rndobject.convert(source) is None
    assert not (tmp_path / 'bad.lit.json').exists()


def test_convert_returns_none_on_unknown_suffix(tmp_path: Path) -> None:
    source = tmp_path / 'thing.bin'
    source.write_bytes(_view())
    assert rndobject.convert(source) is None


def test_tmov_to_json_without_body() -> None:
    meta = rndobject.tmov_to_json(struct.pack('<IIII', 2, 0, 0, 0))
    assert meta['movie'] is None
    assert meta['frames'] is None
    assert meta['tex'] is None


def test_tmov_to_json_unterminated_movie_name() -> None:
    meta = rndobject.tmov_to_json(struct.pack('<IIII', 2, 0, 0, 0) + b'tutorial1.gif')
    assert meta['movie'] == 'tutorial1.gif'
    assert meta['frames'] is None


@pytest.mark.parametrize('parser', [
    rndobject.view_to_json, rndobject.tnm_to_json, rndobject.mmesh_to_json, rndobject.lnm_to_json,
    rndobject.arena_to_json
])
def test_scene_graph_parsers_reject_short_data(
        parser: Callable[[bytes], Mapping[str, object]]) -> None:
    with pytest.raises(InvalidFormatError, match='too short'):
        parser(b'\x00\x00\x00')


@pytest.mark.parametrize(('parser', 'match', 'data'),
                         [(rndobject.mat_to_json, 'Rnd::Mat', struct.pack('<III', 9, 0, 0)),
                          (rndobject.lit_to_json, 'Rnd::Light', bytes(200)),
                          (rndobject.env_to_json, 'Rnd::Environ', struct.pack('<I', 1) + bytes(16)),
                          (rndobject.tmov_to_json, 'Rnd::Movie', struct.pack('<III', 9, 0, 0))])
def test_leaf_parsers_reject_wrong_format(parser: Callable[[bytes], Mapping[str, object]],
                                          match: str, data: bytes) -> None:
    with pytest.raises(InvalidFormatError, match=match):
        parser(data)


def test_env_to_json_unknown_fog_mode() -> None:
    # The trailing u32 is the fog mode; a value past the known modes is reported verbatim.
    assert rndobject.env_to_json(_env()[:-4] + struct.pack('<I', 99))['fog_mode'] == '99'
