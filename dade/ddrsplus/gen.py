"""
The ``.gen`` container each *DDR S+* song ships as.

A file opens with a 64-byte directory of eight ``(offset, size)`` little-endian word pairs. Each
pair addresses one section, an unused pair is zero, the sections are stored back to back, and the
last one ends exactly at end of file. A section either begins with the ``KDEI`` magic, in which
case :py:mod:`dade.ddrsplus.bfcodec` deciphers it, or it is stored in the clear.

The eight slots always hold the same things, so :py:data:`SECTION_EXTENSIONS` names them by index
rather than by sniffing:

=====  =======  =============================================================
Index  Cipher   Contents
=====  =======  =============================================================
0      KDEI     The full song, an MP3.
1      KDEI     A preview clip of about fifteen seconds, an MP3.
2      plain    The banner, a PowerVR texture.
3      KDEI     The standard step charts, an SSQ.
4      KDEI     The charts for the mode the app calls Shake, an SSQ.
5      plain    The music id, the titles, the artist, and the foot ratings.
6      plain    Note counts and groove radar for the standard charts.
7      plain    The same for the Shake charts.
=====  =======  =============================================================

``-[SKExpandMerge readResidentMusicData::]`` at 0x000847c0 in the app binary reads sections 5, 6,
and 7, and its field order is what :py:class:`SongMetadata` and :py:class:`ChartTable` follow.
Section 5's music id is big-endian, read with ``readSizeForByte:::`` where sections 6 and 7 use
``readSizeForLittleByte:::``.

Which difficulties the Shake mode has is fixed rather than per song:
``+[SKStageData isExistenceShakeLevel:]`` at 0x00012394 answers yes for slots 1 and 2 only, and
the table at 0x000bcbe8 maps Shake index 0 to slot 1 and index 1 to slot 2, so the two Shake
ratings are basic and difficult. Section 7 still stores all four slots.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple
import struct

from dade.common.exceptions import InvalidFormatError
from dade.ddrsplus.bfcodec import DEFAULT_IV, GEN_KEY, KDEI_MAGIC, decipher

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ('DIFFICULTY_SLOTS', 'SECTION_EXTENSIONS', 'SHAKE_SLOTS', 'ChartTable', 'GenSection',
           'SongMetadata', 'read_gen', 'split_gen')

DIFFICULTY_SLOTS = ('beginner', 'basic', 'difficult', 'expert')
"""The order records appear in, in sections 5, 6, and 7 alike.

:meta hide-value:
"""
SHAKE_SLOTS = ('basic', 'difficult')
"""The difficulties the Shake mode has, which are slots 1 and 2.

:meta hide-value:
"""
SECTION_EXTENSIONS = {
    0: 'mp3',
    1: 'mp3',
    2: 'pvr',
    3: 'ssq',
    4: 'ssq',
    5: 'info',
    6: 'tbl',
    7: 'tbl'
}
"""File extension per section index.

:meta hide-value:
"""

_DIRECTORY_PAIRS = 8
_DIRECTORY_SIZE = _DIRECTORY_PAIRS * 8
_STRING_FIELDS = 3
_STRING_STRIDE = 73
_LEVEL_STRIDE = 6
_LEVEL_COUNT = 6
_GROOVE_VALUES = 5
_STANDARD_LEVELS = 4
_NO_OVERRIDE = 0xFF
_TABLE_HEADER = 8
_TABLE_RECORD = 7
_METADATA_SIZE = 2 + _STRING_FIELDS * _STRING_STRIDE + 1 + _LEVEL_COUNT * _LEVEL_STRIDE


class GenSection(NamedTuple):
    """One section of a ``.gen`` container, exactly as stored."""

    slot: int
    """The section's slot in the eight-entry directory."""
    offset: int
    """Where the section starts in the file."""
    raw: bytes
    """The section as stored, still enciphered if it was."""
    @property
    def extension(self) -> str:
        """
        The file extension the section's contents call for.

        Returns
        -------
        str
            The extension, without a leading dot.
        """
        return SECTION_EXTENSIONS.get(self.slot, 'bin')

    @property
    def is_enciphered(self) -> bool:
        """
        Whether the section carries the ``KDEI`` magic.

        Returns
        -------
        bool
            ``True`` when the section is enciphered.
        """
        return self.raw[:4] == KDEI_MAGIC

    def data(self, key: bytes = GEN_KEY, iv: bytes = DEFAULT_IV) -> bytes:
        """
        Return the section's payload, deciphered when it needs to be.

        Parameters
        ----------
        key : bytes
            The cipher key.
        iv : bytes
            The eight-byte initialisation vector.

        Returns
        -------
        bytes
            The plaintext.
        """
        return decipher(self.raw, key, iv) if self.is_enciphered else self.raw


