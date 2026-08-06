"""
Asset extraction for the Windows port of Extreme-G XG2.

The PC port uses the same asset formats as the N64 game but little-endian, which byte-reverses the
container codec tags and the 16-bit texel and palette data. The LZSS byte stream is identical, so
the same decompressor serves both.

The source tree under ``data1`` holds model containers in ``BULK/DATA``, uncompressed bike models
in ``BIKES``, level containers in ``TRACKS``, loose palettised bitmaps at the root, and ordinary
WAV sound effects in ``WAVS``. The output mirrors that layout: every container is written out
decompressed, its textures are decoded to PNG beside it, bitmaps become PNG, and the sound effects
are copied verbatim.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import shutil
import struct

from .archive import decode_entries, is_archive, parse_archive, try_sized_lzss
from .images import bmp_to_png, write_png
from .models import collect_textures

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('MODEL_SUBDIRECTORIES', 'iter_model_blobs', 'process_model', 'run')

log = logging.getLogger(__name__)

MODEL_SUBDIRECTORIES = ('BULK/DATA', 'BIKES', 'TRACKS')
"""Subdirectories of ``data1`` scanned for models and level containers.

:meta hide-value:
"""


def _decode_file(data: bytes) -> list[tuple[int, bytes]] | None:
    """
    Decode a PC file into its entries.

    Returns
    -------
    list[tuple[int, bytes]] | None
        Each entry index paired with its decoded bytes, or ``None`` when *data* is not a
        container.
    """
    if not is_archive(data, '<'):
        return None
    try:
        entries = parse_archive(data, 0, '<')
    except struct.error:
        return None
    return [(entry['index'], blob) for entry, blob in decode_entries(data, entries)]


def process_model(blob: bytes, destination: Path, name: str) -> int:
    """
    Write a decompressed model and its textures into a directory.

    Parameters
    ----------
    blob : bytes
        The decompressed model.
    destination : Path
        Directory to write into, created if missing.
    name : str
        Base name for the model file and its texture directory.

    Returns
    -------
    int
        The number of textures written.
    """
    destination.mkdir(parents=True, exist_ok=True)
    (destination / f'{name}.bin').write_bytes(blob)
    textures = collect_textures(blob, '<')
    if not textures:
        return 0
    directory = destination / name
    directory.mkdir(parents=True, exist_ok=True)
    for index, texture in enumerate(textures):
        write_png(
            directory / f'tex{index:03d}_{texture.offset:07X}_{texture.width}x'
            f'{texture.height}_{texture.pixel_format}.png', texture.width, texture.height,
            texture.rgba)
    return len(textures)


def iter_model_blobs(data1: Path) -> list[tuple[str, bytes]]:
    """
    Collect every model blob under the scanned subdirectories.

    Parameters
    ----------
    data1 : pathlib.Path
        The port's ``data1`` directory.

    Returns
    -------
    list[tuple[str, bytes]]
        A label describing where each blob came from, paired with its decompressed bytes.
    """
    out: list[tuple[str, bytes]] = []
    for subdirectory in MODEL_SUBDIRECTORIES:
        source = data1 / subdirectory
        if not source.is_dir():
            continue
        for path in sorted(source.iterdir()):
            if not path.is_file():
                continue
            data = path.read_bytes()
            entries = _decode_file(data)
            if entries is not None:
                out += [(f'{path.name}[{index}]', blob) for index, blob in entries]
            else:
                sized = try_sized_lzss(data)
                out.append((path.name, sized if sized is not None else data))
    return out


def _process_directory(data1: Path, out: Path, subdirectory: str) -> tuple[int, int, int]:
    source = data1 / subdirectory
    destination = out / subdirectory
    containers = raw = textures = 0
    if not source.is_dir():
        return containers, raw, textures
    for path in sorted(source.iterdir()):
        if not path.is_file():
            continue
        data = path.read_bytes()
        stem = path.stem
        entries = _decode_file(data)
        if entries is not None:
            containers += 1
            # A multi-entry archive gets its own directory; a single entry sits alongside.
            base = destination / stem if len(entries) > 1 else destination
            for index, blob in entries:
                name = f'{index:03d}' if len(entries) > 1 else stem
                textures += process_model(blob, base, name)
        else:
            sized = try_sized_lzss(data)
            if sized is not None:
                containers += 1
                textures += process_model(sized, destination, stem)
            else:  # A raw level container.
                raw += 1
                textures += process_model(data, destination, stem)
    return containers, raw, textures


def run(data1: Path, out: Path) -> dict[str, int]:
    """
    Extract every asset from a PC ``data1`` directory.

    Parameters
    ----------
    data1 : pathlib.Path
        The port's ``data1`` directory.
    out : pathlib.Path
        Output directory, created if missing. The source layout is mirrored into it.

    Returns
    -------
    dict[str, int]
        Counts of what was written, keyed by category.
    """
    out.mkdir(parents=True, exist_ok=True)
    counts = {'containers': 0, 'raw': 0, 'textures': 0, 'wavs': 0, 'bitmaps': 0}
    for subdirectory in MODEL_SUBDIRECTORIES:
        containers, raw, textures = _process_directory(data1, out, subdirectory)
        counts['containers'] += containers
        counts['raw'] += raw
        counts['textures'] += textures
    wav_source = data1 / 'WAVS'
    if wav_source.is_dir():
        wav_destination = out / 'WAVS'
        wav_destination.mkdir(parents=True, exist_ok=True)
        for path in sorted(wav_source.glob('*.wav')):
            shutil.copy2(path, wav_destination / path.name)
            counts['wavs'] += 1
    for path in sorted(data1.glob('*.bmp')):
        if bmp_to_png(path, out / f'{path.stem}.png'):
            counts['bitmaps'] += 1
    return counts
