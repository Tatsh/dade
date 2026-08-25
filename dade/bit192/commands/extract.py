"""``tonesphere extract`` - unpack and decode every Tone Sphere asset."""
from __future__ import annotations

from pathlib import Path
import logging

import click

from dade.bit192.extract import extract as extract_assets

from .utils import console, debug_option

__all__ = ('extract',)

log = logging.getLogger(__name__)


@click.command(name='extract')
@click.argument('inputs',
                nargs=-1,
                required=True,
                type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('--keep-group-bin',
              is_flag=True,
              help='Keep raw .group.bin files alongside their decoded folders.')
@click.option('-o',
              '--out',
              required=True,
              type=click.Path(file_okay=False, path_type=Path),
              help='Output directory.')
@debug_option
def extract(inputs: tuple[Path, ...], out: Path, *, keep_group_bin: bool) -> None:
    """
    Extract and decode every asset from INPUTS into the output directory.

    INPUTS is an ``.xapk``/``.apkm`` bundle, or an ``.apk``, optionally with its ``.obb``. Archives
    are unpacked, ``.group.bin`` resources are decoded to open formats in place, and ``.raw`` PCM is
    wrapped as ``.wav``.
    """
    log.debug('Extracting %d input(s) into %s.', len(inputs), out)
    root = extract_assets(inputs, out, keep_group_bin=keep_group_bin)
    console.print(f'[green]Extracted all assets to {root}.[/green]')
