from __future__ import annotations

from typing import TYPE_CHECKING, Any
import json
import math
import struct

import pytest

from dade.monopoly08.meshes import EXTENSIONS, convert

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

_VERTEX_PAD = b'\x7f\x7f\xff\xff'
"""Filler making each vertex 16 bytes wide and hostile to a mis-guessed stride."""
_FLOAT_VERTICES: tuple[tuple[float, float, float], ...] = ((-1.5, 0.5, -2.5), (1.5, -0.5, -1.25),
                                                           (0.5, 1.5, -3.0), (-0.5, -1.5, -2.0))
_CLEAN_STRIP = struct.pack('>8H', 0, 1, 2, 3, 0xFFFF, 3, 2, 1)
"""A four-vertex strip, a restart, then a second strip."""
_DEGENERATE_STRIP = struct.pack('>8H', 0, 1, 1, 2, 0xFFFF, 3, 2, 1)
"""A strip whose first two triangles are degenerate stitching."""
_QUANTIZED_VERTICES: tuple[tuple[int, int, int], ...] = ((1000, 2000, 3000), (40000, 5000, 60000),
                                                         (7000, 8000, 9000), (10000, 11000, 65000))
_NAMES = (b'wt_base_cm\x00wt_base_nm\x00wt_base_sm\x00plainmat\x00wt_base_cm\x00abcd\x00'
          b'bump_only_nm\x00')
_UNTYPED_BLOCK = b'\x40\x00' * 8
"""Sixteen bytes that no candidate stride can split into vertices plus indices."""
_SHORT_BLOCK = b'\x40\x00' * 4
"""Eight bytes, below the minimum geometry span."""

_STRIP_A: tuple[tuple[int, int, int],
                ...] = ((100, 100, 500), (110, 105, 500), (120, 110, 500), (130, 115, 500),
                        (65000, 65000, 500), (140, 120, 500), (150, 125, 500), (160, 130, 500))
_STRIP_B: tuple[tuple[int, int, int], ...] = ((200, 200, 500),)


def _float_block(vertices: Sequence[tuple[float, float, float]], indices: bytes) -> bytes:
    return b''.join(struct.pack('>3f', *v) + _VERTEX_PAD for v in vertices) + indices


def _quantized_block(vertices: Sequence[tuple[int, int, int]], indices: bytes) -> bytes:
    return b''.join(struct.pack('>3H', *v) + _VERTEX_PAD * 2 + b'\x00\x00'
                    for v in vertices) + indices


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _obj_lines(path: Path, prefix: str) -> list[str]:
    lines = path.read_text(encoding='utf-8').splitlines()
    return [line for line in lines if line.startswith(prefix)]


# --------------------------------------------------------------------------- #
# Big-endian PH geometry                                                       #
# --------------------------------------------------------------------------- #


def test_convert_float_positions(make_mesh: Callable[..., bytes], tmp_path: Path) -> None:
    # The trailing zero words stand in for the block padding a real file has.
    source = _write(
        tmp_path, 'm.npm7',
        make_mesh(blocks=(_float_block(_FLOAT_VERTICES, _CLEAN_STRIP) + b'\x00\x00' * 2,)))
    obj_path, json_path, n_verts, n_tris = convert(source)
    assert obj_path == tmp_path / 'm.obj'
    assert json_path == tmp_path / 'm.json'
    assert (n_verts, n_tris) == (4, 3)
    assert _obj_lines(obj_path, 'v ') == [
        'v -1.500000 0.500000 -2.500000', 'v 1.500000 -0.500000 -1.250000',
        'v 0.500000 1.500000 -3.000000', 'v -0.500000 -1.500000 -2.000000'
    ]
    assert _obj_lines(obj_path, 'f ') == ['f 1 2 3', 'f 2 4 3', 'f 4 3 2']
    assert _obj_lines(obj_path, 'o ') == ['o submesh_0']
    assert not (tmp_path / 'm.mtl').exists()
    assert 'mtllib' not in obj_path.read_text()


def test_convert_quantized_positions(make_mesh: Callable[..., bytes], tmp_path: Path) -> None:
    source = _write(
        tmp_path, 'm.npm7',
        make_mesh(diag=(0.0002, 27.0, 0.0002),
                  bmin=(0.0, 0.0, 0.0),
                  bmax=(14.0, 27.0, 14.0),
                  blocks=(_quantized_block(_QUANTIZED_VERTICES, _DEGENERATE_STRIP),)))
    _obj_path, _json_path, n_verts, n_tris = convert(source)
    assert (n_verts, n_tris) == (4, 1)


