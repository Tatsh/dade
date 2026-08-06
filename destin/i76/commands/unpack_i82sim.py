"""``destin i76 unpack-i82sim`` - statically unpack i82sim.dll and its siblings."""
from __future__ import annotations

from pathlib import Path
import logging

from destin.i76.pe_unpack import InvalidImageError, unpack
import click

from .utils import debug_option

__all__ = ('unpack_i82sim',)

log = logging.getLogger(__name__)


@click.command(name='unpack-i82sim')
@click.argument('input_file', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('output_file', type=click.Path(dir_okay=False, path_type=Path))
@debug_option
def unpack_i82sim(input_file: Path, output_file: Path) -> None:
    """
    Unpack packed image INPUT_FILE to OUTPUT_FILE.

    The result is a memory-aligned dump whose file offsets equal its relative virtual addresses,
    with the original entry point restored, so a disassembler can load it at the image's preferred
    base. Base relocations are not applied.

    Raises
    ------
    click.Abort
        If INPUT_FILE is not a packed PE image.
    """
    try:
        image = unpack(input_file.read_bytes())
    except InvalidImageError as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    output_file.write_bytes(image)
    click.echo(f'Wrote {output_file} ({len(image)} bytes).')
