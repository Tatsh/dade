"""Tests for Mario Kart World BFRES model conversion."""
from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING, Any, cast
import json
import struct

from PIL import Image
import numpy as np
import pytest
import zstandard

from dade.mkw.model import decode_model, model_lod_count

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture


def _archive() -> bytearray:
    data = bytearray(0x1800)
    data[:4] = b'FRES'
    struct.pack_into('<I', data, 0x28, 0x180)
    struct.pack_into('<Q', data, 0xB0, 0x160)
    struct.pack_into('<II', data, 0x164, 0x300, 0x1000)
    data[0x180:0x184] = b'FMDL'
    struct.pack_into('<Q', data, 0x1A8, 0x200)
    struct.pack_into('<Q', data, 0x1B8, 0x300)
    struct.pack_into('<HH', data, 0x1EA, 1, 1)
    data[0x200:0x204] = b'FSHP'
    struct.pack_into('<QQ', data, 0x210, 0x400, 0x280)
    data[0x25B] = 1
    struct.pack_into('<IIIII', data, 0x2A0, 0x100, 3, 1, 3, 0)
    data[0x300:0x304] = b'FMAT'
    struct.pack_into('<Q', data, 0x308, 0x810)
    data[0x400:0x404] = b'FVTX'
    struct.pack_into('<Q', data, 0x408, 0x680)
    struct.pack_into('<Q', data, 0x438, 0x480)
    data[0x44C] = 2
    struct.pack_into('<I', data, 0x450, 3)
    struct.pack_into('<I', data, 0x480, 20)
    struct.pack_into('<QIH', data, 0x680, 0x800, 0, 0)
    struct.pack_into('<QIH', data, 0x690, 0x806, 0x1205, 12)
    struct.pack_into('<H3s', data, 0x800, 3, b'_p0')
    struct.pack_into('<H3s', data, 0x806, 3, b'_u0')
    struct.pack_into('<H8s', data, 0x810, 8, b'Material')
    for index, position in enumerate(((0, 0, 0), (1, 0, 0), (0, 1, 0))):
        struct.pack_into('<3f2e', data, 0x1000 + index * 20, *position, 0.0, 0.0)
    struct.pack_into('<3H', data, 0x1100, 0, 1, 2)
    return data


def _document(glb: bytes) -> dict[str, Any]:
    return cast('dict[str, Any]', json.loads(glb[20:20 + struct.unpack_from('<I', glb, 12)[0]]))


def _texture_names(archive: bytearray, *names: str) -> None:
    struct.pack_into('<Q', archive, 0x320, 0x700)
    archive[0x3A3] = len(names)
    for index, name in enumerate(names):
        pointer = 0x830 + index * 0x30
        struct.pack_into('<Q', archive, 0x700 + index * 8, pointer)
        encoded = name.encode()
        struct.pack_into(f'<H{len(encoded)}s', archive, pointer, len(encoded), encoded)


def _png(size: tuple[int, int], color: tuple[int, int, int, int]) -> bytes:
    stream = BytesIO()
    Image.new('RGBA', size, color).save(stream, format='PNG')
    return stream.getvalue()


def _compressed_png(directory: Path, name: str, png: bytes) -> None:
    (directory / f'{name}.bntx.zs').write_bytes(zstandard.ZstdCompressor().compress(png))


def _image(glb: bytes, document: dict[str, Any], index: int) -> Image.Image:
    images = document['images']
    views = document['bufferViews']
    json_size = struct.unpack_from('<I', glb, 12)[0]
    view = views[images[index]['bufferView']]
    start = 28 + json_size + view.get('byteOffset', 0)
    return Image.open(BytesIO(glb[start:start + view['byteLength']]))


def test_model_lod_count_uses_highest_shape_level() -> None:
    archive = _archive()
    struct.pack_into('<H', archive, 0x1EA, 2)
    archive[0x25B] = 3
    archive[0x2BB] = 5
    assert model_lod_count(bytes(archive)) == 5


