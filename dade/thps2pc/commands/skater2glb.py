"""``dade thps2pc skater2glb`` - write skater models as skinned and animated GLB files."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import logging

import click

from dade.thps2pc.skater import (
    build_skater_glb,
    part_names,
    part_parents,
    read_skater,
    remap_clips,
)

from .utils import debug_option, read_scene

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from dade.thps2pc.skater import Clip

__all__ = ('skater2glb',)

log = logging.getLogger(__name__)

_SHARED_CLIPS = 'SK2ANIM'


def _models(sources: Iterable[Path]) -> Iterator[Path]:
    for source in sources:
        if source.is_dir():
            yield from sorted(path for path in source.rglob('*')
                              if path.suffix.upper() == '.PSX' and _header(path) is not None)
        else:
            yield source


def _header(model: Path) -> Path | None:
    return next(
        (path for suffix in ('.PSH', '.psh') if (path := model.with_suffix(suffix)).is_file()),
        None)


def _shared(model: Path, override: Path | None) -> tuple[tuple[Clip, ...], tuple[str, ...]]:
    path = override or next((candidate
                             for name in (f'{_SHARED_CLIPS}.PSX', f'{_SHARED_CLIPS.lower()}.psx')
                             if (candidate := model.with_name(name)).is_file()), None)
    if path is None or (header := _header(path)) is None:
        return (), ()
    skater = read_skater(read_scene(path))
    if skater is None:
        return (), ()
    return skater.clips, part_names(header.read_text(encoding='latin-1'))


@click.command(name='skater2glb')
@click.argument('sources', nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.option('-o',
              '--output-dir',
              required=True,
              type=click.Path(file_okay=False, path_type=Path),
              help='Directory the GLB files are written to.')
@click.option('-c',
              '--clips',
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help='Shared clips for models that store no clips. Defaults to SK2ANIM.PSX beside '
              'each model.')
@debug_option
def skater2glb(sources: tuple[Path, ...], output_dir: Path, clips: Path | None = None) -> None:
    """
    Convert each skater model in SOURCES to a GLB with a skin and its clips as animations.

    A source is a ``.PSX`` file with a ``.PSH`` header beside it, or a directory searched for them.
    A model that stores clips, compressed or as more than one pose clip, is written with its clips.
    Any other model is given the shared clips, matched to its parts by name, and a model the shared
    clips do not fit retains the poses it stores. A model without a hierarchy chunk is arranged by
    the parent comments of its header.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for model in _models(sources):
        if (header := _header(model)) is None:
            click.echo(f'{model}: no .PSH header beside it.', err=True)
            continue
        text = header.read_text(encoding='latin-1')
        if (skater := read_skater(read_scene(model), part_parents(text) or ())) is None:
            log.info('Skipping `%s`. Its hierarchy does not cover every part.', model)
            continue
        names = part_names(text)
        if len(names) != len(skater.scene.sectors):
            log.info('Skipping `%s`, whose header does not identify every part.', model)
            continue
        own = tuple(
            clip for clip in skater.clips if clip.name.startswith('clip') or len(skater.clips) > 1)
        chosen = own
        if not own:
            shared, shared_names = _shared(model, clips)
            try:
                chosen = remap_clips(shared, shared_names, names) if shared else ()
            except KeyError:
                log.debug('Shared clips do not fit `%s`.', model)
            chosen = chosen or skater.clips
        if not chosen:
            log.info('Skipping `%s`. It has no clips or poses.', model)
            continue
        destination = output_dir / f'{model.stem}.glb'
        destination.write_bytes(build_skater_glb(skater, names, chosen, model.stem))
        click.echo(f'{destination}: {len(names)} joints, {len(chosen)} animations')
        written += 1
    click.echo(f'Wrote {written} GLB files.')
