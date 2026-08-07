"""
OpenCL backend for the password brute-forcer, built on PyOpenCL.

The kernel in :file:`kernel.cl` ports the
:py:func:`~destin.bitrock.crypto.verify_password` oracle to the device: SHA-256, the Twofish block
cipher, CBC mode, and the InstallBuilder key-derivation loop. The Twofish byte permutations and
matrices are injected from the constants in :py:mod:`~destin.bitrock.crypto`, so the device and CPU
cannot diverge on the lookup tables. The kernel targets the OpenCL 1.2 baseline, so it builds with
each device's default
standard (the reported platforms range from 2.0 to 3.0).

This module imports :py:mod:`pyopencl`, which is only present with the ``opencl`` extra installed on
a host with an OpenCL device; :py:mod:`destin.bitrock.password_cracker.crack` treats an
:py:class:`ImportError` here as 'no OpenCL'.
"""
from __future__ import annotations

from itertools import islice
from typing import TYPE_CHECKING, TypeAlias
import logging
import time
import warnings

from destin.bitrock.crypto import verify_password
import numpy as np
import numpy.typing as npt
import pyopencl as cl

from .kernel_source import MAX_IV_POOL as _MAX_IV_POOL, MAX_PASSWORD as _MAX_PASSWORD, kernel_source

if TYPE_CHECKING:
    from collections.abc import Iterable

    from destin.bitrock.typing import PayloadInfo

    from .typing import ProgressCallback

    _Header: TypeAlias = dict[str, cl.Buffer | np.int32]
    """The uploaded constant device buffers and scalar arguments, keyed by kernel argument name."""

__all__ = ('crack_opencl',)

log = logging.getLogger(__name__)

_GROUPS_PER_UNIT = 4
"""Work groups per compute unit in a batch: enough to saturate the device without a long batch.

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
"""Work-group size is rounded down to a multiple of this (the preferred multiple on NVIDIA).

:meta hide-value:
"""
_DEFAULT_LOCAL = 128
"""Work-group size used when the device does not report a usable maximum.

:meta hide-value:
"""
_MAX_LOCAL = 256
"""Upper cap on the work-group size; larger groups do not help this register-heavy kernel.