def test_decode_model_produces_indexed_mesh() -> None:
    glb = decode_model(bytes(_archive()), 'simple')
    assert glb is not None
    document = _document(glb)
    primitive = document['meshes'][0]['primitives'][0]
    assert primitive['material'] == 0
    assert 'TEXCOORD_0' in primitive['attributes']
    assert document['materials'][0]['name'] == 'Material'


def test_model_rejects_invalid_header() -> None:
    with pytest.raises(ValueError, match='Invalid BFRES archive'):
        decode_model(b'bad', 'invalid')
    with pytest.raises(ValueError, match='Invalid BFRES archive'):
        model_lod_count(b'bad')


def test_decode_model_skips_animation_archive() -> None:
    archive = _archive()
    archive[0x180:0x184] = b'FANM'
    assert decode_model(bytes(archive), 'animation') is None
    assert model_lod_count(bytes(archive)) == 0


@pytest.mark.parametrize(('pool_info', 'pool_size', 'pool_start'), [(0, 0x300, 0x1000),
                                                                    (0x160, 0, 0x1000),
                                                                    (0x160, 0x300, 0x1800)])
def test_decode_model_rejects_invalid_pool(pool_info: int, pool_size: int, pool_start: int) -> None:
    archive = _archive()
    struct.pack_into('<Q', archive, 0xB0, pool_info)
    struct.pack_into('<II', archive, 0x164, pool_size, pool_start)
    with pytest.raises(ValueError, match='Invalid BFRES GPU pool'):
        decode_model(bytes(archive), 'bad-pool')


def test_decode_model_skips_unavailable_lod() -> None:
    assert decode_model(bytes(_archive()), 'simple', lod=1) is None


def test_decode_model_rejects_invalid_shape_and_vertex() -> None:
    archive = _archive()
    archive[0x200:0x204] = b'BAD!'
    with pytest.raises(ValueError, match='Invalid BFRES shape table'):
        decode_model(bytes(archive), 'bad-shape')
    archive[0x200:0x204] = b'FSHP'
    archive[0x400:0x404] = b'BAD!'
    with pytest.raises(ValueError, match='Invalid BFRES vertex table'):
        decode_model(bytes(archive), 'bad-vertex')


def test_decode_model_rejects_invalid_material() -> None:
    archive = _archive()
    archive[0x300:0x304] = b'BAD!'
    with pytest.raises(ValueError, match='Invalid BFRES material table'):
        decode_model(bytes(archive), 'bad-material')


@pytest.mark.parametrize(('topology', 'index_format', 'expected'), [(2, 1, 'topology'),
                                                                    (3, 9, 'index format')])
def test_decode_model_rejects_unsupported_mesh(topology: int, index_format: int,
                                               expected: str) -> None:
    archive = _archive()
    struct.pack_into('<II', archive, 0x2A4, topology, index_format)
    with pytest.raises(ValueError, match=expected):
        decode_model(bytes(archive), 'bad-mesh')


def test_decode_model_accepts_32_bit_indices() -> None:
    archive = _archive()
    struct.pack_into('<I', archive, 0x2A8, 2)
    struct.pack_into('<3I', archive, 0x1100, 0, 1, 2)
    assert decode_model(bytes(archive), 'wide-indices') is not None


@pytest.mark.parametrize('indices', [(0, 0, 1), (0, 1, 3), (0, 0, 0)])
def test_decode_model_skips_degenerate_or_invalid_faces(indices: tuple[int, int, int]) -> None:
    archive = _archive()
    struct.pack_into('<3H', archive, 0x1100, *indices)
    assert decode_model(bytes(archive), 'bad-face') is None


def test_decode_model_skips_zero_area_face() -> None:
    archive = _archive()
    struct.pack_into('<3f', archive, 0x1028, 2.0, 0.0, 0.0)
    assert decode_model(bytes(archive), 'collinear') is None


