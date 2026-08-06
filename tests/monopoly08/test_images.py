from __future__ import annotations

from typing import TYPE_CHECKING, cast
import struct

from PIL import Image
from destin.monopoly08.images import EXTENSIONS, convert
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_GPU_DXT1 = 0x12
_GPU_DXT4_5 = 0x14
_GPU_8888 = 0x06
_GPU_DXN = 0x31

_WHITE_DXT1 = struct.pack('<HHI', 0xFFFF, 0x0000, 0)
"""DXT1 block whose first endpoint is white and every index selects it."""
_CLEAR_DXT1 = struct.pack('<HHI', 0x0000, 0xFFFF, 0xFFFFFFFF)
"""DXT1 block in three-colour mode where every index selects the transparent slot."""
_RED_DXT5 = bytes((255, 0)) + b'\x00' * 6 + struct.pack('<HHI', 0xF800, 0x0000, 0)
"""DXT5 block: opaque alpha ramp plus a red first endpoint."""
_CLEAR_DXT5 = bytes((0, 255)) + b'\x00' * 6 + struct.pack('<HHI', 0xF800, 0x0000, 0)
"""DXT5 block whose alpha ramp starts fully transparent."""
_DXN_BLOCK = bytes((255, 0)) + b'\x00' * 6 + bytes((0, 255)) + b'\x00' * 6
"""DXN block: red channel saturated, green channel at zero."""
_ARGB_PIXEL = bytes((255, 1, 2, 3))
"""One A8R8G8B8 pixel in post-swap byte order."""


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _pixel(path: Path) -> tuple[int, ...]:
    with Image.open(path) as image:
        return cast('tuple[int, ...]', image.convert('RGBA').getpixel((0, 0)))


def _size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


# --------------------------------------------------------------------------- #
# Xbox 360 XMAP                                                                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(('fmt', 'element', 'expected'),
                         [(_GPU_DXT1, _WHITE_DXT1, (255, 255, 255, 255)),
                          (_GPU_DXT1, _CLEAR_DXT1, (0, 0, 0, 0)),
                          (_GPU_DXT4_5, _RED_DXT5, (255, 0, 0, 255)),
                          (_GPU_DXT4_5, _CLEAR_DXT5, (255, 0, 0, 0)),
                          (_GPU_DXN, _DXN_BLOCK, (255, 0, 127, 255)),
                          (_GPU_8888, _ARGB_PIXEL, (1, 2, 3, 255))])
def test_xmap_formats(make_xmap: Callable[..., bytes], fmt: int, element: bytes,
                      expected: tuple[int, ...], tmp_path: Path) -> None:
    source = _write(tmp_path, 't.xmap', make_xmap(4, 4, fmt, element))
    out, name, width, height = convert(source)
    assert out == tmp_path / 't.png'
    assert name == f'0x{fmt:02x}'
    assert (width, height) == (4, 4)
    assert _size(out) == (4, 4)
    assert _pixel(out) == expected


@pytest.mark.parametrize('fmt', [_GPU_DXT1, _GPU_DXT4_5, _GPU_DXN])
def test_xmap_with_a_partial_block(make_xmap: Callable[..., bytes], fmt: int,
                                   tmp_path: Path) -> None:
    element = _WHITE_DXT1 if fmt == _GPU_DXT1 else _RED_DXT5 if fmt == _GPU_DXT4_5 else _DXN_BLOCK
    source = _write(tmp_path, 't.xmap', make_xmap(2, 2, fmt, element))
    assert _size(convert(source)[0]) == (2, 2)


def test_xmap_rejects_an_unsupported_gpu_format(make_xmap: Callable[..., bytes],
                                                tmp_path: Path) -> None:
    source = _write(tmp_path, 't.xmap', make_xmap(4, 4, 0x20, _WHITE_DXT1))
    with pytest.raises(NotImplementedError, match='GPU format 0x20'):
        convert(source)


def test_xmap_rejects_bad_magic(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='not PAMX'):
        convert(_write(tmp_path, 't.xmap', b'NOPE' + b'\x00' * 60))


# --------------------------------------------------------------------------- #
# PS3 SHPX                                                                     #
# --------------------------------------------------------------------------- #

_DXT3_PAYLOAD = b'\xff' * 8 + struct.pack('<HHI', 0xF800, 0x0000, 0)


@pytest.mark.parametrize(('type_byte', 'payload', 'name', 'expected'),
                         [(0x60, _WHITE_DXT1, 'DXT1', (255, 255, 255, 255)),
                          (0x61, _DXT3_PAYLOAD, 'DXT3', (255, 0, 0, 255)),
                          (0x62, _RED_DXT5, 'DXT5', (255, 0, 0, 255))])
