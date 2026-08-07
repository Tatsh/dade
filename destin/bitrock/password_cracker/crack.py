"""
Password brute-forcer for encrypted InstallBuilder installers.

The per-candidate oracle is :py:func:`~destin.bitrock.crypto.verify_password`, which does the
minimal work needed to decide whether a password is correct. This module drives that oracle over a
keyspace,
selecting a GPU backend when one is available and falling back to pure Python otherwise.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import TYPE_CHECKING, Literal
import logging
import multiprocessing
import signal
import time

from destin.bitrock.archive import InstallBuilderFile
from destin.bitrock.crypto import verify_password
from destin.bitrock.exceptions import BitrockError, NotEncryptedError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from destin.bitrock.typing import PayloadInfo, Reader

    from .typing import ProgressCallback

    _GpuBackend = Callable[[PayloadInfo, Iterable[str | bytes], ProgressCallback | None, int],
                           bytes | None]
    """
    A GPU backend entry point.

    See :py:func:`~destin.bitrock.password_cracker.cuda.crack_cuda` and kin.
    """

__all__ = ('Backend', 'Mask', 'crack', 'iter_wordlist')

log = logging.getLogger(__name__)

Backend = Literal['auto', 'cpu', 'cuda', 'opencl']
"""Backend selector for :py:func:`crack`."""

_CPU_PROGRESS_SECONDS = 0.1
"""Report progress at most this often, in seconds, on the CPU backend."""

_worker_state: dict[str, PayloadInfo] = {}
"""Per-process payload header, seeded by :py:func:`_worker_init` in each pool worker."""


def _worker_init(info: PayloadInfo) -> None:  # pragma: no cover
    """
    Seed a pool worker with the payload header and let the parent own interruption.

    Parameters
    ----------
    info : PayloadInfo
        The parsed payload header, stored for :py:func:`_worker_verify`.
    """
    # Ignore SIGINT in workers so a Ctrl-C is handled only by the parent, which terminates the
    # pool; otherwise every worker prints its own KeyboardInterrupt traceback.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    _worker_state['info'] = info


def _worker_verify(candidate: str | bytes) -> tuple[bytes, bool]:  # pragma: no cover
    """
    Test one candidate against the worker's payload header.

    Parameters
    ----------
    candidate : str | bytes
        The candidate password.

    Returns
    -------
    tuple[bytes, bool]
        The candidate as bytes and whether it is the correct password.
    """
    password = _as_bytes(candidate)
    return password, verify_password(password, _worker_state['info']) is not None


@dataclass(frozen=True)
class Mask:
    """
    A brute-force keyspace: every string over ``charset`` from ``min_length`` to ``max_length``.

    Parameters
    ----------
    charset : bytes
        The bytes each position may take.
    min_length : int
        Shortest candidate length, inclusive.
    max_length : int
        Longest candidate length, inclusive.
    """
    charset: bytes
    """The bytes each position may take."""
    min_length: int = 1
    """Shortest candidate length, inclusive."""
    max_length: int = 16
    """Longest candidate length, inclusive."""
    def __iter__(self) -> Iterator[bytes]:
        """
        Yield every candidate in the keyspace, shortest first.

        Yields
        ------
        bytes
            Each candidate password.
        """
        for length in range(self.min_length, self.max_length + 1):
            for combination in product(self.charset, repeat=length):
                yield bytes(combination)

    def count(self) -> int:
        """
        Return the total number of candidates in the keyspace.

        This is a plain method rather than ``__len__`` because the keyspace routinely exceeds the
        integer size ``len()`` permits.

        Returns
        -------
        int
            The keyspace size.
        """
        base = len(self.charset)
        return sum(base ** length for length in range(self.min_length, self.max_length + 1))


def iter_wordlist(path: str | Path) -> Iterator[bytes]:
    """
    Yield candidate passwords from a wordlist file, one per line.

    Parameters
    ----------
    path : str | :py:class:`~pathlib.Path`
        Path to a newline-delimited wordlist.

    Yields
    ------
    bytes
        Each line with its trailing newline stripped.
    """
    with Path(path).open('rb') as handle:
        for line in handle:
            yield line.rstrip(b'\r\n')


def _as_bytes(candidate: str | bytes) -> bytes:
    """
    Encode a candidate to bytes if it is a string.

    Parameters
    ----------
    candidate : str | bytes
        The candidate password.

    Returns
    -------
    bytes
        The candidate as bytes.
    """
    return candidate.encode() if isinstance(candidate, str) else candidate


def _display(password: bytes) -> str:
    """
    Render a candidate for a log message, keeping non-text bytes readable.

    Parameters
    ----------
    password : bytes
        The candidate password.

    Returns
    -------
    str
        A printable representation.
    """
    return password.decode(errors='backslashreplace')


def _crack_cpu_serial(info: PayloadInfo, source: Mask | Iterable[str | bytes],
                      on_progress: ProgressCallback | None) -> bytes | None:
    """
    Test candidates one at a time in this process.

    Parameters
    ----------
    info : PayloadInfo
        The parsed payload header.
    source : Mask | Iterable[str | bytes]
        The keyspace or an iterable of candidates.
    on_progress : ProgressCallback | None
        Called at most every :py:data:`_CPU_PROGRESS_SECONDS` with the running count and the latest
        candidate.

    Returns
    -------
    bytes | None
        The matching password, or ``None`` if the keyspace was exhausted.
    """
    tested = 0
    last_report = time.monotonic()
    for candidate in source:
        password = _as_bytes(candidate)
        tested += 1
        now = time.monotonic()
        if on_progress is not None and now - last_report >= _CPU_PROGRESS_SECONDS:
            last_report = now
            log.debug('Tested %d candidates; latest: `%s`.', tested, _display(password))
            on_progress(tested, password)
        if verify_password(password, info) is not None:
            log.debug('Password found after %d candidates: `%s`.', tested, _display(password))
            if on_progress is not None:
                on_progress(tested, password)
            return password
    log.debug('Keyspace exhausted after %d candidates; no match.', tested)
    return None


def _crack_cpu_parallel(info: PayloadInfo, source: Mask | Iterable[str | bytes],
                        on_progress: ProgressCallback | None, jobs: int) -> bytes | None:
    """
    Test candidates across ``jobs`` worker processes, returning the first match.

    The pool is torn down as soon as a worker reports a match, so the remaining candidates in flight
    are abandoned rather than completed.

    Parameters
    ----------
    info : PayloadInfo
        The parsed payload header.
    source : Mask | Iterable[str | bytes]
        The keyspace or an iterable of candidates.
    on_progress : ProgressCallback | None
        Called at most every :py:data:`_CPU_PROGRESS_SECONDS` with the running count and the latest
        candidate.
    jobs : int
        Number of worker processes.

    Returns
    -------
    bytes | None
        The matching password, or ``None`` if the keyspace was exhausted.
    """
    tested = 0
    last_report = time.monotonic()
    pool = multiprocessing.Pool(jobs, initializer=_worker_init, initargs=(info,))
    try:
        # Poll the iterator with a timeout rather than blocking in it, so a Ctrl-C in the parent is
        # seen promptly instead of being swallowed deep inside the pool's result wait.
        results = pool.imap_unordered(_worker_verify, source)
        latest = b''
        while True:
            try:
                password, matched = results.next(_CPU_PROGRESS_SECONDS)
            except multiprocessing.TimeoutError:  # pragma: no cover
                password, matched = None, False
            except StopIteration:
                break
            if password is not None:  # pragma: no branch
                tested += 1
                latest = password
            now = time.monotonic()
            if on_progress is not None and (matched or now - last_report >= _CPU_PROGRESS_SECONDS):
                last_report = now
                on_progress(tested, latest)
            if matched:
                log.debug('Password found after %d candidates: `%s`.', tested, _display(latest))
                return latest
        log.debug('Keyspace exhausted after %d candidates; no match.', tested)
        return None
    finally:
        # Terminate and join so workers stop and their semaphores are released cleanly, whether the
        # search finished, found a match, or was interrupted.
        pool.terminate()
        pool.join()


def _crack_cpu(info: PayloadInfo,
               source: Mask | Iterable[str | bytes],
               on_progress: ProgressCallback | None = None,
               jobs: int = 1) -> bytes | None:
    """
    Test candidates against the oracle on the CPU, returning the first that verifies.

    Parameters
    ----------
    info : PayloadInfo
        The parsed payload header.
    source : Mask | Iterable[str | bytes]
        The keyspace or an iterable of candidates.
    on_progress : ProgressCallback | None
        Called at most every :py:data:`_CPU_PROGRESS_SECONDS` with the running count and the latest
        candidate.
    jobs : int
        Worker processes to use. ``1`` runs in this process; higher values fan out with
        :py:mod:`multiprocessing` for true parallelism across cores.

    Returns
    -------
    bytes | None
        The matching password, or ``None`` if the keyspace was exhausted.
    """
    log.debug('Starting CPU password search with %d job(s).', jobs)
    if jobs <= 1:
        return _crack_cpu_serial(info, source, on_progress)
    return _crack_cpu_parallel(info, source, on_progress, jobs)


def _resolve_backend(name: Backend) -> _GpuBackend:
    """
    Select the cracking backend, falling back to the CPU when a GPU is unavailable.

    Parameters
    ----------
    name : Backend
        The requested backend.

    Returns
    -------
    _GpuBackend
        The backend callable.

    Raises
    ------
    BitrockError
        If ``name`` names a GPU backend whose optional package cannot be loaded.
    """
    match name:
        case 'cpu':
            return _crack_cpu
        case 'cuda':  # pragma: no cover
            if (cuda := _load_cuda()) is None:
                msg = ('The CUDA backend requires the optional "cupy" package and an NVIDIA GPU; '
                       'install it with `pip install pybitrock[cuda]`.')
                raise BitrockError(msg)
            return cuda
        case 'opencl':  # pragma: no cover
            if (opencl := _load_opencl()) is None:
                msg = ('The OpenCL backend requires the optional "pyopencl" package and an OpenCL '
                       'device; install it with `pip install pybitrock[opencl]`.')
                raise BitrockError(msg)
            return opencl
        case _:
            # ``auto``: prefer CUDA, then OpenCL, then fall back to the CPU.
            return _load_cuda() or _load_opencl() or _crack_cpu


def _has_devices(list_devices: Callable[[], list[str]]) -> bool:  # pragma: no cover
    """
    Report whether a GPU backend has at least one usable device.

    A backend's optional package can import on a host with no working driver or platform, so
    importability alone does not mean a device can be used. Enumerating the devices surfaces a
    broken driver or missing platform, letting ``auto`` fall back to the CPU instead of dispatching
    to a device that would fail.

    Parameters
    ----------
    list_devices : collections.abc.Callable[[], list[str]]
        The backend's device enumerator.

    Returns
    -------
    bool
        Whether at least one device is present and enumeration did not raise.
    """
    try:
        return bool(list_devices())
    except Exception:  # noqa: BLE001  # A broken driver or missing platform means no usable device.
        return False


def _load_cuda() -> _GpuBackend | None:
    """
    Import the CUDA backend if its optional dependency and a usable device are present.

    Returns
    -------
    _GpuBackend | None
        The CUDA backend callable, or ``None`` when :py:mod:`cupy` cannot be imported or no usable
        CUDA device is available.
    """
    try:
        from .cuda import crack_cuda, list_devices  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        return None
    return crack_cuda if _has_devices(list_devices) else None  # pragma: no cover


def _load_opencl() -> _GpuBackend | None:  # pragma: no cover
    """
    Import the OpenCL backend if its optional dependency and a usable device are present.

    Returns
    -------
    _GpuBackend | None
        The OpenCL backend callable, or ``None`` when :py:mod:`pyopencl` cannot be imported or no
        usable OpenCL device is available.
    """
    try:
        from .opencl import crack_opencl, list_devices  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        return None
    return crack_opencl if _has_devices(list_devices) else None  # pragma: no cover


def crack(installer: str | Path | bytes | bytearray | memoryview | Reader,
          source: Mask | Iterable[str | bytes],
          *,
          backend: Backend = 'auto',
          end_offset: int | None = None,
          on_progress: ProgressCallback | None = None,
          jobs: int = 1,
          device: int = 0) -> bytes | None:
    """
    Search for the password of an encrypted InstallBuilder installer.

    Parameters
    ----------
    installer : str | :py:class:`~pathlib.Path` | bytes | bytearray | memoryview | Reader
        The installer to attack: a filesystem path, an in-memory image, or a
        :py:class:`~destin.bitrock.typing.Reader`.
    source : Mask | Iterable[str | bytes]
        The keyspace to search: a :py:class:`Mask` for charset-and-length brute force, or any
        iterable of candidate passwords (for example :py:func:`iter_wordlist`).
    backend : Backend
        ``'auto'`` prefers CUDA, then OpenCL, then the CPU; ``'cuda'``, ``'opencl'``, and ``'cpu'``
        force that backend.
    end_offset : int | None
        Offset just past the ``CFS0002`` signature, when known. Skips the auto-detection scan.
    on_progress : ProgressCallback | None
        Called periodically with the running candidate count and the latest candidate tried.
    jobs : int
        Worker processes for the CPU backend. ``1`` runs in this process; higher values fan out with
        :py:mod:`multiprocessing`. Ignored by the GPU backends.
    device : int
        Ordinal of the GPU device for the CUDA and OpenCL backends. Ignored by the CPU backend.

    Returns
    -------
    bytes | None
        The matching password, or ``None`` if the keyspace was exhausted without a match.

    Raises
    ------
    NotEncryptedError
        If the installer is not password-protected.
    """
    with InstallBuilderFile(installer, end_offset=end_offset) as archive:
        if (info := archive.payload_info) is None:
            msg = 'The installer is not password-protected.'
            raise NotEncryptedError(msg)
        run = _resolve_backend(backend)
        if run is _crack_cpu:
            return _crack_cpu(info, source, on_progress, jobs)
        # A GPU backend was resolved; it dispatches to a real device, unavailable in CI.
        return run(info, source, on_progress, device)  # pragma: no cover
