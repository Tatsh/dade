"""Typing helpers for the jubeat plus converters."""
from __future__ import annotations

from typing import Literal, TypeAlias, TypedDict

__all__ = ('ChartDict', 'ChartEventDict', 'ChartHeaderDict', 'Difficulty')

Difficulty: TypeAlias = Literal['basic', 'advanced', 'extreme']
"""The three difficulties a tune package carries a chart for."""


class ChartEventDict(TypedDict):
    """One decoded chart event."""

    bpm: float | None
    """Beats per minute, for a tempo event only."""
    hold_length_sectors: int | None
    """The hold's length in sectors, for a hold event only."""
    kind: str
    """Event kind name: ``tap``, ``end``, ``measure``, ``beat``, ``tempo``, or ``hold``."""
    kind_id: int
    """The raw event-kind byte."""
    microseconds_per_beat: int | None
    """Microseconds per beat, for a tempo event only."""
    move: int | None
    """The hold arrow's direction, for a hold event only."""
    panel: int | None
    """The playfield panel index (``0`` to ``15``), for a tap or hold event only."""
    sector: int
    """The event's timing position, in sectors."""
    time: float
    """The event's timing position, in seconds."""
    value: int
    """The event's raw second word, whatever its kind."""


class ChartHeaderDict(TypedDict):
    """A chart's decoded 96-byte header."""

    end_sector: int
    """The chart's final sector."""
    end_time: float
    """The chart's final sector, in seconds."""
    event_count: int
    """The number of event records that follow the header."""
    first_marker: int
    """A panel bitmask naming the panels the first marker occupies."""
    first_marker_sector: int
    """The sector at which the first marker appears."""
    first_marker_time: float
    """The sector at which the first marker appears, in seconds."""
    magic: str
    """The four-byte magic: ``IJBQ``, ``IJSQ``, or ``JBSQ``."""
    music_bar: str
    """The 60-byte music-bar bitmap, hex-encoded."""
    note_count: int
    """The number of scoring notes the header claims."""
    reserved: str
    """The twelve header bytes at ``0x18`` that are zero in every known chart, hex-encoded."""
    unknown_0x10: int
    """The unnamed 16-bit field at ``0x10``, which the engine never reads."""


class ChartDict(TypedDict):
    """A whole decoded chart."""

    counts: dict[str, int]
    """How many events there are of each kind, keyed by kind name."""
    difficulty: Difficulty | None
    """The difficulty the chart was read as, when it came from a named archive entry."""
    events: list[ChartEventDict]
    """Every event, in file order."""
    header: ChartHeaderDict
    """The decoded header."""
    note_count: int
    """The number of scoring notes actually present, which the engine trusts over the header."""
    sectors_per_second: int
    """The sector rate every time in this document is derived with."""
