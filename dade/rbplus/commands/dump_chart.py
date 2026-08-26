"""``dade rbplus dump-chart`` - read one note chart out of a tune package."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast
import json
import logging
import zipfile

import bascom
import click

from dade.common.bfcodec import DEFAULT_IV
from dade.rbplus.chart import ChartError, parse_chart
from dade.rbplus.package import (
    CHART_ENTRIES,
    PackageError,
    chart_difficulty,
    chart_level,
    infer_difficulty,
    open_package,
    read_chart_file,
)
from dade.rbplus.render import (
    DEFAULT_SCALE,
    DEFAULT_SEED,
    DEFAULT_SPEED,
    SCALE_RANGE,
    SPEED_RANGE,
    render_chart_image,
)

if TYPE_CHECKING:
    from dade.rbplus.typing import ChartDict, TuneInfoDict

__all__ = ('dump_chart',)

log = logging.getLogger(__name__)

_DIFFICULTIES = {'bas': 'note_bas', 'med': 'note_med', 'har': 'note_har'}
_DEFAULT_DIFFICULTY = 'bas'
_PACKAGE_SUFFIX = '.rb'

debug_option = bascom.debug_option({'dade.common': {}, 'dade.rbplus': {}})
"""Attach ``-d/--debug`` to a command and route it through :py:func:`bascom.setup_logging`.

:meta hide-value:
"""


# The tune metadata and the parsed chart of one difficulty. A package that holds no chart of that
# difficulty is a user error rather than a parse failure, so it reports what it does hold.
def _read_package(package: Path, entry: str) -> tuple[TuneInfoDict, ChartDict]:
    with open_package(package) as tune:
        info = tune.info()
        if entry not in tune.names:
            held = ', '.join(name for name in CHART_ENTRIES if name in tune.names)
            msg = f'`{package.name}` holds no {entry} chart. It holds: {held}.'
            raise PackageError(msg)
        return info, parse_chart(tune.read(entry))


# One chart read from a file of its own. There is no metadata beside it, so the difficulty has to
# come from the file name or from the caller.
def _read_bare(path: Path, difficulty: str | None, *, key: bytes | None,
               iv: bytes) -> tuple[TuneInfoDict, str, ChartDict]:
    entry = _DIFFICULTIES[difficulty] if difficulty else infer_difficulty(path)
    if entry is None:
        msg = (f'`{path.name}` does not say which difficulty it is. '
               f'Name it, as in `{path.name} har`.')
        raise PackageError(msg)
    return cast('TuneInfoDict', {}), entry, parse_chart(read_chart_file(path, iv=iv, key=key))


# A key or an initialisation vector given as hex, which is how both are usually written down.
def _hex(ctx: click.Context, param: click.Parameter, value: str | None) -> bytes | None:
    if value is None:
        return None
    try:
        return bytes.fromhex(value.removeprefix('0x').replace(' ', ''))
    except ValueError as e:
        msg = f'`{value}` is not hex.'
        raise click.BadParameter(msg, ctx=ctx, param=param) from e


@click.command(name='dump-chart', context_settings={'help_option_names': ('-h', '--help')})
@click.argument('package',
                metavar='PACKAGE',
                type=click.Path(dir_okay=False, exists=True, path_type=Path))
@click.argument('difficulty',
                metavar='DIFFICULTY',
                default=None,
                required=False,
                type=click.Choice(tuple(_DIFFICULTIES)))
@debug_option
@click.option('--iv',
              callback=_hex,
              help='Initialisation vector as hex, for a chart enciphered with a different one.')
@click.option('--key',
              callback=_hex,
              help='Key as hex, for a chart enciphered under neither of the game keys.')
@click.option('--image',
              type=click.Path(dir_okay=False, path_type=Path),
              help='Also render the chart as a strip image at this path.')
@click.option('--scale',
              type=click.FloatRange(*SCALE_RANGE),
              default=DEFAULT_SCALE,
              show_default=True,
              help='Write --image this many times its usual size.')
@click.option('--seed',
              type=int,
              default=DEFAULT_SEED,
              help='Pin the lane layout --image draws, which is otherwise fresh each run.')
@click.option('--speed',
              type=click.FloatRange(*SPEED_RANGE),
              default=DEFAULT_SPEED,
              show_default=True,
              help='Speed modifier for --image, from 1.0 to 2.0 in steps of 0.1.')
@click.option('--summary', is_flag=True, help='Report only the header, dropping the note list.')
def dump_chart(package: Path,
               difficulty: str | None,
               image: Path | None,
               iv: bytes | None,
               key: bytes | None,
               scale: float,
               seed: int | None,
               speed: float,
               *,
               summary: bool = False) -> None:
    """
    Write the DIFFICULTY chart of the tune package PACKAGE as JSON.

    PACKAGE may be a ``.rb`` tune package, or one note chart in a file of its own, either as the
    package stores it or already deciphered.

    DIFFICULTY is ``bas``, ``med``, or ``har``. Given a package it names which chart to read and
    defaults to ``bas``. Given a single chart it is only needed when the file name does not already
    say, as ``note_har`` and ``har`` both do.

    A chart in a file of its own is deciphered under whichever of the game's keys fits, or read as
    it stands when it is already plain. Give --key, and --iv if it also differs, for one enciphered
    under neither.

    The JSON goes to standard output.

    With --image the chart is also drawn as a strip. Time runs upward, wrapped into columns, with
    the whole of side 0 in the left panel and the whole of side 1 in the right. A note aimed at an
    alternative target is green, one that travels to the other side to be swiped back is gold, a
    hold extends as a bar to its release, and each note of a chain is joined to the next by a line.
    The image carries a legend.
    """  # noqa: DOC501
    try:
        # A file named .rb is meant as a package whether or not it opens as one, so a broken one
        # says so rather than being taken for a chart.
        if package.suffix.casefold() == _PACKAGE_SUFFIX or zipfile.is_zipfile(package):
            entry = _DIFFICULTIES[difficulty or _DEFAULT_DIFFICULTY]
            info, chart = _read_package(package, entry)
        else:
            info, entry, chart = _read_bare(package, difficulty, iv=iv or DEFAULT_IV, key=key)
    except (ChartError, OSError, PackageError) as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    if image is not None:
        render_chart_image(chart,
                           image,
                           artist=info.get('ArtistName'),
                           bpm=info.get('BpmMin'),
                           difficulty=chart_difficulty(entry),
                           level=chart_level(info, entry),
                           scale=scale,
                           seed=seed,
                           speed=speed,
                           title=info.get('MusicName'))
        log.info('Wrote `%s`.', image)
    payload = dict(chart)
    if summary:
        payload = {
            'header': chart['header'],
            'slide_record_count': len(chart['slides']),
            'tempo_event_count': len(chart['tempo_events'])
        }
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
