"""
CUDA backend for the password brute-forcer, built on CuPy.

The kernel in :file:`kernel.cl` (shared with the OpenCL backend via an ``#ifdef`` prelude) ports the
:py:func:`~destin.bitrock.crypto.verify_password` oracle to the GPU: SHA-256, the Twofish block
cipher, CBC mode, and the InstallBuilder key-derivation loop. The Twofish byte permutations and
matrices are injected from the constants in :py:mod:`~destin.bitrock.crypto`, so the GPU and CPU
cannot diverge on the lookup tables.

This module imports :py:mod:`cupy`, which is only present with the ``cuda`` extra installed on a
host with an NVIDIA GPU; :py:mod:`~destin.bitrock.password_cracker.crack` treats an
:py:class:`ImportError` here as 'no GPU'.
"""
from __future__ import annotations

from itertools import islice
from typing import TYPE_CHECKING
import logging
import time

from destin.bitrock.crypto import verify_password
import cupy as cp  # type: ignore[import-untyped]
import numpy as np

from .kernel_source import MAX_IV_POOL as _MAX_IV_POOL, MAX_PASSWORD as _MAX_PASSWORD, kernel_source

if TYPE_CHECKING:
    from collections.abc import Iterable

    from destin.bitrock.typing import PayloadInfo

    from .typing import ProgressCallback

__all__ = ('crack_cuda',)

log = logging.getLogger(__name__)

_BLOCKS_PER_SM = 4
"""Blocks per SM in a batch: enough to saturate every SM without making a batch run so long that

:meta hide-value:
"""
_POLL_SECONDS = 0.1
"""How often the host wakes to update progress and check for interruption while a batch runs.

:meta hide-value:
"""
_DEBUG_INTERVAL = 2.0
"""How often, in seconds, to emit an in-batch progress line at debug level.

:meta hide-value:
"""
_WARP = 32
"""CUDA warp size; the block size is rounded down to a multiple of this.

:meta hide-value:
"""
_DEFAULT_THREADS = 128
"""Block size used when the device does not report an occupancy limit.

:meta hide-value:
"""
_MAX_THREADS = 256
"""Upper cap on the block size; larger blocks give no benefit for this register-heavy kernel.

:meta hide-value:
"""


