"""
Decode Monopoly 2008 EA audio banks (``.mus`` / ``.sdt``) to WAV in place.

This module consolidates four verified per-platform EA audio converters into a
single magic-driven pipeline (6329+ streams decoded across Xbox 360, PS3, PS2
and Wii builds). The decode algorithms are preserved exactly; only the framing
is standardised.

Two container families are auto-detected by the bytes in the payload, never by
the platform:

* **EA "SCHl"** (PS2 / classic little-endian banks). Each logical sound is a
  self-contained ``SCHl`` .. ``SCEl`` unit. The PS2 ``.mus`` (magic ``cefb807a``)
  wraps these too. vgmstream decodes them natively (layout "blocked (EA SCHl)"),
  so each unit is carved out and handed to ``vgmstream-cli``.
* **EAAC** (Xbox 360 / PS3 / Wii SNR/SNS streams). ``.mus`` (magic ``ce fb 80
  7a``) wraps **EA-XMA** segments; ``.sdt`` (``ADAT`` speech or a headerless
  bank) wraps **EALayer3** streams. A standard EA ``.snr`` / ``.sns`` pair is
  reconstructed per segment/stream and decoded by vgmstream.

For every source file the WAVs are written next to it as ``<stem>_<NNNN>.wav``
(4-digit). ADAT speech ``.sdt`` files additionally get a ``<stem>.subtitles.txt``
sidecar written next to the source.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple
import functools
import logging
import os
import shutil
import struct
import subprocess as sp
import tempfile
import wave

import numpy as np
import numpy.typing as npt

from destin.common.io import u32

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = (
    'EXTENSIONS',
    'AudioJob',
    'convert_file',
    'jobs_for',
    'run_job',
)

log = logging.getLogger(__name__)

EXTENSIONS = frozenset({'.mus', '.sdt'})
"""File extensions handled by :py:func:`convert_file`.

:meta hide-value:
"""

_MUS_MAGIC = 0xCEFB807A
"""Big-endian magic for the EA ``.mus`` (``TbSound``) container.

:meta hide-value:
"""
_SCHL_MAGIC = b'SCHl'
"""Marker beginning each EA SCHl stream unit.

:meta hide-value:
"""
_SCEL_MAGIC = b'SCEl'
"""Marker ending each EA SCHl stream unit.

:meta hide-value:
"""
_ADAT_MAGIC = b'ADAT'
"""Marker beginning each record of an EAAC ADAT speech bank.

:meta hide-value:
"""
_SUB3_MAGIC = b'SUB3'
"""Marker beginning a subtitle chunk inside an ADAT record.

:meta hide-value:
"""

_SNR_TABLE = 0x3600
"""Offset of the EAAC SNR header table inside a ``.mus`` container.

:meta hide-value:
"""
_EAAC_EALAYER3_V1 = 5
"""EAAC codec id for EALayer3 (V1, ``EL31``) used by ``.sdt`` streams.

:meta hide-value:
"""

_WAV_HEADER_SIZE = 44
"""Size in bytes of a canonical WAV header; a larger output file carries audio.

:meta hide-value:
"""
_MIN_SNS_BLOCK_SIZE = 8
"""Minimum size of an EA-SNS block (its 8-byte header).

:meta hide-value:
"""
_MAX_SUBTITLE_CHARS = 4000
"""Upper bound on a subtitle chunk's UTF-16 character count used to reject junk.

:meta hide-value:
"""
_CHANNEL_SILENCE_RMS = 0.02
"""RMS threshold below which a whole channel is treated as carrying no signal.

:meta hide-value:
"""
_WINDOW_SILENCE_RMS = 0.003
"""RMS threshold below which a single analysis window is treated as near-silent.

:meta hide-value:
"""
_MAX_SIMPLE_WAV_CHANNELS = 2
"""Highest channel count written with the plain (non-extensible) WAV header.

:meta hide-value:
"""
_MAX_ACTIVE_SILENCE_PCT = 25
"""Active-silence percentage above which a base decode is considered broken.

:meta hide-value:
"""
_MAX_SURROUND_CHANNELS = 6
"""Highest channel count tried when escalating a multi-substream surround decode.

:meta hide-value:
"""
_CLEAN_SILENCE_PCT = 6
"""Active-silence percentage below which an escalated decode is accepted as clean.

