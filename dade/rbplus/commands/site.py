"""``dade rbplus site`` - build a browsable site from a collection of tune packages."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
import html
import importlib.resources
import json
import logging

import bascom
import click

from dade.rbplus.chart import ChartError, parse_chart
from dade.rbplus.package import (
    SPECIAL_DIFFICULTY,
    PackageError,
    TunePackage,
    chart_difficulty,
    chart_level,
    extended_tune_id,
    is_extend_note,
    open_package,
)
from dade.rbplus.reading import GOJUON_ROWS, gojuon_row, initial, to_romaji

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from dade.rbplus.typing import ChartDict, TuneInfoDict

__all__ = ('site',)

log = logging.getLogger(__name__)

_DATA_DIRECTORY = 'data'
"""Where the chart data goes, relative to the site's own root.

:meta hide-value:
"""
_INDEX_NAME = 'index.json'
"""What the list of tunes is called inside :py:data:`_DATA_DIRECTORY`.

:meta hide-value:
"""

# The three ordinary difficulties, hardest last. A package holding only the first of these and
# nothing in the other two is an extend note, whose one chart is harder than any of them.
_DIFFICULTIES = ('note_bas', 'note_med', 'note_har')
_PACKAGE_SUFFIX = '.rb'

debug_option = bascom.debug_option({'dade.common': {}, 'dade.rbplus': {}})
"""Attach ``-d/--debug`` to a command and route it through :py:func:`bascom.setup_logging`.

