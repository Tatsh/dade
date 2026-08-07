"""Run the CPU-bound conversion phases across a process pool for a multi-core speedup."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any
import logging
import logging.handlers
import multiprocessing

from destin.common import ps2_icon
from typing_extensions import override

from . import audio, bitmap, dataarray, mesh, midi, milo, movie, rndobject, video
from .typing import PoolOutcome

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path
    from queue import Queue

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
    Route a file to its content converter and run it (a process-pool task).

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
    Decompose a single Milo ``.rnd`` archive (a process-pool task).

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
    Split one sample bank into per-sample WAVs (a process-pool task).

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
    Convert one disc ``.str`` song to a WAV at the given destination (a process-pool task).

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


class _ReinjectHandler(logging.Handler):
    """Re-emit a worker process's log records into this process's logging."""
    @override
    def emit(self, record: logging.LogRecord) -> None:
        """
        Dispatch a worker record to this process's handlers for ``record.name``.

        Parameters
        ----------
        record : logging.LogRecord
            The record forwarded from a worker process.
        """
        logging.getLogger(record.name).handle(record)


def _init_worker(log_queue: Queue[Any]) -> None:
    root = logging.getLogger()
    root.handlers = [logging.handlers.QueueHandler(log_queue)]
    root.setLevel(logging.DEBUG)


def _run_sequential(func: Callable[[Any], Path | None], work: list[Any], *, ignore_failures: bool,
                    label: str) -> PoolOutcome:
    succeeded = failed = 0
    for item in work:
        try:
            result = func(item)
        except Exception:
            if not ignore_failures:
                log.exception('Failed to %s `%s`.', label, item)
                raise
            failed += 1
            log.warning('Failed to %s `%s` (ignored).', label, item, exc_info=True)
            continue
        if result is not None:
            succeeded += 1
    return PoolOutcome(succeeded, failed)


def run_pool(func: Callable[[Any], Path | None], items: Iterable[Any], *, jobs: int,
             ignore_failures: bool, label: str) -> PoolOutcome:
    """
    Run ``func`` over ``items`` across a process pool and tally the outcomes.

    With ``jobs <= 1`` (or a single item) the work runs sequentially in-process, which keeps the
    full per-converter debug logging and simplifies debugging. Otherwise the items run on a
    :class:`~concurrent.futures.ProcessPoolExecutor`; worker log records are forwarded to this
    process through a queue so ``-d`` still shows per-file detail. A failure stops the pool unless
    ``ignore_failures`` is set, in which case it is logged and skipped.

    Parameters
    ----------
    func : collections.abc.Callable[[typing.Any], pathlib.Path | None]
        The picklable, module-level task to run on each item.
    items : collections.abc.Iterable[typing.Any]
        The work items (each passed to ``func``).
    jobs : int
        Maximum worker processes; ``1`` runs sequentially.
    ignore_failures : bool
        Log and skip a failing item instead of raising.
    label : str
        Short verb phrase for log messages (e.g. ``'convert'``).

    Returns
    -------
    PoolOutcome
        The success and failure counts.
    """
    work = list(items)
    if jobs <= 1 or len(work) <= 1:
        return _run_sequential(func, work, ignore_failures=ignore_failures, label=label)
    succeeded = failed = 0
    with multiprocessing.Manager() as manager:
        log_queue = manager.Queue()
        listener = logging.handlers.QueueListener(log_queue, _ReinjectHandler())
        listener.start()
        executor = ProcessPoolExecutor(max_workers=jobs,
                                       initializer=_init_worker,
                                       initargs=(log_queue,))
        try:
            futures = {executor.submit(func, item): item for item in work}
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception:
                    if not ignore_failures:
                        executor.shutdown(cancel_futures=True, wait=False)
                        log.exception('Failed to %s `%s`.', label, futures[future])
                        raise
                    failed += 1
                    log.warning('Failed to %s `%s` (ignored).',
                                label,
                                futures[future],
                                exc_info=True)
                    continue
                if result is not None:
                    succeeded += 1
        finally:
            executor.shutdown(wait=True)
            listener.stop()
    return PoolOutcome(succeeded, failed)
