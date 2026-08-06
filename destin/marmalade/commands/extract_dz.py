"""``marm extract-dz`` - unpack a Derbh (``.dz``) archive."""
from __future__ import annotations

from pathlib import Path
import logging

from destin.marmalade.derbh import unpack
import click

from .utils import console, debug_option

__all__ = ('extract_dz',)

log = logging.getLogger(__name__)


@click.command(name='extract-dz')
@click.argument('archive', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('outdir', type=click.Path(file_okay=False, path_type=Path))
@click.option('--delete/--no-delete',
              default=True,
              help='Delete ARCHIVE after a successful extraction.')
@click.option('-q', '--quiet', is_flag=True, help='Only print the final count.')
@debug_option
def extract_dz(archive: Path, outdir: Path, *, delete: bool, quiet: bool) -> None:
    """
    Unpack Derbh archive ARCHIVE into OUTDIR.

    Each file is decompressed per its stored method and written under OUTDIR using the archive's own
    folder layout. ARCHIVE is deleted afterwards unless ``--no-delete`` is given.
    """
    log.debug('Extracting Derbh archive %s into %s.', archive, outdir)
    data = archive.read_bytes()
    count = 0
    for entry in unpack(data):
        dst = outdir / entry.path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(entry.data)
        count += 1
        if not quiet:
            console.print(f'Extracted {entry.path} ([dim]{len(entry.data)} bytes[/dim]).')
    console.print(f'[green]Extracted {count} files to {outdir}.[/green]')
    if delete:
        archive.unlink()
        log.debug('Deleted source archive %s.', archive)
        console.print(f'[dim]Deleted source {archive}.[/dim]')
