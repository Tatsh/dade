"""``destin rhythmin dump-map`` - parse a sugoroku ``map_%03d.map`` board."""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging

import click

from destin.rhythmin.treasure_map import map_to_json, read_treasure_map, render_ascii, render_image

from .utils import READABLE_FILE, WRITABLE_FILE, debug_option, echo_json

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('dump_map',)

log = logging.getLogger(__name__)


@click.command(name='dump-map')
@click.argument('board_path', metavar='MAP', type=READABLE_FILE)
@click.option('--ascii', 'as_text', is_flag=True, help='Print a text board instead of JSON.')
@click.option('--image',
              type=WRITABLE_FILE,
              help='Render the board as a PNG at this path instead of printing JSON.')
@click.option('--scale',
              default=2.0,
              show_default=True,
              help='Geometry multiplier applied to every distance in --image.')
@debug_option
def dump_map(board_path: Path, image: Path | None, scale: float, *, as_text: bool) -> None:
    """
    Parse the sugoroku board MAP and write it to standard output as JSON.

    The board holds one square per record, with its coordinates, kind, message text, and the
    identifiers of the squares it links to, plus the deduplicated edge list the game builds from
    those links.

    Raises
    ------
    click.Abort
        If MAP is not a board file.
    """
    log.debug('Reading `%s`.', board_path)
    try:
        board = read_treasure_map(board_path)
    except ValueError as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    if image is not None:
        width, height = render_image(board, image, scale)
        click.echo(f'Wrote {image} ({width}x{height}).', err=True)
        return
    if as_text:
        click.echo(f'{board.name}: {len(board.squares)} squares, {len(board.edges)} edges - '
                   f'{board.title}')
        for row in render_ascii(board):
            click.echo(f'  {row}')
        return
    echo_json(map_to_json(board))
