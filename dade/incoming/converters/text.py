"""Text converters: Dreamcast Shift-JIS / ISO-8859-15 ``.TXT`` files to UTF-8."""
from __future__ import annotations

from typing import TYPE_CHECKING

from dade.common.text import recode_to_utf8

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('txt_to_utf8',)


def txt_to_utf8(source: Path, dest_dir: Path) -> Path:
    """
    Re-encode an Incoming ``.TXT`` file as UTF-8.

    The source encoding is detected as UTF-8, Shift-JIS (Japanese), or ISO-8859-15 (Western), in
    that order. ASCII and already-UTF-8 files are written unchanged. Japanese text is Shift-JIS;
    Western text (French, German, Spanish, Italian) is ISO-8859-15, a single-byte encoding that
    decodes any byte and so is the final fallback.

    Parameters
    ----------
    source : Path
        The source ``.txt`` file.
    dest_dir : Path
        The directory the UTF-8 file is written to.

    Returns
    -------
    Path
        The written UTF-8 path.
    """
    return recode_to_utf8(source, dest_dir)
