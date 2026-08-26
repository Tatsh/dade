"""
Apple-optimised PNG conversion.

Xcode rewrites the PNGs it bundles into an application: it prepends a ``CgBI`` chunk, byte-swaps
the colour channels, and premultiplies the alpha. No PNG reader outside Apple's own frameworks
handles the result. ``pngdefry`` undoes all three, and leaves an ordinary PNG alone.

Every iOS title handled here ships images in this form, so the conversion lives here rather than in
any one game's package.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import shutil
import subprocess as sp

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('CGBI_CHUNK_TYPE', 'PNG_MAGIC', 'defry_png', 'is_apple_optimized', 'write_defried_png')

PNG_MAGIC = b'\x89PNG\r\n\x1a\n'
"""The PNG signature, which also tells a decipher that worked from one that did not.

:meta hide-value:
"""
CGBI_CHUNK_TYPE = b'CgBI'
"""The chunk type Xcode writes ahead of ``IHDR`` in an optimised PNG.

:meta hide-value:
"""

_CHUNK_TYPE_OFFSET = len(PNG_MAGIC) + 4

log = logging.getLogger(__name__)


def is_apple_optimized(data: bytes) -> bool:
    """
    Report whether a PNG carries the ``CgBI`` chunk Xcode adds.

    The chunk is required to come first, before ``IHDR``, so only the one position is examined.

    Parameters
    ----------
    data : bytes
        The start of a PNG. Fewer bytes than the signature and one chunk header is not an error.

    Returns
    -------
    bool
        Whether the image is Apple-optimised.
    """
    return (data.startswith(PNG_MAGIC)
            and data[_CHUNK_TYPE_OFFSET:_CHUNK_TYPE_OFFSET + 4] == CGBI_CHUNK_TYPE)


def defry_png(source: Path, destination: Path, pngdefry: Path) -> bool:
    """
    Rewrite one Apple-optimised PNG as an ordinary one.

    ``pngdefry`` leaves a PNG that was never optimised alone, writing nothing and still succeeding,
    so a false return is the normal outcome for an ordinary PNG rather than an error.

    Parameters
    ----------
    source : pathlib.Path
        The PNG to convert.
    destination : pathlib.Path
        The file to write. Its parent directory must already exist.
    pngdefry : pathlib.Path
        The ``pngdefry`` binary.

    Returns
    -------
    bool
        Whether a converted file was written. ``pngdefry`` failing raises
        :py:class:`subprocess.CalledProcessError`.
    """
    # pngdefry names its output after the input and can only be pointed at a directory, so it runs
    # against a scratch directory beside the destination and the one file it writes is moved over.
    scratch = destination.parent / f'.{destination.name}.defry'
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        sp.run((str(pngdefry), f'-o{scratch}', str(source)),
               capture_output=True,
               check=True,
               text=True)
        written = scratch / source.name
        if not written.is_file():
            return False
        written.replace(destination)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return True


def write_defried_png(source: Path, destination: Path, pngdefry: Path) -> Path:
    """
    Write an ordinary PNG for a source that may or may not be Apple-optimised.

    Parameters
    ----------
    source : pathlib.Path
        The PNG to convert.
    destination : pathlib.Path
        The file to write. Its parent directory must already exist.
    pngdefry : pathlib.Path
        The ``pngdefry`` binary.

    Returns
    -------
    pathlib.Path
        The written file, which is *destination* whether it was converted or copied.
    """
    if not defry_png(source, destination, pngdefry):
        # Not an Apple-optimised PNG, so it is already readable everywhere and is copied as it is.
        if source != destination:
            shutil.copy2(source, destination)
        log.debug('`%s` is an ordinary PNG; copied.', source.name)
    return destination