:meta hide-value:
"""


# Every package named, with a directory standing for the packages inside it. A path named twice is
# read once, and the order is settled so that two runs over the same collection agree.
def _packages(sources: Sequence[Path]) -> list[Path]:
    found: set[Path] = set()
    for source in sources:
        if source.is_dir():
            found.update(path for path in source.rglob(f'*{_PACKAGE_SUFFIX}') if path.is_file())
        else:
            found.add(source)
    return sorted(found)


class _Tune:
    """One package, read far enough to file it and to write its charts out."""
    def __init__(self, path: Path, info: TuneInfoDict, charts: dict[str, ChartDict | None]) -> None:
        self.path = path
        self.info = info
        self.charts = charts
        # The conditional binds looser than `or`, so the parentheses are what make this read the
        # way it looks: the metadata's own identifier, or the file name when it is a number.
        self.id = info.get('ID') or (int(path.stem) if path.stem.isdigit() else 0)
        self.extend = is_extend_note(charts)

    @property
    def artist(self) -> str:
        return self.info.get('ArtistName') or ''

    @property
    def title(self) -> str:
        return self.info.get('MusicName') or self.path.stem


# One chart, or nothing when the entry is absent or will not parse. A chart that will not parse is
# reported and left out rather than stopping the run.
def _chart(tune: TunePackage, entry: str) -> ChartDict | None:
    if entry not in tune.names:
        return None
    try:
        return parse_chart(tune.read(entry))
    except ChartError:
        log.warning('`%s` holds a %s chart that will not parse.', tune.path.name, entry)
        return None


def _read(path: Path) -> _Tune | None:
    # One package, or nothing when it will not open. A collection is often part rubbish, so a
    # package that cannot be read is reported and stepped over rather than stopping the run.
    try:
        with open_package(path) as tune:
            return _Tune(path, tune.info(), {entry: _chart(tune, entry) for entry in _DIFFICULTIES})
    except (OSError, PackageError) as e:
        log.warning('Skipping `%s`: %s', path.name, e)
        return None


def _entry(tune: _Tune, special: _Tune | None) -> dict[str, Any]:
    # One tune as the site lists it. Both readings are romanised, since the shipped packages leave
    # the metadata's own romanised fields empty and a Latin keyboard has nothing else to match.
    title_reading = tune.info.get('MusicNameHira') or ''
    artist_reading = tune.info.get('ArtistNameHira') or ''
    title_romaji = to_romaji(title_reading)
    levels = {
        chart_difficulty(entry): chart_level(tune.info, entry)
        for entry in _DIFFICULTIES if tune.charts.get(entry)
    }
    if special is not None:
        # An extend note's level is in the catalogue, which an offline reader has not got.
        levels[SPECIAL_DIFFICULTY] = chart_level(special.info, 'note_bas')
    return {
        'artist': tune.artist,
        'artistReading': artist_reading,
        'artistRomaji': to_romaji(artist_reading),
        'bpm': [tune.info.get('BpmMin'), tune.info.get('BpmMax')],
        'id': tune.id,
        # A title already written in letters is filed under its own first one; only a title that
        # gives no letter falls back to its reading. Otherwise *Gymnopedie* would be filed under J,
        # its reading being ジムノペディ.
        'letter': initial(tune.title, title_romaji),
        'levels': levels,
        'row': gojuon_row(title_reading, tune.title),
        'special': None if special is None else special.id,
        'title': tune.title,
        'titleReading': title_reading,
        'titleRomaji': title_romaji
    }


def _charts(tune: _Tune, special: _Tune | None) -> dict[str, ChartDict]:
    # Every chart the site can draw for one tune, under the name the site knows it by.
    charts = {
        chart_difficulty(entry): chart
        for entry in _DIFFICULTIES if (chart := tune.charts.get(entry)) is not None
    }
    if special is not None and (chart := special.charts.get('note_bas')) is not None:
        charts[SPECIAL_DIFFICULTY] = chart
    return charts


# Each extend note against the tune it extends. One whose tune is not in the collection is left to
# stand on its own, since dropping it would lose a chart that is nowhere else.
def _pair(tunes: Sequence[_Tune]) -> tuple[list[_Tune], dict[int, _Tune]]:
    by_id = {tune.id: tune for tune in tunes if not tune.extend}
    attached: dict[int, _Tune] = {}
    orphans: list[_Tune] = []
    for tune in tunes:
        if not tune.extend:
            continue
        parent = by_id.get(extended_tune_id(tune.id))
        if parent is None:
            log.warning('`%s` extends tune %d, which is not here.', tune.path.name,
                        extended_tune_id(tune.id))
            orphans.append(tune)
        else:
            attached[parent.id] = tune
    return [*(tune for tune in tunes if not tune.extend), *orphans], attached


# Where the site is served from, with a slash at each end so that a path can simply be added to it.
def _slashed(ctx: click.Context, param: click.Parameter, value: str | None) -> str | None:
    if value is None:
        return None
    if not value.startswith('/'):
        msg = f'`{value}` must begin with a slash, as in `/rbpcharts/`.'
        raise click.BadParameter(msg, ctx=ctx, param=param)
    return value.rstrip('/') + '/'


def _at_base(page: str, base: str) -> str:
    """
    Tell a page where it is served from.

    Two things are written in. A ``<base>`` element, so that every relative address the page
    holds - its script, its stylesheet, and the chart data it fetches - is resolved against the
    site's own root rather than against whatever path the reader happens to be at. And the base on
    the root element, which is what the site reads to work out which tune a path names.

    Parameters
    ----------
    page : str
        The built page.
    base : str
        Where the site is served from, with a slash at each end.

    Returns
    -------
    str
        The page, addressed.

    Raises
    ------
    PackageError
        If the built page does not hold what has to be written into. A page that went unaddressed
        would look right and then fail to find its own script, so it is refused rather than
        written.
    """
    where = html.escape(base)
    addressed = page.replace('<html', f'<html data-base="{where}"', 1)
    addressed = addressed.replace('<head>', f'<head><base href="{where}">', 1)
    if addressed == page:
        msg = 'The built page holds no `<html>` and no `<head>`, so it cannot be told where it is.'
        raise PackageError(msg)
    return addressed


# The built page and its bundle, copied out beside the data. They are shipped inside the package,
# since anyone who installs this from PyPI has no Node to build them with.
def _copy_assets(output_dir: Path, base: str | None) -> None:
    built = importlib.resources.files('dade.rbplus') / 'site'
    copied = 0
    for asset in built.iterdir():
        if not asset.is_file():
            continue
        if asset.name == 'index.html' and base is not None:
            page = _at_base(asset.read_text(encoding='utf-8'), base)
            (output_dir / asset.name).write_text(page, encoding='utf-8')
            # GitHub Pages answers a path it holds no file for with `404.html`. Making that the
            # page is what lets a link to one tune be opened directly: the site is served, reads
            # the path it was asked for, and shows that tune. Without it every link but the root
            # would be a not-found page.
            (output_dir / '404.html').write_text(page, encoding='utf-8')
            copied += 2
            continue
        # Read and written rather than copied, since what the assets are read from is whatever the
        # package was installed as and need not be a file on disk.
        (output_dir / asset.name).write_bytes(asset.read_bytes())
        copied += 1
    if not copied:
        log.warning('The site was not built. Run `yarn build` and try again.')


def _write(payload: object, path: Path) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':'), sort_keys=True),
                    encoding='utf-8')


# The site itself: the page and its bundle, one file of charts per tune, and the list the page
# opens with, which is written last so that a run cut short leaves no index promising charts that
# are not there.
def _build(listed: Sequence[_Tune], attached: Mapping[int, _Tune], output_dir: Path,
           base: str | None) -> list[dict[str, Any]]:
    data = output_dir / _DATA_DIRECTORY
    data.mkdir(parents=True, exist_ok=True)
    # GitHub Pages runs Jekyll over what it serves unless told not to, and Jekyll leaves out
    # anything whose name begins with an underscore.
    (output_dir / '.nojekyll').touch()
    _copy_assets(output_dir, base)
    entries = []
    for tune in listed:
        special = attached.get(tune.id)
        entries.append(_entry(tune, special))
        _write(_charts(tune, special), data / f'{tune.id}.json')
    entries.sort(key=lambda entry: (entry['titleRomaji'] or entry['title']).casefold())
    _write(
        {
            'letters': sorted({entry['letter']
                               for entry in entries}),
            'rows': [row for row in GOJUON_ROWS if any(entry['row'] == row for entry in entries)],
            'tunes': entries
        }, data / _INDEX_NAME)
    return entries


def _report(listed: Sequence[dict[str, Any]]) -> Iterator[str]:
    yield f'{len(listed)} tunes'
    if specials := sum(1 for entry in listed if entry['special'] is not None):
        yield f'{specials} with a SPECIAL chart'
    yield f'{len({entry["letter"] for entry in listed})} letters'
    yield f'{len({entry["row"] for entry in listed})} gojūon rows'


@click.command(name='site', context_settings={'help_option_names': ('-h', '--help')})
@click.argument('sources',
                metavar='SOURCES...',
                nargs=-1,
                required=True,
                type=click.Path(exists=True, path_type=Path))
@debug_option
@click.option('--base',
              callback=_slashed,
              help='Where the site will be served from, as in `/rbpcharts/` for a GitHub Pages '
              'project site. Given one, the site addresses tunes by path and a 404.html is written '
              'so that a link to one opens it. Without one it addresses them by fragment, which '
              'needs no such thing and works from anywhere.')
@click.option('-o',
              '--output-dir',
              default=Path('site'),
              help='Where to build the site.',
              show_default=True,
              type=click.Path(file_okay=False, path_type=Path))
def site(sources: tuple[Path, ...], output_dir: Path, base: str | None) -> None:
    """
    Build a browsable site from the tune packages in SOURCES.

    SOURCES may name ``.rb`` packages, directories holding them, or both. A directory is searched
    all the way down.

    Every tune's charts are written as JSON and the page draws them, so the site is static and can
    be served from anywhere, GitHub Pages included.

    A package holding one chart in the basic entry and nothing in the other two is an extend note:
    a SPECIAL chart, harder than hard, sold for a tune that already exists. It is filed under that
    tune rather than listed on its own. Which tune is worked out from the numbering, an extend note
    sitting 50000 above the tune it extends.
    """  # noqa: DOC501
    tunes = [tune for path in _packages(sources) if (tune := _read(path)) is not None]
    if not tunes:
        click.echo('No tune packages could be read.', err=True)
        raise click.Abort
    listed, attached = _pair(tunes)
    try:
        entries = _build(listed, attached, output_dir, base)
    except (OSError, PackageError) as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    click.echo(f'Wrote {output_dir}: ' + ', '.join(_report(entries)) + '.')
