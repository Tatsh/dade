"""
Decryption of the ``.bfttf`` and ``.bfotf`` fonts of Mario Kart World.

A file is an 8-byte header and then the font, each 32-bit word XORed with a 4-byte key. The header
is the magic ``0x18029A7F`` and the length of the font, both XORed with the same key, and the key
therefore follows from the first word alone. The decrypted font is an ordinary TrueType or OpenType
file, or a TrueType collection.
"""
from __future__ import annotations

import numpy as np

__all__ = ('decode_font',)

_HEADER_SIZE = 8
_MAGIC = b'\x7f\x9a\x02\x18'
_WORD = 4
_SUFFIXES = {b'\x00\x01\x00\x00': '.ttf', b'true': '.ttf', b'OTTO': '.otf', b'ttcf': '.ttc'}


def decode_font(data: bytes) -> tuple[bytes, str]:
    """
    Decrypt a font.

    Parameters
    ----------
    data : bytes
        Decompressed ``.bfttf`` or ``.bfotf`` file.

    Returns
    -------
    tuple[bytes, str]
        The font, and its suffix: ``.ttf`` for one TrueType face, ``.otf`` for an OpenType face
        with CFF outlines, or ``.ttc`` for a collection of faces.

    Raises
    ------
    ValueError
        The data is too short, its recorded length does not fit the file, or it does not decrypt to
        a font.
    """
    if len(data) < _HEADER_SIZE + _WORD:
        message = 'The font is too short.'
        raise ValueError(message)
    key = bytes(a ^ b for a, b in zip(data[:_WORD], _MAGIC, strict=True))
    size = int.from_bytes(bytes(a ^ b for a, b in zip(data[_WORD:_HEADER_SIZE], key, strict=True)),
                          'big')
    if not 0 < size <= len(data) - _HEADER_SIZE:
        message = 'The recorded length of the font does not fit the file.'
        raise ValueError(message)
    padded = -(-size // _WORD) * _WORD
    body = np.frombuffer(data, np.uint8, min(padded, len(data) - _HEADER_SIZE), _HEADER_SIZE)
    keystream = np.resize(np.frombuffer(key, np.uint8), len(body))
    font = (body ^ keystream).tobytes()[:size]
    if (suffix := _SUFFIXES.get(font[:_WORD])) is None:
        message = 'The data does not decrypt to a font.'
        raise ValueError(message)
    return font, suffix
