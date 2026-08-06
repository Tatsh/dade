"""Fixtures for the Monopoly 2008 tests."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, cast
import importlib
import struct
import subprocess as sp
import wave

from destin.monopoly08 import audio
import numpy as np
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence
    from types import ModuleType
    from typing import Any, BinaryIO, TypeAlias

    from pytest_mock import MockerFixture

    Builder: TypeAlias = Callable[..., bytes]
    """A fixture-provided callable that builds a synthetic file."""

_GPU_DXT1 = 0x12
"""Xbox 360 GPU texture format code for DXT1."""
_GPU_8888 = 0x06
"""Xbox 360 GPU texture format code for A8R8G8B8."""
_SHPX_ENTRY_OFFSET = 0x20
"""Offset the synthetic ``SHPX`` directory points its single entry header at."""
_SNR_TABLE = 0x3600
"""Offset of the EAAC SNR header table inside a ``.mus`` container."""
_MESH_HEADER_SIZE = 0xC8
"""Size of the mesh container header, up to and including the section table."""
_PH_MARKER = b'PH'
"""Two-byte submesh marker on the big-endian geometry path."""
_PH_HEADER_SIZE = 0x4E
"""Bytes between the ``PH`` marker and the start of a submesh's vertex buffer."""


def _swap(data: bytes, group: int) -> bytes:
    """
    Reverse each ``group``-byte run, matching the Xbox 360 8in16/8in32 endian swap.

    Parameters
    ----------
    data : bytes
        The bytes to swap.
    group : int
        Group size in bytes.

    Returns
    -------
    bytes
        The swapped bytes.
    """
    return b''.join(data[i:i + group][::-1] for i in range(0, len(data), group))


class VgmPlan(NamedTuple):
    """How the stubbed ``vgmstream-cli`` should behave for one invocation."""

    channels: int = 1
    """Channel count of the WAV the stub writes."""
    frames: int = 2048
    """Frame count of the WAV the stub writes."""
    message: str = ''
    """Text reported on stdout, which the caller scans for ``corrupt``."""
    mode: str = 'loud'
    """Signal shape: ``'loud'``, ``'silent'`` or ``'half'`` (half loud, half silent)."""
    output: bool = True
    """Whether a WAV is written at all."""
    rate: int = 22050
    """Sample rate of the WAV the stub writes."""
    returncode: int = 0
    """Exit status; a non-zero value raises :py:class:`subprocess.CalledProcessError`."""


