"""``destin thps2pc dump-descriptors`` - diagnostics for a scene's descriptor table."""
from __future__ import annotations

from pathlib import Path

from destin.thps2pc.analysis import describe
import click

from .utils import debug_option, read_scene

__all__ = ('dump_descriptors',)


@click.command(name='dump-descriptors')
@click.argument('scene', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('-o',
              '--out',
              type=click.Path(dir_okay=False, path_type=Path),
              help='Write the report to this file instead of standard output.')
@debug_option
def dump_descriptors(scene: Path, out: Path | None = None) -> None:
    """
    Cross-reference SCENE's mesh descriptors against its sector geometry.

    Reports whether sector vertices look local or world-baked, whether descriptor *i* places
    sector *i*, the distribution of the descriptor fields that are still unidentified, and the
    contents of the chunk list.
    """
    report = '\n'.join(describe(read_scene(scene)))
    if out is None:
        click.echo(report)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report + '\n')
    click.echo(f'Wrote {out}.')
