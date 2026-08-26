"""
A whole *REFLEC BEAT plus* download, converted in one pass.

The bundle is mirrored into the output directory: every file keeps its place, and a file with a
converter gets its converted form in the same spot. Nothing is written back to the source.

Mach-O images are the one thing not carried over at all: neither the executable nor the debug copy
under ``.dSYM`` is read, converted, or copied.

Audio is split by container. A ``.caf`` holds PCM in a wrapper little outside Apple's frameworks
reads, so it becomes a WAV. An ``.m4a`` is already portable, so it is copied rather than expanded
to several times its size.

A ``.rb`` tune package becomes a directory of its own: the metadata as JSON, every image as an
ordinary PNG, every chart both as JSON and as a rendered strip, and both audio streams as ``.m4a``.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple
import logging
import plistlib
import shutil
import tempfile
import zipfile

from dade.common.apple_png import is_apple_optimized, write_defried_png
from dade.common.audio import is_m4a, to_wav
from dade.common.json import write_json
from dade.common.workers import default_jobs
from dade.misc.coredata import convert as convert_coredata
from dade.misc.sc_info import read_bundles, sc_info_to_json
from dade.misc.strings import read_strings

from .archive import MANIFEST_ENTRY, archive_root, entry_names, open_archive, read_manifest
from .chart import ChartError, parse_chart
from .package import (
    EntryKind,
    PackageError,
    chart_difficulty,
    chart_level,
    classify_entry,
    open_package,
)
from .render import DEFAULT_SCALE, DEFAULT_SEED, DEFAULT_SPEED, render_chart_image

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ('MACHO_MAGICS', 'Action', 'StepStats', 'extract_assets', 'extract_ipa', 'find_bundle',
           'unpack')

MACHO_MAGICS = (b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf', b'\xce\xfa\xed\xfe', b'\xcf\xfa\xed\xfe')
"""Leading bytes of a Mach-O image, universal or little-endian thin.

:meta hide-value:
"""

log = logging.getLogger(__name__)

_COREDATA_SUFFIXES = frozenset({'.cdm', '.mom'})
_PLIST_SUFFIXES = frozenset({'.plist', '.xcent'})
_FAILURES_LOGGED = 10
_SC_INFO_DIR = 'SC_Info'


class Action:
    """What the pipeline does with one file."""

    AUDIO = 'audio'
    """Rewrap a ``.caf`` as a WAV."""
    COPY = 'copy'
    """Copy the file unchanged."""
    COREDATA = 'coredata'
    """Deserialise a compiled Core Data model to JSON."""
    IMAGE = 'image'
    """Write an Apple-optimised PNG as an ordinary one."""
    PACKAGE = 'package'
    """Unpack a ``.rb`` tune package into a directory."""
    PLIST = 'plist'
    """Write a property list as JSON."""
    STRINGS = 'strings'
    """Write a ``.strings`` table as JSON."""


class StepStats(NamedTuple):
    """Success and failure counts for one pipeline step."""

    fail: int
    """Number of items that raised an error."""
    ok: int
    """Number of items processed successfully."""


class _Job(NamedTuple):
    """One file's conversion, in a form a worker process can be handed."""

    action: str
    destination: Path
    ffmpeg: Path | None
    pngdefry: Path | None
    source: Path
    render: bool
    scale: float
    seed: int | None
    speed: float


def extract_ipa(archive: Path, destination: Path) -> Path:
    """
    Unpack an ``.ipa`` and return the ``Payload`` directory inside it.

    Parameters
    ----------
    archive : pathlib.Path
        The ``.ipa``.
    destination : pathlib.Path
        A directory to unpack into.

    Returns
    -------
    pathlib.Path
        The ``Payload`` directory.

    Raises
    ------
    ValueError
        If the archive holds no ``Payload`` directory.
    """
    with zipfile.ZipFile(archive) as zipped:
        zipped.extractall(destination)
    payload = destination / 'Payload'
    if not payload.is_dir():
        msg = f'No Payload directory inside `{archive}`.'
        raise ValueError(msg)
    return payload


