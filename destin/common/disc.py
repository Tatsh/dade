"""
Mount a disc source as a read-only directory tree.

A game unpacker wants a directory it can walk, but its input may equally be an already-extracted
directory, a raw ISO 9660 image, or a cue/bin pair. :py:func:`mount` (and its synchronous companion
:py:func:`mount_sync`) hide that difference: a directory is yielded unchanged, while an image is
materialised into a temporary directory for the duration of the context and removed afterwards. The
source itself is only ever opened read-only.
"""
from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
import asyncio
import shutil
import tempfile

from destin.common.cuebin import cuebin_to_iso
from destin.common.io import MmapReader
from destin.common.iso9660 import Iso9660Image
import anyio

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

__all__ = ('mount', 'mount_sync', 'open_image')


def open_image(source: Path) -> Iso9660Image:
    """
    Open a disc-image file as an ISO 9660 image.

    A ``.cue`` file is read together with its ``.bin`` track and decoded to a plain image; any other
    file is treated as a raw ISO 9660 image and memory-mapped. A file that is neither a cue/bin pair
    nor a valid ISO 9660 image raises
    :py:class:`~destin.common.exceptions.InvalidFormatError` from the underlying reader.

    Parameters
    ----------
    source : pathlib.Path
        The disc-image file (an ISO image or the ``.cue`` of a cue/bin pair).

    Returns
    -------
    destin.common.iso9660.Iso9660Image
        The parsed image.
    """
    if source.suffix.lower() == '.cue':
        return Iso9660Image.from_bytes(cuebin_to_iso(source))
    return Iso9660Image(MmapReader(source))


def _extract_image(image: Iso9660Image, dest: Path) -> None:
    """
    Write every file of an image into ``dest`` mirroring its paths.

    Parameters
    ----------
    image : destin.common.iso9660.Iso9660Image
        The image to extract.
    dest : pathlib.Path
        The directory to populate (must already exist).
    """
    for path, _ in image.iter_files():
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(image.read_file(path))


@contextmanager
def mount_sync(source: Path) -> Iterator[Path]:
    """
    Yield a directory for ``source``, extracting a disc image to a temporary one if needed.

    Parameters
    ----------
    source : pathlib.Path
        An already-extracted directory, an ISO image, or the ``.cue`` of a cue/bin pair.

    Yields
    ------
    pathlib.Path
        A directory holding the source's files: ``source`` itself when it is a directory, otherwise
        a temporary directory removed when the context closes.
    """
    if source.is_dir():
        yield source
        return
    mount_point = Path(tempfile.mkdtemp(prefix='destin-mount-'))
    try:
        _extract_image(open_image(source), mount_point)
        yield mount_point
    finally:
        shutil.rmtree(mount_point, ignore_errors=True)


@asynccontextmanager
async def mount(source: Path) -> AsyncIterator[Path]:
    """
    Yield a directory for ``source``, extracting a disc image to a temporary one if needed.

    This is the asynchronous form of :py:func:`mount_sync`; the image parse and extraction run in a
    worker thread so the event loop is not blocked.

    Parameters
    ----------
    source : pathlib.Path
        An already-extracted directory, an ISO image, or the ``.cue`` of a cue/bin pair.

    Yields
    ------
    pathlib.Path
        A directory holding the source's files: ``source`` itself when it is a directory, otherwise
        a temporary directory removed when the context closes.
    """
    if await anyio.Path(source).is_dir():
        yield source
        return
    mount_point = Path(tempfile.mkdtemp(prefix='destin-mount-'))
    try:
        image = await asyncio.to_thread(open_image, source)
        await asyncio.to_thread(_extract_image, image, mount_point)
        yield mount_point
    finally:
        await asyncio.to_thread(shutil.rmtree, mount_point, ignore_errors=True)