def test_decode_model_skips_invalid_vertex_in_face() -> None:
    archive = _archive()
    struct.pack_into('<I', archive, 0x450, 11)
    for index in range(3, 11):
        struct.pack_into('<3f2e', archive, 0x1000 + index * 20, 0.0, 1.0, 0.0, 0.0, 0.0)
    struct.pack_into('<f', archive, 0x1000 + 10 * 20, 2000.0)
    struct.pack_into('<3H', archive, 0x1100, 0, 1, 10)
    assert decode_model(bytes(archive), 'invalid-face') is None


def test_decode_model_rejects_index_buffer_outside_archive() -> None:
    archive = _archive()
    struct.pack_into('<I', archive, 0x2A0, 0x800)
    with pytest.raises(ValueError, match='index buffer exceeds'):
        decode_model(bytes(archive), 'bad-indices')


@pytest.mark.parametrize(('stride', 'count', 'start'), [(0, 3, 0), (20, 0, 0), (20, 3, 0x800)])
def test_decode_model_rejects_invalid_vertex_storage(stride: int, count: int, start: int) -> None:
    archive = _archive()
    struct.pack_into('<I', archive, 0x480, stride)
    struct.pack_into('<I', archive, 0x450, count)
    struct.pack_into('<I', archive, 0x448, start)
    if start:
        with pytest.raises(ValueError, match='vertex buffer exceeds'):
            decode_model(bytes(archive), 'invalid-vertices')
    else:
        assert decode_model(bytes(archive), 'invalid-vertices') is None


def test_decode_model_rejects_missing_position_and_outliers() -> None:
    archive = _archive()
    struct.pack_into('<Q', archive, 0x680, 0x806)
    assert decode_model(bytes(archive), 'no-position') is None
    struct.pack_into('<Q', archive, 0x680, 0x800)
    struct.pack_into('<H', archive, 0x68C, 16)
    assert decode_model(bytes(archive), 'bad-position-offset') is None
    struct.pack_into('<H', archive, 0x68C, 0)
    struct.pack_into('<f', archive, 0x1000, 2000.0)
    assert decode_model(bytes(archive), 'outlier') is None


@pytest.mark.parametrize(
    ('format_', 'width', 'packed'), [(0x1205, 4, struct.pack('<2e', 0.25, 0.75)),
                                     (0x1705, 8, struct.pack('<2f', 0.25, 0.75)),
                                     (0x1201, 4, struct.pack('<2H', 16384, 49151)),
                                     (0x1202, 4, struct.pack('<2h', 8192, 24575)),
                                     (0x0901, 2, bytes((64, 191))), (0x0902, 2, bytes((32, 95)))])
def test_decode_model_accepts_uv_formats(format_: int, width: int, packed: bytes) -> None:
    archive = _archive()
    struct.pack_into('<I', archive, 0x698, format_)
    archive[0x100C:0x100C + width] = packed
    glb = decode_model(bytes(archive), 'uv-format')
    assert glb is not None
    assert 'TEXCOORD_0' in _document(glb)['meshes'][0]['primitives'][0]['attributes']


@pytest.mark.parametrize(('format_', 'offset'), [(0xFFFF, 12), (0x1205, 19)])
def test_decode_model_omits_unknown_or_truncated_uv(format_: int, offset: int) -> None:
    archive = _archive()
    struct.pack_into('<IH', archive, 0x698, format_, offset)
    glb = decode_model(bytes(archive), 'no-uv')
    assert glb is not None
    assert 'TEXCOORD_0' not in _document(glb)['meshes'][0]['primitives'][0]['attributes']


def test_decode_model_exports_packed_normals() -> None:
    archive = _archive()
    archive[0x44C] = 3
    struct.pack_into('<QIH', archive, 0x6A0, 0x850, 0x0E02, 16)
    struct.pack_into('<H3s', archive, 0x850, 3, b'_n0')
    for index in range(3):
        struct.pack_into('<I', archive, 0x1010 + index * 20, 511)
    glb = decode_model(bytes(archive), 'normal')
    assert glb is not None
    assert 'NORMAL' in _document(glb)['meshes'][0]['primitives'][0]['attributes']


