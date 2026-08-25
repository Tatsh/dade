"""
End-to-end unpacking pipeline.

The source is an ``.ipa`` or an already-extracted directory. Either way the application bundle is
found, mirrored into the output directory, and every file converted to something that opens outside
iOS: Apple-optimised PNGs are de-optimised, ``.tex`` textures are deciphered and de-optimised,
``.caf`` sound effects are rewrapped as WAV, ``.jbt`` tune packages and the marker ZIPs are unpacked
into directories named after themselves and their entries decoded in turn, property lists and
localisation tables and Core Data models become JSON, and the executable's properties are written
out as JSON beside it. Anything with no converter is copied unchanged, so the output is a complete
bundle rather than a selection.

The source is never written to. Conversion is fanned out across processes, because the bundle holds
a couple of thousand PNGs and each one is a separate ``pngdefry`` invocation.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from typing import TYPE_CHECKING, Final, NamedTuple
import logging
import plistlib
import shutil
import zipfile

from dade.common.json import write_json
from dade.common.workers import default_jobs
from dade.misc.coredata import convert as convert_coredata
from dade.misc.macho import read_macho
from dade.misc.sc_info import read_bundles, sc_info_to_json
from dade.misc.strings import read_strings

from .archives import unpack_jbt, unpack_zip
from .audio import caf_to_wav
from .images import decipher_image, write_defried_png
from .plists import read_plist

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

__all__ = ('MACHO_MAGICS', 'StepStats', 'find_bundle', 'unpack')

MACHO_MAGICS: Final = (b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf', b'\xce\xfa\xed\xfe',
                       b'\xcf\xfa\xed\xfe')
"""Leading bytes of a Mach-O image, universal or little-endian thin.

