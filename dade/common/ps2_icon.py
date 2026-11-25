"""
Convert PS2 save metadata (``icon.sys``) to JSON and PS2 3D icons (``.ico``/``.icn``) to glTF.

An icon opens with five 32-bit words: ``0x10000``, the number of animation shapes, the texture
type, a float of 1.0, and the vertex count. Each vertex stores one position per shape (four
signed 16-bit values, the fourth unused), a normal in the same form, a texture coordinate pair,
and an RGBA colour, every coordinate in 4.12 fixed point. The vertices form a triangle list.

The animation follows: ``1``, the frame length, the speed, the play offset, and the frame count,
then one record per frame of a shape, a key count, and that many keys of a time in frames and a
weight. Two keys at the same time are a step. The texture comes last, 128 by 128 RGBA5551, stored
raw or, with bit 3 of the texture type set, as a run-length coded block after its size. An icon
can omit the texture and is then coloured by its vertices.

An icon is written as a GLB with the texture embedded and as a glTF with the texture beside it as
a PNG. The first shape is the mesh and each other shape a morph target, and the frames are an
animation of the target weights. The icon is y down, and the mesh is turned to glTF's y up. Frames
are taken at 60 a second. The speed the icon records is written to the animation's ``extras``,
and how the console applies it is unconfirmed.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple
import base64
import json
import logging
import struct

from dade.common.exceptions import InvalidFormatError
from dade.common.gltf import ARRAY_BUFFER, TRIANGLES, UNSIGNED_BYTE, GLBDocument
from dade.common.image import double_ps2_alpha
from dade.common.io import u16, u32
from dade.common.json import write_json
from dade.common.png import encode_rgba

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from dade.common.typing import IconSysMeta

__all__ = ('EXTENSIONS', 'FRAMES_PER_SECOND', 'PS2Icon', 'build_icon_gltf', 'convert',
           'icon_sys_to_json', 'read_ps2_icon', 'write_ps2_icon')

log = logging.getLogger(__name__)

EXTENSIONS = frozenset({'.ico', '.icn', '.sys'})
"""File extensions handled by :py:func:`convert`.

:meta hide-value:
"""
FRAMES_PER_SECOND = 60
"""The rate the frames of an icon animation are written at.

:meta hide-value:
"""

_ICON_MAGIC = 0x10000
_ICON_HEADER = struct.Struct('<3IfI')
_ANIMATION_HEADER = struct.Struct('<2If2I')
_TEXTURE_DIM = 128
_TEXTURE_BYTES = _TEXTURE_DIM * _TEXTURE_DIM * 2
_COMPRESSED = 0x8
_FIXED = 4096.0
_ICON_SYS_SIZE = 0x1C8
_STEP = 1e-4
"""Seconds between the two keys written for a step, glTF requiring strictly increasing times.

