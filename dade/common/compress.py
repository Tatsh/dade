"""One-shot DEFLATE decompression helpers shared by the game submodules."""
from __future__ import annotations

from typing import Literal
import zlib

from typing_extensions import assert_never

__all__ = ('GZIP_WBITS', 'inflate')

GZIP_WBITS = 16 + zlib.MAX_WBITS
"""Window-bits value selecting a gzip wrapper for :py:func:`zlib.decompress`.

:meta hide-value:
"""


def inflate(data: bytes, *, mode: Literal['zlib', 'gzip', 'raw']) -> bytes:
    """
    Decompress a one-shot DEFLATE stream.

    Parameters
    ----------
    data : bytes
        The compressed bytes.
    mode : Literal['zlib', 'gzip', 'raw']
        The stream framing: ``'zlib'`` for a zlib-wrapped stream, ``'gzip'`` for a gzip-wrapped
        stream, or ``'raw'`` for a headerless (raw DEFLATE) stream.

    Returns
    -------
    bytes
        The decompressed bytes.
    """
    match mode:
        case 'zlib':
            return zlib.decompress(data)
        case 'gzip':
            return zlib.decompress(data, GZIP_WBITS)
        case 'raw':
            return zlib.decompress(data, -zlib.MAX_WBITS)
        case _:  # pragma: no cover
            assert_never(mode)
