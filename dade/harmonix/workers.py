"""Run the CPU-bound conversion phases concurrently across threads for a multi-core speedup."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
import asyncio
import logging
import os

from dade.common import ps2_icon

from . import audio, bitmap, dataarray, mesh, midi, milo, movie, rndobject, video
from .typing import PoolOutcome

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

__all__ = ('convert_file', 'decompose_milo_file', 'has_converter', 'run_pool', 'split_bank_file',
           'str_to_wav_file')

log = logging.getLogger(__name__)

_CONVERTERS: dict[str, Callable[[Path], Path | None]] = {
    ext: module.convert
    for module in (bitmap, dataarray, mesh, midi, audio, ps2_icon, video, movie, rndobject)
    for ext in module.EXTENSIONS
}
# Longest extension first so multi-suffix names (e.g. ``.txt.bin``) win over ``.bin``.
_CONVERT_EXTS = tuple(sorted(_CONVERTERS, key=len, reverse=True))


def has_converter(name: str) -> bool:
    """
    Return whether a content converter handles a file with the given name.

    Parameters
    ----------
    name : str
        The file name to test.

    Returns
    -------
    bool
        ``True`` if some converter's extension matches the name.
    """
    low = name.lower()
    return any(low.endswith(ext) for ext in _CONVERT_EXTS)


def convert_file(path: Path) -> Path | None:
    """
    Route a file to its content converter and run it (a worker task).

    Parameters
    ----------
    path : pathlib.Path
        The file to convert.

    Returns
    -------
    pathlib.Path | None
        The converter's output path, or ``None`` if no converter matched the name.
    """
    low = path.name.lower()
    converter = next((_CONVERTERS[ext] for ext in _CONVERT_EXTS if low.endswith(ext)), None)
    return converter(path) if converter is not None else None


def decompose_milo_file(path: Path) -> Path | None:
    """
    Decompose a single Milo ``.rnd`` archive (a worker task).

    Parameters
    ----------
    path : pathlib.Path
        The ``.rnd`` file.

    Returns
    -------
    pathlib.Path | None
        The output directory, or ``None`` if the file was not a Milo archive.
    """
    return milo.convert(path)


def split_bank_file(path: Path) -> Path | None:
    """
    Split one sample bank into per-sample WAVs (a worker task).

    A ``.hd`` is split with its sibling ``.bd`` (FreQuency); a ``.bnk`` is split with its sibling
    ``.nse`` (Amplitude).

    Parameters
    ----------
    path : pathlib.Path
        The ``.hd`` or ``.bnk`` bank file.

    Returns
    -------
    pathlib.Path | None
        The output folder, or ``None`` if the bank could not be split.
    """
    if path.suffix.lower() == '.hd':
        return audio.split_sd_bank(path)
    return audio.split_bank(path)


def str_to_wav_file(item: tuple[Path, Path]) -> Path:
    """
    Convert one disc ``.str`` song to a WAV at the given destination (a worker task).

    Parameters
    ----------
    item : tuple[pathlib.Path, pathlib.Path]
        A ``(source, destination)`` pair.

    Returns
    -------
    pathlib.Path
        The written WAV path.
    """
    src, dst = item
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(audio.str_to_wav(src.read_bytes()))
    return dst


def _concurrency(jobs: int) -> int:
    return (os.cpu_count() or 1) if jobs <= 0 else jobs


async def run_pool(func: Callable[[Any], Path | None],
                   items: Iterable[Any],
                   *,
                   jobs: int,
                   ignore_failures: bool,
                   label: str,
                   consumed: list[Any] | None = None) -> PoolOutcome:
    """
    Run ``func`` over ``items`` concurrently and tally the outcomes.

    Each ``func(item)`` runs in a worker thread via :py:func:`asyncio.to_thread`, bounded by a
    semaphore of ``jobs`` slots (or the CPU count when ``jobs <= 0``). A failing item stops the run
    by re-raising unless ``ignore_failures`` is set, in which case it is logged and counted as a
    failure without aborting the rest.

    Parameters
    ----------
    func : collections.abc.Callable[[typing.Any], pathlib.Path | None]
        The synchronous task to run on each item (executed in a worker thread).
    items : collections.abc.Iterable[typing.Any]
        The work items (each passed to ``func``).
    jobs : int
        Maximum concurrent workers; ``0`` (or less) uses the CPU count.
    ignore_failures : bool
        Log and skip a failing item instead of raising.
    label : str
        Short verb phrase for log messages (e.g. ``'convert'``).
    consumed : list[typing.Any] | None
        If given, each item whose task produced an output at a different path (a true intermediate,
        not an in-place edit) is appended to it, so a caller can delete those inputs afterwards.

    Returns
    -------
    PoolOutcome
        The success and failure counts.
    """
    work = list(items)
    if not work:
        return PoolOutcome(0, 0)
    semaphore = asyncio.Semaphore(_concurrency(jobs))

    async def _run_one(item: Any) -> Path | None:
        async with semaphore:
            return await asyncio.to_thread(func, item)

    results = await asyncio.gather(*(_run_one(item) for item in work), return_exceptions=True)
    succeeded = failed = 0
    for item, result in zip(work, results, strict=True):
        if isinstance(result, BaseException):
            if not ignore_failures:
                log.error('Failed to %s `%s`.', label, item, exc_info=result)
                raise result
            failed += 1
            log.warning('Failed to %s `%s` (ignored).', label, item, exc_info=result)
            continue
        if result is not None:
            succeeded += 1
            if consumed is not None and result != item:
                consumed.append(item)
    return PoolOutcome(succeeded, failed)