class SongMetadata(NamedTuple):
    """Section 5: the song's identity and its difficulty ratings."""

    music_id: int
    """The music id, which names the file for downloaded songs."""
    title: str
    """The Japanese title."""
    title_english: str
    """The English title."""
    artist: str
    """The artist."""
    is_english: int
    """Whether the game should prefer the English title."""
    levels: tuple[int, ...]
    """Six foot ratings: four standard, then the two Shake ones."""
    overrides: tuple[tuple[int | None, ...], ...]
    """Groove radar overrides per rating, ``None`` where the section leaves the value alone."""
    @property
    def name(self) -> str:
        """
        The English title when there is one, else the Japanese title.

        Returns
        -------
        str
            The song name.
        """
        return self.title_english or self.title

    def to_json(self) -> dict[str, Any]:
        """
        Represent the section as JSON-ready data.

        Returns
        -------
        dict[str, Any]
            Every field the section holds.
        """
        def records(offset: int, names: Sequence[str]) -> list[dict[str, Any]]:
            return [{
                'difficulty': name,
                'grooveOverride': list(self.overrides[offset + index]),
                'level': self.levels[offset + index]
            } for index, name in enumerate(names)]

        return {
            'artist': self.artist,
            'isEnglish': self.is_english,
            'musicId': self.music_id,
            'nameEnglish': self.title_english,
            'nameJapanese': self.title,
            'shake': records(_STANDARD_LEVELS, SHAKE_SLOTS),
            'standard': records(0, DIFFICULTY_SLOTS)
        }


class ChartTable(NamedTuple):
    """Section 6 or 7: per-difficulty note counts and groove radar."""

    music_time: int
    """How long the song runs, in seconds."""
    measures: int
    """How many measures the song spans."""
    max_bpm: int
    """The highest tempo, rounded to an integer."""
    min_bpm: int
    """The lowest tempo, rounded to an integer."""
    max_combos: tuple[int, ...]
    """Max combo per difficulty slot. Zero means the difficulty has no chart."""
    grooves: tuple[tuple[int, ...], ...]
    """Five groove radar values per difficulty slot."""
    def to_json(self) -> dict[str, Any]:
        """
        Represent the section as JSON-ready data.

        Returns
        -------
        dict[str, Any]
            Every field the section holds.
        """
        return {
            'charts': [{
                'difficulty': name,
                'groove': list(self.grooves[index]),
                'maxCombo': self.max_combos[index],
                'present': self.max_combos[index] > 0
            } for index, name in enumerate(DIFFICULTY_SLOTS)],
            'maxBpm': self.max_bpm,
            'measures': self.measures,
            'minBpm': self.min_bpm,
            'musicTime': self.music_time
        }


