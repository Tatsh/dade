"""
Extraction of an In The Groove PS2 disc into a StepMania data tree.

The game mounts every pack under ``PCKS`` over one file system, and a path stored by more than one
pack stores the same bytes in each. The union is written in StepMania's data layout (``Songs``,
``Courses``, ``Themes``, ``NoteSkins``, and the rest), under a directory identifying the release.

Most files are already in StepMania's formats and are copied. The rest are converted:

- An ``.av`` stream is written as a WAV of its PCM and, when it has video, its MPEG-1 video in an
  MPEG program stream. Neither is re-encoded.
- A simfile is rewritten to play from those files (see :py:mod:`dade.itgps2.simfile`).
- A ``.orig`` file is the arcade original of a file the PS2 build reduced. An image is written under
  the name without ``.orig``, and the reduced copies of it (a palette BMP, or a PNG with a
  resolution hint such as ``(640x480)``) are omitted. A simfile retains ``.orig``, and the PS2
  simfile is the one written as ``.sm``.

A song's preview stream (``X (sample).av``) is written under ``Samples``, the song's path less its
``Songs`` directory. StepMania plays a preview from the song's music and does not read the preview
streams. The memory card icons are written as GLB, glTF, and PNG (see
:py:mod:`dade.common.ps2_icon`). The engine's ``Cache`` directory is omitted.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, NamedTuple
import collections
import logging
import re
import subprocess as sp
import wave
import zlib

from dade.common.exceptions import InvalidFormatError
from dade.common.io import MmapReader
from dade.common.iso9660 import ISO9660Image
from dade.common.ps2_icon import read_ps2_icon, write_ps2_icon

from .av import read_av
from .pck import PCKEntry, read_directory, read_entry
from .simfile import rewrite_simfile

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from dade.common.io import Reader

__all__ = ('RELEASES', 'extract_disc')

log = logging.getLogger(__name__)

RELEASES = {'SLUS_000.00': 'itg2-beta', 'SLUS_211.77': 'itg'}
"""The directory each release is written to, by the name of its executable.