def find_bundle(root: Path) -> Path:
    """
    Locate the ``.app`` bundle in an unpacked download.

    Parameters
    ----------
    root : pathlib.Path
        The ``.app`` bundle, the ``Payload`` directory, or a directory holding ``Payload``.

    Returns
    -------
    pathlib.Path
        The bundle.

    Raises
    ------
    ValueError
        If no bundle is found.
    """
    if root.suffix == '.app' and root.is_dir():
        return root
    for candidate in (root / 'Payload', root):
        if candidate.is_dir() and (bundles := sorted(candidate.glob('*.app'))):
            return bundles[0]
    msg = f'No .app bundle at or below `{root}`.'
    raise ValueError(msg)


def _is_macho(path: Path) -> bool:
    try:
        with path.open('rb') as handle:
            return handle.read(4) in MACHO_MAGICS
    except OSError:
        return False


def _action_for(source: Path, executables: set[Path]) -> str | None:
    # The action for one file, or None when it is not carried over at all.
    if source in executables:
        return None
    suffix = source.suffix.lower()
    match suffix:
        case '.rb':
            return Action.PACKAGE
        case '.png':
            return Action.IMAGE
        case '.caf':
            return Action.AUDIO
        case '.strings':
            return Action.STRINGS
        case _ if suffix in _PLIST_SUFFIXES:
            return Action.PLIST
        case _ if suffix in _COREDATA_SUFFIXES:
            return Action.COREDATA
        case _:
            return Action.COPY


def _destination_for(action: str, source: Path, out_dir: Path) -> Path:
    match action:
        case Action.AUDIO:
            return out_dir / f'{source.stem}.wav'
        case Action.COREDATA | Action.PLIST | Action.STRINGS:
            return out_dir / f'{source.name}.json'
        case Action.PACKAGE:
            return out_dir / source.stem
        case _:
            return out_dir / source.name


def _executables(bundle: Path) -> set[Path]:
    # Every Mach-O image in the bundle, which is the executable and its debug copy.
    return {path for path in bundle.rglob('*') if path.is_file() and _is_macho(path)}


def _convert_package(job: _Job) -> None:
    """Unpack one tune package into a directory of readable assets."""
    out = job.destination
    out.mkdir(parents=True, exist_ok=True)
    with open_package(job.source) as package:
        info = package.info()
        write_json(out / 'info.json', dict(info), ensure_ascii=False, sort_keys=True)
        for name in package.names:
            data = package.read(name)
            if name == 'info':
                continue
            if classify_entry(name) == EntryKind.CHART:
                try:
                    chart = parse_chart(data)
                except ChartError as e:
                    log.warning('`%s` chart `%s` did not parse: %s', job.source.name, name, e)
                    (out / f'{name}.bin').write_bytes(data)
                    continue
                write_json(out / f'{name}.json', chart, ensure_ascii=False, sort_keys=True)
                if job.render:
                    render_chart_image(chart,
                                       out / f'{name}.png',
                                       artist=info.get('ArtistName'),
                                       bpm=info.get('BpmMin'),
                                       difficulty=chart_difficulty(name),
                                       level=chart_level(info, name),
                                       scale=job.scale,
                                       seed=job.seed,
                                       speed=job.speed,
                                       title=info.get('MusicName'))
                continue
            if is_m4a(data):
                # Already a portable container, so it is written out rather than transcoded.
                (out / f'{name}.m4a').write_bytes(data)
                continue
            raw = out / f'{name}.png'
            raw.write_bytes(data)
            if job.pngdefry is not None and is_apple_optimized(data):
                write_defried_png(raw, raw, job.pngdefry)


def _apply(job: _Job) -> None:
    match job.action:
        case Action.PACKAGE:
            _convert_package(job)
        case Action.IMAGE:
            if job.pngdefry is None:
                shutil.copy2(job.source, job.destination)
            else:
                write_defried_png(job.source, job.destination, job.pngdefry)
        case Action.AUDIO:
            if job.ffmpeg is None:
                shutil.copy2(job.source, job.destination.with_name(job.source.name))
            else:
                to_wav(job.source, job.destination, job.ffmpeg)
        case Action.PLIST:
            with job.source.open('rb') as handle:
                write_json(job.destination,
                           plistlib.load(handle),
                           ensure_ascii=False,
                           sort_keys=True)
        case Action.STRINGS:
            write_json(job.destination,
                       read_strings(job.source),
                       ensure_ascii=False,
                       sort_keys=True)
        case Action.COREDATA:
            write_json(job.destination,
                       convert_coredata(job.source),
                       ensure_ascii=False,
                       sort_keys=True)
        case _:
            shutil.copy2(job.source, job.destination)


