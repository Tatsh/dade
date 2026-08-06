"""Convert PS2 save metadata (``icon.sys``) to JSON and PS2 3D icons (``.ico``/``.icn``) to OBJ."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json
import logging
import struct

from PIL import Image
from destin.common.obj import encode_obj
from destin.common.typing import InvalidFormatError

if TYPE_CHECKING:
    from pathlib import Path

    from destin.common.typing import IconSysMeta

__all__ = ('EXTENSIONS', 'convert', 'icon_sys_to_json', 'ps2_icon_decompose')

log = logging.getLogger(__name__)

EXTENSIONS = frozenset({'.ico', '.icn', '.sys'})
"""File extensions handled by :py:func:`convert`."""

_ICON_MAGIC = 0x10000
_TEXTURE_BYTES = 0x8000  # 128 x 128 RGBA5551.
_TEXTURE_DIM = 128
_FIXED = 4096.0  # s16 fixed-point scale (4096 == 1.0).
_ICON_SYS_SIZE = 0x1C8  # Minimum icon.sys size (through the delete-icon filename field).


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
        If the data is not a ``PS2D`` icon.sys.
    """
    if data[:4] != b'PS2D' or len(data) < _ICON_SYS_SIZE:
        msg = 'Not a `PS2D` icon.sys.'
        raise InvalidFormatError(msg)

    def cstr(off: int, length: int) -> str:
        return data[off:off + length].split(b'\0')[0].decode('shift_jis', 'replace')

    return {
        'magic': 'PS2D',
        'title_line_break': struct.unpack_from('<H', data, 6)[0],
        'background_transparency': struct.unpack_from('<I', data, 0xC)[0],
        'title': cstr(0xC0, 68),
        'icon_normal': cstr(0x108, 64),
        'icon_copy': cstr(0x148, 64),
        'icon_delete': cstr(0x188, 64)
    }


def ps2_icon_decompose(path: Path, out_dir: Path) -> Path | None:  # noqa: PLR0914
    """
    Decompose a PS2 3D icon into ``out_dir/{model.obj, texture.png, model.mtl}``.

    The header is ``u32 0x10000, u32 animShapes, u32 texType, ..., u32 nVerts@0x10``. The vertex
    stride is ``8 * animShapes + 16`` (pos s16/4096, normal, uv s16/4096, RGBA) and the mesh is a
    triangle list. The texture is the trailing 0x8000 bytes, a 128x128 RGBA5551 image.

    Parameters
    ----------
    path : pathlib.Path
        The ``.ico`` / ``.icn`` file.
    out_dir : pathlib.Path
        Output directory.

    Returns
    -------
    pathlib.Path | None
        ``out_dir``, or ``None`` if the file is not a decodable PS2 icon.
    """
    data = path.read_bytes()
    if len(data) < 0x14 + _TEXTURE_BYTES or struct.unpack_from('<I', data, 0)[0] != _ICON_MAGIC:
        return None
    anim = struct.unpack_from('<I', data, 4)[0]
    nverts = struct.unpack_from('<I', data, 0x10)[0]
    stride = 8 * anim + 16
    if nverts <= 0 or nverts % 3 or 0x14 + nverts * stride > len(data) - _TEXTURE_BYTES:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    texture = data[-_TEXTURE_BYTES:]
    rgba = bytearray(_TEXTURE_DIM * _TEXTURE_DIM * 4)
    for i in range(_TEXTURE_DIM * _TEXTURE_DIM):
        pixel = struct.unpack_from('<H', texture, i * 2)[0]
        o = i * 4
        rgba[o] = (pixel & 0x1F) << 3
        rgba[o + 1] = ((pixel >> 5) & 0x1F) << 3
        rgba[o + 2] = ((pixel >> 10) & 0x1F) << 3
        rgba[o + 3] = 255
    Image.frombytes('RGBA', (_TEXTURE_DIM, _TEXTURE_DIM), bytes(rgba)).save(out_dir / 'texture.png')
    vertices, texcoords, normals = [], [], []
    for i in range(nverts):
        off = 0x14 + i * stride
        x, y, z = struct.unpack_from('<3h', data, off)
        nx, ny, nz = struct.unpack_from('<3h', data, off + 8 * anim)
        u, v = struct.unpack_from('<2h', data, off + 8 * anim + 8)
        vertices.append((x / _FIXED, y / _FIXED, z / _FIXED))
        texcoords.append((u / _FIXED, 1 - v / _FIXED))
        normals.append((nx / _FIXED, ny / _FIXED, nz / _FIXED))
    obj_text = encode_obj(vertices, [(t * 3, t * 3 + 1, t * 3 + 2) for t in range(nverts // 3)],
                          texcoords=texcoords,
                          normals=normals,
                          header=('# PS2 icon -> OBJ', 'mtllib model.mtl', 'usemtl icon'),
                          coordinate_format='{:.5g}',
                          texcoord_format='{:.5g}')
    (out_dir / 'model.obj').write_text(obj_text, encoding='utf-8')
    (out_dir / 'model.mtl').write_text('newmtl icon\nKd 1 1 1\nmap_Kd texture.png\n',
                                       encoding='utf-8')
    log.debug('PS2 icon `%s`: %d verts, 128x128 texture -> `%s/`.', path.name, nverts, out_dir.name)
    return out_dir


def convert(path: Path) -> Path | None:
    """
    Convert a PS2 ``icon.sys`` to JSON or a ``.ico``/``.icn`` icon to ``<name>/`` (OBJ + texture).

    Parameters
    ----------
    path : pathlib.Path
        The ``.sys`` / ``.ico`` / ``.icn`` file.

    Returns
    -------
    pathlib.Path | None
        The written output, or ``None`` if the file was not a recognised PS2 resource.
    """
    if path.suffix.lower() == '.sys':
        try:
            meta = icon_sys_to_json(path.read_bytes())
        except InvalidFormatError:
            return None
        out = path.with_name(f'{path.name}.json')
        out.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        log.debug('Saved icon.sys metadata for `%s` -> `%s`.', path.name, out.name)
        return out
    out_dir = path.with_suffix('')
    if ps2_icon_decompose(path, out_dir) is None:
        return None
    path.unlink()
    return out_dir
