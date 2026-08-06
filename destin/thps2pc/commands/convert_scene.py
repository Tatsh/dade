"""``destin thps2pc convert-scene`` - export a PSX scene as a mesh with its textures."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import logging
import subprocess as sp

from destin.thps2pc.imagemagick import ImageMagickNotFoundError, convert
from destin.thps2pc.mesh import (
    DEFAULT_SCALE,
    UNTEXTURED_KEY,
    build_batches,
    index_bitmaps,
    pack,
    write_manifest,
)
import click

from .utils import convert_path_option, debug_option, read_scene

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ('convert_scene',)

log = logging.getLogger(__name__)


def _write_textures(batches: Mapping[str, object], index: Mapping[str, Path], outdir: Path,
                    convert_path: Path | None) -> set[str]:
    """
    Convert every referenced texture into a destination directory.

    A batch whose checksum has no matching bitmap is skipped rather than treated as an error, so
    a partial texture set still produces a usable mesh.

    Parameters
    ----------
    batches : Mapping[str, object]
        Batches keyed by texture checksum.
    index : Mapping[str, Path]
        Upper-case bitmap stem to its path.
    outdir : Path
        Directory the PNGs are written into. It is created if missing.
    convert_path : Path | None
        An explicit path to the ImageMagick ``convert`` binary.

    Returns
    -------
    set[str]
        The batch keys whose texture was written.

    Raises
    ------
    click.Abort
        If ImageMagick is missing or a conversion fails.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    resolved: set[str] = set()
    for key in sorted(batches):
        if key == UNTEXTURED_KEY:
            continue
        destination = outdir / f'{key}.png'
        if destination.exists():
            resolved.add(key)
            continue
        if (source := index.get(key)) is None:
            log.debug('No bitmap found for texture %s.', key)
            continue
        try:
            convert([str(source), str(destination)], convert_path)
        except (ImageMagickNotFoundError, OSError, sp.CalledProcessError) as e:
            click.echo(f'Could not convert {source}: {e}', err=True)
            raise click.Abort from e
        resolved.add(key)
    return resolved


@click.command(name='convert-scene')
@click.argument('scene', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('outdir', type=click.Path(file_okay=False, path_type=Path))
@click.option('-n', '--name', help='Base name for the mesh files. Defaults to the scene file stem.')
@click.option('-t',
              '--texture-dir',
              'texture_dirs',
              multiple=True,
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help='Directory of hash-named BMP textures to resolve against (repeatable).')
@click.option('--corner-source',
              default='length',
              show_default=True,
              type=click.Choice(('flag', 'length')),
              help='How to derive a face corner count.')
@click.option('--triangulation',
              default='fan',
              show_default=True,
              type=click.Choice(('fan', 'strip')),
              help='How to split a quad into triangles.')
@click.option('--scale',
              default=DEFAULT_SCALE,
              show_default=True,
              help='Uniform scale factor recorded in the manifest.')
@click.option('--no-textures', is_flag=True, help='Skip texture resolution and conversion.')
@convert_path_option
@debug_option
def convert_scene(scene: Path,
                  outdir: Path,
                  texture_dirs: tuple[Path, ...],
                  corner_source: str,
                  triangulation: str,
                  scale: float,
                  name: str | None = None,
                  convert_path: Path | None = None,
                  *,
                  no_textures: bool = False) -> None:
    """
    Convert SCENE into an interleaved mesh and its textures under OUTDIR.

    Writes ``models/<name>.bin`` holding [x, y, z, u, v] as 32-bit floats per triangle vertex,
    ``models/<name>.json`` describing the batches, and one PNG per referenced texture under
    ``textures/<name>``. Textures are resolved by checksum against the BMP directories given with
    --texture-dir and converted with ImageMagick; pass --no-textures to skip that entirely.
    """
    parsed = read_scene(scene)
    stem = name or scene.stem
    batches = build_batches(parsed,
                            parsed.texture_checksums(),
                            corner_source=corner_source,
                            triangulation=triangulation)
    resolved = (set() if no_textures else _write_textures(batches, index_bitmaps(texture_dirs),
                                                          outdir / 'textures' / stem, convert_path))
    blob, manifest = pack(batches, resolved, scale)
    models = outdir / 'models'
    models.mkdir(parents=True, exist_ok=True)
    (models / f'{stem}.bin').write_bytes(blob)
    write_manifest(manifest, models / f'{stem}.json')
    vertices = sum(entry['vertex_count'] for entry in manifest['batches'])
    untextured = sum(
        entry['vertex_count'] for entry in manifest['batches'] if entry['texture'] is None)
    click.echo(f'batches={len(manifest["batches"])} textures_resolved={len(resolved)} '
               f'triangle_verts={vertices} bin_bytes={len(blob)}')
    click.echo(f'untextured/placeholder verts={untextured}')
