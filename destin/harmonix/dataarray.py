"""Decode compiled Harmonix DataArray (DTB) files (``.txt.bin`` / ``.ui.bin``) to JSON."""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import struct

from destin.common.json import write_json

if TYPE_CHECKING:
    from pathlib import Path

    from .typing import DataArrayNode

__all__ = ('EXTENSIONS', 'convert', 'dtb_to_obj')

log = logging.getLogger(__name__)

EXTENSIONS = frozenset({'.txt.bin', '.ui.bin'})
"""File extensions handled by :py:func:`convert`.

:meta hide-value:
"""

_DTB_VERSION = 2


def dtb_to_obj(data: bytes) -> tuple[list[DataArrayNode], bool]:
    """
    Decode a compiled DataArray (version 2) into nested lists.

    The compiled 2-bit element tag is ``0`` int32, ``1`` string (DTA symbol or quoted string),
    ``2`` float32, ``3`` sub-array. (Verified: a tag-2 value ``0x3F333333`` decodes to ``0.7``;
    the runtime loader at ``0x296c08`` reads the four raw bytes per scalar.)

    Parameters
    ----------
    data : bytes
        The compiled DataArray file contents.

    Returns
    -------
    tuple[list[DataArrayNode], bool]
        The decoded root array and whether the stream parsed exactly to its end.

    Raises
    ------
    ValueError
        If the file is not a version-2 DataArray.
    """
    if not data or data[0] != _DTB_VERSION:
        msg = 'Not a version-2 DataArray.'
        raise ValueError(msg)
    nsym = struct.unpack_from('<I', data, 1)[0]
    off = 5
    for _ in range(nsym):  # Skip the symbol table (source-path strings).
        off += 4 + struct.unpack_from('<I', data, off)[0]

    def node(off: int) -> tuple[list[DataArrayNode], int]:
        count = data[off] | (data[off + 1] << 8)
        off += 10  # u16 count, u16 id, u16 flags, u32 symIndex.
        ntw = (count + 0xF) >> 4
        tags = struct.unpack_from(f'<{ntw}I', data, off) if ntw else ()
        off += ntw * 4
        out: list[DataArrayNode] = []
        for i in range(count):
            match (tags[i >> 4] >> ((i & 0xF) * 2)) & 3:
                case 0:
                    out.append(struct.unpack_from('<i', data, off)[0])
                    off += 4
                case 1:
                    ln = struct.unpack_from('<I', data, off)[0]
                    off += 4
                    out.append(data[off:off + ln].decode('latin-1'))
                    off += ln
                case 2:
                    out.append(round(struct.unpack_from('<f', data, off)[0], 6))
                    off += 4
                case _:
                    child, off = node(off)
                    out.append(child)
        return out, off

    root, end = node(off)
    return root, end == len(data)


def convert(path: Path) -> Path | None:
    """
    Convert a compiled DataArray file to a sibling ``.json``, leaving the original in place.

    Parameters
    ----------
    path : pathlib.Path
        The ``.txt.bin`` / ``.ui.bin`` file.

    Returns
    -------
    pathlib.Path | None
        The written JSON path, or ``None`` if the file did not parse cleanly.
    """
    try:
        root, clean = dtb_to_obj(path.read_bytes())
    except (ValueError, struct.error, IndexError):
        return None
    if not clean:
        return None
    out = path.with_suffix('.json')
    write_json(out, root, ensure_ascii=False, trailing_newline=False)
    log.debug('DataArray `%s`: %d root elements -> `%s`.', path.name, len(root), out.name)
    return out
