"""``dade rbplus extract-assets`` - unpack one downloadable texture archive."""
from __future__ import annotations

from pathlib import Path
import logging

import bascom
import click

from dade.common.tools import ToolNotFoundError, locate_tool
from dade.rbplus.archive import ArchiveError
from dade.rbplus.pipeline import extract_assets as extract_archive

__all__ = ('extract_assets',)

log = logging.getLogger(__name__)

debug_option = bascom.debug_option({'dade.common': {}, 'dade.rbplus': {}})
"""Attach ``-d/--debug`` to a command and route it through :py:func:`bascom.setup_logging`.

:meta hide-value:
"""


@click.command(name='extract-assets', context_settings={'help_option_names': ('-h', '--help')})
@click.argument('archive',
                metavar='ARCHIVE',
                type=click.Path(dir_okay=False, exists=True, path_type=Path))
@debug_option
@click.option('-j',
              '--jobs',
              type=int,
              default=None,
              help='Process-pool size (defaults to the CPU count).')
@click.option('--no-png', is_flag=True, help='Leave any Apple-optimised PNG as it is.')
@click.option('-o',
              '--output-dir',
              default=Path(),
              type=click.Path(file_okay=False, path_type=Path),
              help='Directory to write into (defaults to the current directory).')
@click.option('--pngdefry-path',
              type=click.Path(dir_okay=False, exists=True, path_type=Path),
              help='Path to pngdefry, when it is not on PATH.')
def extract_assets(archive: Path,
                   output_dir: Path,
                   pngdefry_path: Path | None,
                   jobs: int | None,
                   *,
                   no_png: bool = False) -> None:
    """
    Extract the downloadable texture archive ARCHIVE.

    ARCHIVE is one of the three the game fetches: ``iPad``, ``iPad2x``, or ``iPhone@2x``. Each is
    encrypted with ZipCrypto under a password the executable carries, and holds a little over two
    thousand PNG textures under one top-level directory.

    The archive's own index, a second encrypted ZIP stored as the ``list`` entry, is written out as
    ``manifest.json``. Each texture is examined and only the Apple-optimised ones go through
    ``pngdefry``; the rest are already ordinary PNGs.
    """  # noqa: DOC501
    log.debug('Reading `%s`.', archive)
    try:
        pngdefry = None if no_png else locate_tool('pngdefry', pngdefry_path)
    except ToolNotFoundError as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    try:
        stats = extract_archive(archive, output_dir, pngdefry=pngdefry, workers=jobs)
    except (ArchiveError, OSError) as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    for action, result in stats.items():
        click.echo(f'{action:10} {result.ok} ok, {result.fail} fail')
