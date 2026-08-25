"""
Materialise a disc source into an output directory.

A game unpacker processes its assets in place inside the output directory, so the source is first
copied there: :py:func:`materialize` extracts an ISO 9660 image (or a cue/bin pair) into the output
directory, or copies an already-extracted source directory into it. The source itself (the image
file or the input directory) is only ever opened read-only and is never modified.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import asyncio
import shutil

import anyio

from dade.common.cuebin import cuebin_to_iso
from dade.common.io import MmapReader
from dade.common.iso9660 import Iso9660Image

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = ('iter_ark_bytes', 'materialize', 'open_image')

_ARK_SUFFIX = '.ARK'
"""The upper-case suffix identifying an ARK archive on a disc.

:meta hide-value:
"""


def open_image(source: Path) -> Iso9660Image:
    """
    Open a disc-image file as an ISO 9660 image.

    A ``.cue`` file is read together with its ``.bin`` track and decoded to a plain image; any other
    file is treated as a raw ISO 9660 image and memory-mapped. A file that is neither a cue/bin pair
    nor a valid ISO 9660 image raises
    :py:class:`~dade.common.exceptions.InvalidFormatError` from the underlying reader.

    Parameters
    ----------
    source : pathlib.Path
        The disc-image file (an ISO image or the ``.cue`` of a cue/bin pair).

    Returns
    -------
    dade.common.iso9660.Iso9660Image
        The parsed image.
    """
    if source.suffix.lower() == '.cue':
        return Iso9660Image.from_bytes(cuebin_to_iso(source))
    return Iso9660Image(MmapReader(source))


def iter_ark_bytes(source: Path) -> Iterator[bytes]:
    """
    Yield the raw bytes of every ARK archive on ``source``, without materialising anything.

    A directory source's ``*.ark`` files are read from disk; a disc-image source's ARK files are
    read straight out of the image. This is the read-only path used by the unpacker's iteration.

    Parameters
    ----------
    source : pathlib.Path
        An already-extracted directory, an ISO image, or the ``.cue`` of a cue/bin pair.

    Yields
    ------
    bytes
        The bytes of each ARK archive, in path order.
    """
    if source.is_dir():
        for ark_path in sorted(
                p for p in source.rglob('*') if p.is_file() and p.suffix.lower() == '.ark'):
            yield ark_path.read_bytes()
        return
    image = open_image(source)
    for path, _ in image.iter_files():
        if path.upper().endswith(_ARK_SUFFIX):
            yield image.read_file(path)


async def materialize(source: Path, out: Path) -> None:
    """
    Populate ``out`` with the source's files, then leave it to be processed in place.

    A disc image is extracted into ``out``; an already-extracted source directory is copied into it.
    The source is only read, never modified. The parse, extraction, and copy run in a worker thread
    so the event loop is not blocked.

    Parameters
    ----------
    source : pathlib.Path
        An already-extracted directory, an ISO image, or the ``.cue`` of a cue/bin pair.
    out : pathlib.Path
        The output directory to populate (created if missing).
    """
    await anyio.Path(out).mkdir(parents=True, exist_ok=True)
    if await anyio.Path(source).is_dir():
        await asyncio.to_thread(shutil.copytree, source, out, dirs_exist_ok=True)
        return
    image = await asyncio.to_thread(open_image, source)
    await asyncio.to_thread(_extract_image, image, out)


def _extract_image(image: Iso9660Image, dest: Path) -> None:
    """
    Write every file of an image into ``dest`` mirroring its paths.

    Parameters
    ----------
    image : dade.common.iso9660.Iso9660Image
        The image to extract.
    dest : pathlib.Path
        The directory to populate (must already exist).
    """
    for path, _ in image.iter_files():
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(image.read_file(path))