def test_convert_writes_materials(make_mesh: Callable[..., bytes], tmp_path: Path) -> None:
    source = _write(tmp_path, 'm.npm7',
                    make_mesh(names=_NAMES, blocks=(_float_block(_FLOAT_VERTICES, _CLEAN_STRIP),)))
    obj_path, _json_path, _n_verts, _n_tris = convert(source)
    mtl = (tmp_path / 'm.mtl').read_text()
    assert 'newmtl wt_base\n' in mtl
    assert 'map_Kd wt_base_cm.png\n' in mtl
    assert 'map_Bump wt_base_nm.png\n' in mtl
    assert 'map_Ns wt_base_sm.png\n' in mtl
    assert 'newmtl plainmat\n' in mtl
    assert 'newmtl abcd' not in mtl
    assert 'newmtl bump_only\nKd 0.8 0.8 0.8\nmap_Bump bump_only_nm.png\n' in mtl
    assert 'mtllib m.mtl\n' in obj_path.read_text()
    assert _obj_lines(obj_path, 'usemtl ') == ['usemtl wt_base']


@pytest.mark.parametrize('block', [_SHORT_BLOCK, _UNTYPED_BLOCK])
def test_convert_skips_undecodable_blocks(make_mesh: Callable[..., bytes], block: bytes,
                                          tmp_path: Path) -> None:
    source = _write(tmp_path, 'm.npm7', make_mesh(blocks=(block,)))
    _obj_path, _json_path, n_verts, n_tris = convert(source)
    assert (n_verts, n_tris) == (0, 0)


def test_convert_multiple_submeshes(make_mesh: Callable[..., bytes], tmp_path: Path) -> None:
    block = _float_block(_FLOAT_VERTICES, _CLEAN_STRIP)
    source = _write(tmp_path, 'm.npm7', make_mesh(names=_NAMES, blocks=(block, block)))
    obj_path, _json_path, n_verts, n_tris = convert(source)
    assert (n_verts, n_tris) == (8, 6)
    assert _obj_lines(obj_path, 'o ') == ['o submesh_0', 'o submesh_1']
    assert _obj_lines(obj_path, 'f ')[-1] == 'f 8 7 6'


@pytest.mark.parametrize('magic', [b'NPM7', b'PPM7', b'RPM7'])
def test_convert_big_endian_variants(make_mesh: Callable[..., bytes], magic: bytes,
                                     tmp_path: Path) -> None:
    source = _write(tmp_path, 'm.npm7',
                    make_mesh(magic, blocks=(_float_block(_FLOAT_VERTICES, _CLEAN_STRIP),)))
    _obj_path, json_path, _n_verts, _n_tris = convert(source)
    assert json.loads(json_path.read_text())['format'] == magic.decode()


# --------------------------------------------------------------------------- #
# PS2 SPM7 / VIF geometry                                                      #
# --------------------------------------------------------------------------- #


def _vif_v3_16(make_vif_unpack: Callable[..., bytes], vertices: Sequence[tuple[int, int,
                                                                               int]]) -> bytes:
    return make_vif_unpack(2, 1, len(vertices), b''.join(struct.pack('<3H', *v) for v in vertices))


def test_convert_spm7(make_mesh: Callable[..., bytes], make_vif_unpack: Callable[..., bytes],
                      tmp_path: Path) -> None:
    stream = (
        bytes((0, 0, 0, 0x20)) + b'\x00' * 4  # STMASK.
        + bytes((0, 0, 0, 0x30)) + b'\x00' * 16  # STROW.
        + bytes((0, 0, 0, 0x31)) + b'\x00' * 16  # STCOL.
        + make_vif_unpack(0, 0, 2)  # An UNPACK that is not V3-16.
        + make_vif_unpack(2, 1, 0)  # A V3-16 UNPACK with no elements.
        + _vif_v3_16(make_vif_unpack, _STRIP_A) + _vif_v3_16(make_vif_unpack, _STRIP_B) + bytes(
            (0, 0, 0, 0x00)))  # NOP.
    source = _write(tmp_path, 'm.spm7', make_mesh(b'SPM7', stream=stream))
    obj_path, _json_path, n_verts, n_tris = convert(source)
    assert (n_verts, n_tris) == (9, 3)
    assert _obj_lines(obj_path, 'o ') == ['o submesh_0', 'o submesh_1']


