"""
The game's two image forms.

A loose ``.png`` is an ordinary Apple-optimised PNG: Xcode rewrote it with a ``CgBI`` chunk, byte-
swapped channels, and premultiplied alpha, which no PNG reader outside Apple's frameworks handles.
``pngdefry`` undoes all three.

A ``.tex`` is the same thing enciphered. Its plaintext is a four-byte header the loaders discard
followed by the image itself, which is again an Apple-optimised PNG, so a converted texture goes
through ``pngdefry`` as well. The header is not a magic - it differs per file - and the engine
never looks at it, so it is dropped here as the engine drops it.

The ``pngdefry`` conversion itself is :py:mod:`dade.common.apple_png`, shared with the other iOS
titles.
"""
from __future__ import annotations

from typing import Final

from dade.common.apple_png import PNG_MAGIC, defry_png, write_defried_png
from dade.common.bfcodec import BFCodec

from .cipher import texture_key

__all__ = ('ENCRYPTED_HEADER_SIZE', 'PNG_MAGIC', 'decipher_image', 'defry_png', 'write_defried_png')

ENCRYPTED_HEADER_SIZE: Final = 4
"""Bytes of header the loaders drop before decoding the image.

:meta hide-value:
"""


def decipher_image(data: bytes, key: bytes | None = None) -> bytes:
    """
    Decipher an encrypted image and drop its header.

    Parameters
    ----------
    data : bytes
        The enciphered image, length trailer included.
    key : bytes | None
        The cipher key, defaulting to :py:func:`dade.jubeatplus.cipher.texture_key`.

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
