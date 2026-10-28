from __future__ import annotations

from typing import Any
import json
import struct

import pytest

from dade.tgr.f3dex import Corner, Material, Triangle
from dade.tgr.model import (
    CAR_BASE,
    DEFAULT_PAINT,
    TRACK_BASE,
    Part,
    build_glb,
    is_car,
    is_part_model,
    is_track,
    orientations,
    paint_car,
    read_car,
    read_part_model,
    read_track,
    stream_track_textures,
    textures,
)
from dade.tgr.texture import FMT_CI, FMT_I, FMT_RGBA, SIZ_4B, SIZ_8B, SIZ_16B, TextureKey

_IDENTITY = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
_NONE = 0xFFFFFFFF
_STREAM = bytes(range(256)) * 4
_KEY = TextureKey(0, -1, FMT_RGBA, SIZ_16B, 2, 1, 0)


def _pointer(base: int, offset: int) -> int:
    return 0x80000000 | (base + offset)


def _draw(base: int, vertices: int) -> bytes:
    triangle = (2 << 8 | 4).to_bytes(4, 'big')
    return (struct.pack('>II', 0x04 << 24 | 3 << 10, _pointer(base, vertices)) + b'\xbf\0\0\0' +
            triangle + b'\xb8' + bytes(7))


def _vertices() -> bytes:
    return b''.join(
        struct.pack('>hhhHhhBBBB', x, y, z, 0, 0, 0, 0, 0, 127, 255)
        for x, y, z in ((0, 0, 0), (255, 0, 0), (0, 255, 0)))


def _car(*, count: int = 7, fmt: int = 4, image: int = 0x540, wheel: bool = True) -> bytes:
    data = bytearray(0x1000)
    struct.pack_into('>II', data, 0x10, count, _pointer(CAR_BASE, 0x300))
    for index, texel, palette, bits in ((0, 0x560, 0x4C0, 0), (1, 0x500, 0x4A0, 1),
                                        (3, 0x500, 0x480, 1), (6, image, 0, fmt)):
        at = 0x300 + index * 0x24
        struct.pack_into('>II', data, at, texel and _pointer(CAR_BASE, texel), palette
                         and _pointer(CAR_BASE, palette))
        struct.pack_into('>HHI', data, at + 0xC, 4, 2, 0)
        struct.pack_into('>I', data, at + 0x20, bits << 24)
    for index, offset in ((3, 0x600), (4, 0x600), (6, 0x600), (9, 0x700)):
        struct.pack_into('>I', data, 0x18 + index * 4, _pointer(CAR_BASE, offset))
    if wheel:
        struct.pack_into('>I', data, 0xBC, _pointer(CAR_BASE, 0x600))
    struct.pack_into('>12f', data, 0xE0, *range(12))
    data[0x110] = 1
    data[0x4A0:0x4A2] = b'\x00\x01'
    data[0x600:0x618] = _draw(CAR_BASE, 0x900)
    data[0x700] = 0xB8
    data[0x900:0x930] = _vertices()
    return bytes(data)


def _track(frames: int = 2) -> bytes:
    data = bytearray(0x1000)
    struct.pack_into('>I', data, 4, 0x230)
    struct.pack_into('>II', data, 0x18, 5, _pointer(TRACK_BASE, 0x240))
    for index, image, palette, source, bits in ((0, 0x500, 0x480, 0x001, 1 << 24),
                                                (1, 0x540, 0x800, _pointer(TRACK_BASE, 0x780),
                                                 1 << 20 | 0x20), (2, 0x5A0, 0x5C0, 0xFFF, 1 << 24),
                                                (3, 0, 0x5E0, 0x002, 1 << 24), (4, 0x5E0, 0, 0x002,
                                                                                1 << 24)):
        struct.pack_into('>III', data, 0x240 + index * 0x24, image and _pointer(TRACK_BASE, image),
                         palette and _pointer(TRACK_BASE, palette), source)
        struct.pack_into('>I', data, 0x240 + index * 0x24 + 0x20, bits)
    struct.pack_into('>H', data, 0x782, frames)
    struct.pack_into('>9I', data, 0x788, _NONE, 0x40, 0x60, 0, 0x100, 0x120, 0, 0, 0)
    struct.pack_into('>I', data, 0x50, _pointer(TRACK_BASE, 0xA00))
    struct.pack_into('>II', data, 0x60, _pointer(TRACK_BASE, 0x300), 4)
    for index, address, flags, x in ((0, 0xA00, 4, 0.0), (1, 0xA00, 0, 5.0), (2, 0, 0, 0.0),
                                     (3, 0xA40, 0, 0.0)):
        at = 0x300 + index * 0x54
        struct.pack_into('>16f', data, at, *_IDENTITY[:12], x, 0.0, 0.0, 1.0)
        struct.pack_into('>I', data, at + 0x44, address and _pointer(TRACK_BASE, address))
        struct.pack_into('>H', data, at + 0x4C, flags)
    data[0xA00:0xA18] = _draw(TRACK_BASE, 0xB00)
    data[0xA40] = 0xB8
    data[0xB00:0xB30] = _vertices()
    return bytes(data)


