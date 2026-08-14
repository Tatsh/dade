"""
Reading of the downloaded ``chara_%03d.chr`` character-data files.

The game downloads these into its Application Support directory. Each is a :mod:`BFCodec
<destin.rhythmin.bfcodec>` payload wrapping lenient JSON that describes preferred music and
character sets, unlock bits, and so on, read by ``CharaManager::charaDecodeChr``. The JSON is
lenient in one respect only: it may carry a trailing comma before a closing bracket or brace, which
:func:`parse_chara` strips before handing the text to :mod:`json`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
import json
import re

from .bfcodec import decipher

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('decrypt_chara', 'parse_chara', 'read_chara')

_TRAILING_COMMA = re.compile(r',(\s*[\]}])')


def decrypt_chara(data: bytes, key: bytes | None = None) -> bytes:
    """
    Decrypt one ``.chr`` file to its JSON text.

    A payload whose length trailer does not check out, which means the file is truncated or is not
    a ``BFCodec`` payload at all, raises the :py:class:`ValueError`
    :py:func:`destin.rhythmin.bfcodec.decipher` raises.

    Parameters
    ----------
    data : bytes
        The file's contents.
    key : bytes | None
        The cipher key, defaulting to :py:func:`destin.rhythmin.bfcodec.default_key`.

    Returns
    -------
    bytes
        The decrypted payload, which should be UTF-8 JSON.
    """
    return decipher(data, key)


def parse_chara(payload: bytes) -> Any:
    """
    Parse a decrypted ``.chr`` payload.

    A payload that is not JSON even once its trailing commas are removed, which usually means it
    was decrypted with the wrong key, raises the :py:class:`json.JSONDecodeError`
    :py:func:`json.loads` raises.

    Parameters
    ----------
    payload : bytes
        The decrypted JSON text.

    Returns
    -------
    Any
        The parsed object.
    """
    return json.loads(_TRAILING_COMMA.sub(r'\1', payload.decode(errors='replace')))


def read_chara(path: Path, key: bytes | None = None) -> Any:
    """
    Read, decrypt, and parse one ``.chr`` file.

    This is :func:`decrypt_chara` followed by :func:`parse_chara`, and raises whatever either of
    them does.

    Parameters
    ----------
    path : pathlib.Path
        The file to read.
    key : bytes | None
        The cipher key, defaulting to :py:func:`destin.rhythmin.bfcodec.default_key`.

    Returns
    -------
    Any
        The parsed object.
    """
    return parse_chara(decrypt_chara(path.read_bytes(), key))