def test_shpx_compressed_formats(make_shpx: Callable[..., bytes], type_byte: int, payload: bytes,
                                 name: str, expected: tuple[int, ...], tmp_path: Path) -> None:
    source = _write(tmp_path, 't.shpx', make_shpx(type_byte, 4, 4, payload))
    out, fmt, width, height = convert(source)
    assert fmt == name
    assert (width, height) == (4, 4)
    assert _pixel(out) == expected


def test_shpx_bgra8888(make_shpx: Callable[..., bytes], tmp_path: Path) -> None:
    source = _write(tmp_path, 't.shpx', make_shpx(0x7D, 2, 2, bytes((3, 2, 1, 255)) * 4))
    out, fmt, width, height = convert(source)
    assert fmt == 'BGRA8888'
    assert (width, height) == (2, 2)
    assert _pixel(out) == (1, 2, 3, 255)


def test_shpx_rejects_compressed_image_data(make_shpx: Callable[..., bytes],
                                            tmp_path: Path) -> None:
    source = _write(tmp_path, 't.shpx', make_shpx(0x80 | 0x60, 4, 4, _WHITE_DXT1))
    with pytest.raises(ValueError, match='RefPack-compressed'):
        convert(source)


@pytest.mark.parametrize(('width', 'height'), [(0, 4), (4, 0), (9000, 4)])
def test_shpx_rejects_bad_dimensions(make_shpx: Callable[..., bytes], width: int, height: int,
                                     tmp_path: Path) -> None:
    source = _write(tmp_path, 't.shpx', make_shpx(0x60, width, height, _WHITE_DXT1))
    with pytest.raises(ValueError, match='bad dims'):
        convert(source)


def test_shpx_rejects_an_unhandled_type(make_shpx: Callable[..., bytes], tmp_path: Path) -> None:
    source = _write(tmp_path, 't.shpx', make_shpx(0x10, 4, 4, _WHITE_DXT1))
    with pytest.raises(ValueError, match='unhandled image type 0x10'):
        convert(source)


def test_shpx_rejects_bad_magic(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='not SHPX'):
        convert(_write(tmp_path, 't.shpx', b'NOPE' + b'\x00' * 60))


# --------------------------------------------------------------------------- #
# PS2 SHPS                                                                     #
# --------------------------------------------------------------------------- #

_PS2_ENTRY = bytes((10, 20, 30, 64))
"""One PS2 palette entry; its alpha doubles to 128 on decode."""


