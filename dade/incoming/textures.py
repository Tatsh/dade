"""
Resolve and materialise textures referenced by converted models.

Dreamcast ``*_M.BIN`` models reference a sub-texture index into the level's ``*_T.PVR`` pack. PC
``.ian`` models carry no texture of their own; the referencing ``.odl`` pairs each mesh with a
``.ppm`` texture. This module locates those textures and writes them next to the model output.
"""
from __future__ import annotations

from functools import cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING
import logging
import re
import subprocess as sp

from PIL import Image

from .pvrpack import iter_pack_textures
from .tools import find_spvr2png

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ('find_level_pack', 'place_ian_texture', 'place_pack_textures')

log = logging.getLogger(__name__)

_OBJFILE_SKIP = re.compile(r'^\s*objfile\s+(?:lod|as)\b', re.IGNORECASE)
_OBJFILE = re.compile(r'^\s*objfile\s+"([^"]+)"', re.IGNORECASE)
_TEXTURE = re.compile(r'^\s*texture\s+"([^"]+)"', re.IGNORECASE)


def _norm(path: str) -> str:
    return path.replace('\\', '/').strip().lower()


@cache
def _odl_ian_textures(input_root: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for odl in Path(input_root).rglob('*'):
        if not odl.is_file() or odl.suffix.lower() != '.odl':
            continue
        current: str | None = None
        for line in odl.read_text(encoding='latin-1').splitlines():
            if _OBJFILE_SKIP.match(line):
                continue
            if objfile := _OBJFILE.match(line):
                current = _norm(objfile.group(1))
            elif (texture := _TEXTURE.match(line)) is not None and current is not None:
                value = _norm(texture.group(1))
                mapping.setdefault(current, value)
                mapping.setdefault(Path(current).name, value)
                current = None
    return mapping


@cache
def _ppm_index(input_root: str) -> dict[str, str]:
    index: dict[str, str] = {}
    for ppm in Path(input_root).rglob('*'):
        if not ppm.is_file() or ppm.suffix.lower() != '.ppm':
            continue
        parts = [p.lower() for p in ppm.parts]
        if 'ppm' in parts:
            tail = '/'.join(parts[len(parts) - parts[::-1].index('ppm'):])
            index.setdefault(tail, str(ppm))
        index.setdefault(ppm.name.lower(), str(ppm))
    return index


def place_ian_texture(source: Path, input_root: Path, dest_dir: Path) -> str | None:
    """
    Resolve the ``.ppm`` texture for an IAN model via the ODL files and write it as a PNG.

    Parameters
    ----------
    source : Path
        The ``.ian`` source file.
    input_root : Path
        The root of the source tree.
    dest_dir : Path
        The directory the PNG is written to (next to the model output).

    Returns
    -------
    str | None
        The written PNG file name, or ``None`` if no texture could be resolved.
    """
    mapping = _odl_ian_textures(str(input_root))
    try:
        relative = _norm(str(source.relative_to(input_root)))
    except ValueError:
        relative = source.name.lower()
    stripped = relative.removeprefix('pcobject/')
    texture = mapping.get(stripped) or mapping.get(source.name.lower())
    if texture is None:
        return None
    found = _ppm_index(str(input_root)).get(texture) or _ppm_index(str(input_root)).get(
        Path(texture).name)
    if found is None:
        return None
    destination = dest_dir / f'{source.stem}.png'
    try:
        with Image.open(found) as image:
            image.save(destination, format='PNG')
    except OSError as e:
        log.debug('Could not convert texture `%s`: %s', found, e)
        return None
    return destination.name


def place_pack_textures(pack: Path, indices: Iterable[int], dest_dir: Path,
                        prefix: str) -> dict[int, str]:
    """
    Extract the given sub-textures from a ``*_T.PVR`` pack and write them as PNGs.

    Parameters
    ----------
    pack : Path
        The ``*_T.PVR`` pack file.
    indices : Iterable[int]
        The sub-texture indices to extract.
    dest_dir : Path
        The directory the PNGs are written to.
    prefix : str
        File-name prefix for the written PNGs.

    Returns
    -------
    dict[int, str]
        Map of sub-texture index to written PNG file name.
    """
    textures = {t.position: t for t in iter_pack_textures(pack.read_bytes())}
    written: dict[int, str] = {}
    with TemporaryDirectory() as raw_dir:
        names = {}
        for index in sorted(set(indices)):
            if (texture := textures.get(index)) is None:
                continue
            name = f'{prefix}_tex{index}'
            (Path(raw_dir) / f'{name}.pvr').write_bytes(texture.data)
            names[index] = name
        if names:
            spvr2png = find_spvr2png()
            sp.run([str(spvr2png), '-s', raw_dir, '-d',
                    str(dest_dir)],
                   check=True,
                   capture_output=True)
    for index, name in names.items():
        if (dest_dir / f'{name}.png').is_file():
            written[index] = f'{name}.png'
    return written


def find_level_pack(input_root: Path, base: str) -> Path | None:
    """
    Find a level's ``*_T.PVR`` texture pack in the source tree.

    Parameters
    ----------
    input_root : Path
        The root of the source tree.
    base : str
        The level base name (for example ``AFRICA``).

    Returns
    -------
    Path | None
        The pack path, or ``None`` if not found.
    """
    target = f'{base}_t.pvr'.lower()
    return next((p for p in input_root.rglob('*') if p.is_file() and p.name.lower() == target),
                None)
