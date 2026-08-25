"""``dade thps2pc decode-textures`` - decode the textures embedded in a lighting file."""
from __future__ import annotations

from pathlib import Path
import logging

import click

from dade.thps2pc.textures import iter_decoded, parse_lighting, to_ppm

from .utils import convert_path_option, debug_option, run_montage, save_image

__all__ = ('decode_textures',)

log = logging.getLogger(__name__)


@click.command(name='decode-textures')
@click.argument('lighting', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('outdir', type=click.Path(file_okay=False, path_type=Path))
@click.option('--tile-size',
              default='96x96',
              show_default=True,
              help='Geometry each texture is scaled to. Empty keeps the native size.')
@click.option('--per-page',
              default=48,
              show_default=True,
              help='Number of tiles per contact sheet.')
@click.option('--tile',
              default='8x6',
              show_default=True,
              help='Contact sheet grid passed to montage.')
@click.option('--suffix',
              default='.png',
              show_default=True,
              help='Image format for each texture. Use .ppm to avoid needing ImageMagick.')
@click.option('--no-montage', is_flag=True, help='Write the textures without contact sheets.')
@click.option('--montage-path',
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help='Path to the ImageMagick montage binary.')
@convert_path_option
@debug_option
def decode_textures(lighting: Path,
                    outdir: Path,
                    tile_size: str,
                    per_page: int,
                    tile: str,
                    suffix: str,
                    convert_path: Path | None = None,
                    montage_path: Path | None = None,
                    *,
                    no_montage: bool = False) -> None:
    """
    Decode every texture embedded in the lighting file LIGHTING into OUTDIR.

    LIGHTING is a scene's ``*_L.PSX`` companion. Each texture is written as
    ``<CHECKSUM><suffix>`` and, unless --no-montage is given, gathered into labelled contact
    sheets named ``page<N><suffix>`` for visual identification. Instances naming a palette that
    is not present are skipped.
    """
    data = lighting.read_bytes()
    tables = parse_lighting(data)
    outdir.mkdir(parents=True, exist_ok=True)
    scale_args = ['-scale', tile_size] if tile_size else []
    written: list[Path] = []
    for instance, pixels in iter_decoded(data, tables):
        destination = outdir / f'{instance.checksum:08X}{suffix}'
        save_image(to_ppm(pixels, instance.width, instance.height), destination, convert_path,
                   scale_args)
        written.append(destination)
    if not written:
        click.echo('No textures could be decoded.', err=True)
        return
    if no_montage:
        click.echo(f'Decoded {len(written)} textures into {outdir}.')
        return
    pages = 0
    for start in range(0, len(written), per_page):
        page = outdir / f'page{start // per_page}{suffix}'
        args = [
            *(str(p) for p in written[start:start + per_page]), '-tile', tile, '-geometry', '+2+2',
            '-background', 'gray20', '-fill', 'white', '-label', '%t',
            str(page)
        ]
        run_montage(args, page, montage_path)
        pages += 1
    click.echo(f'Decoded {len(written)} textures into {pages} contact sheets under {outdir}.')
