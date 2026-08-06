"""
Extreme-G Standard MIDI conversion.

The generic SMF and XG rewriting machinery lives in :py:mod:`destin.common.smf`; only
:py:data:`GM_DRUM_MAP`, the game's own drum-key mapping, is specific to Extreme-G. It is re-exported
here alongside the shared helpers so callers can import everything from one module.
"""
from __future__ import annotations

from destin.common.smf import (
    DRUM_CHANNEL,
    read_vlq,
    remap_channel,
    split_tracks,
    to_xg,
    used_channels,
    write_vlq,
)

__all__ = ('DRUM_CHANNEL', 'GM_DRUM_MAP', 'read_vlq', 'remap_channel', 'split_tracks', 'to_xg',
           'used_channels', 'write_vlq')

GM_DRUM_MAP = {
    36: 38,  # Snare: mid and high body, no lows.
    38: 42,  # Closed hi-hat: 94% high band, 100ms.
    39: 49,  # Crash cymbal: 2.2s, bright.
    40: 46,  # Open hi-hat.
    42: 42,  # Closed hi-hat: 37ms.
    43: 36,  # Bass drum: all energy below 400Hz, tonal, the most used.
    44: 46,  # Open hi-hat.
    45: 46,  # Open hi-hat.
    46: 46,  # Open hi-hat.
    48: 42,  # Closed hi-hat, the workhorse.
    50: 51,  # Ride cymbal: very bright, 807ms.
    52: 45,  # Low tom.
    53: 39,  # Hand clap: mid-body click.
    54: 41,  # Low floor tom: 84% low band.
    55: 57,  # Crash cymbal 2.
    56: 47,  # Low-mid tom.
    57: 37,  # Side stick: short mid click.
    58: 55,  # Splash cymbal: long swelling tail.
    62: 49,  # Crash cymbal.
    64: 48,  # Hi-mid tom.
    65: 50,  # High tom.
    67: 51  # Ride, outside the in-game kit; the nearest useful equivalent.
}
"""Game drum key to General MIDI percussion note.

These identities were judged from the acoustic character of the samples rather than read from the
game, so treat them as a starting point and audition the extracted drums before relying on them.

:meta hide-value:
"""