:meta hide-value:
"""

# An EALayer3 EA-SNS block holds a few MPEG frames; the measured maximum across
# the game's banks is ~4001 samples. Anything far above this (garbage chains seen
# in ADAT/SUB3 metadata reached 215040+) is not audio; 16384 cleanly separates
# real audio from junk.
_MAX_BLOCK_SAMPLES = 16384
"""Upper bound on per-block sample counts used to reject non-audio while walking.

:meta hide-value:
"""

# EALayer3 / MPEG common-header tables (from vgmstream
# ``mpeg_custom_utils_ealayer3.c``).
_MPEG_SAMPLE_RATES = (
    (11025, 12000, 8000, -1),
    (-1, -1, -1, -1),
    (22050, 24000, 16000, -1),
    (44100, 48000, 32000, -1),
)
"""Sample-rate lookup indexed by ``[version_index][sample_rate_index]``.

:meta hide-value:
"""
_MPEG_CHANNELS = {0: 2, 1: 2, 2: 2, 3: 1}
"""Channel count by MPEG channel-mode: stereo/joint/dual = 2, single = 1.

:meta hide-value:
"""

# EA multichannel comes out in order FL FC FR BL BR LFE (vgmstream does NOT
# remap). Reorder to canonical WAV order and emit a speaker mask so the
# multichannel WAV is lossless AND correctly mapped. Mask bits: FL FR FC LFE BL
# BR = 0x01 0x02 0x04 0x08 0x10 0x20.
_WAV_LAYOUT = {
    1: ((0,), 0x4),  # mono -> front center
    2: ((0, 1), 0x3),  # stereo FL FR
    4: ((0, 1, 2, 3), 0x33),  # quad FL FR BL BR (raw EA order, best effort)
    6: ((0, 2, 1, 5, 3, 4), 0x3F),  # EA FL FC FR BL BR LFE -> WAV FL FR FC LFE BL BR
}
"""Per-channel-count ``(permutation, speaker_mask)`` for canonical WAV output.

:meta hide-value:
"""

_KSDATAFORMAT_SUBTYPE_PCM = bytes.fromhex('0100000000001000800000aa00389b71')
"""GUID for ``KSDATAFORMAT_SUBTYPE_PCM`` in ``WAVE_FORMAT_EXTENSIBLE`` headers.