def test_decode_model_omits_unsupported_normals() -> None:
    archive = _archive()
    archive[0x44C] = 3
    struct.pack_into('<QIH', archive, 0x6A0, 0x850, 0xFFFF, 16)
    struct.pack_into('<H3s', archive, 0x850, 3, b'_n0')
    glb = decode_model(bytes(archive), 'normal')
    assert glb is not None
    assert 'NORMAL' not in _document(glb)['meshes'][0]['primitives'][0]['attributes']


def test_decode_model_keeps_plain_material_without_uv() -> None:
    archive = _archive()
    archive[0x44C] = 1
    glb = decode_model(bytes(archive), 'plain')
    assert glb is not None
    document = _document(glb)
    assert document['meshes'][0]['primitives'][0]['material'] == 0
    assert len(document['materials']) == 1


def test_decode_model_embeds_masked_colour(tmp_path: Path, mocker: MockerFixture) -> None:
    archive = _archive()
    _texture_names(archive, 'Leaf_Alb', 'Leaf_Msk')
    _compressed_png(tmp_path, 'Leaf_Alb', _png((2, 2), (20, 30, 40, 255)))
    _compressed_png(tmp_path, 'Leaf_Msk', _png((2, 2), (0, 0, 0, 255)))
    mocker.patch('dade.mkw.model.decode_texture', side_effect=lambda data: data)
    glb = decode_model(bytes(archive), 'masked', tmp_path)
    assert glb is not None
    document = _document(glb)
    assert document['materials'][0]['alphaMode'] == 'MASK'
    with _image(glb, document, 0) as image:
        assert image.convert('RGBA').getchannel('A').getextrema() == (0, 0)


def test_decode_model_resizes_separate_mask(tmp_path: Path, mocker: MockerFixture) -> None:
    archive = _archive()
    _texture_names(archive, 'Leaf_Alb', 'Leaf_Msk')
    _compressed_png(tmp_path, 'Leaf_Alb', _png((4, 4), (20, 30, 40, 255)))
    _compressed_png(tmp_path, 'Leaf_Msk', _png((2, 2), (255, 255, 255, 255)))
    mocker.patch('dade.mkw.model.decode_texture', side_effect=lambda data: data)
    glb = decode_model(bytes(archive), 'masked', tmp_path)
    assert glb is not None
    with _image(glb, _document(glb), 0) as image:
        assert image.convert('RGBA').getchannel('A').getextrema() == (255, 255)


@pytest.mark.parametrize(('pointer', 'length'), [(0, 0), (0x810, 0), (0x810, 257)])
def test_decode_model_handles_invalid_material_name(pointer: int, length: int) -> None:
    archive = _archive()
    struct.pack_into('<Q', archive, 0x308, pointer)
    if pointer:
        struct.pack_into('<H', archive, pointer, length)
    glb = decode_model(bytes(archive), 'invalid-material-name')
    assert glb is not None
    assert not _document(glb)['materials'][0]['name']


def test_decode_model_resizes_bazaar_texture(tmp_path: Path, mocker: MockerFixture) -> None:
    archive = _archive()
    _texture_names(archive, 'Roof_Alb')
    _compressed_png(tmp_path, 'Roof_Alb', _png((1024, 512), (20, 30, 40, 255)))
    mocker.patch('dade.mkw.model.decode_texture', side_effect=lambda data: data)
    glb = decode_model(bytes(archive), 'Stage_ShyGuyBazaar.A', tmp_path)
    assert glb is not None
    with _image(glb, _document(glb), 0) as image:
        assert image.size == (512, 256)