def _block_size(kernel: cp.RawKernel) -> int:
    """
    Choose an occupancy-safe block size for ``kernel`` on the current device.

    The kernel's ``max_threads_per_block`` reflects its register and local-memory usage, so it is a
    safe upper bound; it is rounded down to a warp multiple.

    Parameters
    ----------
    kernel : object
        The compiled ``crack_kernel`` function.

    Returns
    -------
    int
        The block size (threads per block).
    """
    # CuPy reports -1 for attributes the current toolkit does not expose; fall back in that case.
    reported = int(getattr(kernel, 'attributes', {}).get('max_threads_per_block', -1))
    limit = reported if reported > 0 else _DEFAULT_THREADS
    return max(_WARP, (min(limit, _MAX_THREADS) // _WARP) * _WARP)


def _encode(candidate: str | bytes) -> bytes:
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


def _upload_batch(batch: list[bytes]) -> tuple[object, object]:
    """
    Pack a batch of candidates into device arrays.

    Parameters
    ----------
    batch : list[bytes]
        The candidate passwords.

    Returns
    -------
    tuple[object, object]
        The ``(len(batch), _MAX_PASSWORD)`` byte buffer and the per-candidate length array.

    Raises
    ------
    ValueError
        If a candidate exceeds the kernel's maximum password length.
    """
    host = bytearray(len(batch) * _MAX_PASSWORD)
    host_lengths = np.empty(len(batch), dtype=np.int32)
    for i, candidate in enumerate(batch):
        if len(candidate) > _MAX_PASSWORD:
            msg = f'Candidate exceeds the kernel maximum of {_MAX_PASSWORD} bytes.'
            raise ValueError(msg)
        host[i * _MAX_PASSWORD:i * _MAX_PASSWORD + len(candidate)] = candidate
        host_lengths[i] = len(candidate)
    buffer = cp.asarray(bytearray(host), dtype=cp.uint8).reshape(len(batch), _MAX_PASSWORD)
    return buffer, cp.asarray(host_lengths)


def _run_batch(kernel: cp.RawKernel, header: dict[str, object], batch: list[bytes], threads: int, *,
               base: int, rate: float, on_progress: ProgressCallback | None) -> tuple[int, float]:
    """
    Launch one batch asynchronously, updating progress by time estimate until it finishes.

    Because every thread finishes its heavy key derivation only at the very end, a device-side
    'completed' counter would read zero for almost the whole batch. Instead, in-flight progress is
    estimated from elapsed time and ``rate`` (candidates per second measured from prior batches),
    which gives a smooth line. Polling ``stream.done`` also keeps a :py:class:`KeyboardInterrupt`
    responsive within :py:data:`_POLL_SECONDS`.

    Parameters
    ----------
    kernel : object
        The compiled ``crack_kernel`` function.
    header : dict[str, object]
        The uploaded constant device arrays and scalars, keyed by kernel argument name.
    batch : list[bytes]
        The candidate passwords for this launch.
    threads : int
        Threads per block for this launch.
    base : int
        Number of candidates already tried before this batch, for the progress count.
    rate : float
        Estimated candidates per second, used to interpolate in-flight progress. Zero disables it.
    on_progress : ProgressCallback | None
        Called about every :py:data:`_POLL_SECONDS` with the running count and a batch candidate.

    Returns
    -------
    tuple[int, float]
        The index of an accepted candidate (or ``-1``) and the batch's wall-clock seconds.
    """
    buffer, lengths = _upload_batch(batch)
    found = cp.full(1, -1, dtype=cp.int32)
    blocks = (len(batch) + threads - 1) // threads
    # Finish the uploads (issued on the default stream) before the async launch, since a
    # non-blocking stream does not wait for the default stream and would otherwise read garbage.
    cp.cuda.Stream.null.synchronize()
    stream = cp.cuda.Stream(non_blocking=True)
    start = time.monotonic()
    with stream:
        kernel((blocks,), (threads,),
               (buffer, lengths, np.int32(len(batch)), header['password_key'], header['iv'],
                header['times'], header['encrypted_key'], header['ivs_hash'],
                header['encrypted_ivs'], header['ivs_len'], found))
    last_debug = start
    while not stream.done:
        time.sleep(_POLL_SECONDS)
        now = time.monotonic()
        done = min(int((now - start) * rate), len(batch)) if rate > 0 else 0
        if on_progress is not None:
            on_progress(base + done, batch[min(done, len(batch) - 1)])
        if now - last_debug >= _DEBUG_INTERVAL:
            last_debug = now
            log.debug('Batch running %.0fs; ~%d/%d candidates (~%.2f/s).', now - start, done,
                      len(batch), rate)
    stream.synchronize()
    return int(found.get()[0]), time.monotonic() - start


def list_devices() -> list[str]:
    """
    Return a human-readable description of each CUDA device, indexed by ordinal.

    Returns
    -------
    list[str]
        One entry per device, in ordinal order, naming the device.
    """
    return [
        cp.cuda.runtime.getDeviceProperties(i)['name'].decode()
        for i in range(cp.cuda.runtime.getDeviceCount())
    ]


def crack_cuda(info: PayloadInfo,
               source: Iterable[str | bytes],
               on_progress: ProgressCallback | None = None,
               device: int = 0) -> bytes | None:
    """
    Search for the password on the GPU, returning the first candidate that verifies.

    Parameters
    ----------
    info : PayloadInfo
        The parsed payload header.
    source : Iterable[str | bytes]
        A :py:class:`~destin.bitrock.password_cracker.crack.Mask` or an iterable of
        ``str``/``bytes`` candidates.
    on_progress : ProgressCallback | None
        Called after each batch with the running candidate count and the last candidate of the
        batch.
    device : int
        Ordinal of the CUDA device to run on, as listed by :py:func:`list_devices`.

    Returns
    -------
    bytes | None
        The matching password, or ``None`` if the keyspace was exhausted.

    Raises
    ------
    ValueError
        If a candidate exceeds the kernel's maximum password length, or the IV pool is too large.
    """
    if len(info.encrypted_payload_ivs) > _MAX_IV_POOL:
        msg = f'Encrypted IV pool exceeds the kernel maximum of {_MAX_IV_POOL} bytes.'
        raise ValueError(msg)
    start = time.monotonic()
    cp.cuda.Device(device).use()
    kernel = cp.RawModule(code=kernel_source()).get_function('crack_kernel')
    threads = _block_size(kernel)
    name = cp.cuda.runtime.getDeviceProperties(device)['name'].decode()
    sm_count = cp.cuda.Device(device).attributes['MultiProcessorCount']
    log.info('Compiling CUDA kernel on %s (%d SMs) with %d threads/block, times=%d. Please wait...',
             name, sm_count, threads, info.times)
    header: dict[str, object] = {
        'password_key': cp.asarray(bytearray(info.password_key), dtype=cp.uint8),
        'iv': cp.asarray(bytearray(info.iv), dtype=cp.uint8),
        'encrypted_key': cp.asarray(bytearray(info.encrypted_key), dtype=cp.uint8),
        'ivs_hash': cp.asarray(bytearray(info.payload_ivs_hash), dtype=cp.uint8),
        'encrypted_ivs': cp.asarray(bytearray(info.encrypted_payload_ivs), dtype=cp.uint8),
        'ivs_len': np.int32(len(info.encrypted_payload_ivs)),
        'times': np.int32(info.times),
    }
    # Force the one-time NVRTC compile now (so it is not counted against the first batch) and seed
    # an initial rate from a small warm-up so the first real batch can show in-flight progress.
    warmup = threads * _WARP
    _, warm_elapsed = _run_batch(kernel,
                                 header, [b'\x00'] * warmup,
                                 threads,
                                 base=0,
                                 rate=0.0,
                                 on_progress=None)
    rate = warmup / warm_elapsed if warm_elapsed > 0 else 0.0
    log.info('Kernel ready in %.2fs (~%.2f candidates/s); starting search.',
             time.monotonic() - start, rate)
    batch_size = sm_count * _BLOCKS_PER_SM * threads
    candidates = (_encode(c) for c in source)
    tested = 0
    while batch := list(islice(candidates, batch_size)):
        log.debug('Launching %d candidates (total so far %d); first: `%s`, last: `%s`.', len(batch),
                  tested, _display(batch[0]), _display(batch[-1]))
        index, elapsed = _run_batch(kernel,
                                    header,
                                    batch,
                                    threads,
                                    base=tested,
                                    rate=rate,
                                    on_progress=on_progress)
        tested += len(batch)
        rate = len(batch) / elapsed if elapsed > 0 else rate
        log.debug('Batch done in %.2fs (%.2f candidates/s).', elapsed, rate)
        if on_progress is not None:
            on_progress(tested, batch[-1])
        if index >= 0:
            winner = batch[index]
            log.debug('Kernel reported a hit: `%s`; confirming on CPU.', _display(winner))
            # Confirm the GPU verdict on the CPU to guard against a kernel defect.
            return winner if verify_password(winner, info) is not None else None
    log.debug('Keyspace exhausted after %d candidates; no match.', tested)
    return None