def _part_model() -> bytes:
    data = bytearray(0x100)
    struct.pack_into('>II', data, 0, 3, 0)
    for index, address, flags in ((0, 0x48, 4), (1, 0, 0), (2, 0x60, 0)):
        struct.pack_into('>IH2x3f', data, 8 + index * 0x14, address, flags, 1.0, 2.0, 3.0)
    data[0x48:0x60] = _draw(0, 0x80)
    data[0x60] = 0xB8
    data[0x80:0xB0] = _vertices()
    return bytes(data)


def _gltf(glb: bytes) -> dict[str, Any]:
    length, _ = struct.unpack_from('<I4s', glb, 12)
    return json.loads(glb[20:20 + length])  # type: ignore[no-any-return]


def _triangle(key: TextureKey | None,
              positions: tuple[tuple[float, float, float], ...],
              uvs: tuple[tuple[float, float], ...],
              *,
              lit: bool = True,
              colour: tuple[int, int, int, int] = (0, 0, 127, 255)) -> Triangle:
    a, b, c = (Corner(p, uv, colour) for p, uv in zip(positions, uvs, strict=True))
    return Triangle(Material(key, lit, two_sided=False), (a, b, c))


_UPRIGHT = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))


def test_is_car() -> None:
    assert is_car(_car())
    assert not is_car(_car(wheel=False))
    assert not is_car(_car()[:0x200])


def test_is_track() -> None:
    assert is_track(_track())
    assert not is_track(_car())
    assert not is_track(_track()[:0x230])


@pytest.mark.parametrize(('data', 'expected'), [
    (b'', False),
    (bytes(16), False),
    ((3).to_bytes(4, 'big') + bytes(0x1C), False),
    (_part_model()[:4] + (0x100).to_bytes(4, 'big') + _part_model()[8:], False),
    ((1).to_bytes(4, 'big') + bytes(0x40), False),
    ((1).to_bytes(4, 'big') + bytes(4) + (0x24).to_bytes(4, 'big') + bytes(0x40), False),
    ((1).to_bytes(4, 'big') + bytes(4) + (0x10).to_bytes(4, 'big') + bytes(0x40), False),
    (_part_model(), True),
])
def test_is_part_model(data: bytes, *, expected: bool) -> None:
    assert is_part_model(data) is expected


def test_paint_car() -> None:
    painted = paint_car(_car())
    red, green, blue = DEFAULT_PAINT
    assert struct.unpack_from(
        '>HH', painted, 0x4A0) == (1 | red << 11 | green << 6 | blue << 1,
                                   1 | (red & 0x1E) << 10 | (green & 0x1E) << 5 | (blue & 0x1E))
    assert painted[0x4C0:0x4C4] == bytes(4)


@pytest.mark.parametrize(('fmt', 'underside'),
                         [(4, TextureKey(0x540, -1, FMT_I, SIZ_8B, 4, 2, 0)),
                          (0, TextureKey(0x540, -1, FMT_RGBA, SIZ_16B, 4, 2, 0))])
def test_read_car(fmt: int, underside: TextureKey) -> None:
    parts = read_car(_car(fmt=fmt))
    assert [p.name for p in parts] == [
        'near-detail', 'body', 'underside', 'wheel-0', 'wheel-1', 'wheel-2', 'wheel-3'
    ]
    assert parts[0].triangles[0].material.texture == TextureKey(0x500, 0x480, FMT_CI, SIZ_4B, 4, 2,
                                                                0)
    assert parts[1].triangles[0].material.texture is None
    assert parts[2].triangles[0].material.texture == underside
    assert parts[0].triangles[0].material.lit
    assert parts[3].matrix[0] == pytest.approx(1 / 255)
    assert parts[4].matrix[12:15] == (3.0, 4.0, 5.0)


@pytest.mark.parametrize('car', [_car(count=3), _car(image=0)])
def test_read_car_missing_texture(car: bytes) -> None:
    assert read_car(car)[2].triangles[0].material.texture is None


def test_read_car_without_wheels() -> None:
    assert [p.name for p in read_car(_car(wheel=False))] == ['near-detail', 'body', 'underside']


def test_read_part_model() -> None:
    (part,) = read_part_model(_part_model())
    assert part.name == 'part-0'
    assert part.matrix[12:15] == (1.0, 2.0, 3.0)
    assert all(t.material.two_sided and t.material.lit for t in part.triangles)


