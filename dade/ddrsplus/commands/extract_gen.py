"""``dade ddrsplus extract-gen`` - unpack a song container into a directory."""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging

import click

from dade.common.exceptions import InvalidFormatError
from dade.common.tools import ToolNotFoundError, locate_tool
from dade.ddrsplus.bfcodec import DEFAULT_IV, GEN_KEY
from dade.ddrsplus.extract import extract_gen as extract

from .utils import READABLE_FILE, WRITABLE_DIR, debug_option

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('extract_gen',)

log = logging.getLogger(__name__)


@click.command(name='extract-gen')
@click.argument('files', metavar='FILE', nargs=-1, required=True, type=READABLE_FILE)
@click.option('--ffmpeg', type=READABLE_FILE, help='Path to the ffmpeg binary.')
@click.option('-g',
              '--gap',
              type=float,
              help='Seconds from the start of the audio to beat 0, written as #OFFSET:-GAP. '
              'Measured from the audio when not given.')
@click.option('--iv', default=DEFAULT_IV.hex(), help='Initialisation vector, in hex.')
@click.option('-k', '--key', default=GEN_KEY.hex(), help='Cipher key, in hex.')
@click.option('--no-crop', is_flag=True, help="Keep the banner's transparent padding.")
@click.option('-o',
              '--output-dir',
              type=WRITABLE_DIR,
              help='Write here instead of a directory named after each input.')
@debug_option
def extract_gen(files: tuple[Path, ...],
                ffmpeg: Path | None,
                gap: float | None,
                iv: str,
                key: str,
                output_dir: Path | None,
                *,
                no_crop: bool = False) -> None:
    """
    Unpack each FILE, a Dance Dance Revolution S+ song container, into a directory.

    Every section is written out as stored. The banner also becomes a PNG, the metadata and note
    count tables also become JSON, and each set of step charts also becomes a StepMania simfile.
    Nothing replaces the section it came from.

    The simfile's ``#OFFSET`` is measured from the audio, which needs ``ffmpeg``; pass ``--gap``
    to set it yourself.
    """  # noqa: DOC501
    if ffmpeg is None and gap is None:
        try:
            ffmpeg = locate_tool('ffmpeg')
        except ToolNotFoundError:
            log.warning('`ffmpeg` was not found, so the offset gap will be zero.')
    for path in files:
        target = output_dir or path.with_suffix('')
        try:
            result = extract(path.read_bytes(),
                             path.stem,
                             target,
                             crop_banner=not no_crop,
                             ffmpeg=ffmpeg,
                             gap=gap,
                             iv=bytes.fromhex(iv),
                             key=bytes.fromhex(key))
        except (InvalidFormatError, OSError, ValueError) as e:
            click.echo(f'{path}: {e}', err=True)
            raise click.Abort from e
        click.echo(f'{path} -> {target} ({len(result.paths)} files, gap {result.gap:.3f}s)')