def _samples(plan: VgmPlan) -> bytes:
    one = np.resize(np.array([8000, -8000], np.int16), plan.frames)
    if plan.mode == 'silent':
        one = np.zeros(plan.frames, np.int16)
    elif plan.mode == 'half':
        one[plan.frames // 2:] = 0
    return np.tile(one[:, None], (1, plan.channels)).astype('<i2').tobytes()


def _write_wav(path: Path, plan: VgmPlan) -> None:
    with wave.open(str(path), 'wb') as handle:
        handle.setnchannels(plan.channels)
        handle.setsampwidth(2)
        handle.setframerate(plan.rate)
        handle.writeframes(_samples(plan))


def _requested_channels(path: Path) -> int:
    raw = path.read_bytes()
    if len(raw) != 8:  # Not a synthesized EAAC .snr header, so no plan can match.
        return 0
    return ((int.from_bytes(raw[:4], 'big') >> 18) & 0x3F) + 1


class _FakeStat(NamedTuple):
    """Stand-in for :py:class:`os.stat_result` exposing only the size."""

    st_size: int
    """Reported file size in bytes."""


class _OversizedPath:
    """A path-like whose reported size exceeds the real file, faking a truncated archive."""
    def __init__(self, path: Path, claimed_size: int) -> None:
        self._claimed_size = claimed_size
        self._path = path

    @property
    def stem(self) -> str:
        """The real path's stem."""
        return self._path.stem

    def open(self, mode: str = 'rb') -> BinaryIO:
        """
        Open the real file.

        Parameters
        ----------
        mode : str
            Mode passed through to :py:meth:`pathlib.Path.open`.

        Returns
        -------
        typing.BinaryIO
            The opened file object.
        """
        return cast('BinaryIO', self._path.open(mode))

    def stat(self) -> _FakeStat:
        """
        Report the inflated size.

        Returns
        -------
        _FakeStat
            A stat-like object carrying the claimed size.
        """
        return _FakeStat(self._claimed_size)


@pytest.fixture
def make_refpack() -> Callable[[bytes, int, int], bytes]:
    """
    Build a RefPack stream around an already-encoded opcode body.

    Returns
    -------
    collections.abc.Callable[[bytes, int, int], bytes]
        A callable taking the opcode body, the declared uncompressed size and the header flag
        byte.
    """
    def build(body: bytes, outsize: int, flags: int = 0x10) -> bytes:
        szlen = 4 if flags & 0x01 else 3
        head = bytes((flags, 0xFB))
        if flags & 0x80:  # A compressed-size field precedes the uncompressed size.
            head += (len(body) + 2 + szlen * 2).to_bytes(szlen, 'big')
        return head + outsize.to_bytes(szlen, 'big') + body

    return build


@pytest.fixture
def make_refpack_stream() -> Callable[[bytes], bytes]:
    """
    Encode a payload as a RefPack stream of literal runs only.

    Returns
    -------
    collections.abc.Callable[[bytes], bytes]
        A callable turning a payload into a stream that decodes back to it.
    """
    def build(payload: bytes) -> bytes:
        body = bytearray()
        i = 0
        while len(payload) - i >= 4:
            run = min(112, (len(payload) - i) // 4 * 4)
            body.append(0xE0 + (run - 4) // 4)
            body += payload[i:i + run]
            i += run
        body.append(0xFC + len(payload) - i)  # EOF plus the trailing sub-word literals.
        body += payload[i:]
        return bytes((0x10, 0xFB)) + len(payload).to_bytes(3, 'big') + bytes(body)

    return build


@pytest.fixture
def make_rpk() -> Callable[..., bytes]:
    """
    Build a decompressed ``STRM``/``MRTS`` resource pack container.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking the asset payload tuples, the string table and the byte order.
    """
    def build(assets: Sequence[tuple[int, int, bytes]] = (),
              strings: Sequence[str] = (),
              endian: str = '>',
              fillers: int = 0,
              *,
              truncate_first_aset: bool = False) -> bytes:
        magic, tags = ((b'STRM', (b'AGRP', b'ASET', b'STRS')) if endian == '>' else
                       (b'MRTS', (b'PRGA', b'TESA', b'SRTS')))
        table = b''.join(s.encode('latin1') + b'\x00' for s in strings)
        table += b'\x00' * (-len(table) % 4)
        agrp_size = 8 + len(assets) * 40 + fillers * 8
        strs_size = 8 + len(table)
        data_start = 8 + agrp_size + strs_size + 8
        group = bytearray(tags[0] + struct.pack(endian + 'I', agrp_size))
        group += (b'PAD ' + struct.pack(endian + 'I', 8)) * fillers
        payloads = bytearray()
        for i, (name_hash, type_id, payload) in enumerate(assets):
            size = 0 if truncate_first_aset and i == 0 else 40
            group += tags[1] + struct.pack(endian + 'I', size)
            group += struct.pack(endian + '8I', name_hash, type_id, 0, 0,
                                 data_start + len(payloads), len(payload), 0, 0)
            payloads += payload
        return (magic + struct.pack(endian + 'I', data_start + len(payloads)) + bytes(group) +
                tags[2] + struct.pack(endian + 'I', strs_size) + table + b'DATA' +
                struct.pack(endian + 'I', 8 + len(payloads)) + bytes(payloads))

    return build


@pytest.fixture
def make_big() -> Callable[[Sequence[tuple[str, bytes]]], bytes]:
    """
    Build an EA ``BIGF`` archive from ``(name, payload)`` pairs.

    Returns
    -------
    collections.abc.Callable[[collections.abc.Sequence[tuple[str, bytes]]], bytes]
        A callable taking the entries and returning the complete archive.
    """
    def build(entries: Sequence[tuple[str, bytes]]) -> bytes:
        header_len = 16 + sum(9 + len(name.encode('latin1')) for name, _ in entries)
        toc = bytearray()
        payload = bytearray()
        offset = header_len
        for name, data in entries:
            toc += struct.pack('>II', offset, len(data)) + name.encode('latin1') + b'\x00'
            payload += data
            offset += len(data)
        return (b'BIGF' + struct.pack('<I', header_len + len(payload)) +
                struct.pack('>II', len(entries), header_len) + bytes(toc) + bytes(payload))

    return build


@pytest.fixture
def serial_pool(mocker: MockerFixture) -> Any:
    """
    Run the pipeline's process-pool work in the test process.

    Returns
    -------
    typing.Any
        The installed patcher.
    """
    def factory(**_kwargs: Any) -> Any:
        pool = mocker.MagicMock()
        pool.__enter__.return_value = pool
        pool.__exit__.return_value = False
        pool.map = lambda fn, items: [fn(item) for item in items]
        return pool

    return mocker.patch('destin.monopoly08.pipeline.ProcessPoolExecutor', side_effect=factory)


@pytest.fixture
def audio_module() -> Iterator[ModuleType]:
    """
    Reload :py:mod:`destin.monopoly08.audio` so its cached binary lookup starts empty.

    Yields
    ------
    types.ModuleType
        The freshly reloaded module.
    """
    yield importlib.reload(audio)
    importlib.reload(audio)


@pytest.fixture
def fake_vgmstream(mocker: MockerFixture, tmp_path: Path,
                   monkeypatch: pytest.MonkeyPatch) -> Callable[..., Any]:
    """
    Replace ``vgmstream-cli`` with a stub writing WAVs according to per-channel plans.

    Returns
    -------
    collections.abc.Callable[..., typing.Any]
        A callable taking the default plan and an optional per-requested-channel-count override
        map, and returning the installed mock.
    """
    binary = tmp_path / 'vgmstream-cli'
    binary.write_bytes(b'')
    monkeypatch.setenv('VGMSTREAM_CLI', str(binary))

    def install(default: VgmPlan | None = None, plans: Mapping[int, VgmPlan] | None = None) -> Any:
        fallback = default if default is not None else VgmPlan()

        def run(args: Sequence[str], **_kwargs: Any) -> sp.CompletedProcess[str]:
            plan = (plans or {}).get(_requested_channels(Path(args[-1])), fallback)
            if plan.output:
                _write_wav(Path(args[args.index('-o') + 1]), plan)
            if plan.returncode:
                raise sp.CalledProcessError(plan.returncode, list(args), plan.message, '')
            return sp.CompletedProcess(list(args), 0, plan.message, '')

        return mocker.patch('subprocess.run', side_effect=run)

    return install


@pytest.fixture
def make_sns() -> Callable[..., bytes]:
    """
    Build a run of EA-SNS blocks forming one EALayer3 stream.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking the MPEG version/rate/channel-mode codes, the per-block sample counts
        and the block payload size.
    """
    def build(version: int = 3,
              rate_index: int = 0,
              channel_mode: int = 0,
              samples: Sequence[int] = (1024, 1024),
              payload: int = 16) -> bytes:
        head = bytes((0, (version << 6) | (rate_index << 4) | (channel_mode << 2)))
        body = head + b'\x00' * max(0, payload - len(head))
        out = bytearray()
        for i, count in enumerate(samples):
            flag = 0x80 if i == len(samples) - 1 else 0x00
            out += struct.pack('>II', (flag << 24) | (8 + len(body)), count) + body
        return bytes(out)

    return build


@pytest.fixture
def make_schl() -> Callable[..., bytes]:
    """
    Build a classic EA bank of ``SCHl`` .. ``SCEl`` units.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking the unit payloads and whether to omit the final ``SCEl`` terminator.
    """
    def build(units: Sequence[bytes], *, drop_last_terminator: bool = False) -> bytes:
        out = bytearray()
        for i, payload in enumerate(units):
            out += b'SCHl' + payload
            if not (drop_last_terminator and i == len(units) - 1):
                out += b'SCEl' + struct.pack('<I', 8)
        return bytes(out)

    return build


@pytest.fixture
def make_mus() -> Callable[..., bytes]:
    """
    Build an EAAC ``.mus`` container holding EA-XMA segments.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking the ``(snr_header, payload)`` segments, the container magic and an
        optional out-of-order seek-table offset.
    """
    def build(segments: Sequence[tuple[bytes, bytes]] = (),
              magic: int = 0xCEFB807A,
              *,
              descending: bool = False) -> bytes:
        head = bytearray(_SNR_TABLE + max(1, len(segments)) * 0x10)
        struct.pack_into('>I', head, 0, magic)
        payloads = bytearray()
        offsets = []
        for i, (header, payload) in enumerate(segments):
            head[_SNR_TABLE + i * 0x10:_SNR_TABLE + i * 0x10 + 8] = header
            offsets.append(len(head) + len(payloads))
            payloads += payload
        if descending:
            offsets = sorted(offsets, reverse=True)
        for i, offset in enumerate(offsets):
            struct.pack_into('>III', head, 0x10 + i * 12, offset, 0, 0)
        return bytes(head + payloads)

    return build


@pytest.fixture
def make_adat() -> Callable[..., bytes]:
    """
    Build an EAAC ADAT speech bank of records, each with optional subtitles and streams.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking the records as ``(subtitles, streams)`` pairs.
    """
    def build(records: Sequence[tuple[Sequence[tuple[int, str]], Sequence[bytes]]],
              gap: bytes = b'',
              *,
              hash_in_second_slot: bool = False) -> bytes:
        out = bytearray()
        for subtitles, streams in records:
            out += b'ADAT' + bytes(12)
            if subtitles:
                body = bytearray(struct.pack('>I', len(subtitles)))
                for name_hash, text in subtitles:
                    encoded = text.encode('utf-16-be') + b'\x00\x00'
                    slots = ((0, name_hash) if hash_in_second_slot else (name_hash, 0))
                    body += struct.pack('>IIII', *slots, 0, len(encoded) // 2) + encoded
                out += b'SUB3' + struct.pack('>I', len(body)) + bytes(body)
            for stream in streams:
                out += gap + stream
        return bytes(out)

    return build


@pytest.fixture
def make_mesh() -> Callable[..., bytes]:
    """
    Build an EA mesh container with the given header, name blob and geometry blocks.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking the magic, the header transform and bounds, the material name blob and
        either big-endian ``PH`` blocks or a little-endian VIF stream.
    """
    def build(magic: bytes = b'NPM7',
              diag: tuple[float, float, float] = (1.0, 1.0, 1.0),
              pivot: tuple[float, float, float] = (0.0, 0.0, 0.0),
              bmin: tuple[float, float, float] = (-4.0, -4.0, -4.0),
              bmax: tuple[float, float, float] = (4.0, 4.0, 4.0),
              names: bytes = b'',
              blocks: Sequence[bytes] = (),
              sections: Sequence[tuple[int, int]] = (),
              stream: bytes = b'') -> bytes:
        endian = '<' if magic == b'SPM7' else '>'
        body = bytearray(_MESH_HEADER_SIZE)
        body[0:4] = magic
        struct.pack_into(endian + 'I', body, 8, 0x20)
        for offset, value in zip((0x20, 0x34, 0x48), diag, strict=True):
            struct.pack_into(endian + 'f', body, offset, value)
        for base, vector in ((0x50, pivot), (0x60, bmin), (0x70, bmax)):
            for i, value in enumerate(vector):
                struct.pack_into(endian + 'f', body, base + i * 4, value)
        for i, (count, offset) in enumerate(sections):
            struct.pack_into(endian + 'II', body, 0x80 + i * 8, count, offset)
        body += names
        for block in blocks:
            body += _PH_MARKER + bytes(_PH_HEADER_SIZE) + block
        body += stream
        struct.pack_into(endian + 'I', body, 4, len(body))
        struct.pack_into(endian + 'I', body, 0x0C, _MESH_HEADER_SIZE)
        return bytes(body)

    return build


@pytest.fixture
def make_vif_unpack() -> Callable[..., bytes]:
    """
    Build one PS2 VIF ``UNPACK`` command word plus its padded payload.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking the ``vn``/``vl`` codes, the element count and the payload.
    """
    def build(vn: int, vl: int, num: int, payload: bytes = b'') -> bytes:
        total = (vn + 1) * {0: 4, 1: 2, 2: 1, 3: 2}[vl] * num
        command = bytes((0, 0, num, 0x60 | (vn << 2) | vl))
        return command + payload.ljust(total, b'\x00') + b'\x00' * (-total % 4)

    return build


@pytest.fixture
def make_xmap() -> Callable[..., bytes]:
    """
    Build an Xbox 360 ``PAMX``/XMAP texture whose every element is ``element``.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking the dimensions, the GPU format word and the repeated element.
    """
    def build(width: int, height: int, fmt: int, element: bytes = b'', mips: int = 1) -> bytes:
        if fmt == _GPU_8888:
            ew, eh, elem = width, height, 4
            swapped = _swap(element, 4)
        else:
            ew, eh = (width + 3) // 4, (height + 3) // 4
            elem = 8 if fmt == _GPU_DXT1 else 16
            swapped = _swap(element, 2)
        need = ((ew + 31) & ~31) * ((eh + 31) & ~31) * elem
        data = (swapped * (need // len(swapped) + 1))[:need] if swapped else b''
        return b'PAMX' + struct.pack('<7I', 3, len(data), 1, width, height, mips, fmt) + data

    return build


@pytest.fixture
def make_shpx() -> Callable[..., bytes]:
    """
    Build a PS3 ``SHPX`` texture around a raw image payload.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking the image type byte, the dimensions and the payload.
    """
    def build(type_byte: int, width: int, height: int, payload: bytes = b'') -> bytes:
        head = bytearray(_SHPX_ENTRY_OFFSET)
        head[0:4] = b'SHPX'
        struct.pack_into('<III', head, 4, len(payload), 1, 1)
        head[0x10:0x14] = b'ENTR'
        struct.pack_into('<I', head, 0x14, _SHPX_ENTRY_OFFSET)
        entry = bytearray(16)
        entry[0] = type_byte
        struct.pack_into('<HH', entry, 4, width, height)
        return bytes(head + entry) + payload

    return build


@pytest.fixture
def make_shps() -> Callable[..., bytes]:
    """
    Build a PS2 ``SHPS`` texture with a trailing palette attachment.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking the image type, the dimensions, the index plane and the palette.
    """
    def build(type_byte: int,
              width: int,
              height: int,
              indices: bytes,
              palette: bytes = b'',
              count: int = 0) -> bytes:
        body = bytearray(0x40)
        body[0:4] = b'SHPS'
        body[0x30] = type_byte
        struct.pack_into('<HH', body, 0x34, width, height)
        body += indices
        body[0x31:0x34] = (len(body) - 0x30).to_bytes(3, 'little')
        attachment = bytearray(16)
        attachment[0] = 0x21
        struct.pack_into('<H', attachment, 4, count)
        return bytes(body + attachment) + palette

    return build


@pytest.fixture
def make_shpg() -> Callable[..., bytes]:
    """
    Build a Wii ``SHPG`` texture with a trailing palette attachment.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking the image type, the dimensions, the pixel data and the palette.
    """
    def build(type_byte: int, width: int, height: int, data: bytes, palette: bytes = b'') -> bytes:
        body = bytearray(0x40)
        body[0:4] = b'SHPG'
        body[0x30] = type_byte
        struct.pack_into('>HH', body, 0x34, width, height)
        struct.pack_into('>H', body, 0x3E, 1)
        body += data
        body[0x31:0x34] = (len(body) - 0x30).to_bytes(3, 'big')
        attachment = bytearray(16)
        return bytes(body + attachment) + palette

    return build


@pytest.fixture
def make_oversized_path() -> Callable[[Path, int], Path]:
    """
    Wrap a real file in a path-like that over-reports its size.

    Returns
    -------
    collections.abc.Callable[[pathlib.Path, int], pathlib.Path]
        A callable taking the real path and the size to claim.
    """
    def build(path: Path, claimed_size: int) -> Path:
        return cast('Path', _OversizedPath(path, claimed_size))

    return build


@pytest.fixture
def make_disc(tmp_path: Path) -> Callable[[Sequence[str]], Path]:
    """
    Populate a disc root with empty marker files at the given relative paths.

    Returns
    -------
    collections.abc.Callable[[collections.abc.Sequence[str]], pathlib.Path]
        A callable taking the relative paths and returning the disc root.
    """
    def build(names: Sequence[str]) -> Path:
        root = tmp_path / 'disc'
        root.mkdir(exist_ok=True)
        for name in names:
            target = root / name
            if name.endswith('/'):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'')
        return root

    return build