def test_convert_spm7_without_positions(make_mesh: Callable[..., bytes], tmp_path: Path) -> None:
    source = _write(tmp_path, 'm.spm7', make_mesh(b'SPM7', stream=bytes((0, 0, 0, 0x00)) * 4))
    _obj_path, _json_path, n_verts, n_tris = convert(source)
    assert (n_verts, n_tris) == (0, 0)


def test_convert_spm7_with_a_flat_bounding_box(make_mesh: Callable[..., bytes],
                                               make_vif_unpack: Callable[..., bytes],
                                               tmp_path: Path) -> None:
    source = _write(
        tmp_path, 'm.spm7',
        make_mesh(b'SPM7',
                  bmin=(1.0, 1.0, 1.0),
                  bmax=(1.0, 1.0, 1.0),
                  stream=_vif_v3_16(make_vif_unpack, _STRIP_A)))
    _obj_path, _json_path, n_verts, n_tris = convert(source)
    assert (n_verts, n_tris) == (8, 6)


# --------------------------------------------------------------------------- #
# JSON metadata                                                                #
# --------------------------------------------------------------------------- #


def test_metadata(make_mesh: Callable[..., bytes], tmp_path: Path) -> None:
    source = _write(
        tmp_path, 'm.npm7',
        make_mesh(names=_NAMES,
                  sections=((3, 0x90),),
                  blocks=(_float_block(_FLOAT_VERTICES, _CLEAN_STRIP),)))
    _obj_path, json_path, _n_verts, _n_tris = convert(source)
    meta: dict[str, Any] = json.loads(json_path.read_text())
    assert meta['format'] == 'NPM7'
    assert meta['fileSize'] == len(source.read_bytes())
    assert meta['matrixOffset'] == 0x20
    assert meta['geometryOffset'] == 0xC8
    assert meta['transform'][0] == [1.0, 0.0, 0.0, 0.0]
    assert meta['bounds'] == {
        'pivot': [0.0, 0.0, 0.0, 0.0],
        'min': [-4.0, -4.0, -4.0, 0.0],
        'max': [4.0, 4.0, 4.0, 0.0]
    }
    assert meta['sectionTable'] == [{'count': 3, 'offset': 0x90}, {'count': 0, 'offset': 0}]
    assert [n['name'] for n in meta['materialNames']] == [
        'wt_base_cm', 'wt_base_nm', 'wt_base_sm', 'plainmat', 'wt_base_cm', 'bump_only_nm'
    ]


@pytest.mark.parametrize(('sections', 'expected'), [((), 9), (((1, 0x200),), 9)])
def test_metadata_section_table_lengths(make_mesh: Callable[..., bytes],
                                        sections: Sequence[tuple[int, int]], expected: int,
                                        tmp_path: Path) -> None:
    source = _write(
        tmp_path, 'm.npm7',
        make_mesh(sections=sections, blocks=(_float_block(_FLOAT_VERTICES, _CLEAN_STRIP),)))
    _obj_path, json_path, _n_verts, _n_tris = convert(source)
    assert len(json.loads(json_path.read_text())['sectionTable']) == expected


def test_convert_rejects_an_unknown_magic(make_mesh: Callable[..., bytes], tmp_path: Path) -> None:
    source = _write(tmp_path, 'm.npm7',
                    make_mesh(b'XXXX', blocks=(_float_block(_FLOAT_VERTICES, _CLEAN_STRIP),)))
    with pytest.raises(ValueError, match='not NPM7/PPM7/RPM7/SPM7'):
        convert(source)


def test_extensions() -> None:
    assert {'.npm7', '.ppm7', '.rpm7', '.spm7'} == EXTENSIONS


# --------------------------------------------------------------------------- #
# Skinned glTF                                                                 #
# --------------------------------------------------------------------------- #

_IDENTITY = (1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0)
_ARM = (0.0, -1, 0, 0, 1, 0.0, 0, 0, 0, 0, 1.0, 0, 0, -2, 0, 1.0)
"""Inverse bind, for row vectors, of a bone turned 90 degrees about Z and two units along -X."""
_OTHER = (2.0, 0, 0, 0, 0, 2.0, 0, 0, 0, 0, 2.0, 0, 0, 0, 0, 1.0)
_SKIN_FORMAT = 0x22011
_RIGID_FORMAT = 0x19