:meta hide-value:
"""


class AudioJob(NamedTuple):
    """
    A single picklable per-stream decode unit.

    One job decodes exactly one stream/segment from ``source`` to ``out_wav``.
    Jobs are produced by :py:func:`jobs_for` and consumed by :py:func:`run_job`,
    so a caller may pool decodes across many files.
    """

    kind: str
    """Decode path: ``'schl'``, ``'mus'`` (EA-XMA) or ``'sdt'`` (EALayer3)."""
    source: Path
    """Source ``.mus`` / ``.sdt`` file the stream is read from."""
    start: int
    """Byte offset of the stream within ``source``."""
    end: int
    """End byte offset (exclusive) of the stream within ``source``."""
    out_wav: Path
    """Destination WAV path, next to ``source``."""
    header: bytes = b''
    """Reconstructed 8-byte EAAC ``.snr`` header (EA-XMA ``'mus'`` jobs only)."""
    nsamp: int = 0
    """Declared total sample count (EALayer3 ``'sdt'`` jobs only)."""


@functools.cache
def _vgmstream() -> Path:
    """
    Locate the ``vgmstream-cli`` binary, caching the result.

    The resolver checks, in order: the ``VGMSTREAM_CLI`` environment variable,
    a bundled ``tools/vgmstream/vgmstream-cli`` found by walking up the parents
    of this file, then :py:func:`shutil.which`.

    Returns
    -------
    pathlib.Path
        Path to the ``vgmstream-cli`` executable.

    Raises
    ------
    FileNotFoundError
        If no ``vgmstream-cli`` binary can be located.
    """
    if (env := os.environ.get('VGMSTREAM_CLI')) and (env_path := Path(env)).is_file():
        return env_path
    for parent in Path(__file__).resolve().parents:
        if (candidate := parent / 'tools' / 'vgmstream' / 'vgmstream-cli').is_file():
            return candidate
    if (found := shutil.which('vgmstream-cli')) is not None:
        return Path(found)
    msg = ('vgmstream-cli not found: set the VGMSTREAM_CLI environment variable, place the '
           'binary at tools/vgmstream/vgmstream-cli, or install it on PATH.')
    raise FileNotFoundError(msg)


def _read_range(source: Path, start: int, end: int) -> bytes:
    """
    Read the ``[start, end)`` byte range from ``source``.

    Parameters
    ----------
    source : pathlib.Path
        File to read from.
    start : int
        Start byte offset.
    end : int
        End byte offset (exclusive).

    Returns
    -------
    bytes
        The requested byte range.
    """
    with source.open('rb') as f:
        f.seek(start)
        return f.read(end - start)


def _run_vgmstream(snr: Path, out_wav: Path) -> str:
    """
    Run ``vgmstream-cli`` to decode ``snr`` to ``out_wav``.

    Parameters
    ----------
    snr : pathlib.Path
        Input file passed to ``vgmstream-cli`` (a ``.snr`` or carved ``.asf``).
    out_wav : pathlib.Path
        Destination WAV path.

    Returns
    -------
    str
        Combined stdout and stderr of the invocation (empty when capture is
        unavailable).
    """
    try:
        result = sp.run(
            [str(_vgmstream()), '-o', str(out_wav), str(snr)],
            capture_output=True,
            check=True,
            text=True)
    except sp.CalledProcessError as e:
        return f'{e.stdout or ""}{e.stderr or ""}'
    return f'{result.stdout}{result.stderr}'


def _decode_snr_sns(header: bytes, body: bytes, out_wav: Path) -> str:
    """
    Write a temporary EA ``.snr`` / ``.sns`` pair and decode it to ``out_wav``.

    Parameters
    ----------
    header : bytes
        Reconstructed EAAC ``.snr`` header.
    body : bytes
        Stream body written as the ``.sns``.
    out_wav : pathlib.Path
        Destination WAV path.

    Returns
    -------
    str
        Combined vgmstream stdout and stderr.
    """
    with tempfile.TemporaryDirectory() as td:
        snr = Path(td) / 's.snr'
        snr.write_bytes(header)
        (Path(td) / 's.sns').write_bytes(body)
        return _run_vgmstream(snr, out_wav)


# --- EA SCHl path (PS2 / classic little-endian banks) ------------------------
def _carve_schl_streams(b: bytes) -> list[tuple[int, int]]:
    """
    Return ``(start, end)`` byte ranges, one per ``SCHl`` .. ``SCEl`` unit.

    Parameters
    ----------
    b : bytes
        Full bank (or ``.mus`` container) contents.

    Returns
    -------
    list[tuple[int, int]]
        Byte ranges for each stream. ``SCHl`` and ``SCEl`` appear 1:1 and
        properly nested in these banks, so pairing them in order is exact; the
        end is the ``SCEl`` offset plus its own little-endian chunk size, which
        excludes trailing padding/index bytes. If the counts disagree the next
        ``SCHl`` boundary is used as the end instead.
    """
    sch = []
    sce = []
    o = b.find(_SCHL_MAGIC)
    while o >= 0:
        sch.append(o)
        o = b.find(_SCHL_MAGIC, o + 4)
    o = b.find(_SCEL_MAGIC)
    while o >= 0:
        sce.append(o)
        o = b.find(_SCEL_MAGIC, o + 4)
    if len(sch) != len(sce):
        ends = [*sch[1:], len(b)]
        return list(zip(sch, ends, strict=True))
    return [(s, e + struct.unpack_from('<I', b, e + 4)[0]) for s, e in zip(sch, sce, strict=True)]


def _decode_schl(job: AudioJob) -> tuple[Path, bool, str]:
    """
    Decode one carved EA SCHl unit to WAV via vgmstream.

    Parameters
    ----------
    job : AudioJob
        Job whose ``[start, end)`` range is a single ``SCHl`` .. ``SCEl`` unit.

    Returns
    -------
    tuple[pathlib.Path, bool, str]
        Output WAV path, success flag, and a diagnostic message on failure.
    """
    out = job.out_wav
    if out.exists() and out.stat().st_size > _WAV_HEADER_SIZE:
        return out, True, 'skip'
    tmp = out.with_suffix('.asf')  # Extension vgmstream recognises for SCHl.
    try:
        tmp.write_bytes(_read_range(job.source, job.start, job.end))
        msg = _run_vgmstream(tmp, out)
        ok = out.exists() and out.stat().st_size > _WAV_HEADER_SIZE
        return out, ok, '' if ok else msg[-300:]
    except OSError as e:
        return out, False, str(e)
    finally:
        tmp.unlink(missing_ok=True)


# --- EAAC .mus path (Xbox 360 / PS3 / Wii EA-XMA) ----------------------------
def _parse_mus(b: bytes) -> list[tuple[int, bytes, int, int]]:
    """
    Parse an EAAC ``.mus`` container into EA-XMA segments.

    Parameters
    ----------
    b : bytes
        Full ``.mus`` container contents (magic ``cefb807a``).

    Returns
    -------
    list[tuple[int, bytes, int, int]]
        One ``(index, header_bytes, data_offset, data_end)`` tuple per segment,
        where ``header_bytes`` is the 8-byte EAAC header from the SNR table.

    Raises
    ------
    ValueError
        If the container magic is wrong.
    """
    if (magic := u32(b, 0, endian='>')) != _MUS_MAGIC:
        msg = f'bad .mus magic {magic:08x}'
        raise ValueError(msg)
    # Seek table @0x10: [dataOff, field2, snrPtr] until it reaches the SNR table.
    offs: list[int] = []
    o = 0x10
    while o + 12 <= _SNR_TABLE:
        do = struct.unpack_from('>III', b, o)[0]
        if do == 0 or (offs and do <= offs[-1]):
            break
        offs.append(do)
        o += 12
    segs = []
    for i, do in enumerate(offs):
        end = offs[i + 1] if i + 1 < len(offs) else len(b)
        hdr = b[_SNR_TABLE + i * 0x10:_SNR_TABLE + i * 0x10 + 8]
        segs.append((i, hdr, do, end))
    return segs


def _decode_mus_segment(job: AudioJob) -> tuple[Path, bool, str]:
    """
    Decode one EA-XMA ``.mus`` segment to WAV via a reconstructed ``.snr`` pair.

    Parameters
    ----------
    job : AudioJob
        Job carrying the 8-byte EAAC ``header`` and the segment byte range.

    Returns
    -------
    tuple[pathlib.Path, bool, str]
        Output WAV path, success flag, and a diagnostic message on failure.
    """
    out = job.out_wav
    if out.exists() and out.stat().st_size > _WAV_HEADER_SIZE:
        return out, True, 'skip'
    try:
        body = _read_range(job.source, job.start, job.end)
        msg = _decode_snr_sns(job.header, body, out)
        ok = out.exists() and out.stat().st_size > _WAV_HEADER_SIZE
        return out, ok, '' if ok else msg[-300:]
    except OSError as e:
        return out, False, str(e)


# --- EAAC .sdt path (Xbox 360 / PS3 / Wii EALayer3) --------------------------
def _walk_stream(b: bytes, start: int) -> tuple[int, int, int, int] | None:
    """
    Walk EA-SNS blocks from ``start``.

    Parameters
    ----------
    b : bytes
        Bank contents.
    start : int
        Candidate stream start offset.

    Returns
    -------
    tuple[int, int, int, int] | None
        ``(start, end, nblocks, total_samples)`` for a valid stream, or ``None``
        when the bytes at ``start`` are not a valid EA-SNS block run. Validity is
        enforced via the block invariants (flag in ``{0x00, 0x80}``, sane size,
        and per-block samples within one MPEG frame), which makes the walk a
        reliable detector across ADAT/SUB3 metadata gaps.
    """
    o = start
    nsamp = 0
    n = 0
    while o + 8 <= len(b):
        hdr = u32(b, o, endian='>')
        flag = (hdr >> 24) & 0xFF
        size = hdr & 0xFFFFFF
        if flag not in {0x00, 0x80} or size < _MIN_SNS_BLOCK_SIZE or o + size > len(b):
            return None
        samp = u32(b, o + 4, endian='>')
        if samp > _MAX_BLOCK_SAMPLES:
            return None
        nsamp += samp
        n += 1
        nxt = o + size
        if flag & 0x80:
            return start, nxt, n, nsamp
        o = nxt
    return None


def _frame_params(b: bytes, stream_start: int) -> tuple[int, int]:
    """
    Parse the first EALayer3 (V1) frame common header.

    Parameters
    ----------
    b : bytes
        Bank contents.
    stream_start : int
        Offset of the EA-SNS block beginning the stream.

    Returns
    -------
    tuple[int, int]
        ``(channels, sample_rate)``. ``sample_rate`` is ``-1`` for a reserved
        MPEG sample-rate index.
    """
    p = stream_start + 8  # Skip [flag:u8][size:u24][samples:u32] block header.
    bitpos = 8  # After the 8-bit V1 pcm_flag.

    def bits(count: int) -> int:
        nonlocal bitpos
        v = 0
        for _ in range(count):
            v = (v << 1) | ((b[p + (bitpos >> 3)] >> (7 - (bitpos & 7))) & 1)
            bitpos += 1
        return v

    vi, sri, cm, _me = bits(2), bits(2), bits(2), bits(2)
    return _MPEG_CHANNELS.get(cm, 2), _MPEG_SAMPLE_RATES[vi][sri]


def _find_streams(b: bytes, data_start: int) -> list[tuple[int, int, int, int]]:
    """
    Find all EA-SNS audio streams from ``data_start`` to EOF.

    Parameters
    ----------
    b : bytes
        Bank contents.
    data_start : int
        Offset to begin scanning from.

    Returns
    -------
    list[tuple[int, int, int, int]]
        ``(start, end, nblocks, nsamp)`` per stream, skipping non-audio
        (ADAT/SUB3 metadata) gaps between records.
    """
    streams = []
    o = data_start
    while o < len(b):
        if (r := _walk_stream(b, o)) and r[2] >= 1:
            streams.append(r)
            o = r[1]
            # Skip non-audio padding/metadata until the next block run.
            while o < len(b) and _walk_stream(b, o) is None:
                o += 1
        else:
            o += 1
            # Defensive only: ``o`` never runs further past ``data_start`` than the bank is long,
            # so this runaway guard cannot fire.
            if o - data_start > len(b):  # pragma: no cover
                break
    return streams


def _parse_sub3(b: bytes, off: int) -> list[tuple[int, str]]:
    """
    Parse a SUB3 subtitle chunk.

    Parameters
    ----------
    b : bytes
        Bank contents.
    off : int
        Offset of the ``SUB3`` chunk.

    Returns
    -------
    list[tuple[int, str]]
        ``(hash, text)`` per subtitle. Handles both single-subtitle records
        (chapters) and multi-subtitle chunks (``count > 1``).
    """
    if b[off:off + 4] != _SUB3_MAGIC:
        return []
    count = u32(b, off + 8, endian='>')
    subs = []
    p = off + 0x0C
    for _ in range(count):
        if p + 0x10 > len(b):
            break
        w0 = u32(b, p, endian='>')
        w1 = u32(b, p + 4, endian='>')
        clen = u32(b, p + 0x0C, endian='>')
        if clen > _MAX_SUBTITLE_CHARS or p + 0x10 + clen * 2 > len(b):
            break
        text = b[p + 0x10:p + 0x10 + clen * 2].decode('utf-16-be', 'replace').rstrip('\x00')
        subs.append((w1 if w0 == 0 else w0, text))  # Hash slot differs by variant.
        p += 0x10 + clen * 2
    return subs


def _parse_adat(b: bytes) -> list[tuple[int, int, int, int, int | None, str | None]]:
    """
    Parse an ADAT speech ``.sdt`` by its record structure.

    Parameters
    ----------
    b : bytes
        Full ADAT bank contents.

    Returns
    -------
    list[tuple[int, int, int, int, int | None, str | None]]
        ``(start, end, nblocks, nsamp, hash, subtitle)`` per stream. Each record
        starts with the ``ADAT`` magic, an optional ``SUB3`` chunk, then one or
        more EALayer3 streams; subtitles are paired with streams in order.
    """
    starts = []
    o = b.find(_ADAT_MAGIC)
    while o >= 0:
        starts.append(o)
        o = b.find(_ADAT_MAGIC, o + 4)
    recs = []
    for k, adat in enumerate(starts):
        rec_end = starts[k + 1] if k + 1 < len(starts) else len(b)
        sub_off = adat + 0x10
        subs = _parse_sub3(b, sub_off)
        has_sub3 = b[sub_off:sub_off + 4] == _SUB3_MAGIC
        p0 = sub_off + 8 + u32(b, sub_off + 4, endian='>') if has_sub3 else adat + 0x10
        idx = 0
        o = p0
        while o < rec_end - 8:
            if (r := _walk_stream(b, o)) is None:
                o += 1  # Skip padding / metadata between streams.
                continue
            h, text = subs[idx] if idx < len(subs) else (None, None)
            recs.append((r[0], r[1], r[2], r[3], h, text))
            idx += 1
            o = r[1]
    return recs


def _synth_snr(codec: int, ch: int, sr: int, nsamp: int, typ: int = 1) -> bytes:
    """
    Synthesize an 8-byte EAAC ``.snr`` header.

    Parameters
    ----------
    codec : int
        EAAC codec id.
    ch : int
        Channel count.
    sr : int
        Sample rate in Hz.
    nsamp : int
        Total sample count.
    typ : int
        Stream type field (defaults to 1).

    Returns
    -------
    bytes
        The packed 8-byte header.
    """
    h1 = (codec << 24) | ((ch - 1) << 18) | (sr & 0x3FFFF)
    h2 = (typ << 30) | (nsamp & 0x1FFFFFFF)
    return struct.pack('>II', h1, h2)


def _decode_array(snr_bytes: bytes,
                  sns_bytes: bytes) -> tuple[npt.NDArray[np.int16] | None, bool, int]:
    """
    Run vgmstream on a synthesized ``.snr`` / ``.sns`` pair and read the PCM.

    Parameters
    ----------
    snr_bytes : bytes
        Reconstructed 8-byte EAAC header.
    sns_bytes : bytes
        Stream body.

    Returns
    -------
    tuple[numpy.ndarray | None, bool, int]
        ``(samples, corrupt, sample_rate)`` where ``samples`` is an
        ``int16 [frames, channels]`` array (or ``None`` if decoding produced no
        output), ``corrupt`` indicates vgmstream reported corruption, and
        ``sample_rate`` is the decoded rate (``0`` when there is no output).
    """
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / 'o.wav'
        log_text = _decode_snr_sns(snr_bytes, sns_bytes, out)
        corrupt = 'corrupt' in log_text.lower()
        if not out.exists():
            return None, corrupt, 0
        with wave.open(str(out), 'rb') as w:
            a = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2').reshape(
                -1, w.getnchannels())
            return a, corrupt, w.getframerate()


def _active_silence(a: npt.NDArray[np.int16]) -> float:
    """
    Median percentage of near-silent frames across signal-carrying channels.

    Parameters
    ----------
    a : numpy.ndarray
        An ``int16 [frames, channels]`` PCM array.

    Returns
    -------
    float
        Median percentage of near-silent windows; ``100.0`` if no channel
        carries signal.
    """
    act = []
    for c in range(a.shape[1]):
        ce = a[:, c].astype(np.float32) / 32768.0
        if np.sqrt((ce ** 2).mean()) <= _CHANNEL_SILENCE_RMS:
            continue
        fr = np.array(
            [np.sqrt((ce[i:i + 512] ** 2).mean()) for i in range(0, max(1,
                                                                        len(ce) - 512), 512)])
        act.append(np.mean(fr < _WINDOW_SILENCE_RMS) * 100)
    return float(np.median(act)) if act else 100.0


def _write_wav_multich(path: Path, a: npt.NDArray[np.int16], sr: int) -> None:
    """
    Write an ``int16 [frames, channels]`` array as a WAV file.

    Parameters
    ----------
    path : pathlib.Path
        Destination WAV path.
    a : numpy.ndarray
        PCM samples as ``int16 [frames, channels]``.
    sr : int
        Sample rate in Hz.

    Notes
    -----
    For more than two channels a ``WAVE_FORMAT_EXTENSIBLE`` header with a speaker
    channel mask is written so 5.1 maps to the right speakers; every channel is
    preserved (lossless) and reordered from EA order to canonical WAV order.
    """
    nch = a.shape[1]
    perm, mask = _WAV_LAYOUT.get(nch, (tuple(range(nch)), 0))
    raw = np.ascontiguousarray(a[:, list(perm)].astype('<i2')).tobytes()
    if nch <= _MAX_SIMPLE_WAV_CHANNELS:
        with wave.open(str(path), 'wb') as w:
            w.setnchannels(nch)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(raw)
        return
    block_align = nch * 2
    fmt = struct.pack('<HHIIHH', 0xFFFE, nch, sr, sr * block_align, block_align, 16)
    fmt += struct.pack('<HHI', 22, 16, mask) + _KSDATAFORMAT_SUBTYPE_PCM
    body = (b'WAVE' + b'fmt ' + struct.pack('<I', len(fmt)) + fmt + b'data' +
            struct.pack('<I', len(raw)) + raw)
    path.write_bytes(b'RIFF' + struct.pack('<I', len(body)) + body)


def _decode_ealayer3_stream(b: bytes, start: int, end: int, nsamp: int, out_wav: Path) -> None:
    """
    Decode one EALayer3 stream to WAV.

    Parameters
    ----------
    b : bytes
        Bank contents.
    start : int
        Stream start offset.
    end : int
        Stream end offset (exclusive).
    nsamp : int
        Declared total sample count.
    out_wav : pathlib.Path
        Destination WAV path.

    Raises
    ------
    RuntimeError
        If the stream has a bad sample rate or vgmstream fails for every
        candidate channel count.

    Notes
    -----
    Most streams are 1-/2-channel and decode directly. Some localised narrations
    are multi-substream surround (5.1 = 3 interleaved stereo substreams) which
    vgmstream only decodes at the true channel count; that is detected by
    escalating the channel count and picking the clean (non-corrupt, least-silent)
    decode.
    """
    ch, sr = _frame_params(b, start)
    if sr <= 0:
        msg = f'bad sample rate at 0x{start:x}'
        raise RuntimeError(msg)
    sns = b[start:end]
    # Base decode first; only escalate if it comes out broken (corrupt / silent).
    base_a, base_corrupt, base_sr = _decode_array(_synth_snr(_EAAC_EALAYER3_V1, ch, sr, nsamp), sns)
    if (base_a is not None and not base_corrupt
            and _active_silence(base_a) < _MAX_ACTIVE_SILENCE_PCT):
        _write_wav_multich(out_wav, base_a, base_sr)
        return
    best: tuple[npt.NDArray[np.int16], float, int] | None = None
    for nch in dict.fromkeys([ch, ch * 2, ch * 3]):  # 1->{1,2,3}, 2->{2,4,6}
        # Defensive only: the MPEG channel-mode table yields 1 or 2, so the largest candidate is
        # exactly _MAX_SURROUND_CHANNELS.
        if nch > _MAX_SURROUND_CHANNELS:  # pragma: no cover
            continue
        a, corrupt, asr = _decode_array(_synth_snr(_EAAC_EALAYER3_V1, nch, sr, nsamp), sns)
        if a is None or corrupt:
            continue
        sil = _active_silence(a)
        if best is None or sil < best[1]:
            best = (a, sil, asr)
        if sil < _CLEAN_SILENCE_PCT:
            break
    if best is None:
        msg = f'vgmstream failed for all channel counts at 0x{start:x}'
        raise RuntimeError(msg)
    # Preserve all channels (5.1 etc.) reordered to canonical WAV layout.
    _write_wav_multich(out_wav, best[0], best[2])


def _decode_sdt_stream(job: AudioJob) -> tuple[Path, bool, str]:
    """
    Decode one EALayer3 ``.sdt`` stream to WAV.

    Parameters
    ----------
    job : AudioJob
        Job carrying the stream byte range and declared ``nsamp``.

    Returns
    -------
    tuple[pathlib.Path, bool, str]
        Output WAV path, success flag, and a diagnostic message on failure.
    """
    out = job.out_wav
    if out.exists() and out.stat().st_size > _WAV_HEADER_SIZE:
        return out, True, 'skip'
    try:
        body = _read_range(job.source, job.start, job.end)
        _decode_ealayer3_stream(body, 0, len(body), job.nsamp, out)
        ok = out.exists() and out.stat().st_size > _WAV_HEADER_SIZE
    except (OSError, RuntimeError, ValueError) as e:
        return out, False, str(e)
    return out, ok, '' if ok else 'no output'


# --- Job building & dispatch -------------------------------------------------
def _stem_path(source: Path, index: int) -> Path:
    return source.with_name(f'{source.stem}_{index:04d}.wav')


def _is_schl(b: bytes) -> bool:
    """
    Return whether a payload should take the EA SCHl path.

    Parameters
    ----------
    b : bytes
        Full file contents.

    Returns
    -------
    bool
        ``True`` if an ``SCHl`` marker is present (covers PS2 ``.sdt`` banks and
        the PS2 ``.mus`` container, which wraps SCHl streams); ``False`` for EAAC
        ``.mus`` / ``.sdt`` payloads, which never contain ``SCHl``.
    """
    return _SCHL_MAGIC in b


def _write_subtitles(source: Path, subs: Sequence[tuple[int | None, str | None]]) -> None:
    sidecar = source.with_name(f'{source.stem}.subtitles.txt')
    lines = []
    for i, (h, t) in enumerate(subs):
        hash_text = f'{h:08x}' if h is not None else '00000000'
        lines.append(f'{i}\t{hash_text}\t{t or ""}')
    sidecar.write_text('\n'.join(lines) + '\n')


def _schl_jobs(source: Path, b: bytes) -> list[AudioJob]:
    return [
        AudioJob('schl', source, s, e, _stem_path(source, i))
        for i, (s, e) in enumerate(_carve_schl_streams(b))
    ]


def _mus_jobs(source: Path, b: bytes) -> list[AudioJob]:
    return [
        AudioJob('mus', source, do, end, _stem_path(source, i), header=hdr)
        for i, hdr, do, end in _parse_mus(b)
    ]


def _sdt_jobs(source: Path, b: bytes) -> list[AudioJob]:
    if b[:4] == _ADAT_MAGIC:
        recs = _parse_adat(b)
        streams = [(s, e, ns) for s, e, _nb, ns, _h, _t in recs]
        _write_subtitles(source, [(h, t) for _s, _e, _nb, _ns, h, t in recs])
    else:
        streams = [(s, e, ns) for s, e, _nb, ns in _find_streams(b, u32(b, 0, endian='>'))]
    jobs = []
    for i, (start, end, ns) in enumerate(streams):
        if _frame_params(b, start)[1] <= 0:
            continue
        jobs.append(AudioJob('sdt', source, start, end, _stem_path(source, i), nsamp=ns))
    return jobs


def jobs_for(path: str | Path) -> list[AudioJob]:
    """
    Build the per-stream decode jobs for one ``.mus`` / ``.sdt`` file.

    The container family is auto-detected by magic: any payload containing an
    ``SCHl`` marker takes the EA SCHl carve path; otherwise an EAAC ``.mus``
    (EA-XMA) or ``.sdt`` (EALayer3) path is chosen by extension. ADAT speech
    ``.sdt`` files have their ``<stem>.subtitles.txt`` sidecar written here as a
    side effect.

    Parameters
    ----------
    path : str | pathlib.Path
        Source ``.mus`` or ``.sdt`` file.

    Returns
    -------
    list[AudioJob]
        Picklable jobs, each producing one ``<stem>_<NNNN>.wav`` next to
        ``path``. Suitable for pooling across files with :py:func:`run_job`.
    """
    source = Path(path)
    b = source.read_bytes()
    if _is_schl(b):
        return _schl_jobs(source, b)
    if source.suffix.lower() == '.mus':
        return _mus_jobs(source, b)
    return _sdt_jobs(source, b)


def run_job(job: AudioJob) -> tuple[Path, bool, str]:
    """
    Decode a single :py:class:`AudioJob` to its WAV output.

    This is a module-level worker so it can be dispatched through a process pool.

    Parameters
    ----------
    job : AudioJob
        The job to decode.

    Returns
    -------
    tuple[pathlib.Path, bool, str]
        The output WAV path, a success flag, and a diagnostic message (empty or
        ``'skip'`` on success).
    """
    match job.kind:
        case 'schl':
            return _decode_schl(job)
        case 'mus':
            return _decode_mus_segment(job)
        case _:
            return _decode_sdt_stream(job)


def convert_file(path: str | Path) -> list[Path]:
    """
    Convert one ``.mus`` / ``.sdt`` file to WAV in place.

    Each stream/segment is written next to the source as ``<stem>_<NNNN>.wav``
    (4-digit). ADAT speech ``.sdt`` files also get a ``<stem>.subtitles.txt``
    sidecar. Failed streams are logged and skipped.

    Parameters
    ----------
    path : str | pathlib.Path
        Source ``.mus`` or ``.sdt`` file.

    Returns
    -------
    list[pathlib.Path]
        Paths of the WAV files successfully written.
    """
    written = []
    for job in jobs_for(path):
        out, ok, msg = run_job(job)
        if ok:
            written.append(out)
        else:
            log.warning('Failed to decode `%s` (stream at 0x%x): %s.', job.source, job.start, msg)
    return written
