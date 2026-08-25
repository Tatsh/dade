"""
End-to-end unpacking pipeline.

Detects the platform of an extracted disc root, then -- entirely in place, within
that directory -- extracts the ``BIGF`` archives, unpacks the RefPack ``.rpk``
packs, and converts audio, textures, meshes and structured resources next to their
source files. Asset conversion is fanned out across processes.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from typing import TYPE_CHECKING, NamedTuple
import logging

from dade.common.workers import default_jobs

from . import audio, bigfile, images, meshes, packs, structured
from .detect import detect

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from .detect import DiscInfo

__all__ = ('StepStats', 'run')

log = logging.getLogger(__name__)

# Extension to converter, gathered from each decoder module's declared support.
_CONVERTERS: dict[str, Callable[[Path], object]] = {
    ext: module.convert
    for module in (images, meshes, structured)
    for ext in module.EXTENSIONS
}
_ASSET_GROUPS: tuple[tuple[str, frozenset[str]], ...] = (
    ('textures', frozenset(images.EXTENSIONS)),
    ('meshes', frozenset(meshes.EXTENSIONS)),
    ('structured', frozenset(structured.EXTENSIONS)),
)


class StepStats(NamedTuple):
    """Success and failure counts for one pipeline step."""

    ok: int
    """Number of items processed successfully."""
    fail: int
    """Number of items that raised an error."""


def _convert_asset(path: Path) -> tuple[Path, bool, str]:
    try:
        _CONVERTERS[path.suffix.lower()](path)
    # A converter may raise anything; the batch must continue past one asset's decode failure,
    # so the error is captured and returned to the caller rather than propagated.
    except Exception as e:  # noqa: BLE001
        return path, False, f'{type(e).__name__}: {e}'
    return path, True, ''


def _extract_pack(path: Path) -> tuple[Path, bool, str]:
    try:
        packs.extract(path)
    # Extraction may raise anything; the batch must continue past one pack's failure, so the
    # error is captured and returned to the caller rather than propagated.
    except Exception as e:  # noqa: BLE001
        return path, False, f'{type(e).__name__}: {e}'
    return path, True, ''


def _pool_map(fn: Callable[[Path], tuple[Path, bool, str]], items: Sequence[Path],
              workers: int) -> StepStats:
    if not items:
        return StepStats(0, 0)
    ok = 0
    fails: list[tuple[Path, str]] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for path, good, msg in pool.map(fn, items):
            if good:
                ok += 1
            else:
                fails.append((path, msg))
    for path, msg in fails[:10]:
        log.warning('Failed `%s`: %s', path, msg)
    return StepStats(ok, len(fails))


def _extract_bigs(info: DiscInfo, *, no_movies: bool) -> StepStats:
    extracted = 0
    for big in info.bigs:
        if no_movies and 'movie' in big.stem.lower():
            log.info('Skipping movie archive `%s`.', big.name)
            continue
        n, written = bigfile.unpack(big, big.parent)
        log.info('Extracted `%s`: %d entries, %d bytes.', big.name, n, written)
        extracted += 1
    return StepStats(extracted, 0)


def _convert_audio(root: Path, workers: int) -> StepStats:
    sources = sorted(p for p in root.rglob('*') if p.suffix.lower() in audio.EXTENSIONS)
    jobs = [job for src in sources for job in audio.jobs_for(src)]
    if not jobs:
        return StepStats(0, 0)
    ok = 0
    fails: list[tuple[Path, str]] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for out, good, msg in pool.map(audio.run_job, jobs):
            if good:
                ok += 1
            else:
                fails.append((out, msg))
    for out, msg in fails[:10]:
        log.warning('Audio stream failed `%s`: %s', out, msg)
    log.info('Audio: %d/%d streams from %d file(s).', ok, len(jobs), len(sources))
    return StepStats(ok, len(fails))


def run(root: Path, *, no_movies: bool = False, workers: int | None = None) -> dict[str, StepStats]:
    """
    Unpack and convert an extracted disc root in place.

    Parameters
    ----------
    root : pathlib.Path
        The extracted disc root (must be the root of the extracted ISO).
    no_movies : bool
        Skip extracting the (large) movie archives.
    workers : int | None
        Process-pool size; defaults to the CPU count.

    Returns
    -------
    dict[str, StepStats]
        Per-step success/failure counts keyed by step name. Propagates
        :py:class:`ValueError` from :py:func:`.detect.detect` when the platform
        cannot be determined.
    """
    n_workers = workers or default_jobs()
    info = detect(root)
    log.info('Detected %s (binary `%s`); %d archive(s).', info.platform,
             info.binary.name if info.binary else None, len(info.bigs))
    stats = {'archives': _extract_bigs(info, no_movies=no_movies)}
    rpks = sorted(p for p in root.rglob('*.rpk') if p.is_file())
    stats['packs'] = _pool_map(_extract_pack, rpks, n_workers)
    log.info('Packs: %d/%d unpacked.', stats['packs'].ok, len(rpks))
    stats['audio'] = _convert_audio(root, n_workers)
    for name, exts in _ASSET_GROUPS:
        found = sorted(p for p in root.rglob('*') if p.suffix.lower() in exts and p.is_file())
        stats[name] = _pool_map(_convert_asset, found, n_workers)
        log.info('%s: %d/%d converted.', name.capitalize(), stats[name].ok, len(found))
    return stats
