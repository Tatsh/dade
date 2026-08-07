from __future__ import annotations

from typing import TYPE_CHECKING
import io
import json
import math

from destin.common.exceptions import InvalidFormatError
from destin.harmonix import midi
import mido  # type: ignore[import-untyped]
import pytest

if TYPE_CHECKING:
    from pathlib import Path


def _smf() -> bytes:
    midi_file = mido.MidiFile(type=1, ticks_per_beat=480)
    track = mido.MidiTrack()
    track.append(mido.MetaMessage('track_name', name='T1 CATCH', time=0))
    track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))
    track.append(mido.Message('note_on', note=60, velocity=100, time=10))
    track.append(mido.Message('note_off', note=60, velocity=0, time=20))
    midi_file.tracks.append(track)
    midi_file.tracks.append(mido.MidiTrack())
    buffer = io.BytesIO()
    midi_file.save(file=buffer)
    return buffer.getvalue()


def test_smf_to_obj() -> None:
    obj = midi.smf_to_obj(_smf())
    assert obj['format'] == 1
    assert obj['division'] == 480
    assert obj['track_count'] == 2
    first = obj['tracks'][0]
    assert first['name'] == 'T1 CATCH'
    assert first['event_count'] == 5  # Saving appends an ``end_of_track`` meta event.
    assert [event['tick'] for event in first['events']] == [0, 0, 10, 30, 30]
    assert all('time' not in event for event in first['events'])
    assert math.isclose(first['events'][1]['bpm'], 120.0)
    assert not obj['tracks'][1]['name']


@pytest.mark.parametrize('data', [b'', b'not a midi file at all'])
def test_smf_to_obj_not_a_midi_file(data: bytes) -> None:
    with pytest.raises(InvalidFormatError, match='Not a readable Standard MIDI File'):
        midi.smf_to_obj(data)


def test_convert_writes_sidecar(tmp_path: Path) -> None:
    source = tmp_path / 'song.mid'
    source.write_bytes(_smf())
    out = midi.convert(source)
    assert out == tmp_path / 'song.mid.json'
    assert source.exists()  # The standard MIDI is kept.
    assert json.loads(out.read_text(encoding='utf-8'))['track_count'] == 2


def test_convert_returns_none_on_junk(tmp_path: Path) -> None:
    source = tmp_path / 'song.mid'
    source.write_bytes(b'nope')
    assert midi.convert(source) is None
    assert not (tmp_path / 'song.mid.json').exists()
