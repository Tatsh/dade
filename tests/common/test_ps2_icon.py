from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
import json
import struct

from PIL import Image
import pytest

from dade.common import ps2_icon as icon
from dade.common.exceptions import InvalidFormatError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def test_icon_sys_to_json(make_icon_sys: Callable[..., bytes]) -> None:
    meta = icon.icon_sys_to_json(make_icon_sys())
    assert meta == {
        'magic': 'PS2D',
        'title_line_break': 5,
        'background_transparency': 32,
        'title': 'AMPLITUDE',
        'icon_normal': 'normal.ico',
        'icon_copy': 'copy.ico',
        'icon_delete': 'delete.ico'
    }


def test_icon_sys_to_json_decodes_shift_jis(make_icon_sys: Callable[..., bytes]) -> None:
    assert icon.icon_sys_to_json(make_icon_sys(title='セーブ'))['title'] == 'セーブ'


@pytest.mark.parametrize('data', [b'JUNK' + bytes(0x1C8), b'PS2D' + bytes(16)])
def test_icon_sys_to_json_not_an_icon_sys(data: bytes) -> None:
    with pytest.raises(InvalidFormatError, match=r'Not a `PS2D` icon\.sys'):
        icon.icon_sys_to_json(data)


def _document(data: bytes) -> dict[str, Any]:
    return cast('dict[str, Any]', json.loads(data[20:20 + struct.unpack_from('<I', data, 12)[0]]))


def test_read_ps2_icon(make_ps2_icon: Callable[..., bytes]) -> None:
    decoded = icon.read_ps2_icon(make_ps2_icon(vertices=6, anim=2))
    assert len(decoded.shapes) == 2
    assert decoded.shapes[1][1] == (100 / 4096, 1 + 200 / 4096, 300 / 4096)
    assert decoded.normals[0] == (0.0, 1.0, 0.0)
    assert decoded.texcoords[2] == (0.25, 0.125)
    assert decoded.colors[0] == (128, 64, 0, 128)
    assert (decoded.frame_length, decoded.speed, decoded.frames) == (120, 1.0, ((0, ((0.0,
                                                                                      1.0),)),))
    assert decoded.texture is not None
    assert decoded.texture[:8] == bytes((0, 64, 0, 255, 16, 192, 0, 255))


def test_read_ps2_icon_without_a_texture(make_ps2_icon: Callable[..., bytes]) -> None:
    assert icon.read_ps2_icon(make_ps2_icon(texture=b'')).texture is None
    assert icon.read_ps2_icon(make_ps2_icon(texture=b'', texture_type=0xF)).texture is None


def test_read_ps2_icon_decompresses_the_texture(make_ps2_icon: Callable[..., bytes]) -> None:
    runs = struct.pack('<HH', 0x3FFD, 0x7FFF) + struct.pack('<H3H', 0x10000 - 3, 0x1F, 0x3E0,
                                                            0x7C00)
    data = make_ps2_icon(texture=struct.pack('<I', len(runs)) + runs, texture_type=0xF)
    texture = icon.read_ps2_icon(data).texture
    assert texture is not None
    assert texture[:4] == bytes((248, 248, 248, 255))
    assert texture[-12:] == bytes((248, 0, 0, 255, 0, 248, 0, 255, 0, 0, 248, 255))


def test_read_ps2_icon_rejects_a_truncated_compressed_texture(
        make_ps2_icon: Callable[..., bytes]) -> None:
    data = make_ps2_icon(texture=struct.pack('<IHH', 4, 2, 0), texture_type=0xF)
    with pytest.raises(InvalidFormatError, match='compressed icon texture is truncated'):
        icon.read_ps2_icon(data)


@pytest.mark.parametrize(('data', 'message'), [
    (b'\0' * 8, 'header is truncated'),
    (struct.pack('<3IfI', 0x20000, 1, 7, 1.0, 3), 'Not a PS2 icon'),
    (struct.pack('<3IfI', 0x10000, 0, 7, 1.0, 3), 'Not a PS2 icon'),
])
def test_read_ps2_icon_rejects_other_data(data: bytes, message: str) -> None:
    with pytest.raises(InvalidFormatError, match=message):
        icon.read_ps2_icon(data)


@pytest.mark.parametrize('vertices', [0, 4, 100000])
def test_read_ps2_icon_rejects_a_bad_vertex_count(make_ps2_icon: Callable[..., bytes],
                                                  vertices: int) -> None:
    data = bytearray(make_ps2_icon())
    struct.pack_into('<I', data, 0x10, vertices)
    with pytest.raises(InvalidFormatError, match='unusable vertex count'):
        icon.read_ps2_icon(bytes(data))


