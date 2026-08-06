"""Text converters: Dreamcast Shift-JIS / ISO-8859-15 ``.TXT`` files to UTF-8."""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('txt_to_utf8',)

log = logging.getLogger(__name__)


def _decode(raw: bytes) -> str:
    # ASCII and already-UTF-8 text pass as UTF-8; Japanese text is Shift-JIS; Western text (French,
    # German, Spanish, Italian) is ISO-8859-15, a single-byte encoding that decodes any byte and so
    # is the final fallback.
    for encoding in ('utf-8', 'shift-jis'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:  # ruff:ignore[try-except-in-loop]
            continue
    return raw.decode('iso-8859-15')


def txt_to_utf8(source: Path, dest_dir: Path) -> Path:
    """
    Re-encode an Incoming ``.TXT`` file as UTF-8.

    The source encoding is detected as UTF-8, Shift-JIS (Japanese), or ISO-8859-15 (Western), in
    that order. ASCII and already-UTF-8 files are written unchanged.

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
    destination = dest_dir / f'{source.stem}.txt'
    destination.write_text(_decode(source.read_bytes()), encoding='utf-8')
    return destination
