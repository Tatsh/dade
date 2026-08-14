"""``destin rhythmin dump-sheet`` - decrypt and decode a note chart from a song package."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple
import logging
import zipfile

from destin.rhythmin.sheet import (
    SUFFIXES,
    SUFFIX_LEVEL_KEYS,
    arcade_strip,
    arcade_to_json,
    detect_format,
    parse_arcade,
    parse_standard,
    read_sheet,
    render_strip_image,
    standard_strip,
    standard_to_json,
)
import click

from .utils import READABLE_DIR, READABLE_FILE, WRITABLE_FILE, debug_option, echo_json

if TYPE_CHECKING:
    from pathlib import Path

    from destin.rhythmin.sheet import Sheet

__all__ = ('dump_sheet',)

log = logging.getLogger(__name__)

_ARCADE = 'arcade'


class _SongDetails(NamedTuple):
    """The song metadata a package's ``info`` plist carries."""

    title: str | None
    artist: str | None
    level: int | None


def _song_details(sheet: Sheet, suffix: str) -> _SongDetails:
    """
    Pull the song's title, artist or genre, and difficulty level out of the package's info plist.

    An arcade package's info has no artist, so its genre is the marquee line instead.

    Parameters
    ----------
    sheet : destin.rhythmin.sheet.Sheet
        The chart and its package metadata.
    suffix : str
        The difficulty suffix, which selects the level key.

    Returns
    -------
    _SongDetails
        The title, artist, and level, any of which may be ``None``.
    """
    info = sheet.info or {}
    return _SongDetails(info.get('MusicName'),
                        info.get('ArtistName') or info.get('GenreName'),
                        info.get(SUFFIX_LEVEL_KEYS[suffix]))


def _render(package: Path, suffix: str, buttons: Path | None, direction: str, image: Path | None,
            lanes: int, *, raw: bool, summary: bool) -> dict[str, Any] | None:
    """
    Read a chart and produce whichever output was asked for.

    Parameters
    ----------
    package : pathlib.Path
        The song package.
    suffix : str
        The difficulty suffix.
    buttons : pathlib.Path | None
        A directory of button sprites for ``--image``.
    direction : str
        The reading direction, or ``'auto'``.
    image : pathlib.Path | None
        Where to write a strip image, or ``None`` to render JSON.
    lanes : int
        Columns to bucket a standard chart into.
    raw : bool
        Write the decrypted chart bytes to standard output.
    summary : bool
        Leave the per-record list out of the JSON.

    Returns
    -------
    dict[str, Any] | None
        The JSON-ready chart, or ``None`` when the output has already been written.
    """
    sheet = read_sheet(package, suffix)
    if raw:
        click.get_binary_stream('stdout').write(sheet.payload)
        return None
    chart_format = detect_format(sheet.payload, package.suffix)
    details = _song_details(sheet, suffix)
    if image is not None:
        strip = (arcade_strip(parse_arcade(sheet.payload)) if chart_format == _ARCADE else
                 standard_strip(parse_standard(sheet.payload), lanes))
        width, height = render_strip_image(
            strip,
            image,
            artist=details.artist,
            buttons_dir=buttons,
            level=details.level,
            source=f'{package.name} {sheet.entry}',
            title=details.title,
            top_down=(chart_format != _ARCADE if direction == 'auto' else direction == 'top-down'))
        click.echo(f'Wrote {image} ({width}x{height}).', err=True)
        return None
    rendered = (arcade_to_json(parse_arcade(sheet.payload), summary_only=summary)
                if chart_format == _ARCADE else standard_to_json(parse_standard(sheet.payload),
                                                                 summary_only=summary))
    return {
        'package': package.name,
        'entry': sheet.entry,
        'title': details.title,
        'artist': details.artist,
        'level': details.level,
        **rendered,
    }


@click.command(name='dump-sheet')
@click.argument('package', metavar='PACKAGE', type=READABLE_FILE)
@click.argument('suffix', metavar='SUFFIX', type=click.Choice(SUFFIXES))
@click.option('--buttons',
              type=READABLE_DIR,
              help='Directory holding the login_popn01..05@2x.png sprites to draw taps with.')
@click.option('--direction',
              type=click.Choice(('auto', 'bottom-up', 'top-down')),
              default='auto',
              show_default=True,
              help='Reading direction of each column; auto is bottom-up for arcade charts.')
@click.option('--image',
              type=WRITABLE_FILE,
              help='Render the chart as a strip image at this path instead of printing JSON.')
@click.option('--lanes',
              default=7,
              show_default=True,
              help='Columns to bucket a standard chart into, osu!mania style.')
@click.option('--raw', is_flag=True, help='Write the decrypted chart bytes verbatim.')
@click.option('--summary', is_flag=True, help='Leave the per-record list out of the JSON.')
@debug_option
def dump_sheet(package: Path, suffix: str, buttons: Path | None, direction: str, image: Path | None,
               lanes: int, *, raw: bool, summary: bool) -> None:
    """
    Decode the SUFFIX chart of song package PACKAGE and write it to standard output as JSON.

    PACKAGE is a ``.orb`` or ``.acv``; the two carry completely different chart formats, and which
    one this is is detected from the decrypted payload. SUFFIX names the difficulty, so the entry
    read is ``sheet_<SUFFIX>``.

    Raises
    ------
    click.Abort
        If PACKAGE is not a song package, holds no chart of that difficulty, or the chart cannot be
        decrypted or laid out.
    """
    log.debug('Reading `%s` (%s).', package, suffix)
    try:
        rendered = _render(package,
                           suffix,
                           buttons,
                           direction,
                           image,
                           lanes,
                           raw=raw,
                           summary=summary)
    except (KeyError, OSError, ValueError, zipfile.BadZipFile) as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    if rendered is not None:
        echo_json(rendered)
