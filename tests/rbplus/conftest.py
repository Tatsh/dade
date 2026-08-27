"""Shared pytest configuration for the ``dade.rbplus`` suite."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
import plistlib
import struct
import sys
import zipfile
import zlib

import pytest

from dade.common.bfcodec import DEFAULT_IV, BFCodec
from dade.rbplus.cipher import chart_key

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from pytest_mock import MockerFixture

_INFO = {
    'ArtistName': 'Test Artist',
    'ArtistNameHira': 'テスト',
    'ArtistNameRoman': '',
    'Basic': 2,
    'BpmMax': 190,
    'BpmMin': 190,
    'Hard': 7,
    'ID': 100000109,
    'Medium': 5,
    'MusicName': 'Test Tune',
    'MusicNameHira': 'テスト',
    'MusicNameRoman': '',
    'Version': 2,
}


def _chunk(kind: bytes, body: bytes) -> bytes:
    """Assemble one PNG chunk, length and CRC included."""
    return (struct.pack('>I', len(body)) + kind + body +
            struct.pack('>I',
                        zlib.crc32(kind + body) & 0xFFFF_FFFF))


def _png(*, cgbi: bool = False) -> bytes:
    """Assemble a one-pixel greyscale PNG, optionally with Xcode's CgBI chunk in front."""
    ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 0, 0, 0, 0)
    body = _chunk(b'IHDR', ihdr) + _chunk(b'IDAT', zlib.compress(b'\0\xff')) + _chunk(b'IEND', b'')
    lead = _chunk(b'CgBI', b'\x50\x00\x20\x06') if cgbi else b''
    return b'\x89PNG\r\n\x1a\n' + lead + body


def _note(*,
          chain: tuple[int, int, int, int] | None = None,
          flags: int = 0,
          hold_kind: int = 0,
          kind: int = 0,
          note_id: int = 0,
          note_type: int = 0,
          path_points: Sequence[int] = (),
          side: int = 0,
          spawn_time: int = 0,
          start_time: int = -1,
          target: Sequence[int] = (0, 0, 0, 0),
          travel_time: int = 1000) -> bytes:
    """Assemble one note record exactly as the chart stream stores it."""
    if chain is not None:
        flags |= 0x08
    out = struct.pack('<iihhh', spawn_time, travel_time, note_id, start_time, len(path_points))
    out += struct.pack(f'<{len(path_points)}h', *path_points)
    out += struct.pack('<4b', kind, side, hold_kind, note_type)
    out += struct.pack('<4h', *target)
    out += struct.pack('<I', flags)
    # Eight bytes the engine reads and never unpacks.
    out += bytes(8)
    if chain is not None:
        out += struct.pack('<hhii', *chain)
    return out


def _tempo_event(*, kind: int = 3, speed: int = 400, time: int = 0) -> bytes:
    """Assemble one thirty-six byte tempo event."""
    out = bytearray(36)
    struct.pack_into('<h', out, 0, kind)
    struct.pack_into('<i', out, 0x04, time)
    struct.pack_into('<i', out, 0x10, speed)
    return bytes(out)


def _slide(*,
           field2: int = 0,
           lane: int = 0,
           note_index: int = 0,
           value_a: int = 0,
           value_b: int = 0) -> bytes:
    """Assemble one sixteen-byte slide record."""
    return struct.pack('<HHH2xii', note_index, field2, lane, value_a, value_b)


@pytest.fixture(autouse=True)
def serial_pool(mocker: MockerFixture) -> Any:
    """
    Run the pipeline's process-pool work in the test process.

    A worker process is invisible to the coverage run and to any patch installed here, so the pool
    is replaced by one that maps in place. The functions it calls are unchanged.

    Returns
    -------
    typing.Any
        The installed patcher.
    """
    def factory(**_kwargs: Any) -> Any:
        pool = mocker.MagicMock()
        pool.__enter__.return_value = pool
        pool.__exit__.return_value = False
        pool.map = lambda fn, items, **_: [fn(item) for item in items]
        return pool

    return mocker.patch('dade.rbplus.pipeline.ProcessPoolExecutor', side_effect=factory)


@pytest.fixture
def make_note() -> Callable[..., bytes]:
    """
    Build one RBFF note record.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking the note's fields as keyword arguments.
    """
    return _note


@pytest.fixture
def make_tempo_event() -> Callable[..., bytes]:
    """
    Build one RBFF tempo event.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking ``kind``, ``speed``, and ``time``.
    """
    return _tempo_event


@pytest.fixture
def make_slide() -> Callable[..., bytes]:
    """
    Build one RBFF slide record.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking ``field2``, ``lane``, ``note_index``, ``value_a``, and ``value_b``.
    """
    return _slide


