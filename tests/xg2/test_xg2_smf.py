"""Tests for :mod:`destin.xg2.smf`."""
from __future__ import annotations

import struct

from destin.xg2.smf import (
    DRUM_CHANNEL,
    GM_DRUM_MAP,
    read_vlq,
    remap_channel,
    split_tracks,
    to_xg,
    used_channels,
    write_vlq,
)
import pytest


@pytest.mark.parametrize('value', [0, 1, 127, 128, 300, 8192, 100000, 0x0FFFFFFF])
def test_vlq_round_trip(value: int) -> None:
    encoded = write_vlq(value)
    assert read_vlq(encoded, 0) == (value, len(encoded))


@pytest.mark.parametrize(('value', 'expected'), [(0, b'\x00'), (127, b'\x7f'), (128, b'\x81\x00'),
                                                 (0x2000, b'\xc0\x00'),
                                                 (0x100000, b'\xc0\x80\x00')])
def test_write_vlq_encoding(value: int, expected: bytes) -> None:
    assert write_vlq(value) == expected


def test_split_tracks(midi_file: bytes) -> None:
    division, tracks = split_tracks(midi_file)
    assert division == 384
    assert len(tracks) == 1
    assert tracks[0].endswith(bytes([0xFF, 0x2F, 0]))


def test_split_tracks_rejects_other_data() -> None:
    with pytest.raises(ValueError, match='Not a standard MIDI file'):
        split_tracks(b'RIFF' + b'\x00' * 32)


def test_used_channels(midi_file: bytes) -> None:
    assert used_channels(midi_file) == {0, DRUM_CHANNEL}


def test_to_xg_prepends_a_setup_track(midi_file: bytes) -> None:
    converted = to_xg(midi_file)
    division, tracks = split_tracks(converted)
    assert division == 384
    assert len(tracks) == 2
    assert bytes([0xF0, 8, 0x43, 0x10, 0x4C]) in tracks[0]
    assert tracks[1] == split_tracks(midi_file)[1][0]


def test_to_xg_arms_the_drum_channel(midi_file: bytes) -> None:
    setup = split_tracks(to_xg(midi_file))[1][0]
    assert bytes([0xB0 | DRUM_CHANNEL, 0x00, 127]) in setup
    assert bytes([0xC0 | DRUM_CHANNEL, 0]) in setup


def test_to_xg_selects_the_drum_program(midi_file: bytes) -> None:
    setup = split_tracks(to_xg(midi_file, drum_program=8))[1][0]
    assert bytes([0xC0 | DRUM_CHANNEL, 8]) in setup


def test_to_xg_generic_remaps_drum_notes(midi_file: bytes) -> None:
    body = split_tracks(to_xg(midi_file, drum_map=GM_DRUM_MAP))[1][1]
    assert bytes([0x90 | DRUM_CHANNEL, GM_DRUM_MAP[36], 90]) in body
    assert bytes([0x90 | DRUM_CHANNEL, 36, 90]) not in body


def test_to_xg_generic_leaves_melodic_notes_alone(midi_file: bytes) -> None:
    body = split_tracks(to_xg(midi_file, drum_map=GM_DRUM_MAP))[1][1]
    assert bytes([0x90, 43, 100]) in body


def test_to_xg_rejects_other_data() -> None:
    with pytest.raises(ValueError, match='Not a standard MIDI file'):
        to_xg(b'nope' + b'\x00' * 32)


def test_remap_channel_moves_voice_messages(midi_file: bytes) -> None:
    remapped = remap_channel(midi_file, DRUM_CHANNEL, 12)
    assert used_channels(remapped) == {0, 12}


def test_remap_channel_preserves_length(midi_file: bytes) -> None:
    assert len(remap_channel(midi_file, DRUM_CHANNEL, 12)) == len(midi_file)


def test_remap_channel_leaves_meta_events_alone(midi_file: bytes) -> None:
    body = split_tracks(remap_channel(midi_file, DRUM_CHANNEL, 12))[1][0]
    assert bytes([0xFF, 0x51, 3, 0x07, 0xA1, 0x20]) in body


def test_rewrite_preserves_running_status() -> None:
    track = bytearray()
    track += bytes([0x00, 0x90, 60, 100])
    track += bytes([0x10, 62, 100])  # Running status.
    track += bytes([0x00, 0xFF, 0x2F, 0])
    midi = (b'MThd' + struct.pack('>IHHH', 6, 1, 1, 96) + b'MTrk' + struct.pack('>I', len(track)) +
            bytes(track))
    assert split_tracks(remap_channel(midi, 5, 6))[1][0] == bytes(track)


def test_rewrite_handles_sysex() -> None:
    track = bytearray()
    track += bytes([0x00, 0xF0, 3, 0x7E, 0x7F, 0xF7])
    track += bytes([0x00, 0x90, 60, 100])
    track += bytes([0x00, 0xFF, 0x2F, 0])
    midi = (b'MThd' + struct.pack('>IHHH', 6, 1, 1, 96) + b'MTrk' + struct.pack('>I', len(track)) +
            bytes(track))
    assert split_tracks(remap_channel(midi, 3, 4))[1][0] == bytes(track)


def test_rewrite_rejects_an_unhandled_status() -> None:
    track = bytes([0x00, 0xF1, 0x00, 0x00, 0xFF, 0x2F, 0])
    midi = (b'MThd' + struct.pack('>IHHH', 6, 1, 1, 96) + b'MTrk' + struct.pack('>I', len(track)) +
            track)
    with pytest.raises(ValueError, match='Unhandled MIDI status'):
        remap_channel(midi, 0, 1)


def test_gm_drum_map_targets_valid_notes() -> None:
    assert all(0 <= key <= 127 and 0 <= value <= 127 for key, value in GM_DRUM_MAP.items())
