"""
Property lists, made JSON-safe.

A property list can hold three things JSON cannot: raw data, dates, and keyed-archiver UIDs. Dates
become ISO 8601 strings and UIDs become integers, both losslessly.

Data is the interesting one. Two settings in ``DefaultSettings.plist`` - the news feed's URL and the
jubeat Lab URL - are not opaque blobs at all but enciphered strings, keyed with
:py:func:`dade.jubeatplus.cipher.lab_url_key`. Any data value that deciphers with that key into
printable text is reported with the text beside its bytes, which is what turns the two settings back
into the URLs they are; anything else keeps its bytes alone.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
import plistlib

from dade.common.bfcodec import BFCodec

from .cipher import lab_url_key

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('json_safe', 'read_plist')


# Read a data value as an enciphered string, or nothing when it is not one.
def _decipher_text(data: bytes) -> str | None:
    try:
        plain = BFCodec(lab_url_key()).decipher(data)
    except ValueError:
        return None
    try:
        text = plain.decode()
    except UnicodeDecodeError:
        return None
    return text if text.isprintable() else None


def json_safe(value: Any) -> Any:
    """
    Convert a decoded property-list value to something JSON can hold.

    Parameters
    ----------
    value : Any
        A value from :py:func:`plistlib.load`, of any type and nesting.

    Returns
    -------
    Any
        The same value with data, dates, and UIDs replaced by JSON-holdable equivalents.
    """
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, plistlib.UID):
        return value.data
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        data = bytes(value)
        out: dict[str, Any] = {'hex': data.hex(), 'length': len(data)}
        if (text := _decipher_text(data)) is not None:
            out['deciphered'] = text
        return out
    return value


def read_plist(path: Path) -> Any:
    """
    Read a property list, binary or XML, as JSON-holdable values.

    Parameters
    ----------
    path : pathlib.Path
        The property list to read.

    Returns
    -------
    Any
        The decoded root object, passed through :py:func:`json_safe`. A file that is not a property
        list raises :py:class:`plistlib.InvalidFileException`.
    """
    with path.open('rb') as fileobj:
        return json_safe(plistlib.load(fileobj))
