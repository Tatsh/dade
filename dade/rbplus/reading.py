"""
What a tune's kana reading is good for.

A tune's metadata has room for a romanised title and artist, but the shipped packages leave both
empty and fill in the kana reading instead. The reading is therefore the only thing a Latin
keyboard can be matched against, and the only thing that says where a tune is filed when its title
is not written in letters.

The romanisation is meant for searching rather than for reading: the long vowel mark is dropped
rather than written as a macron, and anything that is not kana is carried through as it stands, so
a reading already in Latin letters comes back as it was but in lowercase.
"""
from __future__ import annotations

__all__ = ('GOJUON_ROWS', 'gojuon_row', 'initial', 'to_romaji')

GOJUON_ROWS = ('ア', 'カ', 'サ', 'タ', 'ナ', 'ハ', 'マ', 'ヤ', 'ラ', 'ワ')
"""The ten rows of the gojūon, in their own order, each named by the kana that heads it.

:meta hide-value:
"""

_HIRAGANA_TO_KATAKANA = 0x60
_HIRAGANA = range(0x3041, 0x3097)
# A set rather than a string: the last kana of a reading is followed by the empty string, and that
# is a substring of every string.
_SMALL_Y = frozenset('ャュョ')
_LONG_MARK = 'ーヽヾ'
_GEMINATE = 'ッ'

# yapf: disable  # noqa: ERA001
_PLAIN = {
    'ア': 'a', 'イ': 'i', 'ウ': 'u', 'エ': 'e', 'オ': 'o',
    'カ': 'ka', 'キ': 'ki', 'ク': 'ku', 'ケ': 'ke', 'コ': 'ko',
    'サ': 'sa', 'シ': 'shi', 'ス': 'su', 'セ': 'se', 'ソ': 'so',
    'タ': 'ta', 'チ': 'chi', 'ツ': 'tsu', 'テ': 'te', 'ト': 'to',
    'ナ': 'na', 'ニ': 'ni', 'ヌ': 'nu', 'ネ': 'ne', 'ノ': 'no',  # noqa: RUF001
    'ハ': 'ha', 'ヒ': 'hi', 'フ': 'fu', 'ヘ': 'he', 'ホ': 'ho',
    'マ': 'ma', 'ミ': 'mi', 'ム': 'mu', 'メ': 'me', 'モ': 'mo',
    'ヤ': 'ya', 'ユ': 'yu', 'ヨ': 'yo',
    'ラ': 'ra', 'リ': 'ri', 'ル': 'ru', 'レ': 're', 'ロ': 'ro',
    'ワ': 'wa', 'ヰ': 'i', 'ヱ': 'e', 'ヲ': 'o', 'ン': 'n',
    'ガ': 'ga', 'ギ': 'gi', 'グ': 'gu', 'ゲ': 'ge', 'ゴ': 'go',
    'ザ': 'za', 'ジ': 'ji', 'ズ': 'zu', 'ゼ': 'ze', 'ゾ': 'zo',
    'ダ': 'da', 'ヂ': 'ji', 'ヅ': 'zu', 'デ': 'de', 'ド': 'do',
    'バ': 'ba', 'ビ': 'bi', 'ブ': 'bu', 'ベ': 'be', 'ボ': 'bo',
    'パ': 'pa', 'ピ': 'pi', 'プ': 'pu', 'ペ': 'pe', 'ポ': 'po',
    'ヴ': 'vu',
    'ァ': 'a', 'ィ': 'i', 'ゥ': 'u', 'ェ': 'e', 'ォ': 'o',
    'ャ': 'ya', 'ュ': 'yu', 'ョ': 'yo',
    'ヮ': 'wa', 'ヵ': 'ka', 'ヶ': 'ke'
}
"""Each kana against the letters it is written with on its own.

:meta hide-value:
"""

_DIGRAPHS = {
    'キ': 'k', 'ギ': 'g', 'シ': 'sh', 'ジ': 'j', 'チ': 'ch', 'ヂ': 'j', 'ニ': 'n', 'ヒ': 'h',
    'ビ': 'b', 'ピ': 'p', 'ミ': 'm', 'リ': 'r', 'ヴ': 'v'
}
"""The kana that take a small ya, yu, or yo, against the sound they keep when one follows.

A kana written ``shi`` and its like loses its ``i`` and the small kana loses its ``y``, so ``シ``
and ``ャ`` together are ``sha`` rather than ``shiya``.

:meta hide-value:
"""

_PALATAL = frozenset({'sh', 'ch', 'j'})

