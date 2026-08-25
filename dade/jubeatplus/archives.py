"""
The two kinds of ZIP the game ships.

A ``.jbt`` is one tune: a ZIP holding the tune's metadata, its two artwork sizes, its two title
plates, its charts, and both of its audio streams, with a sixteen-byte MD5 of the ZIP appended
after the end of the archive. Every entry is enciphered with
:py:func:`dade.jubeatplus.cipher.bgm_key`, and, apart from the newer ``infov3`` metadata, none of
them carries a header.

A plain ``.zip`` is a marker animation (``mk*.zip``), a hold-marker animation (``hm*.zip``), or the
share images (``twitterResources.zip``). Their entries are enciphered with
:py:func:`dade.jubeatplus.cipher.texture_key` and do carry the four-byte header, exactly as a
``.tex`` does. Not every entry is enciphered - the share images ship a plain-text ``filename.txt``
and the archiver's own ``__MACOSX`` residue - so each entry is deciphered only if that succeeds and
yields something recognisable.

Both kinds unpack into a directory named after the archive, and every entry is written under the
name it had inside, with the extension its decoded content turned out to need.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final
from xml.parsers.expat import ExpatError
import hashlib
import logging
import plistlib
import zipfile

from dade.common.bfcodec import BFCodec
from dade.common.json import write_json

from .audio import M4A_MAGIC
from .chart import MAGICS as CHART_MAGICS, parse_chart
from .cipher import bgm_key, texture_key, tune_info_key
from .images import ENCRYPTED_HEADER_SIZE, PNG_MAGIC, write_defried_png

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from .typing import Difficulty

__all__ = ('CHART_ENTRIES', 'JBT_DIGEST_SIZE', 'unpack_jbt', 'unpack_zip')

CHART_ENTRIES: dict[str, Difficulty] = {
    'seq_bas': 'basic',
    'seq_adv': 'advanced',
    'seq_ext': 'extreme'
}
"""Tune-package entry name to the difficulty its chart is for.

:meta hide-value:
"""
JBT_DIGEST_SIZE: Final = 16
"""Bytes of MD5 appended after the end of a tune package's ZIP.

:meta hide-value:
"""

log = logging.getLogger(__name__)

_PLIST_MAGICS = (b'bplist00', b'<?xml')
_INFO_V3 = 'infov3'


def _load_plist(data: bytes) -> Any:
    try:
        return plistlib.loads(data)
    except (plistlib.InvalidFileException, ValueError, ExpatError):
        return None


# Decipher an entry, returning nothing when it was never enciphered to begin with.
def _try_decipher(data: bytes, key: bytes, *, header: bool) -> bytes | None:
    try:
        plain = BFCodec(key).decipher(data)
    except ValueError:
        return None
    if not header:
        return plain
    if len(plain) < ENCRYPTED_HEADER_SIZE:
        return None
    return plain[ENCRYPTED_HEADER_SIZE:]


# Write one decoded entry, choosing its extension from what the bytes turned out to be.
def _write_payload(payload: bytes, stem: Path, name: str, pngdefry: Path | None) -> Path:
    if payload.startswith(PNG_MAGIC):
        destination = stem.with_name(f'{stem.name}.png')
        destination.write_bytes(payload)
        if pngdefry is not None:
            write_defried_png(destination, destination, pngdefry)
        return destination
    if payload[4:8] == M4A_MAGIC:
        destination = stem.with_name(f'{stem.name}.m4a')
        destination.write_bytes(payload)
        return destination
    if payload[:4] in CHART_MAGICS:
        destination = stem.with_name(f'{stem.name}.json')
        write_json(destination,
                   parse_chart(payload, CHART_ENTRIES.get(name)),
                   ensure_ascii=False,
                   sort_keys=True)
        return destination
    if payload.startswith(_PLIST_MAGICS) and (loaded := _load_plist(payload)) is not None:
        destination = stem.with_name(f'{stem.name}.json')
        write_json(destination, loaded, ensure_ascii=False, sort_keys=True)
        return destination
    stem.write_bytes(payload)
    return stem


def _entries(archive: zipfile.ZipFile) -> Iterator[tuple[str, bytes]]:
    for info in archive.infolist():
        if info.is_dir():
            continue
        yield info.filename, archive.read(info)


def _unpack(archive: zipfile.ZipFile, destination: Path, key: bytes, *, header: bool,
            pngdefry: Path | None) -> tuple[Path, ...]:
    written = []
    for name, raw in _entries(archive):
        stem = destination / name
        stem.parent.mkdir(parents=True, exist_ok=True)
        # infov3 is the one entry keyed differently from the rest of its archive.
        entry_key = tune_info_key() if name == _INFO_V3 else key
        entry_header = header or name == _INFO_V3
        payload = _try_decipher(raw, entry_key, header=entry_header)
        if payload is None:
            log.debug('`%s` is not enciphered; written as it is.', name)
            payload = raw
        written.append(_write_payload(payload, stem, name, pngdefry))
    return tuple(written)


def unpack_zip(source: Path, destination: Path, pngdefry: Path | None = None) -> tuple[Path, ...]:
    """
    Unpack a marker, hold-marker, or share-image ZIP.

    Parameters
    ----------
    source : pathlib.Path
        The ``.zip`` to unpack.
    destination : pathlib.Path
        The directory to write into. It is created if it does not exist.
    pngdefry : pathlib.Path | None
        The ``pngdefry`` binary. Without it the PNGs are written still Apple-optimised.

    Returns
    -------
    tuple[pathlib.Path, ...]
        Every file written, in archive order.
    """
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as archive:
        return _unpack(archive, destination, texture_key(), header=True, pngdefry=pngdefry)


def unpack_jbt(source: Path, destination: Path, pngdefry: Path | None = None) -> tuple[Path, ...]:
    """
    Unpack a tune package.

    The sixteen bytes after the ZIP are the MD5 of everything before them. They are checked, and a
    mismatch is logged rather than raised, because every entry still decodes on its own.

    Parameters
    ----------
    source : pathlib.Path
        The ``.jbt`` to unpack.
    destination : pathlib.Path
        The directory to write into. It is created if it does not exist.
    pngdefry : pathlib.Path | None
        The ``pngdefry`` binary. Without it the artwork is written still Apple-optimised.

    Returns
    -------
    tuple[pathlib.Path, ...]
        Every file written, in archive order.
    """
    destination.mkdir(parents=True, exist_ok=True)
    # The ZIP is opened first, so anything too short to hold both an archive and a trailer is
    # rejected before the trailer is read at all.
    with zipfile.ZipFile(source) as archive:
        written = _unpack(archive, destination, bgm_key(), header=False, pngdefry=pngdefry)
    raw = source.read_bytes()
    body, digest = raw[:-JBT_DIGEST_SIZE], raw[-JBT_DIGEST_SIZE:]
    if hashlib.md5(body, usedforsecurity=False).digest() != digest:
        log.warning('The MD5 trailer of `%s` does not match its archive.', source.name)
    return written