:meta hide-value:
"""

log = logging.getLogger(__name__)

_COREDATA_SUFFIXES = frozenset({'.cdm', '.mom'})
_PLIST_SUFFIXES = frozenset({'.plist', '.xcent'})
_MACHO_PROPERTIES_SUFFIX = '.macho.json'
_FAILURES_LOGGED = 10


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


# Unpack an .ipa and return the Payload directory inside it.
def _extract_ipa(archive: Path, destination: Path) -> Path:
    with zipfile.ZipFile(archive) as zipped:
        zipped.extractall(destination)
    payload = destination / 'Payload'
    if not payload.is_dir():
        msg = f'No Payload directory inside `{archive}`.'
        raise ValueError(msg)
    return payload


def find_bundle(root: Path) -> Path:
    """
    Find the application bundle within an extracted download.

    Parameters
    ----------
    root : pathlib.Path
        The ``.app`` bundle itself, the ``Payload`` directory holding it, or a directory holding
        ``Payload``.

    Returns
    -------
    pathlib.Path
        The ``.app`` bundle.

    Raises
    ------
    ValueError
        If no ``.app`` bundle can be found at or below *root*.
    """
    if root.suffix == '.app':
        return root
    for candidate in (root / 'Payload', root):
        if candidate.is_dir() and (apps := sorted(candidate.glob('*.app'))):
            return apps[0]
    msg = f'No .app bundle at or below `{root}`.'
    raise ValueError(msg)


# Every bundle's own executable, as its Info.plist names it.
def _executables(bundle: Path) -> set[Path]:
    found = set()
    for info_plist in (bundle, *(p for p in bundle.rglob('*') if p.is_dir())):
        plist = info_plist / 'Info.plist'
        if not plist.is_file():
            continue
        try:
            with plist.open('rb') as fileobj:
                name = plistlib.load(fileobj).get('CFBundleExecutable')
        except (OSError, plistlib.InvalidFileException, ValueError):
            continue
        if name and (executable := info_plist / str(name)).is_file():
            found.add(executable)
    return found


def _is_macho(path: Path) -> bool:
    with path.open('rb') as fileobj:
        return fileobj.read(4) in MACHO_MAGICS


def _action_for(source: Path, executables: set[Path]) -> str:
    suffix = source.suffix.lower()
    if source in executables or (not suffix and source.is_file() and _is_macho(source)):
        return 'macho'
    if suffix == '.tex':
        return 'tex'
    if suffix == '.png':
        return 'png'
    if suffix == '.caf':
        return 'caf'
    if suffix == '.jbt':
        return 'jbt'
    if suffix == '.zip':
        return 'zip'
    if suffix == '.strings':
        return 'strings'
    if suffix in _COREDATA_SUFFIXES:
        return 'coredata'
    if suffix in _PLIST_SUFFIXES:
        return 'plist'
    return 'copy'


def _destination_for(action: str, source: Path, out_dir: Path) -> Path:
    if action in {'tex', 'png'}:
        return out_dir / f'{source.stem}.png'
    if action == 'caf':
        return out_dir / f'{source.stem}.wav'
    if action in {'coredata', 'plist', 'strings'}:
        return out_dir / f'{source.name}.json'
    if action == 'macho':
        return out_dir / f'{source.name}{_MACHO_PROPERTIES_SUFFIX}'
    if action in {'jbt', 'zip'}:
        return out_dir / source.stem
    return out_dir / source.name


def _plan(bundle: Path, out_root: Path, pngdefry: Path | None,
          ffmpeg: Path | None) -> Iterator[_Job]:
    executables = _executables(bundle)
    for source in sorted(bundle.rglob('*')):
        if not source.is_file():
            continue
        out_dir = out_root / source.parent.relative_to(bundle)
        action = _action_for(source, executables)
        yield _Job(action=action,
                   destination=_destination_for(action, source, out_dir),
                   ffmpeg=ffmpeg,
                   pngdefry=pngdefry,
                   source=source)


def _run_job(job: _Job) -> tuple[Path, bool, str]:
    job.destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        _apply(job)
    # A converter may raise anything; one bad asset must not stop the other two thousand, so the
    # error is captured and returned to the caller rather than propagated.
    except Exception as e:  # noqa: BLE001
        return job.source, False, f'{type(e).__name__}: {e}'
    return job.source, True, ''


def _apply(job: _Job) -> None:
    source, destination = job.source, job.destination
    match job.action:
        case 'tex':
            destination.write_bytes(decipher_image(source.read_bytes()))
            if job.pngdefry is not None:
                write_defried_png(destination, destination, job.pngdefry)
        case 'png':
            if job.pngdefry is None:
                shutil.copy2(source, destination)
            else:
                write_defried_png(source, destination, job.pngdefry)
        case 'caf':
            if job.ffmpeg is None:
                shutil.copy2(source, destination.with_suffix('.caf'))
            else:
                caf_to_wav(source, destination, job.ffmpeg)
        case 'jbt':
            unpack_jbt(source, destination, job.pngdefry)
        case 'zip':
            unpack_zip(source, destination, job.pngdefry)
        case 'strings':
            write_json(destination, read_strings(source), ensure_ascii=False, sort_keys=True)
        case 'coredata':
            write_json(destination, convert_coredata(source), ensure_ascii=False, sort_keys=True)
        case 'plist':
            write_json(destination, read_plist(source), ensure_ascii=False, sort_keys=True)
        case 'macho':
            write_json(destination, read_macho(source), ensure_ascii=False, sort_keys=True)
        case _:
            shutil.copy2(source, destination)


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


# Describe the download's FairPlay bookkeeping, when it still carries any.
def _write_sc_info(bundle: Path, out_root: Path) -> StepStats:
    try:
        infos = [info for info in read_bundles(bundle) if info.records]
    except (OSError, ValueError) as e:
        # A repacked bundle has no SC_Info at all, which is not an error; there is simply nothing
        # to describe.
        log.info('No SC_Info to describe: %s', e)
        return StepStats(0, 0)
    if not infos:
        # A decrypted dump keeps the directory but empties it, which leaves nothing worth writing.
        log.info('SC_Info holds no records; no report written.')
        return StepStats(0, 0)
    write_json(out_root / 'SC_Info.json', [sc_info_to_json(info) for info in infos],
               ensure_ascii=False,
               sort_keys=True)
    return StepStats(0, 1)


def unpack(source: Path,
           output_dir: Path,
           *,
           ffmpeg: Path | None = None,
           pngdefry: Path | None = None,
           workers: int | None = None) -> dict[str, StepStats]:
    """
    Unpack and convert a jubeat plus download.

    Parameters
    ----------
    source : pathlib.Path
        An ``.ipa``, the ``.app`` bundle, the ``Payload`` directory, or a directory holding
        ``Payload``. It is only ever read.
    output_dir : pathlib.Path
        Where to write. The bundle is mirrored into a directory named after it.
    ffmpeg : pathlib.Path | None
        The ``ffmpeg`` binary. Without it the ``.caf`` sound effects are copied unconverted.
    pngdefry : pathlib.Path | None
        The ``pngdefry`` binary. Without it the PNGs are written still Apple-optimised.
    workers : int | None
        Process-pool size; defaults to the CPU count.

    Returns
    -------
    dict[str, StepStats]
        Per-action success and failure counts, keyed by action name. A source holding no
        application bundle raises :py:class:`ValueError`.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    if source.is_file() and zipfile.is_zipfile(source):
        staging = output_dir / f'.{source.stem}.ipa-staging'
        shutil.rmtree(staging, ignore_errors=True)
        log.info('Unpacking `%s`.', source.name)
        root = _extract_ipa(source, staging)
    else:
        staging = None
        root = source
    try:
        bundle = find_bundle(root)
        out_root = output_dir / bundle.name
        log.info('Converting `%s` into `%s`.', bundle.name, out_root)
        jobs = list(_plan(bundle, out_root, pngdefry, ffmpeg))
        log.info('%d file(s) to process.', len(jobs))
        stats = _run_jobs(jobs, workers or default_jobs())
        out_root.mkdir(parents=True, exist_ok=True)
        if (sc_info := _write_sc_info(bundle, out_root)).ok:
            stats['sc_info'] = sc_info
        return dict(sorted(stats.items()))
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
