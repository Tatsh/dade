from __future__ import annotations

from typing import TYPE_CHECKING
import json
import struct

from PIL import Image
import pytest

from destin.common import ps2_icon as icon
from destin.common.exceptions import InvalidFormatError

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


def test_ps2_icon_decompose(make_ps2_icon: Callable[..., bytes], tmp_path: Path) -> None:
    source = tmp_path / 'save.ico'
    source.write_bytes(make_ps2_icon(vertices=6))
    out = icon.ps2_icon_decompose(source, tmp_path / 'save')
    assert out == tmp_path / 'save'
    obj = (out / 'model.obj').read_text(encoding='utf-8')
    assert obj.count('\nv ') == 6
    assert obj.count('\nvt ') == 6
    assert obj.count('\nvn ') == 6
    assert obj.count('\nf ') == 2
    assert 'mtllib model.mtl' in obj
    assert 'map_Kd texture.png' in (out / 'model.mtl').read_text(encoding='utf-8')
    with Image.open(out / 'texture.png') as image:
        assert image.size == (128, 128)
        assert image.mode == 'RGBA'


def test_ps2_icon_decompose_multiple_anim_shapes(make_ps2_icon: Callable[..., bytes],
                                                 tmp_path: Path) -> None:
    source = tmp_path / 'save.icn'
    source.write_bytes(make_ps2_icon(anim=3))
    assert icon.ps2_icon_decompose(source, tmp_path / 'save') is not None


def test_ps2_icon_decompose_wrong_magic(make_ps2_icon: Callable[..., bytes],
                                        tmp_path: Path) -> None:
    source = tmp_path / 'save.ico'
    source.write_bytes(make_ps2_icon(magic=0x20000))
    assert icon.ps2_icon_decompose(source, tmp_path / 'out') is None


def test_ps2_icon_decompose_too_short(tmp_path: Path) -> None:
    source = tmp_path / 'save.ico'
    source.write_bytes(struct.pack('<I', 0x10000) + bytes(64))
    assert icon.ps2_icon_decompose(source, tmp_path / 'out') is None


@pytest.mark.parametrize('vertices', [0, 4, 100000])
def test_ps2_icon_decompose_bad_vertex_count(make_ps2_icon: Callable[..., bytes], tmp_path: Path,
                                             vertices: int) -> None:
    # Zero vertices, a count that is not a multiple of three, and a count past the texture.
    data = bytearray(make_ps2_icon())
    struct.pack_into('<I', data, 0x10, vertices)
    source = tmp_path / 'save.ico'
    source.write_bytes(bytes(data))
    assert icon.ps2_icon_decompose(source, tmp_path / 'out') is None


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
    source.write_bytes(make_ps2_icon())
    out = icon.convert(source)
    assert out == tmp_path / 'save'
    assert source.exists()  # The icon is kept beside its decomposed folder.
    assert (out / 'model.obj').is_file()


def test_convert_ps2_icon_invalid(tmp_path: Path) -> None:
    source = tmp_path / 'save.icn'
    source.write_bytes(b'JUNK' + bytes(0x8100))
    assert icon.convert(source) is None
    assert source.exists()