def _chart(*,
           end_time: int = 30000,
           initial_speed: int = 400,
           magic: bytes = b'RBFF',
           notes: Sequence[bytes] = (),
           seed: int = 7,
           slides: Sequence[bytes] = (),
           tempo_events: Sequence[bytes] = (),
           version: int = 11,
           note_count: int | None = None,
           free_note_count: int = 0) -> bytes:
    """Assemble a whole RBFF chart around the records given."""
    header = bytearray(0x1C)
    struct.pack_into('<iii', header, 0x00, initial_speed, end_time, seed)
    struct.pack_into('<hhh', header, 0x0C,
                     len(notes) if note_count is None else note_count, len(tempo_events),
                     free_note_count)
    struct.pack_into('<i', header, 0x14, len(slides))
    return (magic + struct.pack('<I', version) + bytes(8) + bytes(header) + b''.join(notes) +
            b''.join(tempo_events) + b''.join(slides))


@pytest.fixture
def make_chart() -> Callable[..., bytes]:
    """
    Build an RBFF chart.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking ``notes``, ``tempo_events``, ``slides``, ``version``, and the header
        fields as keyword arguments.
    """
    return _chart


@pytest.fixture
def make_png() -> Callable[..., bytes]:
    """
    Build a one-pixel PNG, ordinary or Apple-optimised.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking ``cgbi``.
    """
    return _png


@pytest.fixture
def chart_bytes() -> bytes:
    """
    Build a small chart holding one plain note, one free note, and a long note with its tail.

    Returns
    -------
    bytes
        The chart.
    """
    return _chart(notes=(
        _note(note_id=1, spawn_time=0, start_time=5, travel_time=1000),
        _note(note_id=2,
              spawn_time=1000,
              start_time=-1,
              travel_time=1000,
              kind=1,
              path_points=(3, 4)),
        _note(note_id=3, spawn_time=2000, travel_time=1000, chain=(4, 0, 0, 0), side=1),
        _note(note_id=4, spawn_time=4000, travel_time=1000, side=1),
    ),
                  free_note_count=1,
                  tempo_events=(_tempo_event(kind=3, speed=800,
                                             time=2000), _tempo_event(kind=1, time=3000)),
                  slides=(_slide(lane=0, note_index=1),))


def _package(path: Path,
             *,
             decode_type: int = 0,
             entries: Mapping[str, bytes] | None = None,
             info: Mapping[str, object] | None = None,
             omit_info: bool = False) -> Path:
    """Write a ``.rb`` tune package, every entry enciphered under the chosen key."""
    codec = BFCodec(chart_key(decode_type))
    with zipfile.ZipFile(path, 'w') as archive:
        if not omit_info:
            payload = plistlib.dumps(dict(_INFO if info is None else info))
            archive.writestr('info', codec.encipher(payload))
        for name, data in (entries or {}).items():
            archive.writestr(name, codec.encipher(data))
    return path


@pytest.fixture
def tune_info() -> dict[str, object]:
    """
    Build the metadata a tune package carries, as a copy that a test may change.

    Returns
    -------
    dict[str, object]
        The metadata.
    """
    return dict(_INFO)


@pytest.fixture
def make_package(tmp_path: Path) -> Callable[..., Path]:
    """
    Write a ``.rb`` tune package into the temporary directory.

    Returns
    -------
    collections.abc.Callable[..., pathlib.Path]
        A callable taking a path and the keyword arguments ``decode_type``, ``entries``, ``info``,
        and ``omit_info``.
    """
    def build(name: str = '100000109.rb', **kwargs: Any) -> Path:
        return _package(tmp_path / name, **kwargs)

    return build


@pytest.fixture
def make_chart_file(tmp_path: Path, chart_bytes: bytes) -> Callable[..., Path]:
    """
    Write one note chart into a file of its own, enciphered or not.

    Returns
    -------
    collections.abc.Callable[..., pathlib.Path]
        A callable taking a file name and the keyword arguments ``data``, ``decode_type``, ``iv``,
        and ``key``. Passing ``decode_type=None`` leaves the chart deciphered.
    """
    def build(name: str = 'note_har',
              *,
              data: bytes | None = None,
              decode_type: int | None = 0,
              iv: bytes = DEFAULT_IV,
              key: bytes | None = None) -> Path:
        payload = chart_bytes if data is None else data
        path = tmp_path / name
        if decode_type is None and key is None:
            path.write_bytes(payload)
        else:
            chosen = key if key is not None else chart_key(decode_type or 0)
            path.write_bytes(BFCodec(chosen, iv).encipher(payload))
        return path

    return build


@pytest.fixture
def tune_package(make_package: Callable[..., Path], make_chart: Callable[..., bytes],
                 make_png: Callable[..., bytes], chart_bytes: bytes) -> Path:
    """
    Build a complete tune package: metadata, a chart of each difficulty, images, and audio.

    Returns
    -------
    pathlib.Path
        The package.
    """
    m4a = bytes(4) + b'ftypM4A ' + bytes(16)
    return make_package(
        entries={
            'artist_b': make_png(cgbi=True),
            'artwork': make_png(cgbi=True),
            'bgm': m4a,
            'note_bas': chart_bytes,
            'note_har': make_chart(),
            'note_med': chart_bytes,
            'pre': m4a,
            'title_b': make_png(),
        })