def parse_metadata(data: bytes) -> SongMetadata:
    """
    Parse section 5.

    The three text fields each hold a length byte and 72 bytes of UTF-8. The length counts
    characters rather than bytes, so the text is read to its NUL instead. A groove override of
    0xFF means the value from section 6 or 7 stands, which is why those bytes are overrides rather
    than padding.

    Parameters
    ----------
    data : bytes
        The deciphered section 5.

    Returns
    -------
    SongMetadata
        The parsed metadata.

    Raises
    ------
    InvalidFormatError
        If the section is shorter than the fixed layout needs.
    """
    if len(data) < _METADATA_SIZE:
        msg = f'Section 5 is {len(data)} bytes, short of the {_METADATA_SIZE} the layout needs.'
        raise InvalidFormatError(msg)
    texts = tuple(data[2 + index * _STRING_STRIDE + 1:2 +
                       (index + 1) * _STRING_STRIDE].split(b'\0')[0].decode('utf-8', 'replace')
                  for index in range(_STRING_FIELDS))
    tail = data[2 + _STRING_FIELDS * _STRING_STRIDE:]
    records = tuple(tail[1 + slot * _LEVEL_STRIDE:1 + (slot + 1) * _LEVEL_STRIDE]
                    for slot in range(_LEVEL_COUNT))
    return SongMetadata(
        struct.unpack_from('>H', data, 0)[0], texts[0], texts[1], texts[2], tail[0],
        tuple(record[0] for record in records),
        tuple(
            tuple(None if value == _NO_OVERRIDE else value
                  for value in record[1:1 + _GROOVE_VALUES]) for record in records))


def parse_chart_table(data: bytes) -> ChartTable:
    """
    Parse section 6 or 7.

    Parameters
    ----------
    data : bytes
        The deciphered section.

    Returns
    -------
    ChartTable
        The parsed table.

    Raises
    ------
    InvalidFormatError
        If the section is shorter than the fixed layout needs.
    """
    needed = _TABLE_HEADER + len(DIFFICULTY_SLOTS) * _TABLE_RECORD
    if len(data) < needed:
        msg = f'A chart table is {len(data)} bytes, short of the {needed} the layout needs.'
        raise InvalidFormatError(msg)
    starts = tuple(_TABLE_HEADER + index * _TABLE_RECORD for index in range(len(DIFFICULTY_SLOTS)))
    music_time, measures, max_bpm, min_bpm = struct.unpack_from('<4H', data, 0)
    return ChartTable(music_time, measures, max_bpm, min_bpm,
                      tuple(struct.unpack_from('<H', data, start)[0] for start in starts),
                      tuple(tuple(data[start + 2:start + 2 + _GROOVE_VALUES]) for start in starts))


def split_gen(data: bytes) -> tuple[GenSection, ...]:
    """
    Split a ``.gen`` container into its sections without deciphering any of them.

    Parameters
    ----------
    data : bytes
        The whole file.

    Returns
    -------
    tuple[GenSection, ...]
        The populated sections, in directory order.

    Raises
    ------
    InvalidFormatError
        If the file is too short to hold a directory, or an entry runs past the end of the file.
    """
    if len(data) < _DIRECTORY_SIZE:
        msg = f'Too short for a {_DIRECTORY_SIZE}-byte directory: {len(data)} bytes.'
        raise InvalidFormatError(msg)
    entries = struct.unpack_from(f'<{_DIRECTORY_PAIRS * 2}I', data, 0)
    sections = []
    for index in range(_DIRECTORY_PAIRS):
        offset, size = entries[index * 2], entries[index * 2 + 1]
        if not size:
            continue
        if offset + size > len(data):
            msg = (f'Section {index} runs from {offset} for {size} bytes, past the '
                   f'{len(data)}-byte file.')
            raise InvalidFormatError(msg)
        sections.append(GenSection(index, offset, data[offset:offset + size]))
    return tuple(sections)


def read_gen(data: bytes,
             key: bytes = GEN_KEY,
             iv: bytes = DEFAULT_IV) -> dict[int, tuple[GenSection, bytes]]:
    """
    Split a ``.gen`` container and decipher every section that needs it.

    Parameters
    ----------
    data : bytes
        The whole file.
    key : bytes
        The cipher key.
    iv : bytes
        The eight-byte initialisation vector.

    Returns
    -------
    dict[int, tuple[GenSection, bytes]]
        Each section and its plaintext, keyed by directory index.

    """
    return {section.slot: (section, section.data(key, iv)) for section in split_gen(data)}