_SMALL_VOWEL_PAIRS = {
    'ウ': {'ィ': 'wi', 'ェ': 'we', 'ォ': 'wo'},
    'ク': {'ァ': 'kwa', 'ィ': 'kwi', 'ェ': 'kwe', 'ォ': 'kwo'},
    'グ': {'ァ': 'gwa', 'ィ': 'gwi', 'ェ': 'gwe', 'ォ': 'gwo'},
    'シ': {'ェ': 'she'},
    'ジ': {'ェ': 'je'},
    'チ': {'ェ': 'che'},
    'ツ': {'ァ': 'tsa', 'ィ': 'tsi', 'ェ': 'tse', 'ォ': 'tso'},
    'テ': {'ィ': 'ti', 'ュ': 'tyu'},
    'デ': {'ィ': 'di', 'ュ': 'dyu'},
    'ト': {'ゥ': 'tu'},
    'ド': {'ゥ': 'du'},
    'イ': {'ェ': 'ye'},
    'フ': {'ァ': 'fa', 'ィ': 'fi', 'ェ': 'fe', 'ォ': 'fo', 'ュ': 'fyu'},
    'ヴ': {'ァ': 'va', 'ィ': 'vi', 'ェ': 've', 'ォ': 'vo'}
}
"""Pairs whose second kana is small and which are written as one sound rather than two.

Anything not named here falls back to the two kana written in turn.

:meta hide-value:
"""

# Which row a sound belongs to, by the consonant it starts with.
_ROW_BY_SOUND = {
    'k': 'カ', 'g': 'カ', 's': 'サ', 'sh': 'サ', 'z': 'サ', 'j': 'サ', 't': 'タ',
    'ch': 'タ', 'ts': 'タ', 'd': 'タ', 'n': 'ナ', 'h': 'ハ', 'f': 'ハ', 'b': 'ハ', 'p': 'ハ',
    'v': 'ハ', 'm': 'マ', 'y': 'ヤ', 'r': 'ラ', 'w': 'ワ'
}
# yapf: enable  # noqa: ERA001


def _katakana(text: str) -> str:
    # Hiragana and katakana sit a fixed distance apart, so one becomes the other by arithmetic and
    # the tables only have to be written once.
    return ''.join(
        chr(ord(mark) + _HIRAGANA_TO_KATAKANA) if ord(mark) in _HIRAGANA else mark for mark in text)


def to_romaji(reading: str) -> str:
    """
    Write a kana reading in Latin letters.

    Parameters
    ----------
    reading : str
        The reading, in either kana. Anything that is not kana is carried through as it stands.

    Returns
    -------
    str
        The reading in lowercase Latin letters, with the long vowel and repetition marks dropped.
        Everything carried through is lowercased along with the rest.
    """
    marks = _katakana(reading)
    out: list[str] = []
    at = 0
    while at < len(marks):
        mark = marks[at]
        following = marks[at + 1] if at + 1 < len(marks) else ''
        if mark in _LONG_MARK:
            # The mark lengthens the vowel before it. A search is typed without the length, so it
            # is dropped rather than written twice.
            at += 1
        elif mark == _GEMINATE:
            # The next sound's first letter is written twice. At the end of a reading there is no
            # next sound and nothing is written.
            rest = to_romaji(marks[at + 1:])
            out.append(rest[:1] + rest)
            break
        elif (pair := _SMALL_VOWEL_PAIRS.get(mark, {}).get(following)) is not None:
            # A pair named outright wins over the general rule below, which is what lets `テュ` be
            # `tyu` rather than the `teyu` the two kana would otherwise come to.
            out.append(pair)
            at += 2
        elif following in _SMALL_Y and mark in _DIGRAPHS:
            # A base already written with a palatal takes the bare vowel, so it is `sha` and not
            # `shya`; every other base keeps the small kana's own `y`.
            base = _DIGRAPHS[mark]
            vowel = _PLAIN[following].removeprefix('y')
            out.append(base + vowel if base in _PALATAL else base + 'y' + vowel)
            at += 2
        else:
            out.append(_PLAIN.get(mark, mark))
            at += 1
    return ''.join(out).lower()


def gojuon_row(*readings: str) -> str:
    """
    Pick the gojūon row a tune is filed under.

    Parameters
    ----------
    *readings : str
        The tune's kana readings, most preferred first. The first that begins with a kana decides.

    Returns
    -------
    str
        One of :py:data:`GOJUON_ROWS`, or ``'?'`` for a reading that begins with no kana at all.
    """
    for reading in readings:
        # Only a reading that begins with kana has a row. Romanising first and looking the letters
        # up would file anything at all: *FLOWER* would be read as an `f` and land in the ha row,
        # and a title beginning with a digit would fall through to the a row.
        marks = _katakana(reading).lstrip(_LONG_MARK + _GEMINATE)
        if not marks or marks[0] not in _PLAIN:
            continue
        # The longest consonant wins, and a sound starting with a vowel heads the first row.
        sound = to_romaji(marks[:2])
        return _ROW_BY_SOUND.get(sound[:2]) or _ROW_BY_SOUND.get(sound[:1]) or GOJUON_ROWS[0]
    return '?'


def initial(*names: str) -> str:
    """
    Pick the letter a tune is filed under.

    Parameters
    ----------
    *names : str
        What the tune is called, most preferred first. The first that begins with a letter or a
        digit decides.

    Returns
    -------
    str
        One uppercase letter, ``'#'`` for a name beginning with a digit, or ``'?'`` for one
        beginning with neither.
    """
    for name in names:
        for mark in name:
            if mark.isspace():
                continue
            if mark.isascii() and mark.isalpha():
                return mark.upper()
            if mark.isdigit():
                return '#'
            break
    return '?'
