"""
Readers for the Interstate '82 level formats.

A level is a pair of files sharing a stem: an ``.msa`` world, which is text, and a ``.mrm``
terrain. The world names its textures inline as ``.bmp`` and ``.tga`` file names. The terrain
begins with a ``ZONV`` magic followed by a surface table whose entry count sits at offset 12 and
whose 0x80-byte entries each open with a NUL-terminated texture name.

Textures are resolved against a list of pools, since the shipped archives split them across
separate ``bmp``, ``tga``, and ``data`` extractions.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import re
import struct

from dade.common.io import read_cstring

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

__all__ = ('MRM_MAGIC', 'find_in_pools', 'level_ids', 'surface_names', 'texture_refs')

log = logging.getLogger(__name__)

MRM_MAGIC = b'ZONV'
"""Magic at the start of a ``.mrm`` terrain carrying a surface table.

:meta hide-value:
"""

_TEXTURE_RE = re.compile(r'[A-Za-z0-9_]+\.(?:bmp|tga)')
"""Matches a texture file name named inside an ``.msa`` world.

:meta hide-value:
"""
_SURFACE_COUNT_OFFSET = 12
"""Offset of the surface count within a ``.mrm`` header.

:meta hide-value:
"""
_SURFACE_TABLE_OFFSET = 0x10
"""Offset at which the surface table begins.

:meta hide-value:
"""
_SURFACE_ENTRY_SIZE = 0x80
"""Size in bytes of one surface table entry.

:meta hide-value:
"""
_SURFACE_NAME_SIZE = 0x20
"""Size in bytes of the texture name field in a surface table entry.

:meta hide-value:
"""


def surface_names(mrm: bytes) -> tuple[str, ...]:
    """
    Read the texture names out of a ``.mrm`` terrain's surface table.

    Parameters
    ----------
    mrm : bytes
        Contents of the ``.mrm`` file.

    Returns
    -------
    tuple[str, ...]
        Every non-empty surface texture name, in table order. Empty when the file carries no
        ``ZONV`` magic.
    """
    if mrm[:4] != MRM_MAGIC:
        return ()
    count = struct.unpack_from('<I', mrm, _SURFACE_COUNT_OFFSET)[0]
    names: list[str] = []
    for index in range(count):
        offset = _SURFACE_TABLE_OFFSET + index * _SURFACE_ENTRY_SIZE
        name = read_cstring(mrm[offset:offset + _SURFACE_NAME_SIZE])
        if name:
            names.append(name)
    return tuple(names)


def texture_refs(msa: bytes, mrm: bytes) -> tuple[str, ...]:
    """
    Collect every texture a level references, from both its world and its terrain.

    Parameters
    ----------
    msa : bytes
        Contents of the ``.msa`` world.
    mrm : bytes
        Contents of the ``.mrm`` terrain.

    Returns
    -------
    tuple[str, ...]
        Unique lowercased texture names, sorted.
    """
    refs = {match.lower() for match in _TEXTURE_RE.findall(msa.decode('latin1', 'replace'))}
    refs.update(name.lower() for name in surface_names(mrm))
    return tuple(sorted(refs))


def level_ids(data_dir: Path, mrm_dir: Path) -> tuple[str, ...]:
    """
    Find every level that has both a world and a terrain.

    Parameters
    ----------
    data_dir : pathlib.Path
        Directory holding the ``.msa`` worlds.
    mrm_dir : pathlib.Path
        Directory holding the ``.mrm`` terrains.

    Returns
    -------
    tuple[str, ...]
        The stems present in both directories, sorted.
    """
    worlds = {path.stem for path in data_dir.glob('*.msa')}
    terrains = {path.stem for path in mrm_dir.glob('*.mrm')}
    return tuple(sorted(worlds & terrains))


def find_in_pools(name: str, pools: Sequence[Path]) -> Path | None:
    """
    Resolve a file name against a list of directories, taking the first match.

    Parameters
    ----------
    name : str
        The file name to look for.
    pools : collections.abc.Sequence[pathlib.Path]
        Directories to search, in priority order.

    Returns
    -------
    pathlib.Path | None
        The first existing path, or ``None`` when the name is in no pool.
    """
    for pool in pools:
        if (candidate := pool / name).is_file():
            return candidate
    return None