def _skinned_vertex(position: tuple[int, int, int], pairs: Sequence[tuple[int, int]]) -> bytes:
    return struct.pack('>3Hxx', *position) + bytes(v for pair in pairs for v in pair) + bytes(8)


_SKINNED_VERTICES = (_skinned_vertex(
    (1000, 0, 0), ((0, 255), (0xFF, 0), (0, 0), (0, 0))) + _skinned_vertex(
        (0, 1000, 0), ((0, 128), (1, 127), (0xFF, 0), (0xFF, 0))) + _skinned_vertex(
            (0, 0, 1000), ((1, 255), (0, 0), (0, 0), (0, 0))))
_BONES = (('root', -1, _IDENTITY), ('arm', 0, _ARM))
_SUBMESHES = ((_SKIN_FORMAT, 24, _SKINNED_VERTICES, 3, (0, 1, 2),
               b'\x01\x00'), (_RIGID_FORMAT, 16, bytes(48), 3, (0, 1, 2), None),
              (_SKIN_FORMAT, 24, _SKINNED_VERTICES, 3, (0, 1), b'\x01\x00'))


def _glb(path: Path) -> tuple[dict[str, Any], bytes]:
    data = path.read_bytes()
    length = struct.unpack_from('<I', data, 12)[0]
    return json.loads(data[20:20 + length]), data[28 + length:]


def _accessor_bytes(document: dict[str, Any], blob: bytes, index: int) -> bytes:
    view = document['bufferViews'][document['accessors'][index]['bufferView']]
    return blob[view['byteOffset']:view['byteOffset'] + view['byteLength']]


def _bank_motion(make_ska: Callable[..., bytes]) -> bytes:
    return make_ska((0x80, 0x40, 0xA0, 0x44),
                    frame_floats=struct.pack('>6f', 1, 0, 0, 2, 0, 0),
                    frame_rotations=struct.pack('>16h', 0, 0, 0, 4096, 0, 0, 0, 4096, 0, 0, 0,
                                                -4096, 0, 0, 2896, 2896),
                    counts={
                        'float_bones': 1,
                        'rotation_bytes_per_frame': 16
                    },
                    static_rotations=struct.pack('>8h', 0, 0, 0, 4096, 0, 0, 0, 4096),
                    static_translations=bytes(24))


