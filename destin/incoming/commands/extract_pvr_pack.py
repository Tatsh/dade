"""``extract-pvr-pack`` - unpack an Incoming Dreamcast ``*_T.PVR`` texture pack."""
from __future__ import annotations

from pathlib import Path
import logging

from incoming_extractor.converters.images import pvr_pack_to_files, pvr_pack_to_png
from incoming_extractor.utils import pluralize
import click

from .utils import debug_option

__all__ = ('extract_pvr_pack',)

log = logging.getLogger(__name__)


@click.command(name='extract-pvr-pack', context_settings={'help_option_names': ('-h', '--help')})
@click.argument('pack',
                type=click.Path(exists=True, dir_okay=False, path_type=Path, resolve_path=True))
@click.argument('outdir', type=click.Path(file_okay=False, path_type=Path))
@click.option('--png/--no-png',
              default=False,
              help='Convert the textures to PNG with spvr2png instead of writing raw PVR files.')
@debug_option
def extract_pvr_pack(pack: Path, outdir: Path, *, png: bool) -> None:
    """
    Unpack an Incoming Dreamcast ``*_T.PVR`` texture pack PACK into OUTDIR.

    This pack container is Dreamcast-specific. Each contained texture is written under
    ``OUTDIR/<pack name>/`` as a separate ``.pvr`` file, or as a PNG when ``--png`` is given (which
    requires ``spvr2png`` on ``PATH``).
    """
    outdir.mkdir(parents=True, exist_ok=True)
    log.debug('Unpacking `%s` into `%s` (png=%s).', pack, outdir, png)
    outputs = pvr_pack_to_png(pack, outdir) if png else pvr_pack_to_files(pack, outdir)
    click.echo(f'Extracted {pluralize(len(outputs), "texture")} to {outdir / pack.stem}.')
