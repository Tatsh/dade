"""Typing helpers for the *REFLEC BEAT plus* reader."""
from __future__ import annotations

from typing import TypedDict

__all__ = ('ChartDict', 'ChartHeaderDict', 'NoteDict', 'SlideDict', 'TempoEventDict',
           'TuneInfoDict')


class NoteDict(TypedDict):
    """One note as it is stored in an RBFF chart."""

    spawn_time: int
    """When the note appears, in milliseconds. A chart starts before its audio, so this is often
    negative."""
    travel_time: int
    """How long the note takes to reach the player, in milliseconds."""
    hit_time: int
    """When the note must be hit: :py:attr:`spawn_time` plus :py:attr:`travel_time`. Notes are
    stored in this order, and two notes sharing it are simultaneous."""
    id: int
    """The note identifier, which another note's chain fields refer to."""
    start_time: int
    """
    The chain the note belongs to, or ``-1`` when the note is free.

    The reconstruction names this field for a time, but it holds neither one: it is a group
    number that climbs through the chart, and every note sharing it with the same side is one
    chain the player takes in succession. A free note belongs to no chain.
    """
    kind: int
    """
    The note's place in its chain, counting from zero.

    A chain's places run ``0`` to ``n-1`` with no gaps, so this also gives the chain's length.
    """
    side: int
    """The play side the note belongs to, ``0`` or ``1``. The two sides are separate sets."""
    hold_kind: int
    """``1`` marks a hold's head, which the engine calls ``kHoldKindHead``."""
    type: int
    """
    The note type.

    ``1`` is a hold, whose length is the first target coordinate. ``2`` is a slide, which the
    engine remaps to ``3`` on load; no chart in the shipped packages carries one.
    """
    target: tuple[int, int, int, int]
    """
    The four target coordinates.

    The first is a hold's length in milliseconds, and is zero on every note that is not one. The
    second selects an alternative target: ``0`` for none, ``1`` or ``2`` for the two the game
    draws green. The last two are always zero here.
    """
    flags: int
    """The note flag bits. See :py:data:`dade.rbplus.chart.NOTE_FLAGS`."""
    path_points: tuple[int, ...]
    """The note's path-point coordinates, empty when it carries no path."""
    chain: tuple[int, int, int, int] | None
    """The chain block a long-note head carries, or ``None``."""


class TempoEventDict(TypedDict):
    """One tempo or speed-change event."""

    kind: int
    """The event kind. Kind ``3`` is a speed change."""
    time: int
    """The event's time, in milliseconds."""
    speed: int
    """The scroll speed the event installs, meaningful for kind ``3``."""
    raw: str
    """The whole thirty-six byte event as hexadecimal, since most of it is undocumented."""


class SlideDict(TypedDict):
    """One slide record."""

    note_index: int
    """The index of the note the slide belongs to."""
    field2: int
    """The record's second short, whose meaning is not established."""
    lane: int
    """The remapped target lane, or a negative marker for the three sentinel values."""
    value_a: int
    """The record's first trailing integer."""
    value_b: int
    """The record's second trailing integer."""


class ChartHeaderDict(TypedDict):
    """An RBFF chart's header."""

    version: int
    """The chart format version. Versions 10 to 14 use the modern layout, 6 and 7 a legacy one."""
    initial_speed: int
    """The scroll speed the chart starts at."""
    end_time: int
    """The chart's end time, in milliseconds."""
    seed: int
    """The chart's seed value."""
    note_count: int
    """How many notes the chart holds."""
    tempo_event_count: int
    """How many tempo events follow the notes."""
    free_note_count: int
    """How many of the notes are free notes."""
    slide_record_count: int
    """How many slide records follow the tempo events."""


class ChartDict(TypedDict):
    """A whole parsed RBFF chart."""

    header: ChartHeaderDict
    """The chart header."""
    notes: list[NoteDict]
    """Every note, in stream order."""
    tempo_events: list[TempoEventDict]
    """Every tempo event, in stream order."""
    slides: list[SlideDict]
    """Every slide record, in stream order."""


class TuneInfoDict(TypedDict, total=False):
    """The tune metadata an ``info`` entry carries. Every key is optional."""

    ID: int
    """The tune identifier, which matches the package's file name."""
    MusicName: str
    """The display title."""
    MusicNameHira: str
    """The hiragana reading of the title."""
    MusicNameRoman: str
    """The romanised title."""
    ArtistName: str
    """The artist name."""
    ArtistNameHira: str
    """The hiragana reading of the artist name."""
    ArtistNameRoman: str
    """The romanised artist name."""
    Basic: int
    """The basic chart's level."""
    Medium: int
    """The medium chart's level."""
    Hard: int
    """The hard chart's level."""
    BpmMin: int
    """The lowest tempo in the tune, in beats per minute."""
    BpmMax: int
    """The highest tempo in the tune, in beats per minute."""
    Version: int
    """The metadata's own version."""