:meta hide-value:
"""

_EXECUTABLE = re.compile(r'^S[CL][EKPU][ADMS]_\d{3}\.\d{2}$', re.IGNORECASE)
_RESOLUTION_HINT = re.compile(r' \(\d+x\d+\)$')
_REDUCED_SUFFIXES = frozenset({'.bmp', '.png'})
_SKIPPED = frozenset({'cache'})
_SAMPLE = ' (sample)'
_ICON_SUFFIXES = frozenset({'.icn', '.ico'})
_SAMPLES = 'Samples'


class _File(NamedTuple):
    reader: Reader
    base: int
    entry: PCKEntry


def _packs(source: Path, stack: ExitStack) -> tuple[str, list[tuple[Reader, int, int]]]:
    if source.is_dir():
        files = [path for path in source.rglob('*') if path.is_file()]
        executable = next((path.name for path in files if _EXECUTABLE.match(path.name)), None)
        packs: list[tuple[Reader, int, int]] = []
        for path in sorted(path for path in files if path.suffix.upper() == '.PCK'):
            reader = stack.enter_context(MmapReader(path))
            packs.append((reader, 0, reader.size))
        return executable or source.name, packs
    image = ISO9660Image(stack.enter_context(MmapReader(source)))
    reader = stack.enter_context(MmapReader(source))
    names = [name for name, _ in image.iter_files()]
    executable = next(
        (PurePosixPath(name).name for name in names
         if '/' not in name.strip('/') and _EXECUTABLE.match(PurePosixPath(name).name)), None)
    return executable or source.stem, [(reader, *image.locate(name)) for name in sorted(names)
                                       if PurePosixPath(name).suffix.upper() == '.PCK']


def _union(packs: list[tuple[Reader, int, int]]) -> dict[str, _File]:
    files: dict[str, _File] = {}
    for reader, base, size in packs:
        try:
            name, entries = read_directory(reader, base, size)
        except InvalidFormatError:
            continue
        log.debug('Pack `%s` stores %d files.', name, len(entries))
        for entry in entries:
            files.setdefault(entry.path.lstrip('/'), _File(reader, base, entry))
    return files


def _has_video(file: _File) -> bool:
    head = file.reader.read(file.base + file.entry.offset, min(file.entry.size, 4096))
    if file.entry.compressed:
        head = zlib.decompressobj(-15).decompress(head, 4)
    return head[:1] == b'\x01'


def _reduced(path: str, paths: Mapping[str, object]) -> bool:
    pure = PurePosixPath(path)
    if pure.suffix.lower() not in _REDUCED_SUFFIXES:
        return False
    stem = _RESOLUTION_HINT.sub('', pure.stem)
    return str(pure.with_name(f'{stem}.png.orig')) in paths


def _ffmpeg(executable: Path, data: bytes, destination: Path, source_format: tuple[str, ...],
            encoding: tuple[str, ...]) -> None:
    sp.run((str(executable), '-hide_banner', '-loglevel', 'error', '-y', *source_format, '-i',
            'pipe:0', *encoding, str(destination)),
           check=True,
           input=data)


def _write_av(kind: str, file: _File, destination: Path, ffmpeg: Path | None) -> str:
    stream = read_av(read_entry(file.reader, file.entry, file.base))
    header = stream.header
    if stream.audio:
        with wave.open(str(destination.with_suffix('.wav')), 'wb') as wav:
            wav.setnchannels(header.channels)
            wav.setsampwidth(2)
            wav.setframerate(header.sample_rate)
            wav.writeframes(stream.audio)
    if stream.video and ffmpeg is not None:
        _ffmpeg(ffmpeg, stream.video, destination.with_suffix('.mpg'), ('-f', 'mpegvideo'),
                ('-c', 'copy'))
        log.debug('Wrote `%s` with a %dx%d movie.', destination, header.width, header.height)
    return kind


def _plan(files: Mapping[str, _File]) -> Iterator[tuple[str, str]]:
    for path in sorted(files):
        pure = PurePosixPath(path)
        suffix = pure.suffix.lower()
        if pure.parts[0].lower() in _SKIPPED:
            yield 'skipped', path
        elif suffix == '.av' and pure.stem.endswith(_SAMPLE):
            yield 'sample', path
        elif suffix == '.av':
            yield 'av', path
        elif suffix in _ICON_SUFFIXES:
            yield 'icon', path
        elif suffix == '.sm':
            yield 'simfile', path
        elif suffix == '.orig' and path[:-5] not in files:
            yield 'original', path
        elif _reduced(path, files):
            yield 'reduced', path
        else:
            yield 'copied', path


def extract_disc(source: Path,
                 output_dir: Path,
                 ffmpeg: Path | None = None,
                 jobs: int = 1) -> tuple[str, dict[str, int]]:
    """
    Write the files of an In The Groove PS2 disc as a StepMania data tree.

    Parameters
    ----------
    source : Path
        An ISO image of the disc, or a directory of its files.
    output_dir : Path
        The directory to write under. The tree is written to a directory identifying the release.
    ffmpeg : Path | None
        The ``ffmpeg`` binary the movies are written with. :py:obj:`None` skips the movies.
    jobs : int
        The number of streams converted at once.

    Returns
    -------
    tuple[str, dict[str, int]]
        The directory the release was written to, and how many files were handled each way.

    Raises
    ------
    InvalidFormatError
        If the source has no PCK packs, or an ``.av`` stream or a compressed entry is malformed.
    subprocess.CalledProcessError
        If ``ffmpeg`` fails to write a movie.
    """  # ruff: ignore[docstring-extraneous-exception]
    counts: collections.Counter[str] = collections.Counter()
    with ExitStack() as stack:
        executable, packs = _packs(source, stack)
        if not (files := _union(packs)):
            msg = 'No PCK packs were found.'
            raise InvalidFormatError(msg)
        release = RELEASES.get(executable.upper(), executable)
        root = output_dir / release
        stems: collections.defaultdict[str, dict[str, bool]] = collections.defaultdict(dict)
        for path, file in files.items():
            if (pure := PurePosixPath(path)).suffix.lower() == '.av':
                stems[str(pure.parent)][pure.stem.lower()] = _has_video(file)
        streams = []
        for kind, path in _plan(files):
            file = files[path]
            destination = root / (path[:-5] if kind == 'original' else path)
            if kind == 'sample':
                destination = root / _SAMPLES / PurePosixPath(path).relative_to(
                    PurePosixPath(path).parts[0])
            if kind in {'skipped', 'reduced'}:
                counts[kind] += 1
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            if kind in {'av', 'sample'}:
                streams.append((kind, file, destination))
                continue
            data = read_entry(file.reader, file.entry, file.base)
            if kind == 'icon':
                try:
                    write_ps2_icon(read_ps2_icon(data), destination.with_suffix(''))
                except InvalidFormatError:
                    destination.write_bytes(data)
                    counts['copied'] += 1
                else:
                    counts[kind] += 1
                continue
            if kind == 'simfile':
                data = rewrite_simfile(data.decode('latin-1'), stems[str(
                    PurePosixPath(path).parent)]).encode('latin-1')
            destination.write_bytes(data)
            counts[kind] += 1
        if streams:
            with ThreadPoolExecutor(max_workers=jobs) as pool:
                counts.update(
                    pool.map(lambda item: _write_av(item[0], item[1], item[2], ffmpeg), streams))
    return release, dict(counts)
