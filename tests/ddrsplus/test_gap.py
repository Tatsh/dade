"""Tests for :py:mod:`destin.ddrsplus.gap`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import array

from destin.ddrsplus.gap import beat_phase, estimate_gap, first_audible
import pytest

if TYPE_CHECKING:
    from pathlib import Path


def test_first_audible_finds_the_first_loud_sample() -> None:
    samples = array.array('h', [0] * 10 + [30000] * 10)
    assert first_audible(samples, 100) == pytest.approx(0.1)


def test_first_audible_returns_zero_for_silence() -> None:
    assert first_audible(array.array('h', [0] * 50), 100) == pytest.approx(0.0)


def test_beat_phase_returns_zero_for_a_non_positive_bpm() -> None:
    samples = array.array('h', [0, 30000] * 100)
    assert beat_phase(samples, 0) == pytest.approx(0.0)
    assert beat_phase(samples, -120) == pytest.approx(0.0)


def test_beat_phase_returns_a_phase_within_one_beat() -> None:
    samples = array.array('h', ([0] * 40 + [30000] * 5) * 20)
    phase = beat_phase(samples, 120, 4410)
    assert 0.0 <= phase < 60.0 / 120


def test_beat_phase_returns_zero_when_the_audio_is_too_short_for_a_frame() -> None:
    assert beat_phase(array.array('h', [100, 200]), 120) == pytest.approx(0.0)


def test_estimate_gap_measures_from_the_audio(fake_ffmpeg: Path, tmp_path: Path) -> None:
    source = tmp_path / 'song.mp3'
    source.write_bytes(b'')
    gap = estimate_gap(fake_ffmpeg, source, 120)
    assert gap is not None
    assert gap >= 0.0


def test_estimate_gap_walks_the_chart_back_inside_the_audio(fake_ffmpeg: Path,
                                                            tmp_path: Path) -> None:
    source = tmp_path / 'song.mp3'
    source.write_bytes(b'')
    gap = estimate_gap(fake_ffmpeg, source, 1200, chart_end=1.0)
    assert gap is not None
    assert 0.0 <= gap < 60.0 / 1200


def test_estimate_gap_rejects_a_zero_bpm(fake_ffmpeg: Path, tmp_path: Path) -> None:
    assert estimate_gap(fake_ffmpeg, tmp_path / 'song.mp3', 0) is None


def test_estimate_gap_returns_none_when_ffmpeg_cannot_be_run(tmp_path: Path) -> None:
    assert estimate_gap(tmp_path / 'no-such-ffmpeg', tmp_path / 'song.mp3', 120) is None
