"""
The game's two image forms.

A loose ``.png`` is an ordinary Apple-optimised PNG: Xcode rewrote it with a ``CgBI`` chunk, byte-
swapped channels, and premultiplied alpha, which no PNG reader outside Apple's frameworks handles.
``pngdefry`` undoes all three.

A ``.tex`` is the same thing enciphered. Its plaintext is a four-byte header the loaders discard
followed by the image itself, which is again an Apple-optimised PNG, so a converted texture goes
through ``pngdefry`` as well. The header is not a magic - it differs per file - and the engine
never looks at it, so it is dropped here as the engine drops it.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Final
import logging
import shutil
import subprocess as sp

from destin.common.bfcodec import BFCodec

from .cipher import texture_key

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('ENCRYPTED_HEADER_SIZE', 'PNG_MAGIC', 'decipher_image', 'defry_png', 'write_defried_png')

ENCRYPTED_HEADER_SIZE: Final = 4
"""Bytes of header the loaders drop before decoding the image.

:meta hide-value:
"""
PNG_MAGIC: Final = b'\x89PNG\r\n\x1a\n'
"""The PNG signature, used to tell a decipher that worked from one that did not.

:meta hide-value:
"""

log = logging.getLogger(__name__)


def decipher_image(data: bytes, key: bytes | None = None) -> bytes:
    """
    Decipher an encrypted image and drop its header.

    Parameters
    ----------
    data : bytes
        The enciphered image, length trailer included.
    key : bytes | None
        The cipher key, defaulting to :py:func:`destin.jubeatplus.cipher.texture_key`.

    Returns
    -------
    bytes
        The image bytes, ready to be written out as a PNG.

    Raises
    ------
    ValueError
        If the length trailer does not describe the buffer, or the plaintext is too short to hold
        the four-byte header.
    """
    plain = BFCodec(texture_key() if key is None else key).decipher(data)
    if len(plain) < ENCRYPTED_HEADER_SIZE:
        msg = (f'Too short for the {ENCRYPTED_HEADER_SIZE}-byte image header: {len(plain)} bytes.')
        raise ValueError(msg)
    return plain[ENCRYPTED_HEADER_SIZE:]


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
