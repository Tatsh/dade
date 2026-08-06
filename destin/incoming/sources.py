"""Detect the kind of source supplied and prepare what to convert."""
from __future__ import annotations

from pathlib import Path
from shutil import which
from tempfile import TemporaryDirectory
from typing import NamedTuple
import logging
import subprocess as sp

from .tools import run_gdiextract, run_unshield

__all__ = ('PreparedSource', 'SourceError', 'prepare_source')

log = logging.getLogger(__name__)


class SourceError(Exception):
    """Raised when a source cannot be identified or prepared."""


class PreparedSource(NamedTuple):
    """What to convert after identifying a source."""

    root: Path | None
    """A directory tree to mirror into the output, or ``None`` for a single file."""
    files: tuple[Path, ...]
    """Loose files to convert directly into the output root (CDDA tracks or a single asset)."""


def _find(directory: Path, *names: str) -> Path | None:
    lowered = {n.lower() for n in names}
    return next((child for child in sorted(directory.iterdir())
                 if child.is_file() and child.name.lower() in lowered), None)


def _glob_ci(directory: Path, suffix: str) -> tuple[Path, ...]:
    suffix = suffix.lower()
    return tuple(
        sorted(child for child in directory.iterdir()
               if child.is_file() and child.suffix.lower() == suffix))


def _isodump_extract(isodump: str, iso: Path, cabinet: Path) -> bool:
    # isodump -x writes the named file to stdout; iso9660 names carry a ';1' version, while Rock
    # Ridge names (with -R) keep the original case.
    for args in (('-x', '/DATA1.CAB;1'), ('-R', '-x', '/data1.cab')):
        try:
            with cabinet.open('wb') as out:
                sp.run((isodump, '-i', str(iso), *args), check=True, stdout=out, stderr=sp.DEVNULL)
        except (OSError, sp.CalledProcessError) as e:
            log.debug('isodump %s failed: %s', args, e)
            continue
        if cabinet.stat().st_size:
            return True
    cabinet.unlink(missing_ok=True)
    return False


def _cab_from_iso(iso: Path, dest_dir: Path) -> Path:
    cabinet = dest_dir / 'DATA1.CAB'
    if (isodump := which('isodump')) is not None and _isodump_extract(isodump, iso, cabinet):
        return cabinet
    if (sevenzip := which('7z') or which('7za')) is not None:
        sp.run((sevenzip, 'e', '-ssc-', f'-o{dest_dir}', '-y', str(iso), 'data1.cab'),
               check=True,
               capture_output=True)
        if (found := _find(dest_dir, 'data1.cab')) is not None:
            return found
    msg = 'Could not extract DATA1.CAB from the ISO; install isodump or 7z.'
    raise SourceError(msg)


def prepare_source(source: Path, work_dir: Path) -> PreparedSource:
    """
    Identify *source* and return the tree and loose files to convert.

    Archives are extracted into *work_dir* first: a PC ``DATA1.CAB`` (a file, a directory holding
    one, or one inside an ISO) with unshield, a Dreamcast ``.gdi`` with gdiextract. Already
    extracted directories are mirrored as-is. Dreamcast CDDA ``.raw`` tracks beside a GDI are
    returned as loose files.

    Parameters
    ----------
    source : Path
        A directory, an ISO, a GDI, a ``DATA1.CAB``, or a single asset file.
    work_dir : Path
        A scratch directory archives are extracted into.

    Returns
    -------
    PreparedSource
        The directory to mirror and any loose files.

    Raises
    ------
    SourceError
        If the source does not exist or cannot be prepared.
    """
    if source.is_file():
        return _prepare_file(source, work_dir)
    if source.is_dir():
        return _prepare_dir(source, work_dir)
    msg = f'Source does not exist: {source}.'
    raise SourceError(msg)


def _prepare_file(source: Path, work_dir: Path) -> PreparedSource:
    suffix = source.suffix.lower()
    if suffix == '.gdi':
        run_gdiextract(source, work_dir)
        return PreparedSource(work_dir, _glob_ci(source.parent, '.raw'))
    if source.name.lower() == 'data1.cab' or suffix == '.cab':
        run_unshield(source, work_dir)
        return PreparedSource(work_dir, ())
    if suffix == '.iso':
        with TemporaryDirectory() as cab_dir:
            run_unshield(_cab_from_iso(source, Path(cab_dir)), work_dir)
        return PreparedSource(work_dir, ())
    return PreparedSource(None, (source,))


def _prepare_dir(source: Path, work_dir: Path) -> PreparedSource:
    if (cab := _find(source, 'data1.cab')) is not None:
        run_unshield(cab, work_dir)
        return PreparedSource(work_dir, ())
    if gdi := _glob_ci(source, '.gdi'):
        run_gdiextract(gdi[0], work_dir)
        return PreparedSource(work_dir, _glob_ci(source, '.raw'))
    return PreparedSource(source, ())
