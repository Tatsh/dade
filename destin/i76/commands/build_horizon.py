"""``destin i76 build-horizon`` - assemble a mission's 360-degree horizon panorama."""
from __future__ import annotations

from pathlib import Path
import logging

import click

from destin.common.png import write_rgb
from destin.i76.bwd2 import world_refs
from destin.i76.horizon import assemble_panorama, bundle_stem, horizon_set, parse_hzd
from destin.i76.pak import read_index
from destin.i76.textures import decode_map, load_palette

from .utils import debug_option

__all__ = ('build_horizon',)

log = logging.getLogger(__name__)

_DEFAULT_PALETTE = 't17.act'
"""Palette used when a mission's ``WRLD`` chunk names none.

:meta hide-value:
"""


@click.command(name='build-horizon')
@click.argument('mission', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('outdir', type=click.Path(file_okay=False, path_type=Path))
@click.option('-g',
              '--game-root',
              required=True,
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help='Directory holding the extracted ZFS content.')
@click.option('-p',
              '--palette',
              default=None,
              help="Name of the .act palette to apply. Defaults to the mission's own reference.")
@debug_option
def build_horizon(mission: Path, outdir: Path, game_root: Path, palette: str | None) -> None:
    """
    Assemble the horizon panorama for MISSION into OUTDIR as a PNG.

    The mission's WRLD chunk names an ``.hzd`` strip list, whose strips are laid out left to right
    into one panorama whose horizontal axis is azimuth and whose vertical axis is height.

    Raises
    ------
    click.Abort
        If the strip list, its bundle, or the palette cannot be resolved.
    """
    refs = world_refs(mission.read_bytes())
    if (hzd := next((r for r in refs if r.lower().endswith('.hzd')), None)) is None:
        click.echo(f'{mission} references no .hzd strip list.', err=True)
        raise click.Abort
    if not (hzd_path := game_root / hzd.lower()).is_file():
        click.echo(f'Strip list {hzd} not found in {game_root}.', err=True)
        raise click.Abort
    if not (names := parse_hzd(hzd_path.read_bytes())):
        click.echo(f'Strip list {hzd} names no strips.', err=True)
        raise click.Abort

    stem = bundle_stem(horizon_set(names[0]))
    pak, pix = game_root / f'{stem}.pak', game_root / f'{stem}.pix'
    if not (pak.is_file() and pix.is_file()):
        click.echo(f'Bundle {stem} not found in {game_root}.', err=True)
        raise click.Abort
    index = {entry.name: entry for entry in read_index(pix)}
    bundle = pak.read_bytes()
    strips = [
        decode_map(bundle[entry.offset:entry.offset + entry.length]) for name in names
        if (entry := index.get(name.lower())) is not None
    ]
    if not strips:
        click.echo(f'None of the {len(names)} strips are present in {stem}.', err=True)
        raise click.Abort

    name = palette or next((r for r in refs if r.lower().endswith('.act')), _DEFAULT_PALETTE)
    if not (palette_path := game_root / name.lower()).is_file():
        click.echo(f'Palette {name} not found in {game_root}.', err=True)
        raise click.Abort
    panorama = assemble_panorama(strips, load_palette(palette_path.read_bytes()))
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f'{mission.stem}.png'
    write_rgb(out, panorama.width, panorama.height, panorama.pixels)
    click.echo(f'Wrote {out} ({panorama.width}x{panorama.height} from {len(strips)} strips).')
