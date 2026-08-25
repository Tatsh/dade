"""
The game's Blowfish keys.

Every encrypted file uses :py:class:`dade.common.bfcodec.BFCodec`; only the key varies. Each key
is the MD5 of a passphrase the binary assembles on the stack in pieces, so no passphrase appears
whole in the executable, and every one of them is hashed over ``strlen`` bytes so the terminating
NUL is excluded.

Two of the seven keys carry the shipped assets. :py:data:`TEXTURE_PASSPHRASE` covers ``.tex``
textures and the entries of the marker, hold-marker, and share-image ZIPs, whose plaintext is a
four-byte header followed by a PNG. :py:data:`BGM_PASSPHRASE` covers every entry of a ``.jbt`` tune
package, whose plaintext carries no header at all. The remaining five guard runtime state - the
save file, the mission records, the challenge panel resources, the Lab URL, and the newer ``infov3``
tune metadata - and are provided because a download may still hold files that use them.
"""
from __future__ import annotations

from typing import Final
import functools
import hashlib

__all__ = ('BGM_PASSPHRASE', 'LAB_URL_PASSPHRASE', 'MISSION_DATA_PASSPHRASE',
           'RESOURCE_DATA_PASSPHRASE', 'SAVE_DATA_PASSPHRASE', 'TEXTURE_PASSPHRASE',
           'TUNE_INFO_PASSPHRASE', 'bgm_key', 'key_for_passphrase', 'lab_url_key',
           'mission_data_key', 'resource_data_key', 'save_data_key', 'texture_key', 'tune_info_key')

BGM_PASSPHRASE: Final = b'Konami Bemani Mobile iPad'
"""Passphrase keying every entry of a ``.jbt`` tune package.

:meta hide-value:
"""
LAB_URL_PASSPHRASE: Final = b'js^_YjfYXH`_]MQM;6.'
"""Passphrase keying the "Lab" URL and its table view.

:meta hide-value:
"""
MISSION_DATA_PASSPHRASE: Final = b'jubeatmissiondata'
"""Passphrase keying the per-sheet mission records.

:meta hide-value:
"""
RESOURCE_DATA_PASSPHRASE: Final = b'jubeatskmpledata'
"""Passphrase keying the challenge panel resources.

The binary stores ``skmple`` where ``sample`` was surely meant. The typo is in the shipped string
and so is part of the key; it must be hashed exactly as it is.

:meta hide-value:
"""
SAVE_DATA_PASSPHRASE: Final = b'js^_Yjs5ea`YUe6FQSAH;@S'
"""Passphrase keying the save file.

:meta hide-value:
"""
TEXTURE_PASSPHRASE: Final = b'copious plus knit ripples'
"""Passphrase keying ``.tex`` textures and the entries of the image ZIPs.

:meta hide-value:
"""
TUNE_INFO_PASSPHRASE: Final = b'Konami Bemani Mobile iOS'
"""Passphrase keying the newer ``infov3`` tune metadata.

Its stack prefix is shared with :py:data:`BGM_PASSPHRASE`; the two differ only in the ``iOS``
against ``iPad`` tail, which is enough to make the digests unrelated.

:meta hide-value:
"""


@functools.cache
def key_for_passphrase(passphrase: bytes) -> bytes:
    """
    Derive a cipher key from its passphrase.

    Parameters
    ----------
    passphrase : bytes
        The passphrase, without a terminating NUL.

    Returns
    -------
    bytes
        The 16-byte MD5 digest the game hands to the codec.
    """
    return hashlib.md5(passphrase, usedforsecurity=False).digest()


def bgm_key() -> bytes:
    """
    Derive the key every ``.jbt`` entry uses.

    Returns
    -------
    bytes
        The MD5 of :py:data:`BGM_PASSPHRASE`.
    """
    return key_for_passphrase(BGM_PASSPHRASE)


def lab_url_key() -> bytes:
    """
    Derive the key protecting the "Lab" URL.

    Returns
    -------
    bytes
        The MD5 of :py:data:`LAB_URL_PASSPHRASE`.
    """
    return key_for_passphrase(LAB_URL_PASSPHRASE)


def mission_data_key() -> bytes:
    """
    Derive the key protecting the mission records.

    Returns
    -------
    bytes
        The MD5 of :py:data:`MISSION_DATA_PASSPHRASE`.
    """
    return key_for_passphrase(MISSION_DATA_PASSPHRASE)


def resource_data_key() -> bytes:
    """
    Derive the key protecting the challenge panel resources.

    Returns
    -------
    bytes
        The MD5 of :py:data:`RESOURCE_DATA_PASSPHRASE`.
    """
    return key_for_passphrase(RESOURCE_DATA_PASSPHRASE)


def save_data_key() -> bytes:
    """
    Derive the key protecting the save file.

    Returns
    -------
    bytes
        The MD5 of :py:data:`SAVE_DATA_PASSPHRASE`.
    """
    return key_for_passphrase(SAVE_DATA_PASSPHRASE)


def texture_key() -> bytes:
    """
    Derive the key every ``.tex`` texture and image ZIP entry uses.

    Returns
    -------
    bytes
        The MD5 of :py:data:`TEXTURE_PASSPHRASE`.
    """
    return key_for_passphrase(TEXTURE_PASSPHRASE)


def tune_info_key() -> bytes:
    """
    Derive the key the newer ``infov3`` tune metadata uses.

    Returns
    -------
    bytes
        The MD5 of :py:data:`TUNE_INFO_PASSPHRASE`.
    """
    return key_for_passphrase(TUNE_INFO_PASSPHRASE)
