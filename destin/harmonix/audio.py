"""
Decode the games' audio to WAV.

Amplitude ``.str`` streams become stereo WAV, Amplitude ``.bnk``/``.nse`` banks and FreQuency
``.hd``/``.bd`` SCEI sound banks become per-sample WAV folders (both via PS2 VAG-ADPCM decoding).
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import array
import logging
import struct

from destin.common.exceptions import InvalidFormatError
from destin.common.json import write_json
from destin.common.utils import safe_name
from destin.common.wav import wrap_pcm

if TYPE_CHECKING:
    from pathlib import Path

    from .typing import BankMeta, SampleMeta

__all__ = ('EXTENSIONS', 'STR_BLOCK', 'STR_RATE', 'bnk_to_json', 'convert', 'convert_disc_audio',
           'decode_vag_adpcm', 'parse_sd_bank', 'split_all_banks', 'split_bank', 'split_sd_bank',
           'str_to_wav')

log = logging.getLogger(__name__)

EXTENSIONS = frozenset({'.str'})
"""File extensions handled by :py:func:`convert`.

:meta hide-value:
"""

STR_RATE = 48000
"""Default sample rate (Hz) for ``.str`` streams (the rate is not stored in the file).

:meta hide-value:
"""
STR_BLOCK = 512
"""Default interleave block size in bytes (per channel) for ``.str`` streams.

