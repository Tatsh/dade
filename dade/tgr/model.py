"""
Cars, tracks, and the other models of Top Gear Rally, converted to binary glTF.

Each kind of asset is read into a list of :py:class:`Part` values, each a group of triangles placed
by a matrix, and :py:func:`build_glb` writes any list of parts. The game is z up and glTF is y up,
and every position and normal is turned on the way out.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import math
import struct

from dade.common.gltf import ARRAY_BUFFER, GLBDocument
from dade.common.png import encode_rgba

from .f3dex import DisplayListReader, Triangle
from .texture import FMT_CI, SIZ_4B, SIZ_8B, SIZ_16B, TextureKey, decode

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from .f3dex import Material

__all__ = ('CAR_BASE', 'DEFAULT_PAINT', 'TRACK_BASE', 'Part', 'build_glb', 'is_car',
           'is_part_model', 'is_track', 'orientations', 'paint_car', 'read_car', 'read_part_model',
           'read_track', 'stream_track_textures', 'textures')

CAR_BASE = 0x3C8000
"""The address, less its high byte, a car is relocated to.

:meta hide-value:
"""
TRACK_BASE = 0x025C00
"""The address, less its high byte, a track is relocated to.

:meta hide-value:
"""
DEFAULT_PAINT = (28, 4, 4)
"""The paint of a converted car, a red, in 5-bit channels.