def _run_job(job: _Job) -> tuple[Path, bool, str]:
    job.destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        _apply(job)
    except (OSError, PackageError, ValueError, plistlib.InvalidFileException) as e:
        return job.source, False, str(e)
    return job.source, True, ''


def _plan(bundle: Path, out_root: Path, *, ffmpeg: Path | None, pngdefry: Path | None, render: bool,
          scale: float, seed: int | None, speed: float) -> list[_Job]:
    executables = _executables(bundle)
    jobs = []
    for source in sorted(bundle.rglob('*')):
        if not source.is_file() or source.parent.name == _SC_INFO_DIR:
            continue
        if (action := _action_for(source, executables)) is None:
            continue
        out_dir = out_root / source.parent.relative_to(bundle)
        jobs.append(
            _Job(action=action,
                 destination=_destination_for(action, source, out_dir),
                 ffmpeg=ffmpeg,
                 pngdefry=pngdefry,
                 render=render,
                 scale=scale,
                 seed=seed,
                 speed=speed,
                 source=source))
    return jobs


def _run_jobs(jobs: Sequence[_Job], workers: int) -> dict[str, StepStats]:
    stats: dict[str, StepStats] = {}
    fails: list[tuple[Path, str]] = []
    by_source = {job.source: job.action for job in jobs}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for source, good, message in pool.map(_run_job, jobs, chunksize=8):
            action = by_source[source]
            previous = stats.get(action, StepStats(0, 0))
            stats[action] = (StepStats(previous.fail, previous.ok +
                                       1) if good else StepStats(previous.fail + 1, previous.ok))
            if not good:
                fails.append((source, message))
    for source, message in fails[:_FAILURES_LOGGED]:
        log.warning('Failed `%s`: %s', source, message)
    if len(fails) > _FAILURES_LOGGED:
        log.warning('%d further failure(s) not listed.', len(fails) - _FAILURES_LOGGED)
    return dict(sorted(stats.items()))


def _write_sc_info(bundle: Path, out_root: Path) -> StepStats:
    try:
        infos = [info for info in read_bundles(bundle) if info.records]
    except (OSError, ValueError) as e:
        log.info('No SC_Info to describe: %s', e)
        return StepStats(0, 0)
    if not infos:
        log.info('SC_Info holds no records; no report written.')
        return StepStats(0, 0)
    write_json(out_root / 'SC_Info.json', [sc_info_to_json(info) for info in infos],
               ensure_ascii=False,
               sort_keys=True)
    return StepStats(0, 1)


class _Chunk(NamedTuple):
    """A slice of an asset archive's entries, for one worker to extract."""

    archive: Path
    names: tuple[str, ...]
    out_root: Path
    pngdefry: Path | None
    strip: str


