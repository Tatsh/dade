"""``dade thps2pc psx-info`` - summarise a PSX scene file."""
from __future__ import annotations

from pathlib import Path

import click

from .utils import debug_option, read_scene

__all__ = ('psx_info',)


@click.command(name='psx-info')
@click.argument('scenes',
                nargs=-1,
                required=True,
                type=click.Path(exists=True, dir_okay=False, path_type=Path))
@debug_option
def psx_info(scenes: tuple[Path, ...]) -> None:
    """Print the version, sector, vertex, and face counts of each SCENE."""
    for path in scenes:
        scene = read_scene(path)
        vertices = sum(sector.vertex_count for sector in scene.sectors)
        faces = sum(sector.num_faces for sector in scene.sectors)
        click.echo(f'{path}: version {scene.version:#x} sectors={len(scene.sectors)} '
                   f'verts={vertices} faces={faces} '
                   f'chunkListOff={scene.chunk_list_offset}')
