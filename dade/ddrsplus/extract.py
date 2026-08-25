"""
Turn a ``.gen`` container into a directory of usable files.

Every section is written out as stored, and the ones that can be decoded further get a companion
beside them rather than in place of them: the banner texture also becomes a PNG, sections 5, 6,
and 7 also become JSON, and each SSQ also becomes a StepMania simfile.

The two SSQ sections become separate simfiles because they are alternative charts for the same
song and StepMania cannot hold two ``dance-single`` charts of one difficulty in a single file.
Only the four-panel standard charts have a recorded foot rating, so the double charts and the
duplicated Shake slots are written with a meter of 0, which reads as unrated rather than as a
guess.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import json
import logging

from dade.common.png import write_rgba
from dade.common.ssq import DIFFICULTY_NAMES, STEPS_TYPES, TICKS_PER_BEAT, chart_notes, parse_ssq
from dade.common.stepmania import SimfileChart, write_sm
from dade.ddrsplus.bfcodec import DEFAULT_IV, GEN_KEY
from dade.ddrsplus.gap import estimate_gap
from dade.ddrsplus.gen import parse_chart_table, parse_metadata, read_gen
from dade.ddrsplus.pvr import BANNER_SIZE, crop, decode_pvr

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from dade.common.ssq import SSQ, Chart
    from dade.ddrsplus.gen import SongMetadata

__all__ = ('BANNER_SECTION', 'JSON_SECTIONS', 'MUSIC_SECTION', 'SHAKE_SECTION', 'STANDARD_SECTION',
           'extract_gen')

log = logging.getLogger(__name__)

MUSIC_SECTION = 0
"""Index of the section holding the full song.

:meta hide-value:
"""
BANNER_SECTION = 2
"""Index of the section holding the banner texture.

:meta hide-value:
"""
STANDARD_SECTION = 3
"""Index of the section holding the standard step charts.

:meta hide-value:
"""
SHAKE_SECTION = 4
"""Index of the section holding the Shake step charts.

:meta hide-value:
"""
METADATA_SECTION = 5
"""Index of the section holding the titles and ratings.

:meta hide-value:
"""
JSON_SECTIONS = (5, 6, 7)
"""Indices of the sections that also get a JSON decode.

:meta hide-value:
"""

_STANDARD_LEVEL_SLOTS = {4: 0, 1: 1, 2: 2, 3: 3}
_SHAKE_LEVEL_SLOTS = {1: 4, 2: 5}
_SINGLE_PANELS = 4


class ExtractedSong(NamedTuple):
    """What :py:func:`extract_gen` wrote."""

    paths: tuple[Path, ...]
    """Every file written, in the order it was written."""
    gap: float
    """The gap used for ``#OFFSET``, in seconds."""


def _meters(charts: Sequence[Chart], slots: dict[int, int], levels: Sequence[int]) -> list[int]:
    """
    Line the foot ratings up with the charts they belong to.

    Parameters
    ----------
    charts : collections.abc.Sequence[dade.common.ssq.Chart]
        The charts, in file order.
    slots : dict[int, int]
        Difficulty code to level slot.
    levels : collections.abc.Sequence[int]
        The six ratings.

    Returns
    -------
    list[int]
        One rating per chart, 0 where none is recorded.
    """
    return [
        levels[slot] if
        (slot := slots.get(chart.difficulty) if chart.panels == _SINGLE_PANELS else None)
        is not None and slot < len(levels) else 0 for chart in charts
    ]


def _simfile(ssq: SSQ, metadata: SongMetadata | None, slots: dict[int, int], banner: str,
             music: str, gap: float) -> str:
    """
    Render one SSQ section as a simfile.

    Parameters
    ----------
    ssq : dade.common.ssq.SSQ
        The parsed charts and tempo map.
    metadata : dade.ddrsplus.gen.SongMetadata | None
        The song's titles and ratings.
    slots : dict[int, int]
        Difficulty code to level slot.
    banner : str
        The banner file name, relative to the simfile.
    music : str
        The audio file name, relative to the simfile.
    gap : float
        Seconds from the start of the audio to beat 0.

    Returns
    -------
    str
        The simfile's contents.
    """
    meters = _meters(ssq.charts, slots, metadata.levels if metadata else ())
    return write_sm([
        SimfileChart(STEPS_TYPES[chart.panels], DIFFICULTY_NAMES.get(chart.difficulty, 'Edit'),
                     meter, chart_notes(chart))
        for chart, meter in zip(ssq.charts, meters, strict=True) if chart.panels in STEPS_TYPES
    ],
                    ssq.tempo.bpms() if ssq.tempo else ((0.0, 0.0),),
                    artist=metadata.artist if metadata else '',
                    banner=banner,
                    credit='DDR S+',
                    gap=gap,
                    music=music,
                    stops=ssq.tempo.stops() if ssq.tempo else (),
                    title=metadata.name if metadata else '')