@pytest.mark.parametrize(('type_byte', 'width', 'height'), [(2, 16, 16), (1, 16, 16), (1, 32, 16)])
def test_shps_paletted_formats(make_shps: Callable[..., bytes], type_byte: int, width: int,
                               height: int, tmp_path: Path) -> None:
    indices = bytes(range(256))[:width * height // (1 if type_byte == 2 else 2)]
    source = _write(tmp_path, 't.shps',
                    make_shps(type_byte, width, height, indices, _PS2_ENTRY * 256, 256))
    out, fmt, out_w, out_h = convert(source)
    assert fmt == ('PAL8' if type_byte == 2 else 'PAL4')
    assert (out_w, out_h) == (width, height)
    assert _size(out) == (width, height)
    assert _pixel(out) == (10, 20, 30, 128)


def test_shps_reuses_the_deswizzle_caches(make_shps: Callable[..., bytes], tmp_path: Path) -> None:
    for name in ('a.shps', 'b.shps'):
        body = make_shps(1, 32, 16, bytes(range(256)), _PS2_ENTRY * 256, 256)
        assert _size(convert(_write(tmp_path, name, body))[0]) == (32, 16)


@pytest.mark.parametrize('count', [0, 16])
def test_shps_palette_sizes(make_shps: Callable[..., bytes], count: int, tmp_path: Path) -> None:
    entries = count or 256
    source = _write(tmp_path, 't.shps',
                    make_shps(2, 16, 16, bytes(range(256)), _PS2_ENTRY * entries, count))
    assert _pixel(convert(source)[0]) == (10, 20, 30, 128)


def test_shps_pads_a_short_palette(make_shps: Callable[..., bytes], tmp_path: Path) -> None:
    source = _write(tmp_path, 't.shps', make_shps(2, 16, 16, bytes(range(256)), _PS2_ENTRY * 8,
                                                  256))
    assert _size(convert(source)[0]) == (16, 16)


@pytest.mark.parametrize(('width', 'height'), [(0, 16), (16, 0), (5000, 16)])
def test_shps_rejects_bad_dimensions(make_shps: Callable[..., bytes], width: int, height: int,
                                     tmp_path: Path) -> None:
    source = _write(tmp_path, 't.shps', make_shps(2, width, height, b'\x00' * 16))
    with pytest.raises(ValueError, match='bad dims'):
        convert(source)


def test_shps_rejects_an_unhandled_type(make_shps: Callable[..., bytes], tmp_path: Path) -> None:
    source = _write(tmp_path, 't.shps', make_shps(5, 16, 16, b'\x00' * 256))
    with pytest.raises(ValueError, match='unhandled type 0x05'):
        convert(source)


def test_shps_rejects_bad_magic(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='not SHPS'):
        convert(_write(tmp_path, 't.shps', b'NOPE' + b'\x00' * 80))


# --------------------------------------------------------------------------- #
# Wii SHPG                                                                     #
# --------------------------------------------------------------------------- #

_CMPR_BLOCK = bytes((0xFF, 0xFF, 0, 0, 0, 0, 0, 0))
"""GX CMPR sub-block: big-endian white first endpoint, all indices zero."""


def test_shpg_cmpr(make_shpg: Callable[..., bytes], tmp_path: Path) -> None:
    source = _write(tmp_path, 't.shpg', make_shpg(0x1E, 8, 8, _CMPR_BLOCK * 4))
    out, fmt, width, height = convert(source)
    assert fmt == 'CMPR'
    assert (width, height) == (8, 8)
    assert _pixel(out) == (255, 255, 255, 255)


def test_shpg_cmpr_with_truncated_data(make_shpg: Callable[..., bytes], tmp_path: Path) -> None:
    # Only two of the eight sub-blocks a 16x8 image needs are present.
    source = _write(tmp_path, 't.shpg', make_shpg(0x1E, 16, 8, _CMPR_BLOCK * 2))
    assert _size(convert(source)[0]) == (16, 8)


def test_shpg_pal8(make_shpg: Callable[..., bytes], tmp_path: Path) -> None:
    source = _write(tmp_path, 't.shpg',
                    make_shpg(0x19, 16, 8, bytes(range(128)),
                              bytes((255, 10, 20, 30)) * 256))
    out, fmt, width, height = convert(source)
    assert fmt == 'PAL8'
    assert (width, height) == (16, 8)
    assert _pixel(out) == (10, 20, 30, 255)


def test_shpg_pal8_with_a_short_palette(make_shpg: Callable[..., bytes], tmp_path: Path) -> None:
    source = _write(tmp_path, 't.shpg',
                    make_shpg(0x19, 16, 8, bytes(range(128)),
                              bytes((255, 10, 20, 30)) * 4))
    out, fmt, _width, _height = convert(source)
    assert fmt == 'PAL8'
    assert _size(out) == (16, 8)


def test_shpg_pal4(make_shpg: Callable[..., bytes], tmp_path: Path) -> None:
    source = _write(tmp_path, 't.shpg', make_shpg(0x18, 16, 8, bytes(range(128))))
    out, fmt, _width, _height = convert(source)
    assert fmt == 'PAL4'
    assert _size(out) == (16, 8)


@pytest.mark.parametrize(('width', 'height'), [(0, 8), (8, 0), (5000, 8)])
def test_shpg_rejects_bad_dimensions(make_shpg: Callable[..., bytes], width: int, height: int,
                                     tmp_path: Path) -> None:
    source = _write(tmp_path, 't.shpg', make_shpg(0x1E, width, height, _CMPR_BLOCK * 4))
    with pytest.raises(ValueError, match='bad dims'):
        convert(source)


@pytest.mark.parametrize(('type_byte', 'name'), [(0x16, 'ARGB8888'), (0x55, '0x55')])
def test_shpg_rejects_an_unhandled_type(make_shpg: Callable[..., bytes], type_byte: int, name: str,
                                        tmp_path: Path) -> None:
    source = _write(tmp_path, 't.shpg', make_shpg(type_byte, 8, 8, b'\x00' * 64))
    with pytest.raises(ValueError, match=f'unhandled type {name}'):
        convert(source)


def test_shpg_rejects_bad_magic(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='not SHPG'):
        convert(_write(tmp_path, 't.shpg', b'NOPE' + b'\x00' * 80))


# --------------------------------------------------------------------------- #
# Dispatch                                                                     #
# --------------------------------------------------------------------------- #


def test_extensions() -> None:
    assert {'.shpg', '.shps', '.shpx', '.xmap'} == EXTENSIONS


def test_convert_rejects_an_unhandled_extension(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='unhandled texture extension'):
        convert(_write(tmp_path, 't.png', b''))
