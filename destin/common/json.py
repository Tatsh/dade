"""Shared JSON writer used by more than one game submodule."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
import json

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('write_json',)


def write_json(path: Path,
               obj: Any,
               *,
               sort_keys: bool = False,
               ensure_ascii: bool = True,
               indent: int = 2,
               trailing_newline: bool = True) -> None:
    """
    Serialise ``obj`` to JSON and write it to ``path`` as UTF-8.

    Parameters
    ----------
    path : pathlib.Path
        Destination file to write.
    obj : Any
        A JSON-serialisable object.
    sort_keys : bool
        Sort object keys in the output.
    ensure_ascii : bool
        Escape non-ASCII characters instead of writing them as raw UTF-8.
    indent : int
        Number of spaces to use for indentation.
    trailing_newline : bool
        Append a trailing newline to the written text.
    """
    text = json.dumps(obj, indent=indent, sort_keys=sort_keys, ensure_ascii=ensure_ascii)
    if trailing_newline:
        text += '\n'
    path.write_text(text, encoding='utf-8')
