"""``dade i76 stage-i82-objects`` - stage Interstate '82 object meshes and their textures."""
from __future__ import annotations

from pathlib import Path
import logging
import shutil

import click

from dade.i76.i82 import find_in_pools, level_ids
from dade.i76.i82_objects import (
    chassis_name,
    geometry_files,
    mesh_textures,
    placement_refs,
    stock_paint,
    wheel_meshes,
)

from .utils import debug_option

__all__ = ('stage_i82_objects',)

log = logging.getLogger(__name__)

_DEFAULT_POOLS = ('bmp', 'tga', 'data')
"""Subdirectories of SOURCE searched for textures, in priority order.

:meta hide-value:
"""


def _stage_mesh(stem: str, data: Path, meshes: Path, textures: set[str],
                missing: list[str]) -> bool:
    """
    Copy one binary mesh and record the textures its material table names.

    The ``.sbx`` form is preferred, matching the game's own lookup order, and the ``.six`` is used
    when no ``.sbx`` exists.

    Parameters
    ----------
    stem : str
        Mesh name without its extension.
    data : pathlib.Path
        Directory holding the meshes.
    meshes : pathlib.Path
        Destination directory.
    textures : set[str]
        Set that recovered texture names are added to. Updated in place.
    missing : list[str]
        List that unresolved mesh names are appended to. Updated in place.

    Returns
    -------
    bool
        ``True`` when the mesh was staged.
    """
    if (found := find_in_pools(f'{stem}.sbx', [data])) is None:
        found = find_in_pools(f'{stem}.six', [data])
    if found is None:
        missing.append(f'{stem}.sbx')
        return False
    shutil.copyfile(found, meshes / found.name)
    textures.update(mesh_textures(found.read_bytes()))
    log.debug('Staged mesh `%s`.', found.name)
    return True


@click.command(name='stage-i82-objects')
@click.argument('source', type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument('outdir', type=click.Path(file_okay=False, path_type=Path))
@click.option('--data-dir',
              default=None,
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="Directory holding the .msa worlds and meshes. Defaults to SOURCE's data "
              'subdirectory.')
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
def stage_i82_objects(source: Path, outdir: Path, data_dir: Path | None, mrm_dir: Path | None,
                      texture_pool: tuple[Path, ...]) -> None:
    """
    Stage the objects placed by the Interstate '82 levels under SOURCE into OUTDIR.

    Static objects resolve as ``.stf`` to ``.six`` to ``.sbx``, and vehicles as ``.vdf`` to a
    chassis ``.cdf`` to its body, wheel, and stock paint assets. Wrappers and meshes are copied
    into ``meshes/`` under OUTDIR, and the textures their material tables name into ``objtex/``.

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
    for name in ('meshes', 'objtex'):
        (outdir / name).mkdir(parents=True, exist_ok=True)
    meshes = outdir / 'meshes'

    worlds = [(data / f'{level}.msa').read_bytes() for level in levels]
    statics = sorted({ref for world in worlds for ref in placement_refs(world, '.stf')})
    vehicles = sorted({ref for world in worlds for ref in placement_refs(world, '.vdf')})

    textures: set[str] = set()
    missing: list[str] = []
    staged_statics = staged_vehicles = staged_meshes = 0

    for stf in statics:
        if (found := find_in_pools(stf, [data])) is None:
            missing.append(stf)
            continue
        shutil.copyfile(found, meshes / stf)
        staged_statics += 1
        if geometry := geometry_files(found.read_text(encoding='latin1', errors='replace')):
            staged_meshes += _stage_mesh(geometry[0][:-4].lower(), data, meshes, textures, missing)

    for vdf in vehicles:
        if (found := find_in_pools(vdf, [data])) is None:
            missing.append(vdf)
            continue
        shutil.copyfile(found, meshes / vdf)
        chassis = chassis_name(found.read_text(encoding='latin1', errors='replace'))
        if chassis is None:
            continue
        if (chassis_path := find_in_pools(chassis, [data])) is None:
            missing.append(chassis)
            continue
        shutil.copyfile(chassis_path, meshes / chassis)
        staged_vehicles += 1
        text = chassis_path.read_text(encoding='latin1', errors='replace')
        if geometry := geometry_files(text):
            staged_meshes += _stage_mesh(geometry[0][:-4].lower(), data, meshes, textures, missing)
        if wheels := wheel_meshes(text):
            staged_meshes += _stage_mesh(wheels[0][:-4].lower(), data, meshes, textures, missing)
        if (paint := stock_paint(text)) is not None:
            textures.add(paint)

    staged_textures, missing_textures = 0, []
    for name in sorted(textures):
        if (found := find_in_pools(name, pools)) is None:
            missing_textures.append(name)
            continue
        shutil.copyfile(found, outdir / 'objtex' / name)
        staged_textures += 1

    click.echo(f'Levels: {len(levels)}, .stf refs: {len(statics)}, .vdf refs: {len(vehicles)}.')
    click.echo(f'Staged {staged_statics} .stf, {staged_vehicles} .vdf, {staged_meshes} meshes, '
               f'{staged_textures} textures.')
    if missing:
        click.echo(f'Missing {len(missing)}: {", ".join(missing[:12])}', err=True)
    if missing_textures:
        click.echo(
            f'Missing {len(missing_textures)} textures: '
            f'{", ".join(missing_textures[:12])}',
            err=True)
