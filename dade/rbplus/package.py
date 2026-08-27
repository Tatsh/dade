"""
The ``.rb`` tune package.

A package is an ordinary ZIP named after the tune identifier (``%09d.rb``) whose every entry is
enciphered. Nothing inside is compressed in a way that matters here: the ZIP is unpacked with the
standard library and each entry is deciphered afterwards.

Which of the two keys a package uses is not recorded anywhere in it. ``MusicData +dataWithPath:ID:``
deciphers the ``info`` entry with the first key, and moves to the second when the result is not a
property list; :py:func:`open_package` does the same, so a package that uses neither raises rather
than yielding rubbish.

The five packages that ship with the game carry sixteen entries. ``MusicData.m`` names sixteen more
that no shipped package holds - per-difficulty audio, artwork, and name strips, and the ``note_*2``
light charts - so an unknown entry is classified by its name rather than rejected.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, cast
import logging
import plistlib
import zipfile

from typing_extensions import Self

from dade.common.bfcodec import DEFAULT_IV, BFCodec

from .chart import MAGIC
from .cipher import chart_keys

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path

    from .typing import ChartDict, TuneInfoDict

__all__ = ('AUDIO_ENTRIES', 'CHART_ENTRIES', 'INFO_ENTRY', 'SPECIAL_DIFFICULTY',
           'SPECIAL_ID_OFFSET', 'EntryKind', 'PackageError', 'TunePackage', 'chart_difficulty',
           'chart_level', 'classify_entry', 'extended_tune_id', 'infer_difficulty',
           'is_extend_note', 'open_package', 'read_chart_file')

INFO_ENTRY = 'info'
"""The entry holding the tune metadata, and the one the decode type is established from.

:meta hide-value:
"""
CHART_ENTRIES = ('note_bas', 'note_bas2', 'note_med', 'note_med2', 'note_har', 'note_har2')
"""Every note-chart entry name the game knows, difficulty order, each followed by its light form.

:meta hide-value:
"""
AUDIO_ENTRIES = ('bgm', 'bgm_b', 'bgm_m', 'bgm_h', 'pre')
"""Every audio entry name the game knows: the tune, its per-difficulty forms, and the preview.

:meta hide-value:
"""
SPECIAL_DIFFICULTY = 'special'
"""What an extend note's one chart is called. It is harder than hard.

:meta hide-value:
"""
SPECIAL_ID_OFFSET = 50000
"""How far an extend note's identifier sits above the tune it belongs to.

The catalogue tells the game which tune an extend note extends, and an offline reader has no
catalogue. What it has is the numbering: every extend note observed is ``100050xxx`` and its tune is
the same number less this.

