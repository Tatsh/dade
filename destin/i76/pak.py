"""
Reader for ``.pak`` bundles and their ``.pix`` text indices.

A ``.pak`` is a plain concatenation of members with no internal structure. The matching ``.pix``
file is a text index whose first line is the member count and whose remaining lines each name a
member followed by its byte offset and length within the bundle. Lines with fewer than three
fields are ignored, matching the game's own tolerance for trailing blank lines.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging

from .typing import PakEntry

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping
    from pathlib import Path

__all__ = ('build_bundle_index', 'extract', 'iter_members', 'load_member', 'parse_index',
           'read_index')

log = logging.getLogger(__name__)

_INDEX_FIELDS = 3
"""Number of whitespace-separated fields a usable ``.pix`` line carries.

:meta hide-value:
"""


def parse_index(text: str) -> tuple[PakEntry, ...]:
    """
    Parse the text of a ``.pix`` index.

    Parameters
    ----------
    text : str
        Full contents of the ``.pix`` file. The first line is the member count and is skipped.

    Returns
    -------
    tuple[PakEntry, ...]
        Every indexed member, in index order, with names lowercased.
    """
    return tuple(
        PakEntry(fields[0].lower(), int(fields[1]), int(fields[2]))
        for line in text.splitlines()[1:] if len(fields := line.split()) >= _INDEX_FIELDS)


def read_index(path: Path) -> tuple[PakEntry, ...]:
    """
    Read and parse a ``.pix`` index from disc.

    Parameters
    ----------
    path : pathlib.Path
        Path to the ``.pix`` file.

    Returns
    -------
    tuple[PakEntry, ...]
        Every indexed member, in index order, with names lowercased.
    """
    return parse_index(path.read_text(encoding='latin1', errors='replace'))


def iter_members(data: bytes, entries: Iterable[PakEntry]) -> Iterator[tuple[PakEntry, bytes]]:
    """
    Yield each indexed member's bytes out of a bundle.

    Parameters
    ----------
    data : bytes
        Full contents of the ``.pak`` bundle.
    entries : collections.abc.Iterable[PakEntry]
        Index entries describing the members to slice out.

    Yields
    ------
    tuple[PakEntry, bytes]
        The index entry and the member's bytes.
    """
    for entry in entries:
        yield entry, data[entry.offset:entry.offset + entry.length]


def build_bundle_index(root: Path) -> dict[str, tuple[Path, PakEntry]]:
    """
    Index every member of every ``.pak`` bundle under ``root``.

    A bundle is indexed only when its ``.pix`` index sits beside it. Where two bundles name the
    same member, the one encountered later wins.

    Parameters
    ----------
    root : pathlib.Path
        Directory holding the ``.pak`` bundles and their ``.pix`` indices.

    Returns
    -------
    dict[str, tuple[pathlib.Path, PakEntry]]
        Map of lowercased member name to the bundle holding it and its index entry.
    """
    index: dict[str, tuple[Path, PakEntry]] = {}
    for pix in sorted(root.glob('*.pix')):
        if not (pak := pix.with_suffix('.pak')).is_file():
            continue
        for entry in read_index(pix):
            index[entry.name] = (pak, entry)
    log.debug('Indexed %d bundle members under `%s`.', len(index), root)
    return index


def load_member(index: Mapping[str, tuple[Path, PakEntry]], name: str) -> bytes | None:
    """
    Read one member out of an indexed bundle.

    Parameters
    ----------
    index : collections.abc.Mapping[str, tuple[pathlib.Path, PakEntry]]
        An index as returned by :py:func:`build_bundle_index`.
    name : str
        Member name. Matching is case-insensitive.

    Returns
    -------
    bytes | None
        The member's bytes, or ``None`` when it is not indexed.
    """
    if (found := index.get(name.lower())) is None:
        return None
    pak, entry = found
    return pak.read_bytes()[entry.offset:entry.offset + entry.length]


def extract(pak: Path, outdir: Path) -> int:
    """
    Write every member of a ``.pak`` bundle into ``outdir``.

    The bundle's index is the sibling file with the same stem and a ``.pix`` suffix.

    Parameters
    ----------
    pak : pathlib.Path
        Path to the ``.pak`` bundle.
    outdir : pathlib.Path
        Directory to write members into. It is created if it does not exist.

    Returns
    -------
    int
        The number of members written.

    Raises
    ------
    FileNotFoundError
        If the bundle has no matching ``.pix`` index.
    """
    if not (index := pak.with_suffix('.pix')).is_file():
        msg = f'No .pix index beside {pak}.'
        raise FileNotFoundError(msg)
    outdir.mkdir(parents=True, exist_ok=True)
    data = pak.read_bytes()
    count = 0
    for entry, payload in iter_members(data, read_index(index)):
        (outdir / entry.name).write_bytes(payload)
        log.debug('Extracted `%s` (%d bytes).', entry.name, len(payload))
        count += 1
    return count
