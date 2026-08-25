"""
Estimate where a chart's beat 0 sits inside its MP3.

An SSQ tempo map says beat 0 happens at time 0, but the MP3 shipped beside it does not start
there. Every file carries the encoder's own delay, about 1105 samples or 25 ms for LAME, and some
carry real silence and a musical introduction on top. StepMania decodes all of it, so a simfile
written with ``#OFFSET:0`` starts its notes too early.

The estimate has two parts. The **phase**, the offset within one beat that best matches an energy
flux onset envelope, is objective; across the songs checked it lands between 0.021 s and 0.046 s,
straddling the encoder delay, which is the expected answer because the music itself starts on the
beat and only the encoder pushed it late. The **whole number of measures** is a judgement call,
and the conservative one is made here: beat 0 goes on the first measure boundary at or after the
audio becomes audible, and is then walked back a measure at a time until the chart's last note
falls inside the audio, because a chart cannot outlast its music. That second rule is a fact and
overrides the first.

On one hand-authored reference the result was 5.354 s against 5.339 s, a 15 ms difference, but
this remains a heuristic: a song whose introduction runs an odd number of measures needs the
caller to supply the gap instead.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import array
import logging
import math
import subprocess as sp

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('DEFAULT_SAMPLE_RATE', 'beat_phase', 'estimate_gap', 'first_audible')

log = logging.getLogger(__name__)

DEFAULT_SAMPLE_RATE = 44100
"""Rate to analyse at.

Decoding lower is faster but throws away the cymbal and snare transients that make onsets sharp,
which moves the phase estimate by tens of milliseconds.

:meta hide-value:
"""

_FRAME_SECONDS = 0.01
_AUDIBLE_DBFS = -60.0
_FULL_SCALE = 32768.0
_PHASE_STEP = 0.001
_DECODE_TIMEOUT = 300


def _decode_mono(ffmpeg: Path, path: Path, sample_rate: int) -> array.array[int] | None:
    """
    Decode an audio file to mono 16-bit samples.

    Parameters
    ----------
    ffmpeg : pathlib.Path
        The ``ffmpeg`` binary.
    path : pathlib.Path
        The audio file.
    sample_rate : int
        The rate to resample to.

    Returns
    -------
    array.array[int] | None
        The samples, or ``None`` if ``ffmpeg`` failed.
    """
    try:
        done = sp.run((str(ffmpeg), '-v', 'error', '-i', str(path), '-ac', '1', '-ar',
                       str(sample_rate), '-f', 's16le', '-'),
                      capture_output=True,
                      check=True,
                      timeout=_DECODE_TIMEOUT)
    except (OSError, sp.SubprocessError):
        log.exception('Failed to decode `%s`.', path)
        return None
    samples: array.array[int] = array.array('h')
    samples.frombytes(done.stdout[:len(done.stdout) // 2 * 2])
    return samples


def first_audible(samples: array.array[int], sample_rate: int = DEFAULT_SAMPLE_RATE) -> float:
    """
    Find when the audio first rises above the audibility threshold.

    Parameters
    ----------
    samples : array.array[int]
        Mono samples.
    sample_rate : int
        Their sample rate.

    Returns
    -------
    float
        The time in seconds, or 0.0 when the file is audible immediately.
    """
    threshold = _FULL_SCALE * 10 ** (_AUDIBLE_DBFS / 20)
    return next(
        (index / sample_rate for index, value in enumerate(samples) if abs(value) > threshold), 0.0)


def _flux(samples: array.array[int], sample_rate: int) -> tuple[list[float], float]:
    """
    Build a half-wave-rectified energy difference envelope.

    Parameters
    ----------
    samples : array.array[int]
        Mono samples.
    sample_rate : int
        Their sample rate.

    Returns
    -------
    tuple[list[float], float]
        The envelope and the seconds each entry covers.
    """
    hop = max(1, int(sample_rate * _FRAME_SECONDS))
    energy = [
        math.sqrt(sum(value * value for value in samples[index * hop:(index + 1) * hop]) / hop)
        for index in range(len(samples) // hop)
    ]
    if not energy:
        return [], hop / sample_rate
    return ([0.0] +
            [max(0.0, energy[index] - energy[index - 1])
             for index in range(1, len(energy))], hop / sample_rate)


def beat_phase(samples: array.array[int],
               bpm: float,
               sample_rate: int = DEFAULT_SAMPLE_RATE) -> float:
    """
    Find the offset within one beat that best matches the audio's onsets.

    Parameters
    ----------
    samples : array.array[int]
        Mono samples.
    bpm : float
        The chart's tempo.
    sample_rate : int
        Their sample rate.

    Returns
    -------
    float
        A phase in ``[0, 60 / bpm)`` seconds.
    """
    if bpm <= 0:
        return 0.0
    flux, frame_seconds = _flux(samples, sample_rate)
    if not flux:
        return 0.0
    beat = 60.0 / bpm
    best_score, best_phase = -1.0, 0.0
    for step in range(max(1, int(beat / _PHASE_STEP))):
        phase = step * _PHASE_STEP
        score = sum(
            flux[frame]
            for frame in (round((phase + index * beat) / frame_seconds)
                          for index in range(int((len(flux) * frame_seconds - phase) / beat) + 1))
            if frame < len(flux))
        if score > best_score:
            best_score, best_phase = score, phase
    return best_phase


def estimate_gap(ffmpeg: Path,
                 path: Path,
                 bpm: float,
                 beats_per_measure: int = 4,
                 chart_end: float = 0.0,
                 sample_rate: int = DEFAULT_SAMPLE_RATE) -> float | None:
    """
    Estimate the seconds from the start of the audio to the chart's beat 0.

    Parameters
    ----------
    ffmpeg : pathlib.Path
        The ``ffmpeg`` binary.
    path : pathlib.Path
        The audio file.
    bpm : float
        The chart's tempo.
    beats_per_measure : int
        How many beats a measure holds.
    chart_end : float
        Seconds from beat 0 to the last note of any chart. Zero disables the rule that keeps the
        chart inside the audio.
    sample_rate : int
        The rate to analyse at.

    Returns
    -------
    float | None
        The gap in seconds, or ``None`` when the audio could not be decoded.
    """
    if bpm <= 0 or not (samples := _decode_mono(ffmpeg, path, sample_rate)):
        return None
    audible = first_audible(samples, sample_rate)
    phase = beat_phase(samples, bpm, sample_rate)
    measure = 60.0 / bpm * beats_per_measure
    duration = len(samples) / sample_rate
    measures = max(0, math.ceil((audible - phase) / measure))
    while measures > 0 and chart_end > 0 and phase + measures * measure + chart_end > duration:
        measures -= 1
    return phase + measures * measure
