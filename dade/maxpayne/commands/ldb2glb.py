"""``dade maxpayne ldb2glb`` - convert levels to binary glTF."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import NamedTuple
import logging

import click

from dade.common.workers import default_jobs
from dade.maxpayne.blocks import unwrap
from dade.maxpayne.gltf import build_glb
from dade.maxpayne.ldb import InvalidLevelError, read_level

from .models import load_models
from .utils import debug_option

__all__ = ('ldb2glb',)

log = logging.getLogger(__name__)


class _Result(NamedTuple):
    """Outcome of converting one level."""

    name: str
    """The level's file name."""
    meshes: int
    """Number of placed meshes written."""
    props: int
    """Number of animated props written."""
    faces: int
    """Number of faces written."""
    images: int
    """Number of images embedded."""
    placements: int
    """Number of NPC and pickup placements written."""
    models: int
    """Number of those placements drawn with a real model."""
    clips: int
    """Number of prop animations written."""
    error: str
    """Failure message, empty when the level converted."""


def _convert(job: tuple[Path, Path, Path | None]) -> _Result:
    """
    Convert one level, reporting failure rather than raising.

    Runs in a worker process, so the outcome has to be picklable and exceptions have to be turned
    into data.

    Parameters
    ----------
    job : tuple[Path, Path, Path | None]
        The level to read, the directory to write into, and the game database to take NPC and
        pickup models from.

    Returns
    -------
    _Result
        What was written, or the failure message.
    """
    level, output_dir, database = job
    try:
        parsed = read_level(unwrap(level.read_bytes())[0])
        models = load_models(database, parsed) if database else {}
        payload = build_glb(parsed, models=models, name=level.stem)
    except (IndexError, InvalidLevelError, ValueError) as e:
        return _Result(clips=0,
                       error=str(e),
                       faces=0,
                       images=0,
                       meshes=0,
                       models=0,
                       name=level.name,
                       placements=0,
                       props=0)
    destination = output_dir / f'{level.stem}.glb'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    meshes = parsed.mesh.meshes if parsed.mesh else ()
    props = parsed.props.meshes if parsed.props else ()
    faces = sum(len(m.faces) for m in (*meshes, *props))
    drawn = {f'character:{c.skin}' for c in parsed.characters if f'character:{c.skin}' in models}
    drawn |= {f'item:{i.item}' for i in parsed.items if f'item:{i.item}' in models}
    clips = parsed.props.animations if parsed.props else ()
    return _Result(clips=sum(1 for prop in clips for c in prop if c.start != c.end),
                   error='',
                   faces=faces or len(parsed.geometry.polygons),
                   images=len(parsed.textures),
                   meshes=len(meshes),
                   models=len(drawn),
                   name=level.name,
                   placements=len(parsed.characters) + len(parsed.items),
                   props=len(props))


@click.command(name='ldb2glb')
@click.argument('levels', nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.option('-o',
              '--output-dir',
              default='.',
              help='Directory to write the .glb files into.',
              type=click.Path(file_okay=False, path_type=Path))
@click.option('-j',
              '--jobs',
              default=0,
              help='Worker processes to convert with. Defaults to the CPU count.',
              type=int)
@click.option('-D',
              '--database',
              default=None,
              help="The game's data/database directory, to draw NPCs and pickups with their own "
              'models. Without it they are written as empty named nodes.',
              type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option('--ignore-failures', is_flag=True, help='Log and skip a level that will not read.')
@debug_option
def ldb2glb(levels: tuple[Path, ...], output_dir: Path, jobs: int, database: Path | None, *,
            ignore_failures: bool) -> None:
    """
    Convert each LEVELS ``.ldb`` to a ``.glb`` holding its geometry.

    A directory is searched recursively for ``.ldb`` files. Levels are accepted loose or still
    wrapped in a RA-> block, so a file taken straight out of an archive works.

    Each placed mesh becomes its own node with its own transform, keeping props separate from the
    architecture, and every face is textured with the image the game gives it. Coordinates are
    passed through unchanged because levels are already Y-up.

    Pass ``--database`` to draw the NPCs and pickups with their own models, read from the game's
    ``skins`` and ``level_items`` directories.

    Reading a level is processor-bound, so levels are converted in parallel processes.
    """  # noqa: DOC501
    found: list[Path] = []
    for level in levels:
        found.extend(sorted(level.rglob('*.ldb')) if level.is_dir() else [level])
    if not found:
        click.echo('No .ldb files found.', err=True)
        raise click.Abort
    workers = min(jobs or default_jobs(), len(found))
    results: list[_Result] = []
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results.extend(pool.map(_convert, [(level, output_dir, database) for level in found]))
    else:
        results.extend(_convert((level, output_dir, database)) for level in found)
    converted = 0
    for result in results:
        if result.error:
            if not ignore_failures:
                click.echo(f'{result.name}: {result.error}', err=True)
                raise click.Abort
            log.warning('Skipping `%s`: %s', result.name, result.error)
            continue
        converted += 1
        click.echo(f'{result.name}: {result.meshes} meshes, {result.props} props, '
                   f'{result.faces} faces, {result.images} images, '
                   f'{result.placements} placements ({result.models} modelled), '
                   f'{result.clips} clips')
    click.echo(f'{converted}/{len(found)} levels converted into {output_dir}.')
