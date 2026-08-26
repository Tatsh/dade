"""``dade i76 sdf2obj`` - assemble an ``.sdf`` model and write it as a Wavefront OBJ."""
from __future__ import annotations

from pathlib import Path
import logging

import click

from dade.i76.pak import build_bundle_index, load_member
from dade.i76.sdf import assemble, write_obj

from .utils import debug_option

__all__ = ('sdf2obj',)

log = logging.getLogger(__name__)


@click.command(name='sdf2obj')
@click.argument('model', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('outdir', type=click.Path(file_okay=False, path_type=Path))
@click.option('--game-root',
              default=None,
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help='Directory holding the .pak bundles. Defaults to the directory of MODEL.')
@debug_option
def sdf2obj(model: Path, outdir: Path, game_root: Path | None) -> None:
    """
    Assemble MODEL into OUTDIR as a Wavefront OBJ.

    Each part named by the model's SGEO chunk is looked up as a ``.geo`` member of the ``.pak``
    bundles under the game root, transformed into world space, and merged into one mesh. Parts
    whose geometry is absent are skipped. No material library is written, because the ``.geo``
    format carries neither texture coordinates nor material references.
    """  # noqa: DOC501
    root = model.parent if game_root is None else game_root
    index = build_bundle_index(root)
    mesh = assemble(model.read_bytes(), lambda name: load_member(index, f'{name.lower()}.geo'))
    if not mesh.vertices:
        click.echo(f'No geometry resolved for {model}.', err=True)
        raise click.Abort
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f'{model.stem}.obj'
    write_obj(mesh, out, name=model.stem)
    click.echo(f'Wrote {out} ({len(mesh.vertices)} vertices, {len(mesh.triangles)} triangles).')
