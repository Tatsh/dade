"""
Model blob shapes and the textures inside them.

A decoded archive entry comes in one of three shapes, and feeding the wrong one to a display-list
parser yields rubbish textures decoded out of table bytes:

* a flat model, whose header is a segment-5 pointer table and so begins with ``0x05``;
* a sub-archive, two size words followed by a run of contiguous ``{0, offset, size}`` triples,
  each pointing at a sub-model;
* a sub-archive of raw environment tiles, each exactly 64 by 32 direct-colour RGBA5551 texels,
  which is how track skyboxes are stored and why they never begin with ``0x05``.

The walker is shared between the N64 and PC builds, which use the identical table layout in their
respective byte orders.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from .displaylist import parse_dl_textures, parse_pc_textures
from .images import decode_rgba16
from .typing import Texture

if TYPE_CHECKING:
    from .typing import Endian

__all__ = ('SKYBOX_HEIGHT', 'SKYBOX_WIDTH', 'collect_textures', 'walk_sub_archive')

SKYBOX_WIDTH = 64
"""Width of a raw environment tile in pixels.

:meta hide-value:
"""
SKYBOX_HEIGHT = 32
"""Height of a raw environment tile in pixels.

:meta hide-value:
"""
_SKYBOX_BYTES = SKYBOX_WIDTH * SKYBOX_HEIGHT * 2
_SEGMENT_5 = 0x05
_MIN_SUB_ARCHIVE = 4
_TRIPLE_SIZE = 12
_MIN_HEADER_BYTES = 4


def _is_flat_model(blob: bytes, endian: Endian) -> bool:
    return bool((struct.unpack_from(f'{endian}I', blob, 0)[0] >> 24) == _SEGMENT_5)


def walk_sub_archive(blob: bytes, endian: Endian = '>') -> list[tuple[int, int]]:
    """
    Read the ``{0, offset, size}`` triple table of a sub-archive.

    Parameters
    ----------
    blob : bytes
        A decoded archive entry.
    endian : dade.xg2.typing.Endian
        Byte order of the table.

    Returns
    -------
    list[tuple[int, int]]
        The offset and size of each sub-blob. Empty when *blob* is not a sub-archive; the table
        ends at the first record that is malformed or not contiguous with the previous one.
    """
    n = len(blob)
    pos = 8
    previous: int | None = None
    subs: list[tuple[int, int]] = []
    while pos + _TRIPLE_SIZE <= n:
        zero, offset, size = struct.unpack_from(f'{endian}3I', blob, pos)
        if zero != 0 or not (0 < offset < n and size > 0 and offset + size <= n):
            break
        if previous is not None and offset != previous:
            break
        subs.append((offset, size))
        previous = offset + size
        pos += _TRIPLE_SIZE
    return subs


def collect_textures(blob: bytes, endian: Endian = '>') -> list[Texture]:
    """
    Decode every texture in a decoded archive entry, whatever shape it has.

    Parameters
    ----------
    blob : bytes
        A decoded archive entry.
    endian : dade.xg2.typing.Endian
        Byte order: ``>`` for the N64 builds, ``<`` for the PC port.

    Returns
    -------
    list[dade.xg2.typing.Texture]
        The decoded textures.
    """
    parse = parse_dl_textures if endian == '>' else parse_pc_textures
    n = len(blob)
    if n < _TRIPLE_SIZE or _is_flat_model(blob, endian):
        return parse(blob)
    subs = walk_sub_archive(blob, endian)
    if len(subs) < _MIN_SUB_ARCHIVE:
        return parse(blob)
    out: list[Texture] = []
    for offset, size in subs:
        sub = blob[offset:offset + size]
        if size >= _MIN_HEADER_BYTES and _is_flat_model(sub, endian):
            out += parse(sub)
        elif size == _SKYBOX_BYTES:
            out.append(
                Texture(
                    'rgba16', offset, SKYBOX_WIDTH, SKYBOX_HEIGHT,
                    decode_rgba16(sub, 0, SKYBOX_WIDTH, SKYBOX_HEIGHT, SKYBOX_WIDTH * 2, endian)))
    return out
