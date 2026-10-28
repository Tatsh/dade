"""
Extraction of every asset of the Boss Rally disc, the Windows release of Top Gear Rally.

The cars and the tracks of the disc are the structures of the cartridge with their pointers already
relocated, and they are read by the same code. The disc adds Windows bitmaps, programs with their
resources, its images and archive, and the music as CD audio.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import logging
import re
import shutil
import struct
import subprocess as sp

from PIL import Image

from dade.common.disc import as_directory

from .model import (
    is_car,
    is_part_model,
    is_track,
    paint_car,
    read_car,
    read_part_model,
    read_track,
    stream_track_textures,
)
from .output import write_model, write_png, write_sky
from .pe import save_icons, write_resources

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('CueTrack', 'decode_img', 'extract_disc', 'parse_cue', 'read_pod')

log = logging.getLogger(__name__)

_CAR_OFFSET = 0x8000
_CAR_MAGIC = b'RCar'
_POD_MAGIC = b'POD'
_POD_HEADER = struct.Struct('<4siii')
_POD_ENTRY = struct.Struct('<iIBB2x64s')
_IMG_HEADER = 12
_SECTOR = 2352
_FRAMES_PER_SECOND = 75
_FILE = re.compile(r'^\s*FILE\s+"?(.+?)"?\s+\S+\s*$', re.IGNORECASE)
_TRACK = re.compile(r'^\s*TRACK\s+(\d+)\s+(\S+)', re.IGNORECASE)
_INDEX = re.compile(r'^\s*INDEX\s+(\d+)\s+(\d+):(\d+):(\d+)', re.IGNORECASE)
_PROGRAMS = frozenset({'.dll', '.exe'})


class CueTrack(NamedTuple):
    """An audio track of a cue sheet."""

    number: int
    """The track number."""
    file: Path
    """The image file the track is in."""
    start: int
    """Byte offset of ``INDEX 01`` in the file."""
    end: int
    """Byte offset where the track ends, at the next track in the file or at the end of the file."""


def parse_cue(cue: Path) -> list[CueTrack]:
    """
    List the audio tracks of a cue sheet.

    Parameters
    ----------
    cue : Path
        The cue sheet.

    Returns
    -------
    list[CueTrack]
        The audio tracks, in order.
    """
    found: list[tuple[int, bool, Path, int]] = []
    current: Path | None = None
    track: tuple[int, bool] | None = None
    for line in cue.read_text(encoding='latin-1').splitlines():
        if match := _FILE.match(line):
            current = cue.parent / match.group(1)
        elif match := _TRACK.match(line):
            track = (int(match.group(1)), match.group(2).upper() == 'AUDIO')
        elif (match := _INDEX.match(line)) and track and current and int(match.group(1)) == 1:
            minutes, seconds, frames = (int(match.group(n)) for n in (2, 3, 4))
            sector = (minutes * 60 + seconds) * _FRAMES_PER_SECOND + frames
            found.append((*track, current, sector * _SECTOR))
    tracks = []
    for index, (number, audio, file, start) in enumerate(found):
        following = [s for _, _, f, s in found[index + 1:] if f == file]
        end = following[0] if following else file.stat().st_size
        if audio:
            tracks.append(CueTrack(number, file, start, end))
    return tracks


def _rip(cue: Path, out: Path, ffmpeg_path: Path) -> int:
    tracks = parse_cue(cue)
    for track in tracks:
        with track.file.open('rb') as f:
            f.seek(track.start)
            pcm = f.read(track.end - track.start)
        destination = out / 'music' / f'track{track.number:02d}.flac'
        destination.parent.mkdir(parents=True, exist_ok=True)
        sp.run((str(ffmpeg_path), '-hide_banner', '-loglevel', 'error', '-y', '-f', 's16le', '-ar',
                '44100', '-ac', '2', '-i', 'pipe:0', str(destination)),
               check=True,
               input=pcm)
        log.info('Wrote `%s`.', destination)
    return len(tracks)


def decode_img(data: bytes) -> tuple[int, int, bytes]:
    """
    Decode a ``.img`` image of the disc, such as the splash screen.

    The file is the width and the height as 32-bit little-endian numbers, a word the game skips, and
    then the pixels as 16-bit little-endian values with alpha in the top bit and five bits each of
    red, green, and blue below it.

    Parameters
    ----------
    data : bytes
        The file.

    Returns
    -------
    tuple[int, int, bytes]
        The width, the height, and the pixels as RGBA.
    """
    width, height = struct.unpack_from('<ii', data)
    values = struct.unpack_from(f'<{width * height}H', data, _IMG_HEADER)
    return width, height, b''.join(
        bytes((((v >> 10) & 0x1F) * 255 // 31, ((v >> 5) & 0x1F) * 255 // 31,
               (v & 0x1F) * 255 // 31, 255 if v & 0x8000 else 0)) for v in values)


def read_pod(data: bytes) -> dict[str, bytes]:
    """
    Read the entries of a POD archive.

    Parameters
    ----------
    data : bytes
        The archive.

    Returns
    -------
    dict[str, bytes]
        Each entry by its name.
    """
    signature, _, count, directory = _POD_HEADER.unpack_from(data)
    if signature[:3] != _POD_MAGIC:
        return {}
    entries = {}
    for index in range(count):
        offset, size, _, _, name = _POD_ENTRY.unpack_from(data, directory + index * _POD_ENTRY.size)
        entries[name.split(b'\0', 1)[0].decode('latin-1')] = data[offset:offset + size]
    return entries


def _convert(path: Path, relative: Path, out: Path) -> str:
    destination = out / relative
    data = path.read_bytes()
    suffix = path.suffix.lower()
    match suffix:
        case '.ico':
            save_icons(data, destination.with_suffix(''))
            return 'images'
        case '.bmp':
            image = Image.open(path)
            write = destination.with_suffix('.png')
            write.parent.mkdir(parents=True, exist_ok=True)
            image.convert('RGBA').save(write)
            return 'images'
        case '.rca' if data[:4] == _CAR_MAGIC and is_car(data[_CAR_OFFSET:]):
            memory = paint_car(data[_CAR_OFFSET:])
            write_model(destination.with_suffix('.glb'), memory, read_car(memory))
            return 'cars'
        case '.trk' if is_track(data[:(size := int.from_bytes(data[:4], 'big'))]):
            memory = stream_track_textures(data[:size], data[size:])
            parts = read_track(memory)
            write_model(destination.with_suffix('.glb'), memory,
                        [part for part in parts if part.name != 'sky'])
            if sky := [part for part in parts if part.name == 'sky']:
                write_model(destination.with_name(f'{destination.stem}-sky.glb'), memory, sky)
            return 'tracks'
        case '.ci4' if (palette := path.with_suffix('.lut4')).is_file():
            write_sky(destination.with_suffix('.png'), palette.read_bytes(), data)
            return 'images'
        case '.lut4' if path.with_suffix('.ci4').is_file():
            return 'images'
        case '.img':
            width, height, rgba = decode_img(data)
            write_png(destination.with_suffix('.png'), width, height, rgba)
            return 'images'
        case '.pod':
            for name, entry in read_pod(data).items():
                target = destination.with_suffix('') / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(entry)
                if is_part_model(entry) and (parts := read_part_model(entry)):
                    write_model(target.with_suffix('.glb'), entry, parts)
            return 'other'
        case _:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            if suffix in _PROGRAMS and write_resources(
                    data, destination.with_name(f'{destination.name}.resources')):
                return 'programs'
            return 'other'


def extract_disc(source: Path, out: Path, ffmpeg_path: Path | None = None) -> dict[str, int]:
    """
    Convert every file of the disc, and its CD audio.

    Cars and tracks become GLB with their textures beside them as PNG; bitmaps, icons, the images
    of the disc, and the skies become PNG; the resources of each program are written beside it;
    and every other file is copied. The CD audio becomes FLAC when the source is a cue sheet.

    Parameters
    ----------
    source : Path
        A directory of the disc or of an installation, an ISO image, or the cue sheet or the
        ``.bin`` of a cue/bin pair.
    out : Path
        Output directory.
    ffmpeg_path : Path | None
        The ``ffmpeg`` binary to encode the CD audio with, or :py:obj:`None` to skip the audio.

    Returns
    -------
    dict[str, int]
        The number of files of each kind written.

    Raises
    ------
    InvalidFormatError
        If the source is a file that is not a readable disc image.
    """  # ruff: ignore[docstring-extraneous-exception]
    counts = dict.fromkeys(('cars', 'tracks', 'images', 'programs', 'other', 'music'), 0)
    cue = source if source.suffix.lower() == '.cue' else source.with_suffix('.cue')
    if ffmpeg_path is not None and source.is_file() and cue.is_file():
        counts['music'] = _rip(cue, out, ffmpeg_path)
    with as_directory(source) as root:
        for path in sorted(p for p in root.rglob('*') if p.is_file()):
            counts[_convert(path, path.relative_to(root), out)] += 1
    log.info('Wrote %s.', ', '.join(f'{v} {k}' for k, v in counts.items()))
    return counts