def test_decode_model_references_shared_png(tmp_path: Path, mocker: MockerFixture) -> None:
    archive = _archive()
    _texture_names(archive, 'Roof_Alb')
    png = _png((2, 2), (20, 30, 40, 255))
    _compressed_png(tmp_path, 'Roof_Alb', png)
    mocker.patch('dade.mkw.model.decode_texture', side_effect=lambda data: data)
    external = tmp_path / 'textures/Tex'
    glb = decode_model(bytes(archive), 'Piece_Gridify', tmp_path, external_images=external)
    assert glb is not None
    assert (external / 'Roof_Alb.png').read_bytes() == png
    assert _document(glb)['images'][0]['uri'] == '../../textures/Tex/Roof_Alb.png'
    again = decode_model(bytes(archive), 'Piece_Gridify', tmp_path, external_images=external)
    assert again is not None
    assert _document(again)['images'][0]['uri'] == '../../textures/Tex/Roof_Alb.png'


def test_decode_model_uses_emissive_and_omits_missing_texture(tmp_path: Path,
                                                              mocker: MockerFixture) -> None:
    archive = _archive()
    _texture_names(archive, 'Ring_Emm')
    glb = decode_model(bytes(archive), 'missing-emissive', tmp_path)
    assert glb is not None
    assert 'pbrMetallicRoughness' not in _document(glb)['materials'][0]
    _compressed_png(tmp_path, 'Ring_Emm', _png((2, 2), (20, 30, 40, 255)))
    mocker.patch('dade.mkw.model.decode_texture', side_effect=lambda data: data)
    glb = decode_model(bytes(archive), 'emissive', tmp_path)
    assert glb is not None
    assert 'baseColorTexture' in _document(glb)['materials'][0]['pbrMetallicRoughness']


def test_decode_model_drops_texture_when_uv_missing(tmp_path: Path, mocker: MockerFixture) -> None:
    archive = _archive()
    archive[0x44C] = 1
    _texture_names(archive, 'Leaf_Alb')
    _compressed_png(tmp_path, 'Leaf_Alb', _png((2, 2), (20, 30, 40, 255)))
    mocker.patch('dade.mkw.model.decode_texture', side_effect=lambda data: data)
    glb = decode_model(bytes(archive), 'no-uv-texture', tmp_path)
    assert glb is not None
    document = _document(glb)
    primitive = document['meshes'][0]['primitives'][0]
    assert primitive['material'] == 1
    assert 'pbrMetallicRoughness' not in document['materials'][1]


def test_decode_model_omits_out_of_range_material() -> None:
    archive = _archive()
    struct.pack_into('<H', archive, 0x252, 1)
    archive[0x44C] = 1
    glb = decode_model(bytes(archive), 'missing-material')
    assert glb is not None
    assert 'material' not in _document(glb)['meshes'][0]['primitives'][0]


def test_decode_model_reuses_shared_texture(tmp_path: Path, mocker: MockerFixture) -> None:
    archive = _archive()
    shape = bytes(archive[0x200:0x260])
    archive[0xC00:0xC60] = shape
    archive[0xC60:0xCC0] = shape
    struct.pack_into('<H', archive, 0xCB2, 1)
    struct.pack_into('<Q', archive, 0x1A8, 0xC00)
    struct.pack_into('<H', archive, 0x1EA, 2)
    material = bytes(archive[0x300:0x3B0])
    archive[0x900:0x9B0] = material
    archive[0x9B0:0xA60] = material
    struct.pack_into('<Q', archive, 0x1B8, 0x900)
    struct.pack_into('<H', archive, 0x1EC, 2)
    struct.pack_into('<Q', archive, 0x920, 0x700)
    struct.pack_into('<Q', archive, 0x9D0, 0x700)
    archive[0x9A3] = 1
    archive[0xA53] = 1
    struct.pack_into('<Q', archive, 0x700, 0x830)
    struct.pack_into('<H8s', archive, 0x830, 8, b'Leaf_Alb')
    _compressed_png(tmp_path, 'Leaf_Alb', _png((2, 2), (20, 30, 40, 255)))
    mocker.patch('dade.mkw.model.decode_texture', side_effect=lambda data: data)
    glb = decode_model(bytes(archive), 'shared-texture', tmp_path)
    assert glb is not None
    document = _document(glb)
    assert len(document['meshes']) == 2
    assert len(document['images']) == 1


