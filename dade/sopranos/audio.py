"""
Convert the game's PlayStation 2 audio to WAV.

Sound effects and speech ship as a ``.MSH`` header paired with a ``.MSB`` body. The header lists
every sound's offset, length, and sample rate; the body is nothing but concatenated PS-ADPCM.

Music ships as a ``.MIH`` header paired with a ``.MIB`` body, which is Sony's MultiStream layout:
the channels are interleaved in fixed-size blocks and the header records the block size, the channel
count, and the sample rate.

Spoken dialogue lives in ``.VO2`` files inside ``AUDIO_P.FS``. Those are chunk streams that
interleave ``AUDO`` blocks of PS-ADPCM with ``TIME``, ``GTAG``, and ``LSYN`` lip-sync records, so
the audio has to be stitched back together from the ``AUDO`` payloads alone.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import array
import logging
import struct

from dade.common.exceptions import InvalidFormatError
from dade.common.vag import decode_vag_adpcm
from dade.common.wav import wrap_pcm

from .typing import SoundEntry

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('VOICE_RATE', 'convert_bank', 'convert_stream', 'convert_voice', 'decode_stream',
           'read_sound_bank', 'read_stream_header', 'read_voice_adpcm')

log = logging.getLogger(__name__)

VOICE_RATE = 48000
"""Sample rate in Hz of the ``.VO2`` dialogue, which the files do not record directly.