:meta hide-value:
"""
_CAR_SCALE = 1 / 255
_CAR_TEXTURE_COUNT = 0x10
_CAR_TEXTURES = 0x14
_CAR_DISPLAY_LISTS = 0x18
_CAR_WHEEL_DISPLAY_LIST = 0xBC
_CAR_WHEELS = 0xE0
_CAR_MATERIALS = 0x110
_CAR_MATERIAL_COUNT = 12
_CAR_PARTS = {3: 'near-detail', 4: 'body', 6: 'underside', 8: 'textured', 9: 'highlights'}
_CAR_PART_TEXTURES = {3: 3, 6: 6}
_TEXTURE_STRIDE = 0x24
_TEXTURE_CI4 = 1
_TRACK_HEADER_SIZE = 0x230
_TRACK_TEXTURE_COUNT = 0x18
_TRACK_TEXTURES = 0x1C
_TRACK_SKY = 0x50
_TRACK_INSTANCES = 0x60
_TRACK_INSTANCE_COUNT = 0x64
_INSTANCE_STRIDE = 0x54
_ANIMATED = 1 << 20
_ROM_NONE = 0xFFFFFFFF
_CI4_PALETTE = 0x20
_PALETTE = 0x200
_FRAME_STRIDE = 12
_PART_STRIDE = 0x14
_PART_TWO_SIDED = 0x0004
_MAX_PARTS = 0x100
_UPRIGHT = 0.7
_CAR_HEADER_SIZE = 0x200
_KSEG0 = 0x80
_PART_TABLE = 8
_SNOW_FRAMES = 2
_QUARTERS = 4
_VOTES = 8
_SIGN = 0x80
_IDENTITY = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)


class Part(NamedTuple):
    """A group of triangles and where it sits."""

    name: str
    """Name of the glTF node."""
    triangles: tuple[Triangle, ...]
    """The triangles, in the units of their vertices."""
    matrix: tuple[float, ...]
    """Row-major 4 by 4 matrix whose last row is the position, as the game stores it."""


def _u32(data: bytes | bytearray, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 4], 'big')


def _scaled(scale: float, position: tuple[float, float, float] = (0.0, 0.0, 0.0)) \
        -> tuple[float, ...]:
    return (scale, 0.0, 0.0, 0.0, 0.0, scale, 0.0, 0.0, 0.0, 0.0, scale, 0.0, *position, 1.0)


def _within(address: int, base: int, size: int) -> bool:
    return 0 < (address & 0xFFFFFF) - base < size


def is_car(data: bytes) -> bool:
    """
    Report whether an asset is a car.

    Parameters
    ----------
    data : bytes
        The decompressed asset.

    Returns
    -------
    bool
        Whether its texture table and its first wheel list point into it at the car address.
    """
    return len(data) > _CAR_HEADER_SIZE and all(
        _u32(data, at) >> 24 == _KSEG0 and _within(_u32(data, at), CAR_BASE, len(data))
        for at in (_CAR_TEXTURES, _CAR_WHEEL_DISPLAY_LIST))


def is_track(data: bytes) -> bool:
    """
    Report whether an asset is a track.

    Parameters
    ----------
    data : bytes
        The decompressed asset.

    Returns
    -------
    bool
        Whether its header records the size of a track header.
    """
    return len(data) > _TRACK_HEADER_SIZE and _u32(data, 4) == _TRACK_HEADER_SIZE and _within(
        _u32(data, _TRACK_INSTANCES), TRACK_BASE, len(data))


def is_part_model(data: bytes) -> bool:
    """
    Report whether an asset is a model of parts, as the menus and the title sequence use.

    Parameters
    ----------
    data : bytes
        The decompressed asset.

    Returns
    -------
    bool
        Whether the part table is plausible and every display list in it begins inside the asset.
    """
    if len(data) < _PART_TABLE:
        return False
    count, animations = _u32(data, 0), _u32(data, 4)
    if not 0 < count < _MAX_PARTS or 8 + count * _PART_STRIDE > len(data) or animations >= len(
            data):
        return False
    lists = [_u32(data, 8 + i * _PART_STRIDE) for i in range(count)]
    return any(lists) and all(
        address == 0 or (8 + count * _PART_STRIDE <= address < len(data) and address % 8 == 0)
        for address in lists)


def _read(memory: bytes | bytearray,
          base: int,
          address: int,
          *,
          bound: TextureKey | None = None,
          lit: bool) -> tuple[Triangle, ...]:
    reader = DisplayListReader(memory, base)
    if lit:
        reader.geometry_mode |= 0x20000
    reader.bound = bound
    reader.run(address)
    return tuple(reader.triangles)


def _car_texture(data: bytes | bytearray, index: int) -> TextureKey | None:
    if index >= _u32(data, _CAR_TEXTURE_COUNT):
        return None
    at = (_u32(data, _CAR_TEXTURES) & 0xFFFFFF) - CAR_BASE + index * _TEXTURE_STRIDE
    image, palette = _u32(data, at), _u32(data, at + 4)
    width, height = struct.unpack_from('>HH', data, at + 0xC)
    fmt_bits = (_u32(data, at + 0x20) >> 24) & 0xF
    if image == 0 or width == 0 or height == 0:
        return None
    match fmt_bits:
        case 1:
            fmt, siz = FMT_CI, SIZ_4B
        case 4:
            fmt, siz = 4, SIZ_8B
        case _:
            fmt, siz = 0, SIZ_16B
    return TextureKey((image & 0xFFFFFF) - CAR_BASE,
                      (palette & 0xFFFFFF) - CAR_BASE if fmt == FMT_CI else -1, fmt, siz, width,
                      height, 0)


def paint_car(data: bytes, colour: tuple[int, int, int] = DEFAULT_PAINT) -> bytearray:
    """
    Paint a car, as the game does with the colour a player picks.

    The first two entries of the palette of each paint material take the colour and a darker shade
    of it. The colours the car ships with are placeholders.

    Parameters
    ----------
    data : bytes
        The decompressed car.
    colour : tuple[int, int, int]
        Red, green, and blue, each from 0 to 31.

    Returns
    -------
    bytearray
        The painted car.
    """
    red, green, blue = colour
    memory = bytearray(data)
    table = (_u32(data, _CAR_TEXTURES) & 0xFFFFFF) - CAR_BASE
    for slot, texture in enumerate(data[_CAR_MATERIALS:_CAR_MATERIALS + _CAR_MATERIAL_COUNT]):
        at = table + texture * _TEXTURE_STRIDE
        palette = (_u32(data, at + 4) & 0xFFFFFF) - CAR_BASE
        if not _u32(data, at + 4) or (_u32(data, at + 0x20) >> 24) & 0xF != _TEXTURE_CI4:
            continue
        alpha = memory[palette + slot * 2 + 1] & 1
        struct.pack_into('>HH', memory, palette, alpha | red << 11 | green << 6 | blue << 1,
                         alpha | (red & 0x1E) << 10 | (green & 0x1E) << 5 | (blue & 0x1E))
    return memory


def read_car(data: bytes | bytearray) -> list[Part]:
    """
    Read the nearest level of detail of a car and its four wheels.

    Parameters
    ----------
    data : bytes | bytearray
        The decompressed car.

    Returns
    -------
    list[Part]
        The body parts, then a wheel at each corner.
    """
    scale = _scaled(_CAR_SCALE)
    parts = []
    for index, name in _CAR_PARTS.items():
        if (address := _u32(data, _CAR_DISPLAY_LISTS + index * 4)) == 0:
            continue
        bound = _car_texture(data, _CAR_PART_TEXTURES[index]) if index in _CAR_PART_TEXTURES \
            else None
        if triangles := _read(data, CAR_BASE, address, bound=bound, lit=True):
            parts.append(Part(name, triangles, scale))
    if (wheel := _u32(data, _CAR_WHEEL_DISPLAY_LIST)) and (triangles := _read(
            data, CAR_BASE, wheel, lit=True)):
        for index in range(4):
            position = struct.unpack_from('>3f', data, _CAR_WHEELS + index * 12)
            parts.append(Part(f'wheel-{index}', triangles, _scaled(_CAR_SCALE, position)))
    return parts


def read_part_model(data: bytes) -> list[Part]:
    """
    Read a model of parts, each a display list at a position.

    Parameters
    ----------
    data : bytes
        The decompressed model.

    Returns
    -------
    list[Part]
        One part a display list.
    """
    parts = []
    for index in range(_u32(data, 0)):
        at = 8 + index * _PART_STRIDE
        address = _u32(data, at)
        flags = int.from_bytes(data[at + 4:at + 6], 'big')
        position = struct.unpack_from('>3f', data, at + 8)
        if address == 0:
            continue
        triangles = _read(data, 0, address, lit=True)
        if flags & _PART_TWO_SIDED:
            triangles = tuple(
                t._replace(material=t.material._replace(two_sided=True)) for t in triangles)
        if triangles:
            parts.append(Part(f'part-{index}', triangles, _scaled(1.0, position)))
    return parts


def stream_track_textures(data: bytes, stream: bytes, *, base: int = TRACK_BASE) -> bytearray:
    """
    Copy the textures a track streams into its memory, as they stand at the start of a race.

    A track stores the texels of each texture outside its compressed data, in a stream after it, and
    the game copies them in while the track loads. An animated texture gets its first frame.

    Parameters
    ----------
    data : bytes
        The decompressed track.
    stream : bytes
        The stream of texels after the track.
    base : int
        The address the track is relocated to, less its high byte.

    Returns
    -------
    bytearray
        The track with its textures in place.
    """
    memory = bytearray(data)

    def copy(source: int, target: int, size: int) -> None:
        at = (target & 0xFFFFFF) - base
        if source == _ROM_NONE or size <= 0 or at < 0 or source + size > len(stream):
            return
        memory[at:at + size] = stream[source:source + size]

    table = (_u32(data, _TRACK_TEXTURES) & 0xFFFFFF) - base
    for index in range(_u32(data, _TRACK_TEXTURE_COUNT)):
        at = table + index * _TEXTURE_STRIDE
        image, palette, source, bits = (_u32(data, at), _u32(data, at + 4), _u32(
            data, at + 8), _u32(data, at + 0x20))
        if image == 0:
            continue
        palette_size = _CI4_PALETTE if (bits >> 24) & 0xF == _TEXTURE_CI4 else _PALETTE
        palette_rom = (source & 0xFFF) << 5
        if bits & _ANIMATED:
            animation = (source & 0xFFFFFF) - base
            frames = int.from_bytes(data[animation + 2:animation + 4], 'big')
            frame = 1 if frames == _SNOW_FRAMES and _u32(data, animation + 8) == _ROM_NONE else 0
            first = animation + 8 + frame * _FRAME_STRIDE
            image_rom, palette_rom = _u32(data, first + 4), _u32(data, first + 8)
            copy(image_rom, image, bits & 0x3FFFF)
        if palette:
            copy(palette_rom, palette, palette_size)
    return memory


def read_track(memory: bytes | bytearray, *, base: int = TRACK_BASE) -> list[Part]:
    """
    Read every placed model of a track, and its sky.

    Parameters
    ----------
    memory : bytes | bytearray
        The track with its textures streamed in, from :py:func:`stream_track_textures`.
    base : int
        The address the track is relocated to, less its high byte.

    Returns
    -------
    list[Part]
        One part a placed model, in world units, then the sky when the track has one.
    """
    cache: dict[int, tuple[Triangle, ...]] = {}
    parts = []
    table = (_u32(memory, _TRACK_INSTANCES) & 0xFFFFFF) - base
    for index in range(_u32(memory, _TRACK_INSTANCE_COUNT)):
        at = table + index * _INSTANCE_STRIDE
        matrix = struct.unpack_from('>16f', memory, at)
        address = _u32(memory, at + 0x44)
        flags = int.from_bytes(memory[at + 0x4C:at + 0x4E], 'big')
        if address == 0:
            continue
        if address not in cache:
            cache[address] = _read(memory, base, address, lit=True)
        triangles = cache[address]
        if flags & _PART_TWO_SIDED:
            triangles = tuple(
                t._replace(material=t.material._replace(two_sided=True)) for t in triangles)
        if triangles:
            parts.append(Part(f'instance-{index}', triangles, matrix))
    if (sky := _u32(memory, _TRACK_SKY)) and (triangles := _read(memory, base, sky, lit=False)):
        parts.append(Part('sky', triangles, _IDENTITY))
    return parts


def textures(memory: bytes | bytearray, parts: Iterable[Part]) -> dict[TextureKey, bytes]:
    """
    Decode every texture the parts sample.

    Parameters
    ----------
    memory : bytes | bytearray
        The memory the parts were read from.
    parts : collections.abc.Iterable[Part]
        The parts.

    Returns
    -------
    dict[TextureKey, bytes]
        Each texture as RGBA.
    """
    keys = {t.material.texture for part in parts for t in part.triangles}
    return {key: decode(memory, key) for key in keys if key is not None}


def _sub(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _cross(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def orientations(parts: Iterable[Part]) -> dict[TextureKey, tuple[int, bool]]:
    """
    Work out how each texture is turned in its image, from the faces that sample it.

    The textures of upright faces (walls, signs, and the sides of a car) are often stored on their
    side or upside down, the texture coordinates turning them back. For each texture the direction
    that is down in the world is found in the image across every upright face, weighted by area,
    along with whether the coordinates mirror the image.

    Parameters
    ----------
    parts : collections.abc.Iterable[Part]
        The parts, z up.

    Returns
    -------
    dict[TextureKey, tuple[int, bool]]
        For each texture on an upright face, the quarter turns clockwise that put world down at the
        bottom of the image, and whether to mirror it left to right first.
    """
    votes: dict[TextureKey, list[float]] = {}
    for part in parts:
        for triangle in part.triangles:
            if (key := triangle.material.texture) is None:
                continue
            p = [_transform(part.matrix, *c.position, 1.0) for c in triangle.corners]
            uv = [c.uv for c in triangle.corners]
            e1, e2 = _sub(p[1], p[0]), _sub(p[2], p[0])
            normal = _cross(e1, e2)
            area = _dot(normal, normal) ** 0.5
            du1, dv1 = uv[1][0] - uv[0][0], uv[1][1] - uv[0][1]
            du2, dv2 = uv[2][0] - uv[0][0], uv[2][1] - uv[0][1]
            det = du1 * dv2 - du2 * dv1
            if area == 0 or det == 0 or abs(normal[1]) > _UPRIGHT * area:
                continue
            # Solve e = du * T + dv * B for the tangent and bitangent, then express world down
            # (0, -1, 0) in the tangent and bitangent axes by its components along the two edges,
            # giving the direction of down in the image.
            tangent = tuple((e1[i] * dv2 - e2[i] * dv1) / det for i in range(3))
            bitangent = tuple((e2[i] * du1 - e1[i] * du2) / det for i in range(3))
            mirrored = _dot(_cross(tangent, bitangent), normal) > 0
            down = (tangent[1] if mirrored else -tangent[1], -bitangent[1])
            tally = votes.setdefault(key, [0.0] * _VOTES)
            quarter = round(math.atan2(down[0], down[1]) / (math.tau / 4)) % 4
            tally[quarter + (_QUARTERS if mirrored else 0)] += area
    result = {}
    for key, tally in votes.items():
        best = max(range(_VOTES), key=tally.__getitem__)
        result[key] = (best % _QUARTERS, best >= _QUARTERS)
    return result


def _transform(matrix: Sequence[float], x: float, y: float, z: float,
               w: float) -> tuple[float, float, float]:
    out = [
        x * matrix[c] + y * matrix[4 + c] + z * matrix[8 + c] + w * matrix[12 + c] for c in range(3)
    ]
    return out[0], out[2], -out[1]


def _normal(matrix: Sequence[float], colour: tuple[int, int, int,
                                                   int]) -> tuple[float, float, float]:
    sx, sy, sz = (float(c - 256 if c >= _SIGN else c) for c in colour[:3])
    x, y, z = _transform(matrix, sx, sy, sz, 0.0)
    length = (x * x + y * y + z * z) ** 0.5
    return (x / length, y / length, z / length) if length else (0.0, 1.0, 0.0)


def build_glb(name: str, parts: Sequence[Part], images: dict[TextureKey, bytes]) -> bytes:
    """
    Write parts as one binary glTF, each part a node with the matrix applied to its vertices.

    Parameters
    ----------
    name : str
        Name of the scene.
    parts : collections.abc.Sequence[Part]
        The parts.
    images : dict[TextureKey, bytes]
        The decoded textures, from :py:func:`textures`.

    Returns
    -------
    bytes
        The GLB.
    """
    document = GLBDocument()
    texture_index: dict[TextureKey, int] = {}
    material_index: dict[Material, int] = {}
    for part in parts:
        groups: dict[Material, list[Triangle]] = {}
        for triangle in part.triangles:
            groups.setdefault(triangle.material, []).append(triangle)
        primitives = []
        for key, triangles in groups.items():
            texture, lit, two_sided = key.texture, key.lit, key.two_sided
            if key not in material_index:
                material: dict[str, object] = {
                    'doubleSided': two_sided,
                    'pbrMetallicRoughness': {
                        'metallicFactor': 0.0,
                        'roughnessFactor': 1.0
                    }
                }
                if texture is not None:
                    if texture not in texture_index:
                        texture_index[texture] = document.add_image(
                            encode_rgba(texture.width, texture.height, images[texture]),
                            'image/png', f'texture-{texture.address:06x}')
                    material['pbrMetallicRoughness'] = {
                        'baseColorTexture': {
                            'index': texture_index[texture]
                        },
                        'metallicFactor': 0.0,
                        'roughnessFactor': 1.0
                    }
                    if images[texture][3::4].strip(b'\xff'):
                        material['alphaMode'] = 'MASK'
                if not lit:
                    document.use('KHR_materials_unlit')
                    material['extensions'] = {'KHR_materials_unlit': {}}
                document.materials.append(material)
                material_index[key] = len(document.materials) - 1
            corners = [corner for triangle in triangles for corner in triangle.corners]
            attributes = {
                'POSITION':
                    document.floats([_transform(part.matrix, *c.position, 1.0) for c in corners],
                                    'VEC3',
                                    target=ARRAY_BUFFER,
                                    bounds=True),
                'TEXCOORD_0':
                    document.floats([c.uv for c in corners], 'VEC2', target=ARRAY_BUFFER)
            }
            if lit:
                attributes['NORMAL'] = document.floats(
                    [_normal(part.matrix, c.colour) for c in corners], 'VEC3', target=ARRAY_BUFFER)
            else:
                attributes['COLOR_0'] = document.floats(
                    [tuple(v / 255 for v in c.colour) for c in corners],
                    'VEC4',
                    target=ARRAY_BUFFER)
            primitives.append({
                'attributes': attributes,
                'indices': document.indices(range(len(corners))),
                'material': material_index[key]
            })
        document.meshes.append({'name': part.name, 'primitives': primitives})
        document.nodes.append({'mesh': len(document.meshes) - 1, 'name': part.name})
    return document.finish(name)