@pytest.mark.parametrize('cut', [4, 12])
def test_read_ps2_icon_rejects_a_truncated_animation(make_ps2_icon: Callable[..., bytes],
                                                     cut: int) -> None:
    data = make_ps2_icon(frames=((0, ((0.0, 1.0),)),), texture=b'')
    with pytest.raises(InvalidFormatError, match='animation is truncated'):
        icon.read_ps2_icon(data[:-cut])


def test_build_icon_gltf_animates_the_shapes(make_ps2_icon: Callable[..., bytes]) -> None:
    frames = ((0, ((0.0, 1.0), (30.0, 1.0), (30.0, 0.0))),
              (1, ((0.0, 0.0), (30.0, 0.0), (30.0, 1.0), (60.0, 1.0),
                   (60.0, 0.0))), (2, ((15.0, 0.0), (45.0, 1.0))), (9, ((0.0, 1.0),)))
    decoded = icon.read_ps2_icon(make_ps2_icon(anim=4, frames=frames, texture=b''))
    document = _document(icon.build_icon_gltf(decoded, 'save').finish('save'))
    primitive = document['meshes'][0]['primitives'][0]
    assert len(primitive['targets']) == 3
    assert 'TEXCOORD_0' not in primitive['attributes']
    assert document['meshes'][0]['weights'] == [0.0, 0.0, 0.0]
    animation = document['animations'][0]
    assert animation['extras'] == {'frameLength': 120, 'speed': 1.0}
    times = document['accessors'][animation['samplers'][0]['input']]
    assert times['count'] == 7
    assert times['max'] == [pytest.approx(1.0 + 1e-4)]
    binary = icon.build_icon_gltf(decoded, 'save').blob
    view = document['bufferViews'][document['accessors'][animation['samplers'][0]['output']]
                                   ['bufferView']]
    weights = struct.unpack_from('<21f', binary, view['byteOffset'])
    assert [round(value, 3) for value in weights] == [
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0.5,
        0,
        1,
        0.5,
        0,
        1,
        1,
        0,
        1,
        1,
        0,
        0,
        1,
        0,
    ]


def test_build_icon_gltf_without_tracks(make_ps2_icon: Callable[..., bytes]) -> None:
    decoded = icon.read_ps2_icon(make_ps2_icon(anim=2))
    document = _document(icon.build_icon_gltf(decoded, 'save').finish('save'))
    assert 'animations' not in document
    assert document['images'][0]['mimeType'] == 'image/png'


def test_write_ps2_icon(make_ps2_icon: Callable[..., bytes], tmp_path: Path) -> None:
    decoded = icon.read_ps2_icon(make_ps2_icon(vertices=6))
    written = icon.write_ps2_icon(decoded, tmp_path / 'out' / 'save')
    assert [path.name for path in written] == ['save.glb', 'save.gltf', 'save.png']
    assert written[0].read_bytes()[:4] == b'glTF'
    gltf = json.loads(written[1].read_text(encoding='utf-8'))
    assert gltf['images'] == [{'name': 'save', 'uri': 'save.png'}]
    assert gltf['buffers'][0]['uri'].startswith('data:application/octet-stream;base64,')
    with Image.open(written[2]) as image:
        assert image.size == (128, 128)
        assert image.mode == 'RGBA'


def test_convert_icon_sys(make_icon_sys: Callable[..., bytes], tmp_path: Path) -> None:
    source = tmp_path / 'icon.sys'
    source.write_bytes(make_icon_sys())
    out = icon.convert(source)
    assert out == tmp_path / 'icon.sys.json'
    assert source.exists()
    assert json.loads(out.read_text(encoding='utf-8'))['title'] == 'AMPLITUDE'


def test_convert_icon_sys_invalid(tmp_path: Path) -> None:
    source = tmp_path / 'icon.sys'
    source.write_bytes(b'JUNK' + bytes(0x1C8))
    assert icon.convert(source) is None


def test_convert_ps2_icon(make_ps2_icon: Callable[..., bytes], tmp_path: Path) -> None:
    source = tmp_path / 'save.ico'
    source.write_bytes(make_ps2_icon(texture=b''))
    assert icon.convert(source) == tmp_path / 'save.glb'
    assert source.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ['save.glb', 'save.gltf', 'save.ico']


def test_convert_ps2_icon_invalid(tmp_path: Path) -> None:
    source = tmp_path / 'save.icn'
    source.write_bytes(b'JUNK' + bytes(0x8100))
    assert icon.convert(source) is None
    assert source.exists()