def _extract_chunk(chunk: _Chunk) -> tuple[int, int, tuple[str, ...]]:
    # Extract one slice of an archive, opening a handle of this worker's own.
    ok = 0
    failures: list[str] = []
    with open_archive(chunk.archive) as archive:
        for name in chunk.names:
            relative = name.removeprefix(chunk.strip)
            destination = chunk.out_root / relative
            try:
                data = archive.read(name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                # Only a PNG that really carries the CgBI chunk is worth a pngdefry process; the
                # shipped archives are almost entirely ordinary PNGs.
                if chunk.pngdefry is not None and is_apple_optimized(data):
                    write_defried_png(destination, destination, chunk.pngdefry)
            except (OSError, RuntimeError, ValueError) as e:
                failures.append(f'{name}: {e}')
            else:
                ok += 1
    return ok, len(failures), tuple(failures)


def extract_assets(archive_path: Path,
                   output_dir: Path,
                   *,
                   pngdefry: Path | None = None,
                   workers: int | None = None) -> dict[str, StepStats]:
    """
    Extract one downloadable asset archive.

    Parameters
    ----------
    archive_path : pathlib.Path
        The ``iPad``, ``iPad2x``, or ``iPhone@2x`` archive. One that does not open raises
        :py:class:`dade.rbplus.archive.ArchiveError`.
    output_dir : pathlib.Path
        Where to write. The archive is mirrored into a directory named after it.
    pngdefry : pathlib.Path | None
        The ``pngdefry`` binary. Without it any Apple-optimised PNG is written as it is.
    workers : int | None
        Process-pool size; defaults to the CPU count.

    Returns
    -------
    dict[str, StepStats]
        Success and failure counts, keyed by the action name.
    """
    workers = workers or default_jobs()
    with open_archive(archive_path) as archive:
        root = archive_root(archive)
        names = [info.filename for info in entry_names(archive)]
        manifest = read_manifest(archive)
    out_root = output_dir / (root or archive_path.stem)
    out_root.mkdir(parents=True, exist_ok=True)
    if manifest:
        write_json(out_root / 'manifest.json', list(manifest), ensure_ascii=False)
    strip = f'{root}/' if root else ''
    # The manifest lives inside its own nested archive, which is written out decoded instead.
    payload = [name for name in names if name != f'{strip}{MANIFEST_ENTRY}']
    size = max(1, (len(payload) + workers - 1) // workers)
    chunks = [
        _Chunk(archive=archive_path,
               names=tuple(payload[start:start + size]),
               out_root=out_root,
               pngdefry=pngdefry,
               strip=strip) for start in range(0, len(payload), size)
    ]
    log.info('Extracting %d entries from `%s`.', len(payload), archive_path.name)
    ok = fail = 0
    failures: list[str] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for chunk_ok, chunk_fail, chunk_failures in pool.map(_extract_chunk, chunks):
            ok += chunk_ok
            fail += chunk_fail
            failures.extend(chunk_failures)
    for message in failures[:_FAILURES_LOGGED]:
        log.warning('Failed %s', message)
    if len(failures) > _FAILURES_LOGGED:
        log.warning('%d further failure(s) not listed.', len(failures) - _FAILURES_LOGGED)
    stats = {Action.IMAGE: StepStats(fail, ok)}
    if manifest:
        stats['manifest'] = StepStats(0, 1)
    return dict(sorted(stats.items()))


def unpack(source: Path,
           output_dir: Path,
           *,
           ffmpeg: Path | None = None,
           pngdefry: Path | None = None,
           render: bool = True,
           scale: float = DEFAULT_SCALE,
           seed: int | None = DEFAULT_SEED,
           speed: float = DEFAULT_SPEED,
           workers: int | None = None) -> dict[str, StepStats]:
    """
    Unpack and convert a *REFLEC BEAT plus* download.

    Parameters
    ----------
    source : pathlib.Path
        An ``.ipa``, the ``.app`` bundle, the ``Payload`` directory, or a directory holding
        ``Payload``. It is only ever read. One holding no bundle raises :py:class:`ValueError`.
    output_dir : pathlib.Path
        Where to write. The bundle is mirrored into a directory named after it.
    ffmpeg : pathlib.Path | None
        The ``ffmpeg`` binary. Without it the ``.caf`` sound effects are copied unconverted.
    pngdefry : pathlib.Path | None
        The ``pngdefry`` binary. Without it the PNGs are written still Apple-optimised.
    render : bool
        Draw a strip image for every chart alongside its JSON.
    scale : float
        How large to write those images, as a multiple of their usual size.
    seed : int | None
        Pins the lane layout those images draw. ``None`` takes a fresh one for each chart, as the
        game does on every play.
    speed : float
        The speed modifier those images draw at, from 1.0 to 2.0 as the game offers it.
    workers : int | None
        Process-pool size; defaults to the CPU count.

    Returns
    -------
    dict[str, StepStats]
        Success and failure counts for each action taken, keyed by the action name.
    """
    with tempfile.TemporaryDirectory() as staging:
        # An .ipa is unpacked to a staging directory that goes away again afterwards; the source
        # archive itself is never written to.
        root = extract_ipa(source, Path(staging)) if source.suffix.lower() == '.ipa' else source
        bundle = find_bundle(root)
        out_root = output_dir / bundle.stem
        out_root.mkdir(parents=True, exist_ok=True)
        jobs = _plan(bundle,
                     out_root,
                     ffmpeg=ffmpeg,
                     pngdefry=pngdefry,
                     render=render,
                     scale=scale,
                     seed=seed,
                     speed=speed)
        log.info('Converting %d file(s) from `%s`.', len(jobs), bundle.name)
        stats = _run_jobs(jobs, workers or default_jobs())
        if (sc_info := _write_sc_info(bundle, out_root)) != StepStats(0, 0):
            stats['sc-info'] = sc_info
    return dict(sorted(stats.items()))
