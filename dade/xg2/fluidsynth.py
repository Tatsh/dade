"""
Optional rendering of extracted sequences to audio through FluidSynth.

FluidSynth is not required to import this module or to run any extraction. When the binary is not
found, or no SoundFont was produced, rendering is simply skipped.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import shutil
import subprocess as sp

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('find_fluidsynth', 'render_directory')

log = logging.getLogger(__name__)

_GAIN = '0.5'


def find_fluidsynth(override: Path | None = None) -> str | None:
    """
    Locate the FluidSynth binary.

    Parameters
    ----------
    override : pathlib.Path | None
        An explicit path supplied by the caller, which is used as-is when given.

    Returns
    -------
    str | None
        The path to invoke, or ``None`` when FluidSynth is not available.
    """
    if override is not None:
        return str(override)
    return shutil.which('fluidsynth')


def render_directory(directory: Path, soundfont: Path, override: Path | None = None) -> int:
    """
    Render every MIDI file in a directory to WAV alongside itself.

    Parameters
    ----------
    directory : pathlib.Path
        Directory holding the ``.mid`` files.
    soundfont : pathlib.Path
        SoundFont to play them through.
    override : pathlib.Path | None
        Explicit path to the FluidSynth binary.

    Returns
    -------
    int
        The number of files rendered.
    """
    binary = find_fluidsynth(override)
    if binary is None or not soundfont.exists() or not directory.is_dir():
        log.debug('Skipping rendering: FluidSynth or the SoundFont is unavailable.')
        return 0
    rendered = 0
    for midi in sorted(directory.glob('*.mid')):
        wav = midi.with_suffix('.wav')
        try:
            sp.run([binary, '-ni', '-g', _GAIN, '-F',
                    str(wav), str(soundfont),
                    str(midi)],
                   check=True,
                   stdout=sp.DEVNULL,
                   stderr=sp.DEVNULL)
        except (OSError, sp.CalledProcessError):
            log.warning('FluidSynth failed to render `%s`.', midi.name)
            continue
        if wav.exists():
            rendered += 1
    return rendered