:meta hide-value:
"""

_CHART_LEVEL_KEYS: Mapping[str, str] = {
    'note_bas': 'Basic',
    'note_bas2': 'Basic',
    'note_med': 'Medium',
    'note_med2': 'Medium',
    'note_har': 'Hard',
    'note_har2': 'Hard',
}
_CHART_DIFFICULTIES: Mapping[str, str] = {
    'note_bas': 'basic',
    'note_bas2': 'basic-light',
    'note_med': 'medium',
    'note_med2': 'medium-light',
    'note_har': 'hard',
    'note_har2': 'hard-light',
}

log = logging.getLogger(__name__)


class PackageError(Exception):
    """Raised when a file is not a tune package that can be read."""


class EntryKind:
    """The kinds of entry a package holds, by what the deciphered bytes are."""

    AUDIO = 'audio'
    """An MPEG-4 audio stream."""
    CHART = 'chart'
    """An RBFF note chart."""
    IMAGE = 'image'
    """An Apple-optimised PNG."""
    INFO = 'info'
    """The tune metadata property list."""


def classify_entry(name: str) -> str:
    """
    Say what an entry's deciphered bytes are, from its name.

    Parameters
    ----------
    name : str
        The entry name.

    Returns
    -------
    str
        One of the :py:class:`EntryKind` values. Anything unrecognised is an image, which is what
        every remaining entry the game names turns out to be.
    """
    match name:
        case _ if name == INFO_ENTRY:
            return EntryKind.INFO
        case _ if name in CHART_ENTRIES:
            return EntryKind.CHART
        case _ if name in AUDIO_ENTRIES:
            return EntryKind.AUDIO
        case _:
            return EntryKind.IMAGE


def chart_level(info: TuneInfoDict, name: str) -> int | None:
    """
    Read the level the metadata gives a chart entry.

    Parameters
    ----------
    info : TuneInfoDict
        The tune metadata.
    name : str
        The chart entry name.

    Returns
    -------
    int | None
        The level, or ``None`` when the entry has no level key or the metadata omits it.
    """
    if (key := _CHART_LEVEL_KEYS.get(name)) is None:
        return None
    # The metadata is a property list, so a value of the wrong type is possible and is treated the
    # same as an absent one.
    value = cast('Mapping[str, object]', info).get(key)
    return value if isinstance(value, int) else None


def chart_difficulty(name: str) -> str:
    """
    Name the difficulty a chart entry holds.

    Parameters
    ----------
    name : str
        The chart entry name.

    Returns
    -------
    str
        The difficulty name, or *name* itself when it is not a known chart entry.
    """
    return _CHART_DIFFICULTIES.get(name, name)


def is_extend_note(charts: Mapping[str, ChartDict | None]) -> bool:
    """
    Report whether a package holds an extend note rather than an ordinary tune.

    An extend note is a SPECIAL chart sold for a tune that already exists. The game learns which
    tune from the catalogue and reads the chart with
    ``[[MusicData dataWithPath:… ID:ExtMusicID] sheetBasic]``, so the SPECIAL chart is stored where
    the basic chart of an ordinary tune goes and the other two difficulties are left empty. That
    shape is the only thing a reader without the catalogue can go on.

    Parameters
    ----------
    charts : collections.abc.Mapping[str, ChartDict | None]
        Each chart entry name against its parsed chart, or ``None`` where the entry is absent or
        would not parse.

    Returns
    -------
    bool
        Whether the package holds one chart, in the basic entry, and nothing in the other two.
    """
    def filled(name: str) -> bool:
        chart = charts.get(name)
        return chart is not None and bool(chart['notes'])

    return filled('note_bas') and not filled('note_med') and not filled('note_har')


def extended_tune_id(tune_id: int) -> int:
    """
    Name the tune an extend note belongs to.

    Parameters
    ----------
    tune_id : int
        The extend note's own identifier.

    Returns
    -------
    int
        The tune's identifier, being :py:data:`SPECIAL_ID_OFFSET` lower.
    """
    return tune_id - SPECIAL_ID_OFFSET


class TunePackage:
    """
    One ``.rb`` tune package, opened and with its decode type established.

    Use :py:func:`open_package` rather than constructing this directly, since the decode type has to
    be discovered before any entry can be read.
    """
    def __init__(self, path: Path, archive: zipfile.ZipFile, decode_type: int) -> None:
        self.path = path
        """The package's path."""
        self.decode_type = decode_type
        """Which of the two keys the package's entries are enciphered with."""
        self._archive = archive
        self._key = chart_keys()[decode_type]

    def __enter__(self) -> Self:
        """
        Enter a context manager over the package.

        Returns
        -------
        Self
            The package itself.
        """
        return self

    def __exit__(self, *args: object) -> None:
        """Close the underlying archive on leaving the block."""
        self.close()

    @property
    def names(self) -> tuple[str, ...]:
        """Every entry name, in the order the archive lists them."""
        return tuple(self._archive.namelist())

    def close(self) -> None:
        """Close the underlying archive."""
        self._archive.close()

    def read(self, name: str) -> bytes:
        """
        Read one entry and decipher it.

        Parameters
        ----------
        name : str
            The entry name. One the package does not hold raises :py:class:`KeyError`.

        Returns
        -------
        bytes
            The deciphered entry.
        """
        return BFCodec(self._key).decipher(self._archive.read(name))

    def info(self) -> TuneInfoDict:
        """
        Read the tune metadata.

        Returns
        -------
        TuneInfoDict
            The parsed ``info`` property list.

        Raises
        ------
        PackageError
            If the metadata does not parse.
        """
        try:
            return plistlib.loads(self.read(INFO_ENTRY))  # type: ignore[no-any-return]
        except (KeyError, plistlib.InvalidFileException) as e:
            msg = f'`{self.path.name}` has no readable {INFO_ENTRY} entry.'
            raise PackageError(msg) from e

    def charts(self) -> Iterator[tuple[str, bytes]]:
        """
        Yield every chart entry the package holds, difficulty order.

        Yields
        ------
        tuple[str, bytes]
            The entry name and its deciphered bytes.
        """
        held = set(self.names)
        for name in CHART_ENTRIES:
            if name in held:
                yield name, self.read(name)