def _skinned_archive(*, influences: int = 2, smooth: int = 2, bones: int = 2) -> bytearray:
    archive = _archive()
    struct.pack_into('<I', archive, 0x480, 32)
    for index, position in enumerate(((0, 0, 0), (1, 0, 0), (0, 1, 0))):
        struct.pack_into('<3f2e', archive, 0x1000 + index * 32, *position, 0.0, 0.0)
    struct.pack_into('<Q', archive, 0x198, 0x1400)
    archive[0x1400:0x1404] = b'FSKL'
    struct.pack_into('<QQ', archive, 0x1410, 0x1480, 0x1540)
    struct.pack_into('<HHH', archive, 0x1438, bones, smooth, bones - smooth)
    struct.pack_into(f'<{bones}H', archive, 0x1540, *range(bones))
    for index, (name, parent, z) in enumerate((('Root', -1, 0.0), ('Arm', 0, 5.0))[:bones]):
        bone = 0x1480 + index * 0x58
        struct.pack_into('<Q', archive, bone, 0x1560 + index * 0x10)
        struct.pack_into(f'<H{len(name)}s', archive, 0x1560 + index * 0x10, len(name),
                         name.encode())
        struct.pack_into('<h', archive, bone + 0x22, parent)
        struct.pack_into('<3f4f3f', archive, bone + 0x30, 1, 1, 1, 0, 0, 0, 1, 0, 0, z)
    archive[0x25A] = influences
    struct.pack_into('<H', archive, 0x254, bones - 1)
    return archive


def _attribute(archive: bytearray, slot: int, name: str, format_: int, offset: int) -> None:
    archive[0x44C] = max(archive[0x44C], slot + 1)
    pointer = 0x860 + slot * 8
    struct.pack_into('<QIH', archive, 0x680 + slot * 16, pointer, format_, offset)
    struct.pack_into('<H3s', archive, pointer, 3, name.encode())


def _vertex_bytes(archive: bytearray, offset: int, value: bytes) -> None:
    for index in range(3):
        archive[0x1000 + index * 32 + offset:0x1000 + index * 32 + offset + len(value)] = value


def _accessor_values(glb: bytes, document: dict[str, Any], index: int, dtype: str) -> list[Any]:
    accessor = document['accessors'][index]
    view = document['bufferViews'][accessor['bufferView']]
    start = 28 + struct.unpack_from('<I', glb, 12)[0] + view['byteOffset']
    return cast(
        'list[Any]',
        np.frombuffer(glb[start:start + view['byteLength']], dtype).reshape(accessor['count'],
                                                                            -1).tolist())


def test_decode_model_binds_smooth_skin() -> None:
    archive = _skinned_archive()
    _attribute(archive, 2, '_i0', 0x0900, 16)
    _attribute(archive, 3, '_w0', 0x0900, 20)
    _vertex_bytes(archive, 16, bytes((0, 1)))
    _vertex_bytes(archive, 20, bytes((192, 64)))
    glb = decode_model(bytes(archive), 'skinned')
    assert glb is not None
    document = _document(glb)
    assert document['skins'][0]['joints'] == [0, 1]
    assert document['skins'][0]['skeleton'] == 0
    assert document['nodes'][0]['name'] == 'Root'
    assert document['nodes'][0]['children'] == [1]
    assert document['nodes'][2] == {'mesh': 0, 'skin': 0}
    assert document['scenes'][0]['nodes'] == [0, 2]
    attributes = document['meshes'][0]['primitives'][0]['attributes']
    assert _accessor_values(glb, document, attributes['JOINTS_0'], '<u2') == [[0, 1, 0, 0]] * 3
    assert _accessor_values(glb, document, attributes['WEIGHTS_0'],
                            '<f4') == [[0.75, 0.25, 0.0, 0.0]] * 3
    assert document['accessors'][attributes['POSITION']]['max'] == [1.0, 1.0, 0.0]