:meta hide-value:
"""


def _all_devices() -> list[cl.Device]:
    """
    Return every OpenCL device across all platforms, in a stable order.

    Returns
    -------
    list[pyopencl.Device]
        The devices, ordered platform by platform.
    """
    return [d for p in cl.get_platforms() for d in p.get_devices()]


def list_devices() -> list[str]:
    """
    Return a human-readable description of each OpenCL device, indexed as :py:func:`crack_opencl`.

    Returns
    -------
    list[str]
        One entry per device, in selection order, naming the device and its platform.
    """
    return [f'{d.name.strip()} ({d.platform.name.strip()})' for d in _all_devices()]


def _select_device(index: int | None) -> cl.Device:
    """
    Choose an OpenCL device by index, or the first GPU (then any device) when unspecified.

    Parameters
    ----------
    index : int | None
        Ordinal into :py:func:`list_devices`, or ``None`` to auto-select.

    Returns
    -------
    pyopencl.Device
        The selected device.

    Raises
    ------
    RuntimeError
        If no OpenCL device is available, or ``index`` is out of range.
    """
    devices = _all_devices()
    if not devices:
        msg = 'No OpenCL device found.'
        raise RuntimeError(msg)
    if index is not None:
        if not 0 <= index < len(devices):
            msg = f'OpenCL device index {index} out of range (0..{len(devices) - 1}).'
            raise RuntimeError(msg)
        return devices[index]
    gpus = [d for d in devices if d.type & cl.device_type.GPU]
    return gpus[0] if gpus else devices[0]


def _local_size(kernel: cl.Kernel, device: cl.Device) -> int:
    """
    Choose an occupancy-safe work-group size for ``kernel`` on ``device``.

    Parameters
    ----------
    kernel : pyopencl.Kernel
        The compiled ``crack_kernel``.
    device : pyopencl.Device
        The target device.

    Returns
    -------
    int
        The work-group size, a warp multiple within the kernel's reported maximum.
    """
    limit = kernel.get_work_group_info(cl.kernel_work_group_info.WORK_GROUP_SIZE, device)
    limit = limit if limit > 0 else _DEFAULT_LOCAL
    return max(_WARP, (min(limit, _MAX_LOCAL) // _WARP) * _WARP)


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


def _pack_batch(batch: list[bytes]) -> tuple[npt.NDArray[np.uint8], npt.NDArray[np.int32]]:
    """
    Pack a batch of candidates into host arrays.

    Parameters
    ----------
    batch : list[bytes]
        The candidate passwords.

    Returns
    -------
    tuple[numpy.ndarray, numpy.ndarray]
        The flat ``len(batch) * _MAX_PASSWORD`` byte array and the per-candidate length array.

    Raises
    ------
    ValueError
        If a candidate exceeds the kernel's maximum password length.
    """
    host = bytearray(len(batch) * _MAX_PASSWORD)
    lengths = np.empty(len(batch), dtype=np.int32)
    for i, candidate in enumerate(batch):
        if len(candidate) > _MAX_PASSWORD:
            msg = f'Candidate exceeds the kernel maximum of {_MAX_PASSWORD} bytes.'
            raise ValueError(msg)
        host[i * _MAX_PASSWORD:i * _MAX_PASSWORD + len(candidate)] = candidate
        lengths[i] = len(candidate)
    return np.frombuffer(bytes(host), dtype=np.uint8), lengths


def _run_batch(context: cl.Context, queue: cl.CommandQueue, kernel: cl.Kernel, header: _Header,
               batch: list[bytes], local_size: int, *, base: int, rate: float,
               on_progress: ProgressCallback | None) -> tuple[int, float]:
    """
    Enqueue one batch and poll its event, updating progress by time estimate until it finishes.

    Because every work item finishes its heavy key derivation only at the very end, a device-side
    'completed' counter would read zero for almost the whole batch. Instead, in-flight progress is
    estimated from elapsed time and ``rate`` (candidates per second measured from prior batches).
    Polling the event also keeps a :py:class:`KeyboardInterrupt` responsive within
    :py:data:`_POLL_SECONDS`.

    Parameters
    ----------
    context : pyopencl.Context
        The context, used to allocate the batch buffers.
    queue : pyopencl.CommandQueue
        The command queue to enqueue on.
    kernel : pyopencl.Kernel
        The compiled ``crack_kernel``.
    header : _Header
        The uploaded constant device buffers and scalars, keyed by kernel argument name.
    batch : list[bytes]
        The candidate passwords for this launch.
    local_size : int
        Work-group size for this launch.
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
    mf = cl.mem_flags
    passwords, lengths = _pack_batch(batch)
    found = np.full(1, -1, dtype=np.int32)
    passwords_buf = cl.Buffer(context, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=passwords)
    lengths_buf = cl.Buffer(context, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=lengths)
    found_buf = cl.Buffer(context, mf.READ_WRITE | mf.COPY_HOST_PTR, hostbuf=found)
    global_size = -(-len(batch) // local_size) * local_size
    start = time.monotonic()
    event = kernel(queue, (global_size,), (local_size,), passwords_buf, lengths_buf,
                   np.int32(len(batch)), header['password_key'], header['iv'], header['times'],
                   header['encrypted_key'], header['ivs_hash'], header['encrypted_ivs'],
                   header['ivs_len'], found_buf)
    last_debug = start
    complete = cl.command_execution_status.COMPLETE
    while event.command_execution_status != complete:
        time.sleep(_POLL_SECONDS)
        now = time.monotonic()
        done = min(int((now - start) * rate), len(batch)) if rate > 0 else 0
        if on_progress is not None:
            on_progress(base + done, batch[min(done, len(batch) - 1)])
        if now - last_debug >= _DEBUG_INTERVAL:
            last_debug = now
            log.debug('Batch running %.0fs; ~%d/%d candidates (~%.2f/s).', now - start, done,
                      len(batch), rate)
    cl.enqueue_copy(queue, found, found_buf)
    return int(found[0]), time.monotonic() - start


def _build_kernel(context: cl.Context, device: cl.Device) -> cl.Kernel:
    """
    Build the program and return its ``crack_kernel``, routing the build log to the debug log.

    Some devices (notably CPU runtimes) emit non-empty build output that PyOpenCL would otherwise
    raise as a :py:class:`~pyopencl.CompilerWarning`; it is captured and logged at debug level.

    Parameters
    ----------
    context : pyopencl.Context
        The context to build in.
    device : pyopencl.Device
        The device the program is built for, used to read its build log.

    Returns
    -------
    pyopencl.Kernel
        The compiled ``crack_kernel``.
    """
    program = cl.Program(context, kernel_source())
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', cl.CompilerWarning)
        program.build()
    # get_build_info is untyped in the pyopencl stubs.
    log_text = program.get_build_info(
        device, cl.program_build_info.LOG).strip()  # type: ignore[no-untyped-call]
    if log_text:
        log.debug('OpenCL build log:\n%s', log_text)
    return program.crack_kernel


def _upload_header(context: cl.Context, info: PayloadInfo) -> _Header:
    """
    Upload the payload header's constant fields to read-only device buffers.

    Parameters
    ----------
    context : pyopencl.Context
        The context to allocate in.
    info : PayloadInfo
        The parsed payload header.

    Returns
    -------
    _Header
        The device buffers and scalar arguments, keyed by kernel argument name.
    """
    mf = cl.mem_flags

    def buffer(data: bytes) -> cl.Buffer:
        return cl.Buffer(context, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=bytearray(data))

    return {
        'password_key': buffer(info.password_key),
        'iv': buffer(info.iv),
        'encrypted_key': buffer(info.encrypted_key),
        'ivs_hash': buffer(info.payload_ivs_hash),
        'encrypted_ivs': buffer(info.encrypted_payload_ivs),
        'ivs_len': np.int32(len(info.encrypted_payload_ivs)),
        'times': np.int32(info.times),
    }


def crack_opencl(info: PayloadInfo,
                 source: Iterable[str | bytes],
                 on_progress: ProgressCallback | None = None,
                 device: int | None = None) -> bytes | None:
    """
    Search for the password on an OpenCL device, returning the first candidate that verifies.

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
    device : int | None
        Ordinal into :py:func:`list_devices`, or ``None`` to prefer the first GPU.

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
    selected = _select_device(device)
    context = cl.Context(devices=[selected])
    queue = cl.CommandQueue(context)
    kernel = _build_kernel(context, selected)
    local_size = _local_size(kernel, selected)
    units = selected.max_compute_units
    log.info(
        'Compiling OpenCL kernel on %s (%d units) with a work-group of %d, times=%d. Please '
        'wait...', selected.name.strip(), units, local_size, info.times)
    header = _upload_header(context, info)
    # Seed an initial rate from a one-group warm-up. Keeping it to a single work-group keeps it
    # quick even on a slow CPU device, where a larger warm-up would look like a hang.
    _, warm_elapsed = _run_batch(context,
                                 queue,
                                 kernel,
                                 header, [b'\x00'] * local_size,
                                 local_size,
                                 base=0,
                                 rate=0.0,
                                 on_progress=None)
    rate = local_size / warm_elapsed if warm_elapsed > 0 else 0.0
    log.info('Kernel ready in %.2fs (~%.2f candidates/s); starting search.',
             time.monotonic() - start, rate)
    batch_size = units * _GROUPS_PER_UNIT * local_size
    candidates = (_encode(c) for c in source)
    tested = 0
    while batch := list(islice(candidates, batch_size)):
        log.debug('Launching %d candidates (total so far %d); first: `%s`, last: `%s`.', len(batch),
                  tested, _display(batch[0]), _display(batch[-1]))
        index, elapsed = _run_batch(context,
                                    queue,
                                    kernel,
                                    header,
                                    batch,
                                    local_size,
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
            # Confirm the device verdict on the CPU to guard against a kernel defect.
            return winner if verify_password(winner, info) is not None else None
    log.debug('Keyspace exhausted after %d candidates; no match.', tested)
    return None