:meta hide-value:
"""


class PS2Icon(NamedTuple):
    """A decoded PS2 3D icon."""

    shapes: tuple[tuple[tuple[float, float, float], ...], ...]
    """The vertex positions of each animation shape, in icon units of 1.0."""
    normals: tuple[tuple[float, float, float], ...]
    """The normal of each vertex."""
    texcoords: tuple[tuple[float, float], ...]
    """The texture coordinate pair of each vertex, with the origin at the top left."""
    colors: tuple[tuple[int, int, int, int], ...]
    """The RGBA colour of each vertex, with 128 as full intensity."""
    frame_length: int
    """The length of the animation in frames."""
    speed: float
    """The speed the animation records."""
    frames: tuple[tuple[int, tuple[tuple[float, float], ...]], ...]
    """The shape of each frame record and its keys of time in frames and weight."""
    texture: bytes | None
    """The texture as 128 by 128 RGBA, or :py:obj:`None` for an icon without one."""


def icon_sys_to_json(data: bytes) -> IconSysMeta:
    """
    Decode a PS2 ``icon.sys`` (save metadata).

    Parameters
    ----------
    data : bytes
        The ``icon.sys`` contents.

    Returns
    -------
    IconSysMeta
        Metadata (title, icon filenames, background transparency).

    Raises
    ------
    InvalidFormatError
        If the data is not a ``PS2D`` icon.sys or is shorter than 456 bytes.
    """
    if data[:4] != b'PS2D' or len(data) < _ICON_SYS_SIZE:
        msg = 'Not a `PS2D` icon.sys.'
        raise InvalidFormatError(msg)

    def cstr(off: int, length: int) -> str:
        return data[off:off + length].split(b'\0')[0].decode('shift_jis', 'replace')

    return {
        'magic': 'PS2D',
        'title_line_break': u16(data, 6),
        'background_transparency': u32(data, 0xC),
        'title': cstr(0xC0, 68),
        'icon_normal': cstr(0x108, 64),
        'icon_copy': cstr(0x148, 64),
        'icon_delete': cstr(0x188, 64)
    }


def _decompress(data: bytes) -> bytes:
    out = bytearray()
    position = 0
    while position + 2 <= len(data) and len(out) < _TEXTURE_BYTES:
        code = u16(data, position)
        position += 2
        if code & 0x8000:
            count = (0x10000 - code) * 2
            out += data[position:position + count]
            position += count
        else:
            out += data[position:position + 2] * code
            position += 2
    if len(out) < _TEXTURE_BYTES:
        msg = 'The compressed icon texture is truncated.'
        raise InvalidFormatError(msg)
    return bytes(out[:_TEXTURE_BYTES])


def _texture(data: bytes, offset: int, texture_type: int) -> bytes | None:
    if texture_type & _COMPRESSED:
        if offset + 4 > len(data):
            return None
        size = u32(data, offset)
        raw = _decompress(data[offset + 4:offset + 4 + size])
    elif len(data) - offset >= _TEXTURE_BYTES:
        raw = data[offset:offset + _TEXTURE_BYTES]
    else:
        return None
    rgba = bytearray(_TEXTURE_DIM * _TEXTURE_DIM * 4)
    for index, (pixel,) in enumerate(struct.iter_unpack('<H', raw)):
        rgba[index * 4:index * 4 + 4] = bytes(
            ((pixel & 0x1F) << 3, ((pixel >> 5) & 0x1F) << 3, ((pixel >> 10) & 0x1F) << 3, 255))
    return bytes(rgba)


def read_ps2_icon(data: bytes) -> PS2Icon:
    """
    Decode a PS2 3D icon.

    Parameters
    ----------
    data : bytes
        The ``.ico`` or ``.icn`` file.

    Returns
    -------
    PS2Icon
        The shapes, the vertex attributes, the animation, and the texture.

    Raises
    ------
    InvalidFormatError
        If the data is not a PS2 icon, its vertex count is not a positive multiple of three, the
        vertices or the animation run past the end of the data, or a compressed texture is
        truncated.
    """
    if len(data) < _ICON_HEADER.size:
        msg = 'The PS2 icon header is truncated.'
        raise InvalidFormatError(msg)
    magic, shape_count, texture_type, _, count = _ICON_HEADER.unpack_from(data)
    stride = 8 * shape_count + 16
    end = _ICON_HEADER.size + count * stride
    if magic != _ICON_MAGIC or shape_count == 0:
        msg = 'Not a PS2 icon.'
        raise InvalidFormatError(msg)
    if count <= 0 or count % 3 or end + _ANIMATION_HEADER.size > len(data):
        msg = f'The PS2 icon has an unusable vertex count of {count}.'
        raise InvalidFormatError(msg)
    records = [_ICON_HEADER.size + index * stride for index in range(count)]
    shapes = tuple(
        tuple(
            tuple(value / _FIXED for value in struct.unpack_from('<3h', data, record + 8 * shape))
            for record in records) for shape in range(shape_count))
    normal = 8 * shape_count
    normals = tuple(
        tuple(value / _FIXED for value in struct.unpack_from('<3h', data, record + normal))
        for record in records)
    texcoords = tuple(
        tuple(value / _FIXED for value in struct.unpack_from('<2h', data, record + normal + 8))
        for record in records)
    colors = tuple(struct.unpack_from('<4B', data, record + normal + 12) for record in records)
    _, frame_length, speed, _, frame_count = _ANIMATION_HEADER.unpack_from(data, end)
    position = end + _ANIMATION_HEADER.size
    frames = []
    for _ in range(frame_count):
        if position + 8 > len(data):
            msg = 'The PS2 icon animation is truncated.'
            raise InvalidFormatError(msg)
        shape, key_count = struct.unpack_from('<2I', data, position)
        position += 8
        if position + key_count * 8 > len(data):
            msg = 'The PS2 icon animation is truncated.'
            raise InvalidFormatError(msg)
        frames.append(
            (shape,
             tuple(
                 struct.unpack_from('<2f', data, position + key * 8) for key in range(key_count))))
        position += key_count * 8
    return PS2Icon(shapes, normals, texcoords, colors, frame_length, speed, tuple(frames),
                   _texture(data, position, texture_type))


def _turn(vector: Sequence[float]) -> tuple[float, float, float]:
    return vector[0], -vector[1], -vector[2]


def _weight(keys: Sequence[tuple[float, float]], time: float, *, after: bool) -> float:
    if not keys:
        return 0.0
    if exact := [value for key_time, value in keys if key_time == time]:
        return exact[-1] if after else exact[0]
    before = [(key_time, value) for key_time, value in keys if key_time < time]
    later = [(key_time, value) for key_time, value in keys if key_time > time]
    if not before or not later:
        return (before or later)[-1 if before else 0][1]
    (start, first), (stop, second) = before[-1], later[0]
    return first + (second - first) * (time - start) / (stop - start)


def _add_animation(document: GLBDocument, icon: PS2Icon) -> None:
    tracks = [keys for shape, keys in icon.frames if 0 < shape < len(icon.shapes)]
    if not tracks:
        return
    weights: dict[int, tuple[tuple[float, float], ...]] = dict.fromkeys(
        range(1, len(icon.shapes)), ())
    for shape, keys in icon.frames:
        if 0 < shape < len(icon.shapes):
            weights[shape] += tuple(keys)
    times: list[float] = []
    values: list[tuple[float]] = []
    for time in sorted({key_time for keys in tracks for key_time, _ in keys}):
        left = [_weight(weights[shape], time, after=False) for shape in sorted(weights)]
        right = [_weight(weights[shape], time, after=True) for shape in sorted(weights)]
        seconds = time / FRAMES_PER_SECOND
        if left != right and times:
            times.append(seconds)
            values.extend((value,) for value in left)
            seconds += _STEP
        times.append(seconds)
        values.extend((value,) for value in right)
    document.animations.append({
        'channels': [{
            'sampler': 0,
            'target': {
                'node': 0,
                'path': 'weights'
            }
        }],
        'extras': {
            'frameLength': icon.frame_length,
            'speed': icon.speed
        },
        'name':
            'icon',
        'samplers': [{
            'input': document.floats([(time,) for time in times], 'SCALAR', bounds=True),
            'interpolation': 'LINEAR',
            'output': document.floats(values, 'SCALAR')
        }]
    })


def build_icon_gltf(icon: PS2Icon, name: str, texture_uri: str | None = None) -> GLBDocument:
    """
    Build the glTF document of a PS2 icon.

    Parameters
    ----------
    icon : PS2Icon
        The decoded icon.
    name : str
        The name of the mesh, the node, and the scene.
    texture_uri : str | None
        Refer to the texture at this path instead of embedding it.

    Returns
    -------
    GLBDocument
        The document, ready to be finished as a GLB or as a glTF.
    """
    document = GLBDocument()
    base = [_turn(position) for position in icon.shapes[0]]
    attributes: dict[str, int] = {
        'COLOR_0':
            document.accessor(b''.join(
                bytes(double_ps2_alpha(channel) for channel in color) for color in icon.colors),
                              ARRAY_BUFFER,
                              componentType=UNSIGNED_BYTE,
                              count=len(icon.colors),
                              normalized=True,
                              type='VEC4'),
        'NORMAL':
            document.floats([_turn(normal) for normal in icon.normals], 'VEC3',
                            target=ARRAY_BUFFER),
        'POSITION':
            document.floats(base, 'VEC3', target=ARRAY_BUFFER, bounds=True)
    }
    pbr: dict[str, Any] = {'metallicFactor': 0.0}
    if icon.texture is not None:
        attributes['TEXCOORD_0'] = document.floats(list(icon.texcoords),
                                                   'VEC2',
                                                   target=ARRAY_BUFFER)
        texture = (document.add_image_uri(texture_uri, name)
                   if texture_uri is not None else document.add_image(
                       encode_rgba(_TEXTURE_DIM, _TEXTURE_DIM, icon.texture), 'image/png', name))
        pbr['baseColorTexture'] = {'index': texture}
    document.materials.append({'doubleSided': True, 'name': name, 'pbrMetallicRoughness': pbr})
    primitive: dict[str, Any] = {'attributes': attributes, 'material': 0, 'mode': TRIANGLES}
    mesh: dict[str, Any] = {'name': name, 'primitives': [primitive]}
    if len(icon.shapes) > 1:
        primitive['targets'] = [{
            'POSITION':
                document.floats([
                    tuple(moved - still
                          for moved, still in zip(_turn(position), origin, strict=True))
                    for position, origin in zip(shape, base, strict=True)
                ],
                                'VEC3',
                                target=ARRAY_BUFFER,
                                bounds=True)
        } for shape in icon.shapes[1:]]
        mesh['weights'] = [0.0] * (len(icon.shapes) - 1)
    document.meshes.append(mesh)
    document.nodes.append({'mesh': 0, 'name': name})
    _add_animation(document, icon)
    return document


def _gltf(document: GLBDocument, name: str) -> str:
    glb = document.finish(name)
    chunk = u32(glb, 12)
    gltf = json.loads(glb[20:20 + chunk])
    binary = bytes(document.blob)
    gltf['buffers'] = [{
        'byteLength': len(binary),
        'uri': 'data:application/octet-stream;base64,' + base64.b64encode(binary).decode()
    }]
    return json.dumps(gltf, indent=2, sort_keys=True) + '\n'


def write_ps2_icon(icon: PS2Icon, destination: Path) -> tuple[Path, ...]:
    """
    Write a PS2 icon as a GLB and as a glTF, and its texture as a PNG.

    Parameters
    ----------
    icon : PS2Icon
        The decoded icon.
    destination : Path
        The path of the files without a suffix. ``.glb``, ``.gltf``, and ``.png`` are appended.

    Returns
    -------
    tuple[Path, ...]
        The files written. An icon without a texture has no PNG.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    name = destination.name
    glb = destination.with_name(f'{name}.glb')
    gltf = destination.with_name(f'{name}.gltf')
    glb.write_bytes(build_icon_gltf(icon, name).finish(name))
    written = [glb, gltf]
    texture_uri = None
    if icon.texture is not None:
        png = destination.with_name(f'{name}.png')
        png.write_bytes(encode_rgba(_TEXTURE_DIM, _TEXTURE_DIM, icon.texture))
        written.append(png)
        texture_uri = png.name
    gltf.write_text(_gltf(build_icon_gltf(icon, name, texture_uri), name), encoding='utf-8')
    return tuple(written)


def convert(path: Path) -> Path | None:
    """
    Convert a PS2 ``icon.sys`` to JSON or a ``.ico``/``.icn`` icon to GLB, glTF, and PNG.

    Parameters
    ----------
    path : pathlib.Path
        The ``.sys`` / ``.ico`` / ``.icn`` file.

    Returns
    -------
    pathlib.Path | None
        The JSON or the GLB written beside the source, or ``None`` if the file was not a
        recognised PS2 resource.
    """
    if path.suffix.lower() == '.sys':
        try:
            meta = icon_sys_to_json(path.read_bytes())
        except InvalidFormatError:
            return None
        out = path.with_name(f'{path.name}.json')
        write_json(out, meta, ensure_ascii=False, trailing_newline=False)
        log.debug('Saved icon.sys metadata for `%s` -> `%s`.', path.name, out.name)
        return out
    try:
        icon = read_ps2_icon(path.read_bytes())
    except InvalidFormatError:
        return None
    written = write_ps2_icon(icon, path.with_suffix(''))
    log.debug('PS2 icon `%s`: %d vertices, %d shapes.', path.name, len(icon.normals),
              len(icon.shapes))
    return written[0]
