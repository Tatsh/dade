"""``destin thps2pc unpack-pkr`` - unpack a Neversoft PKR2 resource pack."""
from __future__ import annotations

from pathlib import Path

import click

from destin.thps2pc.pkr import PkrArchive, UnsafePathError, extract_all, iter_entries, parse

from .utils import debug_option

__all__ = ('unpack_pkr',)


def _parse(pkr: Path, data: bytes) -> PkrArchive:
    """
    Parse a pack, reporting a malformed one as a Click abort.

    Parameters
    ----------
    pkr : Path
        Path to the pack, used in the error message.
    data : bytes
        The whole pack file.

    Returns
    -------
    PkrArchive
        The parsed pack.

    Raises
    ------
    click.Abort
        If the pack cannot be parsed.
    """
    try:
        return parse(data)
    except ValueError as e:
        click.echo(f'{pkr}: {e}', err=True)
        raise click.Abort from e


def _extract(pkr: Path, data: bytes, destdir: Path) -> tuple[int, int]:
    """
    Extract a pack, reporting any failure as a Click abort.

    Parameters
    ----------
    pkr : Path
        Path to the pack, used in the error message.
    data : bytes
        The whole pack file.
    destdir : Path
        Directory the tree is mirrored into.

    Returns
    -------
    tuple[int, int]
        The number of files and the number of bytes written.

    Raises
    ------
    click.Abort
        If an entry escapes the destination or cannot be decoded.
    """
    try:
        return extract_all(data, destdir)
    except (UnsafePathError, ValueError, NotImplementedError) as e:
        click.echo(f'{pkr}: {e}', err=True)
        raise click.Abort from e


def _require_destdir(destdir: Path | None) -> Path:
    """
    Return the destination directory, rejecting its absence.

    Parameters
    ----------
    destdir : Path | None
        The destination given on the command line.

    Returns
    -------
    Path
        The destination directory.

    Raises
    ------
    click.UsageError
        If no destination was given.
    """
    if destdir is None:
        msg = 'DESTDIR is required unless --list is given.'
        raise click.UsageError(msg)
    return destdir


@click.command(name='unpack-pkr')
@click.argument('pkr', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('destdir', required=False, type=click.Path(file_okay=False, path_type=Path))
@click.option('-l', '--list', 'list_only', is_flag=True, help='List contents and do not extract.')
@debug_option
def unpack_pkr(pkr: Path, destdir: Path | None, *, list_only: bool = False) -> None:
    """
    Unpack the PKR2 resource pack PKR into DESTDIR.

    DESTDIR is required unless --list is given. Entry names are checked before anything is
    written, so an archive cannot place files outside DESTDIR.
    """
    data = pkr.read_bytes()
    archive = _parse(pkr, data)
    header = archive.header
    click.echo(
        f'PKR2: alignment={header.alignment} dirs={header.dir_count} files={header.file_count} '
        f'dataRegion@{header.data_region_start:#x}',
        err=True)
    if (total := sum(d.child_count for d in archive.dirs)) != header.file_count:
        click.echo(
            f'Warning: sum(childCount)={total} does not equal fileCount='
            f'{header.file_count}.',
            err=True)
    if list_only:
        for path, entry in iter_entries(archive):
            click.echo(f'{entry.compressed_size:10d}  {path}')
        return
    target = _require_destdir(destdir)
    count, written = _extract(pkr, data, target)
    click.echo(f'Extracted {count} files ({written} bytes) to {target}.', err=True)
