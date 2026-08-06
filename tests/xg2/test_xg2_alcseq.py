"""Tests for :mod:`destin.xg2.alcseq`."""
from __future__ import annotations

import struct

from destin.xg2.alcseq import DEFAULT_DIVISION, CSeqReader, decode_track, to_midi
from destin.xg2.smf import split_tracks


def test_reader_reads_plain_bytes() -> None:
    reader = CSeqReader(b'\x01\x02\x03', 0)
    assert [reader.byte() for _ in range(3)] == [1, 2, 3]


def test_reader_treats_doubled_block_code_as_a_literal() -> None:
    assert CSeqReader(b'\xfe\xfe', 0).byte() == 0xFE


def test_reader_replays_a_back_reference() -> None:
    # Four literals, then a block replaying two bytes from four back.
    data = bytes([0x41, 0x42, 0x43, 0x44, 0xFE, 0x00, 0x04, 0x02])
    reader = CSeqReader(data, 0)
    first = [reader.byte() for _ in range(4)]
    assert first == [0x41, 0x42, 0x43, 0x44]
    assert [reader.byte() for _ in range(2)] == [0x41, 0x42]


def test_reader_vlq_single_byte() -> None:
    assert CSeqReader(b'\x40', 0).vlq() == 0x40


def test_reader_vlq_multi_byte() -> None:
    assert CSeqReader(b'\x81\x00', 0).vlq() == 128


def test_decode_track_yields_events(alcseq_blob: bytes) -> None:
    events = decode_track(alcseq_blob, 0x44)
    kinds = [kind for _, kind, _ in events]
    assert kinds == ['N', 'M', 'T', 'M']


def test_decode_track_note_carries_its_duration(alcseq_blob: bytes) -> None:
    tick, kind, payload = decode_track(alcseq_blob, 0x44)[0]
    assert (tick, kind) == (0, 'N')
    assert payload == (0x90, 60, 100, 0x40)


def test_decode_track_tempo_payload(alcseq_blob: bytes) -> None:
    tempo = next(p[0] for _, kind, p in decode_track(alcseq_blob, 0x44) if kind == 'T')
    assert tempo == 0x07A120


def test_decode_track_stops_at_end_of_track(alcseq_blob: bytes) -> None:
    assert len(decode_track(alcseq_blob, 0x44)) == 4


def test_to_midi_produces_one_track(alcseq_blob: bytes) -> None:
    midi, tracks = to_midi(alcseq_blob)
    assert tracks == 1
    assert midi[:4] == b'MThd'
    assert split_tracks(midi)[0] == 384


def test_to_midi_expands_a_note_into_on_and_off(alcseq_blob: bytes) -> None:
    body = split_tracks(to_midi(alcseq_blob)[0])[1][0]
    assert bytes([0x90, 60, 100]) in body
    assert bytes([0x80, 60, 0]) in body


def test_to_midi_falls_back_to_the_default_division() -> None:
    header = bytearray(0x44)
    struct.pack_into('>I', header, 0, 0x44)
    struct.pack_into('>I', header, 0x40, 0xFFFFFFFF)
    blob = bytes(header) + bytes([0x00, 0xFF, 0x2F])
    assert split_tracks(to_midi(blob)[0])[0] == DEFAULT_DIVISION


def test_to_midi_skips_tracks_with_no_offset() -> None:
    header = bytearray(0x44)
    struct.pack_into('>I', header, 0x40, 384)
    assert to_midi(bytes(header) + bytes([0x00, 0xFF, 0x2F]))[1] == 0


def test_to_midi_handles_a_program_change(alcseq_blob: bytes) -> None:
    assert bytes([0xC0, 3]) in split_tracks(to_midi(alcseq_blob)[0])[1][0]
