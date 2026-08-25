"""
Re-encode legacy game text as UTF-8.

Games of this era ship localised text in whichever single- or multi-byte encoding the target
territory used, with no declaration of which one. The encoding is therefore recovered by trial:
candidates are attempted in order and the first that decodes cleanly wins, with a single-byte
encoding as the final fallback because it accepts any byte sequence and so can never fail.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

__all__ = ('DEFAULT_ENCODINGS', 'DEFAULT_FALLBACK', 'decode_text', 'recode_to_utf8')

DEFAULT_ENCODINGS = ('utf-8', 'shift-jis')
"""Encodings tried in order before the fallback.

:meta hide-value:
"""
DEFAULT_FALLBACK = 'iso-8859-15'
"""Single-byte encoding used when no candidate decodes cleanly.

:meta hide-value:
"""


def decode_text(raw: bytes,
                encodings: Sequence[str] = DEFAULT_ENCODINGS,
                fallback: str = DEFAULT_FALLBACK) -> str:
    """
    Decode text of an undeclared encoding.

    Parameters
    ----------
    raw : bytes
        The encoded text.
    encodings : Sequence[str]
        Candidate encodings, tried in order. The first that decodes the whole input wins.
    fallback : str
        Encoding applied when no candidate succeeds. This must be one that accepts any byte
        sequence, such as a single-byte encoding, or the call may raise.

    Returns
    -------
    str
        The decoded text.
    """
    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:  # ruff:ignore[try-except-in-loop]
            continue
    return raw.decode(fallback)


def recode_to_utf8(source: Path,
                   dest_dir: Path,
                   encodings: Sequence[str] = DEFAULT_ENCODINGS,
                   fallback: str = DEFAULT_FALLBACK,
                   suffix: str = '.txt') -> Path:
    """
    Re-encode a text file as UTF-8 in *dest_dir*.

    The source file's stem is kept and *suffix* is applied. Text that is already UTF-8 is written
    through unchanged.

    Parameters
    ----------
    source : Path
        The source text file.
    dest_dir : Path
        The directory the UTF-8 file is written to.
    encodings : Sequence[str]
        Candidate source encodings, passed to :py:func:`decode_text`.
    fallback : str
        Fallback source encoding, passed to :py:func:`decode_text`.
    suffix : str
        Suffix given to the written file.

    Returns
    -------
    Path
        The written UTF-8 path.
    """
    destination = dest_dir / f'{source.stem}{suffix}'
    destination.write_text(decode_text(source.read_bytes(), encodings, fallback), encoding='utf-8')
    return destination
