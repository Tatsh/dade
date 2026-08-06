"""``destin i76 stage-i82`` - stage Interstate '82 levels and their textures."""
from __future__ import annotations

from pathlib import Path
import logging
import shutil

from destin.i76.i82 import find_in_pools, level_ids, texture_refs
import click

from .utils import debug_option

__all__ = ('stage_i82',)

log = logging.getLogger(__name__)

_DEFAULT_POOLS = ('bmp', 'tga', 'data')
"""Subdirectories of SOURCE searched for textures, in priority order.

:meta hide-value:
"""


@click.command(name='stage-i82')
@click.argument('source', type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument('outdir', type=click.Path(file_okay=False, path_type=Path))
@click.option('--data-dir',
              default=None,
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="Directory holding the .msa worlds. Defaults to SOURCE's data subdirectory.")
@click.option('--mrm-dir',
              default=None,
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="Directory holding the .mrm terrains. Defaults to SOURCE's mrm subdirectory.")
@click.option('--texture-pool',
              multiple=True,
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help='Directory to search for textures. Repeatable, and searched in the order '
              'given. Defaults to the bmp, tga, and data subdirectories of SOURCE.')
@debug_option
def stage_i82(source: Path, outdir: Path, data_dir: Path | None, mrm_dir: Path | None,
              texture_pool: tuple[Path, ...]) -> None:
    """
    Stage the Interstate '82 levels under SOURCE into OUTDIR.

    SOURCE is a ZFS3 extraction tree. Every level having both an ``.msa`` world and a matching
    ``.mrm`` terrain is copied into ``worlds/`` and ``terrain/`` under OUTDIR, and every texture
    the pair references is copied into ``tex/``.

    Raises
    ------
    click.Abort
        If no level has both a world and a terrain.
    """
    data = data_dir or source / 'data'
    terrain = mrm_dir or source / 'mrm'
    pools = list(texture_pool) or [source / name for name in _DEFAULT_POOLS]
    if not (levels := level_ids(data, terrain)):
        click.echo(f'No level under {source} has both a world and a terrain.', err=True)
        raise click.Abort
    for name in ('terrain', 'tex', 'worlds'):
        (outdir / name).mkdir(parents=True, exist_ok=True)

    textures: set[str] = set()
    for level in levels:
        world, surface = data / f'{level}.msa', terrain / f'{level}.mrm'
        shutil.copyfile(world, outdir / 'worlds' / f'{level}.msa')
        shutil.copyfile(surface, outdir / 'terrain' / f'{level}.mrm')
        textures.update(texture_refs(world.read_bytes(), surface.read_bytes()))
        log.debug('Staged level `%s`.', level)

    staged, missing = 0, []
    for name in sorted(textures):
        if (found := find_in_pools(name, pools)) is None:
            missing.append(name)
            continue
        shutil.copyfile(found, outdir / 'tex' / name)
        staged += 1
    click.echo(f'Staged {len(levels)} levels: {", ".join(levels)}.')
    click.echo(f'Textures: {staged} staged, {len(missing)} missing.')
    if missing:
        click.echo(f'Missing: {", ".join(missing[:20])}', err=True)