@pytest.mark.parametrize(('frames', 'image', 'palette'), [(2, 0x100, 0x120), (3, 0x40, 0x60)])
def test_stream_track_textures(frames: int, image: int, palette: int) -> None:
    memory = stream_track_textures(_track(frames), _STREAM)
    assert memory[0x480:0x4A0] == _STREAM[0x20:0x40]
    assert memory[0x540:0x560] == _STREAM[image:image + 0x20]
    assert memory[0x800:0xA00] == _STREAM[palette:palette + 0x200]
    assert memory[0x5C0:0x5E0] == bytes(0x20)
    assert memory[0x5E0:0x600] == bytes(0x20)


def test_read_track() -> None:
    parts = read_track(_track())
    assert [p.name for p in parts] == ['instance-0', 'instance-1', 'sky']
    assert parts[0].triangles[0].material.two_sided
    assert not parts[1].triangles[0].material.two_sided
    assert parts[1].matrix[12] == pytest.approx(5.0)
    assert not parts[2].triangles[0].material.lit
    assert parts[2].matrix == _IDENTITY


def test_textures_decodes_each_sampled_texture() -> None:
    parts = [
        Part('a', (_triangle(_KEY, _UPRIGHT,
                             ((0, 0), (1, 0),
                              (0, 1))), _triangle(None, _UPRIGHT, ((0, 0), (1, 0), (0, 1)))),
             _IDENTITY)
    ]
    assert textures(b'\xf8\x01\xf8\x00', parts) == {_KEY: bytes((255, 0, 0, 255, 255, 0, 0, 0))}


@pytest.mark.parametrize(('uvs', 'expected'), [(((0, 1), (1, 1), (0, 0)), (0, False)),
                                               (((1, 1), (0, 1), (1, 0)), (0, True)),
                                               (((0, 0), (1, 0), (0, 1)), (2, True)),
                                               (((1, 1), (1, 0), (0, 1)), (1, False)),
                                               (((1, 0), (1, 1), (0, 0)), (3, True))])
def test_orientations(uvs: tuple[tuple[float, float], ...], expected: tuple[int, bool]) -> None:
    flat = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    other = TextureKey(8, -1, FMT_RGBA, SIZ_16B, 2, 1, 0)
    parts = [
        Part('a', (_triangle(_KEY, _UPRIGHT, uvs), _triangle(None, _UPRIGHT, uvs),
                   _triangle(other, flat, uvs), _triangle(
                       other, (_UPRIGHT[0],) * 3, uvs), _triangle(other, _UPRIGHT, ((0, 0),) * 3)),
             _IDENTITY)
    ]
    assert orientations(parts) == {_KEY: expected}


def test_build_glb() -> None:
    uvs = ((0, 0), (1, 0), (0, 1))
    textured = _triangle(_KEY, _UPRIGHT, uvs, colour=(0x81, 0, 0, 255))
    parts = [
        Part('body', (textured, _triangle(None, _UPRIGHT, uvs, colour=(0, 0, 0, 255))), _IDENTITY),
        Part('copy',
             (textured, textured._replace(material=Material(_KEY, lit=True, two_sided=True))),
             _IDENTITY),
        Part('sky',
             (_triangle(None, _UPRIGHT, uvs,
                        lit=False)._replace(material=Material(None, lit=False, two_sided=True)),),
             _IDENTITY)
    ]
    gltf = _gltf(build_glb('scene', parts, {_KEY: bytes((255, 0, 0, 255, 255, 0, 0, 0))}))
    assert [m['name'] for m in gltf['meshes']] == ['body', 'copy', 'sky']
    assert len(gltf['images']) == 1
    assert len(gltf['materials']) == 4
    assert gltf['materials'][0]['alphaMode'] == 'MASK'
    assert gltf['materials'][2]['pbrMetallicRoughness']['baseColorTexture'] == {'index': 0}
    assert gltf['materials'][3]['doubleSided']
    assert gltf['materials'][3]['extensions'] == {'KHR_materials_unlit': {}}
    assert 'KHR_materials_unlit' in gltf['extensionsUsed']
    assert 'NORMAL' in gltf['meshes'][0]['primitives'][0]['attributes']
    assert 'COLOR_0' in gltf['meshes'][2]['primitives'][0]['attributes']
    assert gltf['meshes'][1]['primitives'][0]['material'] == 0


def test_build_glb_opaque_texture_has_no_alpha_mode() -> None:
    parts = [Part('a', (_triangle(_KEY, _UPRIGHT, ((0, 0), (1, 0), (0, 1))),), _IDENTITY)]
    gltf = _gltf(build_glb('scene', parts, {_KEY: bytes((255, 0, 0, 255) * 2)}))
    assert 'alphaMode' not in gltf['materials'][0]
