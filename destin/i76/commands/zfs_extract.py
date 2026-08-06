"""``destin i76 zfs-extract`` - unpack a ZFSF or ZFS3 archive."""
from __future__ import annotations

from pathlib import Path
import logging

from destin.i76.zfs import InvalidArchiveError, extract
import click

from .utils import debug_option

__all__ = ('zfs_extract',)

log = logging.getLogger(__name__)


@click.command(name='zfs-extract')
@click.argument('archive', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('outdir', type=click.Path(file_okay=False, path_type=Path))
@debug_option
def zfs_extract(archive: Path, outdir: Path) -> None:
    """
    Unpack ZFS archive ARCHIVE into OUTDIR.

    Both the Interstate '76 ZFSF format, whose records are LZO-compressed, and the Interstate '82
    ZFS3 format, whose records are stored, are accepted. Members are written under their lowercased
    names.

    Raises
    ------
    click.Abort
        If ARCHIVE is not a ZFS archive.
    """
    try:
        count = extract(archive.read_bytes(), outdir)
    except InvalidArchiveError as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    click.echo(f'Extracted {count} files to {outdir}.')
