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
from dade.maxpane.ras import MAGIC

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ('ARCHIVE_SUFFIXES', 'CABINET_NAME', 'NoArchivesFoundError', 'iter_archives')

log = logging.getLogger(__name__)

_CABINET_PART_RE = re.compile(r'^data\d*\.(cab|hdr)$', re.IGNORECASE)

ARCHIVE_SUFFIXES = ('.ras', '.mpm')
"""Suffixes identifying an archive, matched case-insensitively.

:meta hide-value:
"""
CABINET_NAME = 'data1.cab'
"""Name of the InstallShield cabinet holding the archives that are not loose on the disc.

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


def _iter_image(source: Path) -> Iterator[tuple[str, bytes]]:
    image = open_image(source)
    paths = [path for path, _ in image.iter_files()]
    for path in paths:
        if _is_archive_name(path):
            log.debug('Reading `%s` from the image.', path)
            yield path, image.read_file(path)
    for cabinet in (path for path in paths if path.lower().endswith(CABINET_NAME)):
        # unshield reads the volumes and header sitting beside the cabinet, so they have to be
        # staged together. Nothing else on the disc is copied out.
        directory = PurePosixPath(cabinet).parent
        with TemporaryDirectory() as staging:
            for path in paths:
                name = PurePosixPath(path)
                if name.parent == directory and _CABINET_PART_RE.match(name.name):
                    (Path(staging) / name.name).write_bytes(image.read_file(path))
            yield from _iter_cabinet(Path(staging) / PurePosixPath(cabinet).name)


def iter_archives(source: Path) -> Iterator[tuple[str, bytes]]:
    """
    Yield every archive reachable from *source*.

    A file beginning with the RAS magic is yielded as-is. A directory is scanned recursively. A
    disc image, either an ISO or the ``.cue`` of a cue/bin pair, yields the archives lying loose on
    it and then those inside its InstallShield cabinet, which is unpacked to a temporary directory.
    Max Payne's retail disc needs both: the levels are loose but the shared game database is in the
    cabinet.

    A cabinet is skipped with a warning when ``unshield`` is missing or fails, so the archives that
    were reachable are still returned.

    Parameters
    ----------
    source : Path
        An archive, a directory, an InstallShield cabinet, or a disc image.

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
    if source.is_dir():
        members: Iterator[tuple[str, bytes]] = _iter_directory(source)
    elif source.suffix.lower() == '.cab' or source.name.lower() == CABINET_NAME:
        members = _iter_cabinet(source)
    elif _is_archive_file(source):
        members = iter(((source.name, source.read_bytes()),))
    else:
        members = _iter_image(source)
    for label, data in members:
        found += 1
        yield label, data
    if not found:
        msg = f'No RAS archives found in `{source}`.'
        raise NoArchivesFoundError(msg)
