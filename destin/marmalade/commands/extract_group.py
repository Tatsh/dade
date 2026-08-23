"""``marm extract-group`` - decode an IwResGroup (``.group.bin``) to open formats."""
from __future__ import annotations

from pathlib import Path
import logging

import click

from destin.marmalade.convert import ConvertOptions, decode_group_to_dir

from .utils import console, debug_option

__all__ = ('extract_group',)

log = logging.getLogger(__name__)


@click.command(name='extract-group')
@click.argument('group', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('outdir', type=click.Path(file_okay=False, path_type=Path))
@click.option('--png/--no-png', default=True, help='Convert textures and fonts to PNG.')
@click.option('--obj/--no-obj', default=True, help='Convert models to Wavefront OBJ.')
@click.option('--html/--no-html', default=True, help='Emit a WebGL viewer next to each OBJ.')
@click.option('--material-json/--no-material-json', default=True, help='Convert materials to JSON.')
@click.option('--raw', is_flag=True, help='Dump every resource as a raw .bin (no conversion).')
@click.option('--delete/--no-delete',
              default=True,
              help='Delete GROUP after a successful extraction.')
@debug_option
def extract_group(group: Path, outdir: Path, *, png: bool, obj: bool, html: bool,
                  material_json: bool, raw: bool, delete: bool) -> None:
    """
    Decode IwResGroup GROUP into OUTDIR, one subfolder per resource class.

    Textures and fonts become PNG, materials become JSON, and models become OBJ (plus a standalone
    WebGL viewer). Use ``--raw`` to skip all conversion, or the individual ``--no-*`` flags to
    a specific conversion. GROUP is deleted afterwards unless ``--no-delete`` is given.
    """
    log.debug('Decoding group %s into %s (raw=%s).', group, outdir, raw)
    options = (ConvertOptions(png=False, material_json=False, obj=False, html=False)
               if raw else ConvertOptions(png=png, material_json=material_json, obj=obj, html=html))
    counts = decode_group_to_dir(group.read_bytes(), outdir, options)
    summary = ', '.join(f'{cls} x{n}' for cls, n in counts.items()) or 'no resources'
    console.print(f'[green]Decoded {group.name} ({summary}) into {outdir}.[/green]')
    if delete:
        group.unlink()
        log.debug('Deleted source group %s.', group)
        console.print(f'[dim]Deleted source {group}.[/dim]')