:meta hide-value:
"""

_BANK_ENTRY_OFFSET = 0x0C
_BANK_ENTRY_SIZE = 16
_MIN_HEADER_SIZE = 0x18
_AUDIO_TAG = b'AUDO'
_CHUNK_HEADER_SIZE = 16
_AUDIO_PAYLOAD_OFFSET = 64  # The 16-byte chunk header plus a 48-byte sub-header.


def read_sound_bank(data: bytes) -> tuple[SoundEntry, ...]:
    """
    Parse a ``.MSH`` sound bank header.

    Entries are 16 bytes each and start at offset ``0x0C``. An entry is playable only when both its
    length and its sample rate are non-zero: some banks reserve the first slot to carry a default
    rate, and that slot's offset overlaps the first real sound.

    The second word is a sequential index in some banks and a name hash in others, so it is reported
    verbatim as :py:attr:`SoundEntry.identifier` while :py:attr:`SoundEntry.number` counts playable
    entries.

    Parameters
    ----------
    data : bytes
        The whole ``.MSH`` file.

    Returns
    -------
    tuple[SoundEntry, ...]
        One entry per playable sound, in the order the header lists them.

    Raises
    ------
    InvalidFormatError
        If the header is truncated or declares more entries than it can hold.
    """
    if len(data) < _BANK_ENTRY_OFFSET:
        msg = 'Sound bank header is too small.'
        raise InvalidFormatError(msg)
    count = struct.unpack_from('<I', data, 8)[0]
    if _BANK_ENTRY_OFFSET + count * _BANK_ENTRY_SIZE > len(data):
        msg = f'Sound bank header declares {count} entries but is only {len(data)} bytes.'
        raise InvalidFormatError(msg)
    entries: list[SoundEntry] = []
    for i in range(count):
        size, identifier, offset, rate = struct.unpack_from(
            '<4I', data, _BANK_ENTRY_OFFSET + i * _BANK_ENTRY_SIZE)
        if size and rate:
            entries.append(SoundEntry(len(entries), offset, size, rate, identifier))
    return tuple(entries)


def convert_bank(header: Path, body: Path, output_dir: Path) -> tuple[Path, ...]:
    """
    Decode every sound in a ``.MSH``/``.MSB`` pair to WAV.

    Parameters
    ----------
    header : Path
        The ``.MSH`` file.
    body : Path
        The ``.MSB`` file holding the PS-ADPCM data.
    output_dir : Path
        Directory to write into. It is created if missing.

    Returns
    -------
    tuple[Path, ...]
        The WAV files written, named ``<stem>_<number>.wav``.
    """
    entries = read_sound_bank(header.read_bytes())
    blob = body.read_bytes()
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for entry in entries:
        if entry.offset >= len(blob):
            log.warning('Sound %d of `%s` starts past the end of the body.', entry.number,
                        header.name)
            continue
        available = min(entry.size, len(blob) - entry.offset)
        pcm = decode_vag_adpcm(blob, entry.offset, available)
        destination = output_dir / f'{header.stem}_{entry.number:03d}.wav'
        destination.write_bytes(wrap_pcm(pcm.tobytes(), rate=entry.rate))
        written.append(destination)
    return tuple(written)


def read_voice_adpcm(data: bytes) -> bytes:
    """
    Stitch the PS-ADPCM out of a ``.VO2`` dialogue file.

    The file interleaves ``AUDO`` blocks with lip-sync records, so only the ``AUDO`` payloads are
    kept. Each block's header records the block's total length, including the 16-byte header, and a
    further 48-byte sub-header precedes the samples. Decoding those 48 bytes as audio would drive
    the ADPCM history to zero once per block and put an audible tick at every block boundary.

    Parameters
    ----------
    data : bytes
        The whole ``.VO2`` file.

    Returns
    -------
    bytes
        The concatenated PS-ADPCM, empty when the file carries no audio.
    """
    out = bytearray()
    at = 0
    while at + _CHUNK_HEADER_SIZE <= len(data):
        if data[at:at + 4] == _AUDIO_TAG:
            total = struct.unpack_from('<I', data, at + 8)[0]
            if total > _AUDIO_PAYLOAD_OFFSET and at + total <= len(data):
                out += data[at + _AUDIO_PAYLOAD_OFFSET:at + total]
                at += total
                continue
        at += 1
    return bytes(out)


def convert_voice(path: Path, destination: Path, *, rate: int = VOICE_RATE) -> Path | None:
    """
    Decode one ``.VO2`` dialogue file to WAV.

    Parameters
    ----------
    path : Path
        The ``.VO2`` file.
    destination : Path
        The WAV file to write.
    rate : int
        Sample rate in Hz to record in the WAV header.

    Returns
    -------
    Path | None
        The file written, or ``None`` when the ``.VO2`` holds only lip-sync data.
    """
    if not (adpcm := read_voice_adpcm(path.read_bytes())):
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(wrap_pcm(decode_vag_adpcm(adpcm).tobytes(), rate=rate))
    return destination


def read_stream_header(data: bytes) -> tuple[int, int, int, int]:
    """
    Parse a ``.MIH`` music stream header.

    Parameters
    ----------
    data : bytes
        The whole ``.MIH`` file.

    Returns
    -------
    tuple[int, int, int, int]
        The channel count, sample rate in Hz, interleave block size in bytes, and block count.

    Raises
    ------
    InvalidFormatError
        If the header is truncated or declares an unusable channel count or block size.
    """
    if len(data) < _MIN_HEADER_SIZE:
        msg = 'Music stream header is too small.'
        raise InvalidFormatError(msg)
    channels, rate, interleave, blocks = struct.unpack_from('<4I', data, 8)
    if not 1 <= channels <= 8 or not interleave:  # noqa: PLR2004
        msg = f'Music stream header declares {channels} channels and a {interleave}-byte block.'
        raise InvalidFormatError(msg)
    return channels, rate, interleave, blocks


def decode_stream(data: bytes, channels: int, interleave: int) -> bytes:
    """
    De-interleave and decode a ``.MIB`` body to interleaved 16-bit PCM.

    Parameters
    ----------
    data : bytes
        The whole ``.MIB`` file.
    channels : int
        Number of channels.
    interleave : int
        Interleave block size in bytes, per channel.

    Returns
    -------
    bytes
        Interleaved signed 16-bit PCM frames.
    """
    per_channel = [bytearray() for _ in range(channels)]
    stride = interleave * channels
    for block in range(0, len(data), stride):
        for channel in range(channels):
            start = block + channel * interleave
            per_channel[channel] += data[start:start + interleave]
    decoded = [decode_vag_adpcm(bytes(chunk)) for chunk in per_channel]
    if channels == 1:
        return decoded[0].tobytes()
    frames = min(len(part) for part in decoded)
    out = array.array('h')
    for i in range(frames):
        out.extend(part[i] for part in decoded)
    return out.tobytes()


def convert_stream(header: Path, body: Path, destination: Path) -> Path:
    """
    Decode a ``.MIH``/``.MIB`` music pair to a single WAV file.

    Parameters
    ----------
    header : Path
        The ``.MIH`` file.
    body : Path
        The ``.MIB`` file holding the interleaved PS-ADPCM data.
    destination : Path
        The WAV file to write.

    Returns
    -------
    Path
        The file written.
    """
    channels, rate, interleave, _blocks = read_stream_header(header.read_bytes())
    pcm = decode_stream(body.read_bytes(), channels, interleave)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(wrap_pcm(pcm, channels=channels, rate=rate))
    return destination
