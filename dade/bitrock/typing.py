"""Typing helpers for :py:mod:`bitrock`."""
from __future__ import annotations

from typing import Literal, NamedTuple

from dade.common.cookfs import Block
from dade.common.io import Reader

__all__ = ('Block', 'ExtractedFile', 'PageCompression', 'PayloadInfo', 'Reader')

PageCompression = Literal['lzham', 'lzma', 'zip']
"""Compression algorithms InstallBuilder applies to encrypted pages."""


class ExtractedFile(NamedTuple):
    """Description of a single member produced by an unpack operation."""
    path: str
    """Logical member path, relative to the archive root."""
    size: int
    """Size of the member in bytes."""
    executable: bool
    """Whether the member was marked executable."""
    written: bool
    """Whether the member was written to disk (``False`` for a dry run)."""


class PayloadInfo(NamedTuple):
    """
    Parsed ``installbuilder.payloadinfo`` header of a password-protected installer.

    All fields are the raw values read from the installer. See
    :py:func:`dade.bitrock.crypto.verify_password`.
    """
    times: int
    """Number of key-derivation iterations."""
    iv: bytes
    """16-byte initialisation vector."""
    password_key: bytes
    """32-byte Twofish key used during key derivation."""
    encrypted_key: bytes
    """64-byte encrypted payload key."""
    payload_ivs_hash: bytes
    """32-byte SHA-256 hash used to verify the decrypted payload IVs."""
    encrypted_payload_ivs: bytes
    """Encrypted pool of per-chunk IVs."""