def open_package(path: Path) -> TunePackage:
    """
    Open a tune package, establishing which key it uses.

    Parameters
    ----------
    path : pathlib.Path
        The ``.rb`` package.

    Returns
    -------
    TunePackage
        The opened package. Close it, or use it as a context manager.

    Raises
    ------
    PackageError
        If the file is not a ZIP, holds no ``info`` entry, or that entry deciphers to a property
        list under neither key.
    """
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        msg = f'`{path.name}` is not a ZIP archive.'
        raise PackageError(msg) from e
    try:
        raw = archive.read(INFO_ENTRY)
    except KeyError as e:
        archive.close()
        msg = f'`{path.name}` holds no {INFO_ENTRY} entry.'
        raise PackageError(msg) from e
    for decode_type, key in enumerate(chart_keys()):
        try:
            plistlib.loads(BFCodec(key).decipher(raw))
        except (ValueError, plistlib.InvalidFileException):
            log.debug('`%s` is not decode type %d.', path.name, decode_type)
            continue
        return TunePackage(path, archive, decode_type)
    archive.close()
    msg = f'`{path.name}` deciphers under no known key.'
    raise PackageError(msg)


def read_chart_file(path: Path, *, key: bytes | None = None, iv: bytes = DEFAULT_IV) -> bytes:
    """
    Read one note chart from a file of its own, rather than from a package.

    The file may be as it is stored, enciphered under either of the game's keys, or already
    deciphered. A chart opens with :py:data:`~dade.rbplus.chart.MAGIC`, so plain bytes are
    recognised outright and each key is otherwise tried in turn.

    Parameters
    ----------
    path : pathlib.Path
        The chart file.
    key : bytes | None
        A key to use instead of the game's own, for a chart enciphered under neither.
    iv : bytes
        The eight-byte initialisation vector, which only differs from the game's alongside *key*.

    Returns
    -------
    bytes
        The deciphered chart.

    Raises
    ------
    PackageError
        If the file is neither a chart nor enciphered under a key that was tried.
    """
    raw = path.read_bytes()
    if raw.startswith(MAGIC):
        log.debug('`%s` is already deciphered.', path.name)
        return raw
    if key is not None:
        try:
            plain = BFCodec(key, iv).decipher(raw)
        except ValueError as e:
            raise PackageError(str(e)) from e
        if plain.startswith(MAGIC):
            return plain
        msg = f'`{path.name}` does not decipher to a chart under the key given.'
        raise PackageError(msg)
    for decode_type, candidate in enumerate(chart_keys()):
        if (plain := BFCodec(candidate, iv).decipher(raw)).startswith(MAGIC):
            log.debug('`%s` is decode type %d.', path.name, decode_type)
            return plain
    msg = (f'`{path.name}` is not a chart, deciphered or under either game key. '
           f'Give one with --key.')
    raise PackageError(msg)


def infer_difficulty(path: Path) -> str | None:
    """
    Work out which difficulty a bare chart file holds, from its name.

    Parameters
    ----------
    path : pathlib.Path
        The chart file.

    Returns
    -------
    str | None
        The chart entry name, or ``None`` when the name says nothing.
    """
    stem = path.name.split('.')[0].casefold()
    return next((entry for entry in CHART_ENTRIES if stem == entry or stem == entry[len('note_'):]),
                None)
