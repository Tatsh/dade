"""Reading of Xcode ``.strings`` localisation tables."""
from __future__ import annotations

from typing import TYPE_CHECKING
import plistlib
import re

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('read_strings',)

# `"key" = "value";`, with either side allowed to contain escaped quotes.
_TEXT_ENTRY = re.compile(r'"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"\s*;')
_COMMENT = re.compile(r'/\*.*?\*/|//[^\n]*', re.DOTALL)
_ESCAPES = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\'}
_UTF16_MARKS = (b'\xff\xfe', b'\xfe\xff')


def _unescape(text: str) -> str:
    """
    Resolve the backslash escapes an old-style table may use.

    Parameters
    ----------
    text : str
        One key or value, as it was spelled between its quotes.

    Returns
    -------
    str
        The text with its escapes resolved. An unrecognised escape yields the character it
        preceded, which is what the format's own readers do.
    """
    return re.sub(r'\\(.)', lambda match: _ESCAPES.get(match.group(1), match.group(1)), text)


def _parse_text(data: bytes) -> dict[str, str]:
    """
    Parse the old-style text form of a table.

    Parameters
    ----------
    data : bytes
        The file's contents. A byte order mark selects UTF-16, otherwise UTF-8 is assumed, which is
        what the format allows.

    Returns
    -------
    dict[str, str]
        Every entry, with comments discarded.
    """
    text = data.decode('utf-16') if data[:2] in _UTF16_MARKS else data.decode()
    text = _COMMENT.sub('', text)
    return {_unescape(key): _unescape(value) for key, value in _TEXT_ENTRY.findall(text)}


def read_strings(path: Path) -> dict[str, str]:
    """
    Read a ``.strings`` table in either of the two forms it ships in.

    Xcode compiles a table into a flat binary plist holding a dictionary of key to localised string,
    and that is what ships inside an application bundle. An uncompiled table is instead the
    old-style text form, so both are tried: the plist first, since it is the common case, and the
    text parse when the file turns out not to be a plist at all.

    Parameters
    ----------
    path : pathlib.Path
        The table to read.

    Returns
    -------
    dict[str, str]
        Every entry in the table.

    Raises
    ------
    ValueError
        When the file is a plist whose root is not a dictionary, so it is not a table.
    """
    data = path.read_bytes()
    try:
        loaded = plistlib.loads(data)
    except plistlib.InvalidFileException:
        return _parse_text(data)
    if not isinstance(loaded, dict):
        msg = f'{path} is a plist but its root is not a dictionary.'
        # The complaint is about the file's contents rather than the argument's type, so this is a
        # ValueError even though the check that found it is an isinstance.
        raise ValueError(msg)  # noqa: TRY004
    return loaded