@pytest.mark.parametrize(('layout', 'dtype', 'components'), [(0x02, '<u1', 1), (0x09, '<u1', 2),
                                                             (0x0B, '<u1', 4), (0x12, '<u2', 2),
                                                             (0x15, '<u2', 4)])
def test_decode_model_reads_joint_layouts(layout: int, dtype: str, components: int) -> None:
    archive = _skinned_archive()
    _attribute(archive, 2, '_i0', layout << 8, 16)
    values = [1, 0, 1, 0][:components]
    _vertex_bytes(archive, 16, np.array(values, dtype).tobytes())
    glb = decode_model(bytes(archive), 'layout')
    assert glb is not None
    document = _document(glb)
    attributes = document['meshes'][0]['primitives'][0]['attributes']
    assert _accessor_values(glb, document, attributes['JOINTS_0'], '<u2') == [[1, 0, 0, 0]] * 3
    assert _accessor_values(glb, document, attributes['WEIGHTS_0'],
                            '<f4') == [[1.0, 0.0, 0.0, 0.0]] * 3


@pytest.mark.parametrize(('influences', 'format_', 'offset'), [(2, 0x0700, 16), (2, 0x1500, 28),
                                                               (0, 0x0900, 16)])
def test_decode_model_moves_shape_without_joints_to_shape_bone(influences: int, format_: int,
                                                               offset: int) -> None:
    archive = _skinned_archive(influences=influences)
    _attribute(archive, 2, '_i0', format_, offset)
    glb = decode_model(bytes(archive), 'shape-bone')
    assert glb is not None
    document = _document(glb)
    attributes = document['meshes'][0]['primitives'][0]['attributes']
    assert _accessor_values(glb, document, attributes['JOINTS_0'], '<u2') == [[1, 0, 0, 0]] * 3
    assert document['accessors'][attributes['POSITION']]['min'] == [0.0, 0.0, 5.0]


def test_decode_model_moves_rigid_entries() -> None:
    archive = _skinned_archive(smooth=1)
    _attribute(archive, 2, '_i0', 0x0200, 16)
    _vertex_bytes(archive, 16, bytes((1,)))
    glb = decode_model(bytes(archive), 'rigid')
    assert glb is not None
    document = _document(glb)
    attributes = document['meshes'][0]['primitives'][0]['attributes']
    assert _accessor_values(glb, document, attributes['JOINTS_0'], '<u2') == [[1, 0, 0, 0]] * 3
    assert document['accessors'][attributes['POSITION']]['max'] == [1.0, 1.0, 5.0]


def test_decode_model_omits_skin_for_single_bone() -> None:
    archive = _skinned_archive(smooth=1, bones=1)
    glb = decode_model(bytes(archive), 'single-bone')
    assert glb is not None
    document = _document(glb)
    assert 'skins' not in document
    assert document['nodes'] == [{'mesh': 0}]
    assert document['scenes'][0]['nodes'] == [0]
    assert 'JOINTS_0' not in document['meshes'][0]['primitives'][0]['attributes']


CLIP = {
    'bones': [{
        'base': {},
        'curves': [],
        'name': 'Arm'
    }],
    'frame_count': 1,
    'rotation': 'quaternion'
}


@pytest.mark.parametrize(('bones', 'smooth', 'expected'), [(2, 2, ['Model:Wave']), (1, 1, None)])
def test_decode_model_embeds_animations_only_with_skin(bones: int, smooth: int,
                                                       expected: list[str] | None) -> None:
    glb = decode_model(bytes(_skinned_archive(bones=bones, smooth=smooth)),
                       'animated',
                       animations=[('Model:Wave', CLIP)])
    assert glb is not None
    document = _document(glb)
    names = [animation['name']
             for animation in document['animations']] if 'animations' in document else None
    assert names == expected