def _chart_end(charts: Sequence[SSQ], bpm: float) -> float:
    """
    Find how far past beat 0 the last note of any chart falls.

    Parameters
    ----------
    charts : collections.abc.Sequence[dade.common.ssq.SSQ]
        The parsed SSQ sections.
    bpm : float
        The tempo.

    Returns
    -------
    float
        The time in seconds, or 0.0 when there are no notes.
    """
    ticks = [max(chart.ticks) for ssq in charts for chart in ssq.charts if chart.ticks]
    return max(ticks) / TICKS_PER_BEAT / bpm * 60 if ticks and bpm > 0 else 0.0


def extract_gen(data: bytes,
                stem: str,
                output_dir: Path,
                *,
                crop_banner: bool = True,
                ffmpeg: Path | None = None,
                gap: float | None = None,
                iv: bytes = DEFAULT_IV,
                key: bytes = GEN_KEY) -> ExtractedSong:
    """
    Extract a ``.gen`` container and write every section plus its converted forms.

    Parameters
    ----------
    data : bytes
        The whole container.
    stem : str
        The base name to build output names from.
    output_dir : pathlib.Path
        Where to write. It is created if it does not exist.
    crop_banner : bool
        Trim the banner's transparent padding away.
    ffmpeg : pathlib.Path | None
        The ``ffmpeg`` binary, used to measure the ``#OFFSET`` gap. Without it, and without an
        explicit ``gap``, the gap is 0.
    gap : float | None
        Seconds from the start of the audio to beat 0. Measured from the audio when ``None``.
    iv : bytes
        The eight-byte initialisation vector.
    key : bytes
        The cipher key.

    Returns
    -------
    ExtractedSong
        The files written and the gap used.

    """
    output_dir.mkdir(parents=True, exist_ok=True)
    sections = read_gen(data, key, iv)
    written = []
    for slot, (section, plain) in sorted(sections.items()):
        path = output_dir / f'{stem}.{slot}.{section.extension}'
        path.write_bytes(plain)
        written.append(path)
    metadata = (parse_metadata(sections[METADATA_SECTION][1])
                if METADATA_SECTION in sections else None)
    for index in JSON_SECTIONS:
        if index not in sections:
            continue
        decoded = (parse_metadata if index == METADATA_SECTION else parse_chart_table)(
            sections[index][1])
        path = output_dir / f'{stem}.{index}.json'
        path.write_text(
            json.dumps(decoded.to_json(), ensure_ascii=False, indent=2, sort_keys=True) + '\n')
        written.append(path)
    banner = ''
    if BANNER_SECTION in sections:
        texture = decode_pvr(sections[BANNER_SECTION][1])
        if crop_banner:
            texture = crop(texture, BANNER_SIZE)
        banner = f'{stem}.{BANNER_SECTION}.png'
        write_rgba(output_dir / banner, texture.width, texture.height, texture.pixels)
        written.append(output_dir / banner)
    music = f'{stem}.{MUSIC_SECTION}.mp3' if MUSIC_SECTION in sections else ''
    parsed = [(suffix, slots, parse_ssq(sections[index][1]))
              for index, suffix, slots in ((STANDARD_SECTION, '', _STANDARD_LEVEL_SLOTS),
                                           (SHAKE_SECTION, '.shake', _SHAKE_LEVEL_SLOTS))
              if index in sections]
    if gap is None:
        bpm = next((ssq.tempo.bpms()[-1][1] for _, _, ssq in parsed if ssq.tempo), 0.0)
        measured = (estimate_gap(ffmpeg,
                                 output_dir / music,
                                 bpm,
                                 chart_end=_chart_end([ssq for _, _, ssq in parsed], bpm))
                    if ffmpeg is not None and music and bpm > 0 else None)
        if measured is None:
            log.warning('Could not measure the offset gap for `%s`; using zero.', stem)
        gap = measured or 0.0
    for suffix, slots, ssq in parsed:
        if not ssq.charts:
            continue
        path = output_dir / f'{stem}{suffix}.sm'
        path.write_text(_simfile(ssq, metadata, slots, banner, music, gap))
        written.append(path)
    return ExtractedSong(tuple(written), gap)
