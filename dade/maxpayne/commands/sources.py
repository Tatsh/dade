"""Resolve a command-line argument into the archives it names."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING
import logging
import re
import subprocess as sp

from dade.common.disc import open_image
from dade.common.tools import ToolNotFoundError, run_unshield
from dade.maxpayne.ras import MAGIC

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from dade.common.iso9660 import Iso9660Image

__all__ = ('ARCHIVE_SUFFIXES', 'CABINET_NAME', 'NoArchivesFoundError', 'iter_archives')

log = logging.getLogger(__name__)

_CABINET_PART_RE = re.compile(r'^data\d*\.(cab|hdr)$', re.IGNORECASE)

ARCHIVE_SUFFIXES = ('.ras', '.mpm')
"""Suffixes identifying an archive, matched case-insensitively.

:meta hide-value:
"""
CABINET_NAME = 'data1.cab'
"""Name of the InstallShield cabinet holding the archives that are not loose on the disc.

It is the one ``unshield`` is pointed at, but not the only one it reads: the header beside it and
every later volume are opened too, so a cabinet split across two discs is only whole once both
have been staged together.

:meta hide-value:
"""


class NoArchivesFoundError(ValueError):
    """Raised when a source holds no RAS archive."""


def _is_archive_name(name: str) -> bool:
    return name.lower().endswith(ARCHIVE_SUFFIXES)


def _is_archive_file(path: Path) -> bool:
    with path.open('rb') as handle:
        return handle.read(len(MAGIC)) == MAGIC


def _iter_directory(root: Path) -> Iterator[tuple[str, bytes]]:
    for path in sorted(root.rglob('*')):
        if path.is_file() and _is_archive_name(path.name):
            log.debug('Reading `%s`.', path)
            yield str(path.relative_to(root)), path.read_bytes()


def _iter_cabinet(cabinet: Path) -> Iterator[tuple[str, bytes]]:
    with TemporaryDirectory() as work_dir:
        try:
            run_unshield(cabinet, Path(work_dir))
        except ToolNotFoundError:
            log.warning('Skipping `%s`: unshield is not installed.', cabinet.name)
            return
        except sp.CalledProcessError:
            log.warning('Skipping `%s`: unshield failed to unpack it.', cabinet.name)
            return
        yield from _iter_directory(Path(work_dir))


def _loose_archives(image: Iso9660Image, paths: Sequence[str]) -> Iterator[tuple[str, bytes]]:
    """
    Yield the archives lying loose on one image.

    Parameters
    ----------
    image : dade.common.iso9660.Iso9660Image
        The opened image.
    paths : collections.abc.Sequence[str]
        Every path on it.

    Yields
    ------
    tuple[str, bytes]
        A label and the whole archive.
    """
    for path in paths:
        if _is_archive_name(path):
            log.debug('Reading `%s` from the image.', path)
            yield path, image.read_file(path)


def _stage_cabinet(image: Iso9660Image, paths: Sequence[str], staging: Path) -> int:
    """
    Copy one image's share of the cabinet into the staging directory.

    Parameters
    ----------
    image : dade.common.iso9660.Iso9660Image
        The opened image.
    paths : collections.abc.Sequence[str]
        Every path on it.
    staging : Path
        Where the parts are gathered.

    Returns
    -------
    int
        How many parts were copied out.
    """
    staged = 0
    for path in paths:
        name = PurePosixPath(path)
        if _CABINET_PART_RE.match(name.name):
            (staging / name.name.lower()).write_bytes(image.read_file(path))
            staged += 1
    return staged


def iter_archives(*sources: Path) -> Iterator[tuple[str, bytes]]:
    """
    Yield every archive reachable from *sources*.

    A file beginning with the RAS magic is yielded as-is. A directory is scanned recursively. A
    disc image -- an ISO, the ``.cue`` of a cue/bin pair, or the ``.bin`` on its own -- yields the
    archives lying loose on it. Max Payne's retail disc needs both kinds: its levels are loose but
    the shared game database is in the cabinet.

    **A cabinet may span several discs**, and its parts are gathered from every source before
    ``unshield`` is run once over the lot. Max Payne 2 ships that way: ``data1.cab``, its header
    and ``data2.cab`` are on the install disc while ``data3.cab`` is on the play disc, and
    unpacking either alone stops part way through. Give both and the whole cabinet comes out.

    The cabinet is skipped with a warning when ``unshield`` is missing or fails, so the archives
    that were reachable are still returned.

    Parameters
    ----------
    sources : Path
        Archives, directories, InstallShield cabinets, or disc images, in any combination.

    Yields
    ------
    tuple[str, bytes]
        A label for messages and the whole archive.

    Raises
    ------
    NoArchivesFoundError
        If no archive could be reached.
    """
    found = 0
    with TemporaryDirectory() as staging:
        parts = 0
        for source in sources:
            if source.is_dir():
                members: Iterator[tuple[str, bytes]] = _iter_directory(source)
            elif source.suffix.lower() == '.cab' or source.name.lower() == CABINET_NAME:
                members = _iter_cabinet(source)
            elif _is_archive_file(source):
                members = iter(((source.name, source.read_bytes()),))
            else:
                image = open_image(source)
                paths = [path for path, _ in image.iter_files()]
                parts += _stage_cabinet(image, paths, Path(staging))
                members = _loose_archives(image, paths)
            for label, data in members:
                found += 1
                yield label, data
        if parts:
            log.debug('Unpacking a cabinet staged from %d parts.', parts)
            for label, data in _iter_cabinet(Path(staging) / CABINET_NAME):
                found += 1
                yield label, data
    if not found:
        listed = ', '.join(f'`{source}`' for source in sources)
        msg = f'No RAS archives found in {listed}.'
        raise NoArchivesFoundError(msg)
