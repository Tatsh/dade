"""Extract assets from an already unpacked Mario Kart World NUP directory."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import fnmatch
import logging
import struct
import subprocess as sp

import zstandard

from dade.common.tools import locate_tool

from .model import decode_model, model_lod_count
from .texture import decode_texture, texture_count, texture_name

__all__ = ('extract',)

log = logging.getLogger(__name__)

_BARS_HEADER_SIZE = 16
_BARS_MISSING_ASSET = 0xFFFFFFFF
_STREAM_DIR = Path('Sound/Resource/Stream')


def _romfs(source: Path) -> Path:
    candidates = (source, source / 'romfs')
    for candidate in candidates:
        if (candidate / 'Model').is_dir() and (candidate / 'Tex').is_dir():
            return candidate
    matches = sorted(source.glob('updates/*/romfs'))
    for candidate in reversed(matches):
        if (candidate / 'Model').is_dir() and (candidate / 'Tex').is_dir():
            return candidate
    message = f'No Mario Kart World romfs directory found under {source}.'
    raise ValueError(message)


def _read_data(source: Path) -> bytes:
    if source.suffix != '.zs':
        return source.read_bytes()
    with source.open('rb') as input_file, BytesIO() as output_file:
        zstandard.ZstdDecompressor().copy_stream(input_file, output_file)
        return output_file.getvalue()


def _write_textures(data: bytes, output: Path, relative: Path, *, force: bool) -> int:
    count = texture_count(data)
    for index in range(count):
        if count == 1:
            png = output / 'textures' / relative.with_suffix('.png')
        else:
            name = texture_name(data, index).replace('/', '_').replace('\\', '_')
            directory = relative.with_suffix('')
            png = output / 'textures' / directory / f'{index:05d}-{name}.png'
        png.parent.mkdir(parents=True, exist_ok=True)
        if force or not png.exists():
            png.write_bytes(decode_texture(data, index))
    return count


def _write_model(data: bytes, name: str, destination: Path, textures: Path,
                 external_images: Path | None, *, force: bool) -> int:
    count = 0
    for lod in range(model_lod_count(data)):
        target = (destination if lod == 0 else
                  destination.with_name(f'{destination.stem}.lod{lod}{destination.suffix}'))
        if target.exists() and not force:
            count += 1
            continue
        if (model := decode_model(data, name, textures, lod=lod,
                                  external_images=external_images)) is not None:
            target.write_bytes(model)
            count += 1
    return count


def _write_bars(data: bytes, output: Path, relative: Path, *, force: bool) -> tuple[int, int]:
    if data[:4] != b'BARS' or len(data) < _BARS_HEADER_SIZE:
        message = 'Invalid BARS header.'
        raise ValueError(message)
    count = struct.unpack_from('<I', data, 12)[0]
    table_end = _BARS_HEADER_SIZE + 12 * count
    if table_end > len(data):
        message = 'Invalid BARS asset table.'
        raise ValueError(message)
    offsets = [
        struct.unpack_from('<I', data, 16 + 4 * count + 8 * index + 4)[0] for index in range(count)
    ]
    ordered = sorted(offset for offset in offsets if offset != _BARS_MISSING_ASSET)
    if any(offset < table_end or offset + 4 > len(data) for offset in ordered):
        message = 'Invalid BARS asset offset.'
        raise ValueError(message)
    ends = dict(zip(ordered, (*ordered[1:], len(data)), strict=True))
    written = 0
    unsupported = 0
    with TemporaryDirectory(prefix='.mkw-', dir=output) as temporary_dir:
        bwav = Path(temporary_dir) / 'asset.bwav'
        for index, offset in enumerate(offsets):
            if offset == _BARS_MISSING_ASSET:
                continue
            if data[offset:offset + 4] != b'BWAV':
                unsupported += 1
                continue
            directory = relative.with_suffix('')
            wav = output / 'audio' / directory / f'{index:05d}.wav'
            wav.parent.mkdir(parents=True, exist_ok=True)
            if force or not wav.exists():
                bwav.write_bytes(data[offset:ends[offset]])
                try:
                    sp.run((str(locate_tool('vgmstream-cli')), '-i', '-o', str(wav), str(bwav)),
                           capture_output=True,
                           check=True)
                except sp.CalledProcessError:
                    wav.unlink(missing_ok=True)
                    unsupported += 1
                    continue
            written += 1
    return written, unsupported


def _write_audio(source: Path, output: Path, relative: Path, *, force: bool) -> None:
    wav = output / 'audio' / relative.with_suffix('.wav')
    if relative.parent == _STREAM_DIR and relative.stem.startswith('BGM_'):
        song = output / 'soundtrack' / f'{relative.stem}.flac'
        song.parent.mkdir(parents=True, exist_ok=True)
        if force or not song.exists():
            with TemporaryDirectory(prefix='.mkw-', dir=output) as temporary_dir:
                work = Path(temporary_dir)
                source_wav = wav if wav.exists() and not force else work / 'song.wav'
                if source_wav != wav:
                    audio_source = source
                    if source.suffix == '.zs':
                        audio_source = work / relative.name
                        audio_source.write_bytes(_read_data(source))
                    sp.run((str(locate_tool('vgmstream-cli')), '-i', '-o', str(source_wav),
                            str(audio_source)),
                           capture_output=True,
                           check=True)
                temporary_flac = work / 'song.flac'
                sp.run((str(locate_tool('ffmpeg')), '-y', '-nostdin', '-loglevel', 'error', '-i',
                        str(source_wav), '-c:a', 'flac', '-compression_level', '8',
                        str(temporary_flac)),
                       capture_output=True,
                       check=True)
                temporary_flac.replace(song)
        (output / 'soundtrack' / f'{relative.stem}.wav').unlink(missing_ok=True)
        wav.unlink(missing_ok=True)
        return
    wav.parent.mkdir(parents=True, exist_ok=True)
    if not force and wav.exists():
        return
    if source.suffix == '.zs':
        with TemporaryDirectory(prefix='.mkw-', dir=output) as temporary_dir:
            audio_source = Path(temporary_dir) / relative.name
            audio_source.write_bytes(_read_data(source))
            sp.run((str(locate_tool('vgmstream-cli')), '-i', '-o', str(wav), str(audio_source)),
                   capture_output=True,
                   check=True)
    else:
        sp.run((str(locate_tool('vgmstream-cli')), '-i', '-o', str(wav), str(source)),
               capture_output=True,
               check=True)


def extract(source: Path,
            output: Path,
            limit: int | None = None,
            pattern: str = '*',
            *,
            force: bool = False) -> dict[str, int]:
    """
    Convert an extracted NUP directory into portable files.

    Parameters
    ----------
    source : Path
        Extracted NUP directory or its romfs directory.
    output : Path
        Destination directory.
    limit : int | None
        Maximum number of files to inspect, for a small verification run.
    pattern : str
        Glob pattern matched against paths relative to romfs.
    force : bool
        Replace converted files already in the output directory.

    Returns
    -------
    dict[str, int]
        Counts of files written by type.
    """
    romfs = _romfs(source)
    counts = {'audio': 0, 'textures': 0, 'models': 0, 'unsupported': 0}
    supported = {'.bwav', '.bfstm', '.bfwav', '.bntx', '.bfres', '.bars'}
    paths = (path for path in romfs.rglob('*')
             if path.is_file() and fnmatch.fnmatch(str(path.relative_to(romfs)), pattern) and (
                 path.with_suffix('') if path.suffix == '.zs' else path).suffix in supported)
    output.mkdir(parents=True, exist_ok=True)
    for index, path in enumerate(sorted(paths)):
        if limit is not None and index >= limit:
            break
        relative = path.relative_to(romfs)
        decoded_relative = relative.with_suffix('') if path.suffix == '.zs' else relative
        if decoded_relative.suffix in {'.bwav', '.bfstm', '.bfwav'}:
            _write_audio(path, output, decoded_relative, force=force)
            counts['audio'] += 1
        elif decoded_relative.suffix == '.bntx':
            try:
                counts['textures'] += _write_textures(_read_data(path),
                                                      output,
                                                      decoded_relative,
                                                      force=force)
            except ValueError as error:
                log.warning('Cannot decode %s: %s.', path, error)
                counts['unsupported'] += 1
        elif decoded_relative.suffix == '.bfres':
            glb = output / 'models' / decoded_relative.with_suffix('.glb')
            glb.parent.mkdir(parents=True, exist_ok=True)
            try:
                external_images = (output / 'textures' /
                                   'Tex' if decoded_relative.name.startswith('Piece_') else None)
                counts['models'] += _write_model(_read_data(path),
                                                 decoded_relative.stem,
                                                 glb,
                                                 romfs / 'Tex',
                                                 external_images,
                                                 force=force)
            except (ValueError, IndexError, struct.error) as error:
                log.warning('Cannot decode %s: %s.', path, error)
                counts['unsupported'] += 1
        else:
            try:
                audio, unsupported = _write_bars(_read_data(path),
                                                 output,
                                                 decoded_relative,
                                                 force=force)
                counts['audio'] += audio
                counts['unsupported'] += unsupported
            except (ValueError, struct.error) as error:
                log.warning('Cannot decode %s: %s.', path, error)
                counts['unsupported'] += 1
    log.info('Converted Mario Kart World assets: %s.', counts)
    return counts
