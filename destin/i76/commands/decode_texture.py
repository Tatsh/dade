"""``destin i76 decode-texture`` - decode a ``.map`` or ``.vqm`` texture to PNG."""
from __future__ import annotations

from pathlib import Path
import logging

from destin.common.png import write_rgb
from destin.i76.textures import (
    decode_map,
    decode_vqm,
    load_codebook,
    load_palette,
    to_rgb,
    vqm_codebook_name,
)
from destin.i76.typing import IndexedImage
import click

from .utils import debug_option

__all__ = ('decode_texture',)

log = logging.getLogger(__name__)


@click.command(name='decode-texture')
@click.argument('texture', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('outdir', type=click.Path(file_okay=False, path_type=Path))
@click.option('-p',
              '--palette',
              required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help='Path to the .act palette to apply.')
@click.option('--codebook-dir',
              default=None,
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help='Directory holding .cbk codebooks. Defaults to the directory of TEXTURE.')
@debug_option
def decode_texture(texture: Path, outdir: Path, palette: Path, codebook_dir: Path | None) -> None:
    """
    Decode texture TEXTURE into OUTDIR as a PNG.

    A ``.map`` is palette-indexed and needs only the palette. A ``.vqm`` is vector-quantised and
    additionally needs the ``.cbk`` codebook it names, which is looked up in ``--codebook-dir``.

    Raises
    ------
    click.Abort
        If the texture format is unsupported or its codebook is absent.
    """
    data = texture.read_bytes()
    colors = load_palette(palette.read_bytes())
    match texture.suffix.lower():
        case '.map':
            image = decode_map(data)
        case '.vqm':
            root = texture.parent if codebook_dir is None else codebook_dir
            name = vqm_codebook_name(data)
            if not (codebook := root / name.lower()).is_file():
                click.echo(f'Codebook {name} not found in {root}.', err=True)
                raise click.Abort
            decoded = decode_vqm(data, load_codebook(codebook.read_bytes()))
            image = IndexedImage(decoded.width, decoded.height, decoded.pixels)
        case suffix:
            click.echo(f'Unsupported texture format `{suffix}`.', err=True)
            raise click.Abort
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f'{texture.stem}.png'
    write_rgb(out, image.width, image.height, to_rgb(image.pixels, image.width, image.height,
                                                     colors))
    click.echo(f'Wrote {out} ({image.width}x{image.height}).')
