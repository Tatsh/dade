"""Command-line entry point for the Amplitude/FreQuency game unpacker."""
from __future__ import annotations

from pathlib import Path

from destin.common.workers import default_jobs
import bascom
import click

from .pipeline import run_game

__all__ = ('main',)

debug_option = bascom.debug_option({'destin.amplitude': {}, 'destin.common': {}})
"""Attach ``-d/--debug`` to a command and route it through :py:func:`bascom.setup_logging`.

:meta hide-value:
"""


@click.command(context_settings={'help_option_names': ('-h', '--help')})
@click.argument('game_dir', type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument('out', type=click.Path(file_okay=False, path_type=Path))
@debug_option
@click.option('-j',
              '--jobs',
              type=click.IntRange(min=1),
              default=default_jobs,
              show_default='number of CPUs',
              help='Worker processes for the CPU-bound conversion phases.')
@click.option('--no-convert', is_flag=True, help='Extract assets without converting them.')
@click.option('--no-gunzip',
              is_flag=True,
              help='Extract .gz entries verbatim instead of decompressing.')
@click.option('--keep-gz',
              is_flag=True,
              help='Keep the original .gz entry alongside the decompressed output.')
@click.option('--ignore-failures',
              is_flag=True,
              help='Log and skip a conversion failure instead of stopping.')
def main(game_dir: Path,
         out: Path,
         *,
         jobs: int = 1,
         no_convert: bool = False,
         no_gunzip: bool = False,
         keep_gz: bool = False,
         ignore_failures: bool = False) -> None:
    """
    Unpack a PS2 game directory (Amplitude or FreQuency) into OUT and convert its assets.

    Every ARK found under GAME_DIR is unpacked into OUT mirroring its location (e.g.
    ``GEN/MAIN.ARK`` -> ``OUT/GEN/MAIN/``), and disc streaming songs (``AUDIO/*.STR``) are
    converted to WAV. The ARK format (Amplitude vs FreQuency) is auto-detected. Assets are
    converted in place: bitmaps to PNG, DataArray to JSON, Milo scenes to object folders, meshes
    to OBJ, and audio streams/banks to WAV.

    Parameters
    ----------
    game_dir : pathlib.Path
        The game's root directory (the disc root) to scan for ARKs and disc audio.
    out : pathlib.Path
        Output directory (created if missing).
    jobs : int
        Worker processes for the CPU-bound conversion phases (defaults to the CPU count).
    no_convert : bool
        Extract raw assets without converting them.
    no_gunzip : bool
        Extract ``.gz`` entries verbatim instead of decompressing them in place.
    keep_gz : bool
        Keep the original ``.gz`` entry alongside the decompressed output.
    ignore_failures : bool
        Log and skip a conversion failure instead of stopping the run.
    """
    stats = run_game(game_dir,
                     out,
                     convert=not no_convert,
                     gunzip=not no_gunzip,
                     ignore_failures=ignore_failures,
                     jobs=jobs,
                     keep_gz=keep_gz)
    for label, summary in stats.items():
        click.echo(f'{label}: {summary}')