def _asset_archive(path: Path,
                   *,
                   entries: Mapping[str, bytes] | None = None,
                   manifest: Sequence[str] | None = None,
                   root: str = 'iPad') -> Path:
    """
    Write an asset archive.

    The entries are stored unencrypted, which every code path here treats identically: a password
    set on a :py:class:`zipfile.ZipFile` is ignored for an entry that does not need one, and the
    standard library cannot write ZipCrypto in any case.
    """
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in (entries or {}).items():
            archive.writestr(f'{root}/{name}' if root else name, data)
        if manifest is not None:
            nested = path.with_suffix('.nested')
            with zipfile.ZipFile(nested, 'w') as inner:
                inner.writestr('lists', '\n'.join(manifest))
            archive.writestr(f'{root}/list' if root else 'list', nested.read_bytes())
            nested.unlink()
    return path


@pytest.fixture
def make_asset_archive(tmp_path: Path) -> Callable[..., Path]:
    """
    Write a downloadable asset archive into the temporary directory.

    Returns
    -------
    collections.abc.Callable[..., pathlib.Path]
        A callable taking ``entries``, ``manifest``, and ``root``.
    """
    def build(name: str = 'iPad.zip', **kwargs: Any) -> Path:
        return _asset_archive(tmp_path / name, **kwargs)

    return build


_PNGDEFRY_STUB = """
import sys
from pathlib import Path

out = source = None
for arg in sys.argv[1:]:
    if arg.startswith('-o'):
        out = Path(arg[2:])
    else:
        source = Path(arg)
data = source.read_bytes()
# The real tool leaves an ordinary PNG alone, writing nothing at all, which is the signal the
# caller reads to tell a converted image from a copied one.
if b'CgBI' in data[:32]:
    out.mkdir(parents=True, exist_ok=True)
    (out / source.name).write_bytes(data.replace(b'CgBI', b'IHDR', 1))
"""

_FFMPEG_STUB = """
import sys
from pathlib import Path

args = sys.argv[1:]
destination = Path(args[-1])
source = Path(args[args.index('-i') + 1])
destination.write_bytes(b'RIFF' + (len(source.read_bytes())).to_bytes(4, 'little') + b'WAVE')
"""


def _stub_tool(directory: Path, name: str, body: str) -> Path:
    """Write an executable stand-in for a native tool, so the subprocess path is really run."""
    path = directory / name
    path.write_text(f'#!{sys.executable}\n{body}')
    path.chmod(0o755)
    return path


@pytest.fixture
def pngdefry(tmp_path: Path) -> Path:
    """
    Write an executable stand-in for ``pngdefry``.

    Returns
    -------
    pathlib.Path
        The stub, which rewrites an Apple-optimised PNG and ignores an ordinary one.
    """
    tools = tmp_path / 'tools'
    tools.mkdir(exist_ok=True)
    return _stub_tool(tools, 'pngdefry', _PNGDEFRY_STUB)


@pytest.fixture
def ffmpeg(tmp_path: Path) -> Path:
    """
    Write an executable stand-in for ``ffmpeg``.

    Returns
    -------
    pathlib.Path
        The stub, which writes a WAV header at the destination it is given.
    """
    tools = tmp_path / 'tools'
    tools.mkdir(exist_ok=True)
    return _stub_tool(tools, 'ffmpeg', _FFMPEG_STUB)


@pytest.fixture
def app_bundle(tmp_path: Path, tune_package: Path, make_png: Callable[..., bytes]) -> Path:
    """
    Build a miniature ``.app`` bundle holding one of everything the pipeline converts.

    Returns
    -------
    pathlib.Path
        The directory holding ``Payload``.
    """
    root = tmp_path / 'download'
    bundle = root / 'Payload' / 'Rb.app'
    (bundle / 'en.lproj').mkdir(parents=True)
    (bundle / 'loose.png').write_bytes(make_png(cgbi=True))
    (bundle / 'sound.caf').write_bytes(b'caff' + bytes(16))
    (bundle / 'tune.m4a').write_bytes(bytes(4) + b'ftypM4A ' + bytes(16))
    (bundle / 'readme.txt').write_bytes(b'copied verbatim')
    (bundle / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleName': 'Rb'}))
    (bundle / 'en.lproj' / 'Localizable.strings').write_bytes(
        plistlib.dumps({'key': 'value'}, fmt=plistlib.FMT_BINARY))
    (bundle / 'Rb').write_bytes(b'\xcf\xfa\xed\xfe' + bytes(64))
    (bundle / tune_package.name).write_bytes(tune_package.read_bytes())
    return root