def _populate(directory: Path, make_skeleton: Callable[..., bytes], make_bank: Callable[..., bytes],
              make_ska: Callable[..., bytes]) -> None:
    files = {
        'skeleton.bin': (
            '00007892', make_skeleton(0x77, (-1, 0, 0, 1), (_OTHER, _IDENTITY, _ARM, _ARM))),
        'larger.bin': ('00007892',
                       make_skeleton(0x77, (-1, 0, 0, 1, 0),
                                     (_OTHER, _IDENTITY, _ARM, _ARM, _OTHER))),
        'unrelated.bin': ('00007892', make_skeleton(0x99, (-1,), (_OTHER,))),
        'bank.bin': ('0000694b',
                     make_bank(0x77, [(2, 0, _bank_motion(make_ska))],
                               [('wave', 0, 2.0, 0x02010000, 0x16000001)])),
        'short.bin': ('0000694b', make_bank(0x77, [(1, 0, make_ska((0x20,)))], [])),
        'stranger.bin': ('0000694b', make_bank(0x99, [(1, 0, make_ska((0x20,)))], []))
    }
    lines = ['name\tmagic\toffset\tsize\tnameHash\ttypeId', 'missing.bin\t0\t0\t0\t0\t0000694b']
    for name, (type_id, data) in files.items():
        (directory / name).write_bytes(data)
        lines.append(f'{name}\t0\t0\t{len(data)}\t0\t{type_id}')
    (directory / '_manifest.tsv').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def test_convert_writes_a_skinned_glb(make_skinned_mesh: Callable[..., bytes],
                                      make_skeleton: Callable[...,
                                                              bytes], make_bank: Callable[...,
                                                                                          bytes],
                                      make_ska: Callable[..., bytes], tmp_path: Path) -> None:
    _populate(tmp_path, make_skeleton, make_bank, make_ska)
    convert(_write(tmp_path, 'm.npm7', make_skinned_mesh(_BONES, _SUBMESHES)))
    document, blob = _glb(tmp_path / 'm.glb')
    assert [node['name']
            for node in document['nodes']] == ['m', 'bone_00', 'root', 'bone_02', 'arm']
    assert document['scenes'][0]['nodes'] == [0, 1]
    assert document['nodes'][1]['children'] == [2, 3]
    assert document['nodes'][4]['translation'] == pytest.approx([-2, 0, 0])
    assert document['nodes'][4]['rotation'] == pytest.approx([0, 0, math.sqrt(0.5), math.sqrt(0.5)])
    assert document['skins'][0]['joints'] == [1, 2, 3, 4]
    (primitive,) = document['meshes'][0]['primitives']
    attributes = primitive['attributes']
    assert _accessor_bytes(document, blob, attributes['JOINTS_0']) == bytes(
        (3, 0, 0, 0, 3, 1, 0, 0, 1, 0, 0, 0))
    assert _accessor_bytes(document, blob, attributes['WEIGHTS_0']) == bytes(
        (255, 0, 0, 0, 128, 127, 0, 0, 255, 0, 0, 0))
    assert struct.unpack('<9f', _accessor_bytes(
        document, blob, attributes['POSITION'])) == pytest.approx((1, 0, 0, 0, 1, 0, 0, 0, 1))
    (animation,) = document['animations']
    assert animation['name'] == 'wave'
    targets = [(c['target']['node'], c['target']['path']) for c in animation['channels']]
    assert targets == [(1, 'rotation'), (1, 'translation'), (2, 'rotation'), (2, 'translation'),
                       (3, 'rotation'), (4, 'rotation'), (4, 'translation')]
    counts = [document['accessors'][s['output']]['count'] for s in animation['samplers']]
    assert counts == [1, 1, 1, 1, 1, 2, 2]
    rotations = struct.unpack('<8f',
                              _accessor_bytes(document, blob, animation['samplers'][5]['output']))
    assert rotations == pytest.approx((0, 0, 0, 1, 0, 0, math.sqrt(0.5), math.sqrt(0.5)), abs=1e-4)


def test_convert_skinned_glb_without_a_skeleton(make_skinned_mesh: Callable[..., bytes],
                                                tmp_path: Path) -> None:
    convert(_write(tmp_path, 'm.npm7', make_skinned_mesh(_BONES, _SUBMESHES[:1])))
    document, blob = _glb(tmp_path / 'm.glb')
    assert [node['name'] for node in document['nodes']] == ['m', 'root', 'arm']
    assert 'animations' not in document
    attributes = document['meshes'][0]['primitives'][0]['attributes']
    assert _accessor_bytes(document, blob, attributes['JOINTS_0']) == bytes(
        (1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0))


def test_convert_skinned_glb_with_many_bones(make_skinned_mesh: Callable[..., bytes],
                                             tmp_path: Path) -> None:
    bones = [('root', -1, _IDENTITY), *((f'b{i}', 0, _IDENTITY) for i in range(1, 300))]
    palette = bytes((0, 0))
    convert(
        _write(
            tmp_path, 'm.npm7',
            make_skinned_mesh(bones,
                              ((_SKIN_FORMAT, 24, _SKINNED_VERTICES, 3, (0, 1, 2), palette),))))
    document, _blob = _glb(tmp_path / 'm.glb')
    joints = document['meshes'][0]['primitives'][0]['attributes']['JOINTS_0']
    assert document['accessors'][joints]['componentType'] == 5123


@pytest.mark.parametrize('submeshes', [_SUBMESHES[1:2], _SUBMESHES[2:]])
def test_convert_skips_a_glb_without_skinned_triangles(make_skinned_mesh: Callable[..., bytes],
                                                       submeshes: Sequence[Any],
                                                       tmp_path: Path) -> None:
    convert(_write(tmp_path, 'm.npm7', make_skinned_mesh(_BONES, submeshes)))
    assert not (tmp_path / 'm.glb').exists()


def test_convert_stops_at_a_short_submesh(make_skinned_mesh: Callable[..., bytes],
                                          tmp_path: Path) -> None:
    convert(
        _write(tmp_path, 'm.npm7',
               make_skinned_mesh(_BONES, (_SUBMESHES[0], _SUBMESHES[0]), block_size=0x10)))
    document, _blob = _glb(tmp_path / 'm.glb')
    assert len(document['meshes'][0]['primitives']) == 1
