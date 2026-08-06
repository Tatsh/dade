"""``destin i76 pak-extract`` - unpack a ``.pak`` bundle using its ``.pix`` index."""
from __future__ import annotations

from pathlib import Path
import logging

from destin.i76.pak import extract
import click

from .utils import debug_option

__all__ = ('pak_extract',)

log = logging.getLogger(__name__)


@click.command(name='pak-extract')
@click.argument('pak', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('outdir', type=click.Path(file_okay=False, path_type=Path))
@debug_option
def pak_extract(pak: Path, outdir: Path) -> None:
    """
    Unpack bundle PAK into OUTDIR.

    The bundle's member list comes from the sibling ``.pix`` index, which must sit beside PAK.

    Raises
    ------
    click.Abort
        If PAK has no matching ``.pix`` index.
    """
    try:
        count = extract(pak, outdir)
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    click.echo(f'Extracted {count} members to {outdir}.')