:meta hide-value:
"""

_VAG_COEFFICIENTS = ((0, 0), (60, 0), (115, -52), (98, -55), (122, -60))
_VAG_FRAME = 16
_VAG_DEFAULT_RATE = 22050
_VAG_END = 1
_VAG_END_MUTE = 7

# FreQuency SCEI sound bank chunk tags. Each 4-char tag is written as a little-endian u32, so on
# disk the bytes read reversed: 'SCEI' -> b'IECS', 'Vers' -> b'sreV', 'Head' -> b'daeH', etc.
_SD_VERS = b'IECSsreV'
_SD_HEAD = b'IECSdaeH'
_SD_VAGI = b'IECSigaV'
_SD_MAX_VAGS = 4096
_SAMP_MIN_SIZE = 12  # SAMP header: magic plus the u32 table size.
_SAMP_HEADER_SIZE = 8  # 'SAMP' tag plus the u32 table size.
_NAME_MAX_LEN = 128  # Upper bound on a plausible sample-name length.
_PCM_MIN = -32768
_PCM_MAX = 32767
_NIBBLE_SIGN = 8  # A 4-bit ADPCM sample of 8..15 is negative.
_NIBBLE_SPAN = 16


def str_to_wav(data: bytes, *, rate: int = STR_RATE, block: int = STR_BLOCK) -> bytes:
    """
    De-block-interleave a stereo ``.str`` stream into a standard stereo WAV.

    Amplitude streams interleave the left and right channels in ``block``-byte chunks
    (``[L][R][L][R]...``) rather than per sample.

    Parameters
    ----------
    data : bytes
        The raw ``.str`` stream.
    rate : int
        Output sample rate in Hz.
    block : int
        Interleave block size in bytes (per channel).

    Returns
    -------
    bytes
        A complete stereo 16-bit PCM WAV.
    """
    left, right = bytearray(), bytearray()
    for i in range(len(data) // block):
        (left if i % 2 == 0 else right).extend(data[i * block:(i + 1) * block])
    n = min(len(left), len(right)) // 2
    interleaved = array.array('h', bytes(n * 4))
    ls, rs = array.array('h'), array.array('h')
    ls.frombytes(bytes(left[:n * 2]))
    rs.frombytes(bytes(right[:n * 2]))
    interleaved[0::2] = ls
    interleaved[1::2] = rs
    pcm = interleaved.tobytes()
    return wrap_pcm(pcm, rate=rate, channels=2)


def convert(path: Path) -> Path | None:
    """
    Convert a ``.str`` stream to a sibling ``.wav``, leaving the original in place.

    Parameters
    ----------
    path : pathlib.Path
        The ``.str`` file.

    Returns
    -------
    pathlib.Path
        The written WAV path.
    """
    out = path.with_suffix('.wav')
    out.write_bytes(str_to_wav(path.read_bytes(), rate=STR_RATE, block=STR_BLOCK))
    log.debug('Stream `%s` -> `%s`.', path.name, out.name)
    return out


def decode_vag_adpcm(data: bytes, start: int = 0, max_bytes: int | None = None) -> array.array[int]:
    """
    Decode PS2 VAG-ADPCM into 16-bit mono PCM.

    Parameters
    ----------
    data : bytes
        The buffer containing VAG frames.
    start : int
        Byte offset of the first frame.
    max_bytes : int | None
        Stop after this many bytes (in addition to the end flag); ``None`` reads to the buffer end.

    Returns
    -------
    array.array[int]
        Signed 16-bit PCM samples.
    """
    hist1 = hist2 = 0
    out = array.array('h')
    end = len(data) if max_bytes is None else min(len(data), start + max_bytes)
    frame = start
    while frame + _VAG_FRAME <= end:
        predictor_shift = data[frame]
        shift = predictor_shift & 0xF
        predictor = predictor_shift >> 4
        if predictor >= len(_VAG_COEFFICIENTS):
            predictor = 0
        flag = data[frame + 1]
        if flag == _VAG_END_MUTE:
            break
        c0, c1 = _VAG_COEFFICIENTS[predictor]
        for nibble_byte in range(14):
            packed = data[frame + 2 + nibble_byte]
            for nibble in (packed & 0xF, packed >> 4):
                t = nibble - _NIBBLE_SPAN if nibble >= _NIBBLE_SIGN else nibble
                s = ((t << 12) >> shift) + ((hist1 * c0 + hist2 * c1) >> 6)
                s = _PCM_MIN if s < _PCM_MIN else min(s, _PCM_MAX)
                out.append(s)
                hist2 = hist1
                hist1 = s
        frame += _VAG_FRAME
        if flag == _VAG_END:
            break
    return out


def _bank_names(data: bytes, limit: int | None = None) -> list[str]:
    sanm = data.find(b'SANM')
    names: list[str] = []
    off = sanm + 12 if sanm >= 0 else len(data)
    while (limit is None or len(names) < limit) and off + 4 <= len(data):
        ln = struct.unpack_from('<I', data, off)[0]
        if 0 < ln < _NAME_MAX_LEN and off + 4 + ln <= len(data):
            names.append(data[off + 4:off + 4 + ln].decode('latin-1'))
            off += 4 + ln
        else:
            break
    return names


def split_bank(bnk: Path) -> Path | None:
    """
    Split a ``.bnk`` sample bank into per-sample WAVs using the sibling ``.nse`` VAG-ADPCM blob.

    The ``.bnk`` is a metadata index (a ``SAMP`` descriptor table plus ``SANM`` names); the audio
    lives in the ``.nse`` blob, indexed by each descriptor's data offset.

    Parameters
    ----------
    bnk : pathlib.Path
        The ``.bnk`` file.

    Returns
    -------
    pathlib.Path | None
        The output directory, or ``None`` if there is no usable sibling ``.nse``.
    """
    nse = bnk.with_suffix('.nse')
    if not nse.is_file():
        return None
    data = bnk.read_bytes()
    if data[:4] != b'SAMP' or len(data) < _SAMP_HEADER_SIZE:
        return None
    count = struct.unpack_from('<I', data, 4)[0] // 22
    rates = [struct.unpack_from('<H', data, 8 + i * 22 + 8)[0] for i in range(count)]
    offsets = [struct.unpack_from('<I', data, 8 + i * 22 + 18)[0] for i in range(count)]
    names = _bank_names(data, count)
    blob = nse.read_bytes()
    out_dir = bnk.with_suffix('')
    out_dir.mkdir(parents=True, exist_ok=True)
    samples: list[dict[str, object]] = []
    used: dict[str, int] = {}
    for i in range(count):
        nxt = min((o for o in offsets if o > offsets[i]), default=len(blob))
        pcm = decode_vag_adpcm(blob, offsets[i], nxt - offsets[i])
        if not len(pcm):
            continue
        name = names[i] if i < len(names) else f'sample_{i:03d}'
        stem = safe_name(name, allow_spaces=True)
        filename = f'{stem}.wav'
        seen = used.get(filename, 0)
        used[filename] = seen + 1
        if seen:
            filename = f'{stem}_{seen}.wav'
        rate = rates[i] or _VAG_DEFAULT_RATE
        body = pcm.tobytes()
        (out_dir / filename).write_bytes(wrap_pcm(body, rate=rate))
        samples.append({
            'name': name,
            'file': filename,
            'rate': rate,
            'offset': offsets[i],
            'pcm_samples': len(pcm)
        })
    manifest = {'source': bnk.name, 'nse': nse.name, 'sample_count': count, 'samples': samples}
    write_json(out_dir / 'manifest.json', manifest, ensure_ascii=False, trailing_newline=False)
    log.debug('Bank `%s`: %d/%d samples -> `%s/`.', bnk.name, len(samples), count, out_dir.name)
    return out_dir


def bnk_to_json(data: bytes) -> BankMeta:
    """
    Decode a ``SAMP`` sample bank's descriptor table to a metadata dict.

    Parameters
    ----------
    data : bytes
        The ``.bnk`` file contents.

    Returns
    -------
    BankMeta
        Bank metadata.

    Raises
    ------
    InvalidFormatError
        If the data is not a ``SAMP`` bank or has no sample names.
    """
    if data[:4] != b'SAMP' or len(data) < _SAMP_MIN_SIZE:
        msg = 'Not a `SAMP` bank.'
        raise InvalidFormatError(msg)
    table_size = struct.unpack_from('<I', data, 4)[0]
    names = _bank_names(data)
    count = len(names)
    if not count:
        msg = 'SAMP bank has no sample names.'
        raise InvalidFormatError(msg)
    sanm = data.find(b'SANM')
    stride = ((sanm - 8) if sanm >= 0 else table_size) // count
    samples: list[SampleMeta] = []
    for i in range(count):
        p = 8 + i * stride
        # The stride is derived from the ``SANM`` offset and the name count, and every name lies
        # past that offset, so the last descriptor always fits; this only bounds a hostile file.
        if p + 10 > len(data):  # pragma: no cover
            break
        samples.append({
            'name': names[i],
            'type': struct.unpack_from('<I', data, p)[0],
            'channels': struct.unpack_from('<I', data, p + 4)[0],
            'rate': struct.unpack_from('<H', data, p + 8)[0]
        })
    return {
        'magic': 'SAMP',
        'table_size': table_size,
        'descriptor_stride': stride,
        'sample_count': count,
        'samples': samples
    }


def parse_sd_bank(data: bytes) -> tuple[int, list[tuple[int, int, int]]] | None:
    """
    Parse a FreQuency SCEI (``sceSdBank``) ``.hd`` header's VAG table.

    The header is a sequence of ``SCEI<tag>`` chunks (each 4-char tag stored little-endian). The
    ``Head`` chunk records the ``.bd`` body size; the ``Vagi`` chunk holds ``count`` u32 offsets
    (relative to the chunk start), each pointing to an 8-byte record ``{u32 bdOffset, u16 rate,
    u16 flags}``.

    Parameters
    ----------
    data : bytes
        The ``.hd`` file contents.

    Returns
    -------
    tuple[int, list[tuple[int, int, int]]] | None
        ``(bd_size, [(bd_offset, rate, flags), ...])``, or ``None`` if not a valid SCEI bank.
    """
    if data[:8] != _SD_VERS:
        return None
    head, vagi = data.find(_SD_HEAD), data.find(_SD_VAGI)
    if head < 0 or vagi < 0 or vagi + 16 > len(data):
        return None
    bd_size = struct.unpack_from('<I', data, head + 16)[0]  # Head: hdrSize, hdSize, bdSize, ...
    count = struct.unpack_from('<I', data, vagi + 12)[0]
    if not 0 < count <= _SD_MAX_VAGS or vagi + 16 + count * 4 > len(data):
        return None
    vags: list[tuple[int, int, int]] = []
    for off in struct.unpack_from(f'<{count}I', data, vagi + 16):
        rec = vagi + off
        if rec + 8 > len(data):
            return None
        vags.append(struct.unpack_from('<IHH', data, rec))  # bdOffset, rate, flags
    return bd_size, vags


def split_sd_bank(hd: Path) -> Path | None:
    """
    Split a FreQuency ``.hd`` SCEI bank into per-sample WAVs using the sibling ``.bd`` VAG body.

    Each VAG's data spans ``[bd_offset[i], bd_offset[i + 1])`` (the last runs to the body size) and
    is decoded as PS2 VAG-ADPCM at the rate stored in the header.

    Parameters
    ----------
    hd : pathlib.Path
        The ``.hd`` header file.

    Returns
    -------
    pathlib.Path | None
        The output directory, or ``None`` if there is no usable sibling ``.bd`` or valid header.
    """
    bd = hd.with_suffix('.bd')
    if not bd.is_file():
        return None
    parsed = parse_sd_bank(hd.read_bytes())
    if parsed is None:
        return None
    bd_size, vags = parsed
    blob = bd.read_bytes()
    limit = min(bd_size, len(blob))
    out_dir = hd.with_suffix('')
    out_dir.mkdir(parents=True, exist_ok=True)
    samples: list[dict[str, object]] = []
    for i, (offset, rate, flags) in enumerate(vags):
        nxt = vags[i + 1][0] if i + 1 < len(vags) else limit
        pcm = decode_vag_adpcm(blob, offset, max(0, nxt - offset))
        if not len(pcm):
            continue
        sample_rate = rate or _VAG_DEFAULT_RATE
        body = pcm.tobytes()
        filename = f'sample_{i:03d}.wav'
        (out_dir / filename).write_bytes(wrap_pcm(body, rate=sample_rate))
        samples.append({
            'index': i,
            'file': filename,
            'rate': sample_rate,
            'bd_offset': offset,
            'flags': flags,
            'pcm_samples': len(pcm)
        })
    manifest = {'source': hd.name, 'bd': bd.name, 'vag_count': len(vags), 'samples': samples}
    write_json(out_dir / 'manifest.json', manifest, ensure_ascii=False, trailing_newline=False)
    log.debug('SCEI bank `%s`: %d/%d VAGs -> `%s/`.', hd.name, len(samples), len(vags),
              out_dir.name)
    return out_dir


def split_all_banks(root: Path) -> tuple[int, int]:
    """
    Split every sample bank under ``root`` (post-extraction pass).

    Amplitude ``.bnk`` banks with a sibling ``.nse`` and FreQuency ``.hd`` banks with a sibling
    ``.bd`` are split into per-sample WAV folders; ``.bnk`` banks without an ``.nse`` get a
    ``.bnk.json`` metadata sidecar.

    Parameters
    ----------
    root : pathlib.Path
        The extraction root.

    Returns
    -------
    tuple[int, int]
        ``(banks_split, json_only)`` counts.
    """
    split = json_only = 0
    for bnk in root.rglob('*.bnk'):
        if bnk.with_suffix('.nse').is_file() and split_bank(bnk):
            split += 1
            continue
        try:
            bank = bnk_to_json(bnk.read_bytes())
        except InvalidFormatError:
            continue
        write_json(bnk.with_name(f'{bnk.name}.json'),
                   bank,
                   ensure_ascii=False,
                   trailing_newline=False)
        json_only += 1
    for hd in root.rglob('*.hd'):
        if split_sd_bank(hd):
            split += 1
    return split, json_only


def convert_disc_audio(src_dir: Path,
                       out_dir: Path,
                       *,
                       rate: int = STR_RATE,
                       block: int = STR_BLOCK) -> int:
    """
    Convert every disc streaming song (``*.str``) in ``src_dir`` to a WAV in ``out_dir``.

    Parameters
    ----------
    src_dir : pathlib.Path
        Directory of disc ``.str`` songs (e.g. the disc ``AUDIO`` directory).
    out_dir : pathlib.Path
        Output directory (created if missing).
    rate : int
        Output sample rate in Hz.
    block : int
        Interleave block size in bytes (per channel).

    Returns
    -------
    int
        The number of songs converted.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    converted = 0
    for src in sorted(src_dir.iterdir()):
        if src.suffix.lower() == '.str':
            wav = str_to_wav(src.read_bytes(), rate=rate, block=block)
            (out_dir / f'{src.stem}.wav').write_bytes(wav)
            converted += 1
    return converted
