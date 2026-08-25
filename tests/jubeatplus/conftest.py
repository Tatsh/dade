"""Shared pytest configuration for the ``dade.jubeatplus`` suite."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
import hashlib
import plistlib
import struct
import zipfile
import zlib

import pytest

from dade.common.bfcodec import BFCodec
from dade.jubeatplus.cipher import bgm_key, lab_url_key, texture_key
from dade.jubeatplus.pipeline import unpack

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from pytest_mock import MockerFixture


def _chunk(kind: bytes, body: bytes) -> bytes:
    """Assemble one PNG chunk, length and CRC included."""
    return (struct.pack('>I', len(body)) + kind + body +
            struct.pack('>I',
                        zlib.crc32(kind + body) & 0xFFFF_FFFF))


def _png(width: int = 1, height: int = 1) -> bytes:
    """Assemble a one-pixel greyscale PNG that any reader will accept."""
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0)
    raw = b''.join(b'\0' + b'\xff' * width for _ in range(height))
    return (b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', ihdr) + _chunk(b'IDAT', zlib.compress(raw)) +
            _chunk(b'IEND', b''))


def _chart(magic: bytes = b'IJBQ',
           events: Sequence[tuple[int, int, int]] = (),
           *,
           end_sector: int = 3000,
           note_count: int = 0,
           unknown: int = 2,
           first_marker: int = 8,
           first_marker_sector: int = 300) -> bytes:
    """Assemble a chart from a list of ``(kind, sector, value)`` events."""
    header = bytearray(0x60)
    header[0:4] = magic
    struct.pack_into('<III', header, 4, len(events), note_count, end_sector)
    struct.pack_into('<HH', header, 0x10, unknown, first_marker)
    struct.pack_into('<I', header, 0x14, first_marker_sector)
    header[0x24:0x60] = bytes(range(60))
    body = b''.join(
        struct.pack('<II', (sector << 8) | kind, value) for kind, sector, value in events)
    return bytes(header) + body


def _mapping_model() -> bytes:
    """Assemble the smallest keyed archive the Core Data reader accepts as a mapping model."""
    return plistlib.dumps(
        {
            '$archiver': 'NSKeyedArchiver',
            '$objects': [
                '$null',
                {
                    '$class': plistlib.UID(3),
                    'NSEntityMappings': plistlib.UID(2)
                },
                {
                    '$class': plistlib.UID(4),
                    'NS.objects': []
                },
                {
                    '$classes': ['NSMappingModel'],
                    '$classname': 'NSMappingModel'
                },
                {
                    '$classes': ['NSArray'],
                    '$classname': 'NSArray'
                },
            ],
            '$top': {
                'root': plistlib.UID(1)
            },
            '$version': 100000
        },
        fmt=plistlib.FMT_BINARY)


@pytest.fixture
def make_png() -> Callable[..., bytes]:
    """
    Build a plain PNG.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking an optional width and height and returning the PNG.
    """
    return _png


@pytest.fixture
def make_apple_png() -> Callable[..., bytes]:
    """
    Build a PNG carrying the ``CgBI`` chunk Xcode adds, which ``pngdefry`` strips.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking an optional width and height and returning the PNG.
    """
    def build(width: int = 1, height: int = 1) -> bytes:
        plain = _png(width, height)
        # The CgBI chunk sits between the signature and IHDR, which is where pngdefry looks.
        return plain[:8] + _chunk(b'CgBI', b'\x50\x00\x20\x02') + plain[8:]

    return build


@pytest.fixture
def make_chart() -> Callable[..., bytes]:
    """
    Build a chart blob.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking the magic and an ``(kind, sector, value)`` event list.
    """
    return _chart


@pytest.fixture
def make_tex(tmp_path: Path, make_png: Callable[..., bytes]) -> Callable[[str], Path]:
    """
    Write an enciphered ``.tex`` texture wrapping a PNG.

    Returns
    -------
    collections.abc.Callable[[str], pathlib.Path]
        A callable taking the file's stem and returning the written texture.
    """
    def build(stem: str = 'texture') -> Path:
        path = tmp_path / f'{stem}.tex'
        path.write_bytes(BFCodec(texture_key()).encipher(b'\1\2\3\4' + make_png()))
        return path

    return build


@pytest.fixture
def tune_info() -> dict[str, object]:
    """
    Build the catalogue entry a tune package carries.

    Returns
    -------
    dict[str, object]
        The metadata dictionary.
    """
    return {
        'Artist': 'W.T. Orchestra',
        'ID': 100000201,
        'LvAdv': 7,
        'LvBas': 3,
        'LvExt': 9,
        'Name': 'Overture',
        'NameYomi': 'おーばーちゅあ'
    }


@pytest.fixture
def make_jbt(tmp_path: Path, make_apple_png: Callable[..., bytes], make_chart: Callable[..., bytes],
             tune_info: dict[str, object]) -> Callable[..., Path]:
    """
    Write a tune package: enciphered entries plus the MD5 trailer after the ZIP.

    Returns
    -------
    collections.abc.Callable[..., pathlib.Path]
        A callable taking the info entry's name and whether to corrupt the trailer.
    """
    def build(info_name: str = 'info', *, corrupt_digest: bool = False) -> Path:
        codec = BFCodec(bgm_key())
        entries: dict[str, bytes] = {
            info_name: codec.encipher(plistlib.dumps(tune_info)),
            'artwork': codec.encipher(make_apple_png(2, 2)),
            'bgm': codec.encipher(b'\0\0\0\x20ftypM4A \0\0\0\0M4A mp42'),
            'seq_bas': codec.encipher(_chart(events=((5, 0, 500000), (1, 300, 3), (2, 3000, 0)))),
        }
        body = tmp_path / f'{info_name}-package'
        with zipfile.ZipFile(body, 'w') as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        raw = body.read_bytes()
        body.unlink()
        digest = hashlib.md5(raw, usedforsecurity=False).digest()
        path = tmp_path / '100000201.jbt'
        path.write_bytes(raw + (b'\0' * 16 if corrupt_digest else digest))
        return path

    return build


@pytest.fixture
def marker_zip(tmp_path: Path, make_apple_png: Callable[..., bytes]) -> Path:
    """
    Write a marker ZIP: enciphered images with the four-byte header, plus two plain entries.

    Returns
    -------
    pathlib.Path
        The written ZIP.
    """
    path = tmp_path / 'mk0026.zip'
    codec = BFCodec(texture_key())
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('markers/', b'')
        archive.writestr('markers/ma00', codec.encipher(b'\1\2\3\4' + make_apple_png()))
        archive.writestr('markers/filename.txt', b'classic')
        archive.writestr('markers/settings.plist', plistlib.dumps({'frames': 24}))
    return path


@pytest.fixture
def make_bundle(tmp_path: Path, make_apple_png: Callable[..., bytes], make_jbt: Callable[..., Path],
                marker_zip: Path,
                make_signed_bundle_executable: Callable[[Path], None]) -> Callable[..., Path]:
    """
    Lay out an application bundle holding one of everything the pipeline converts.

    Returns
    -------
    collections.abc.Callable[..., pathlib.Path]
        A callable taking the layout (``payload``, ``bare``, or ``app``) and returning the path to
        hand the pipeline.
    """
    def build(layout: str = 'payload') -> Path:
        root = tmp_path / 'download'
        bundle = root / 'Payload' / 'Example.app' if layout != 'bare' else root / 'Example.app'
        bundle.mkdir(parents=True)
        (bundle / 'Info.plist').write_bytes(
            plistlib.dumps({
                'CFBundleExecutable': 'Example',
                'CFBundleIdentifier': 'jp.konami.jubeatplus'
            }))
        (bundle / 'icon.png').write_bytes(make_apple_png(2, 2))
        (bundle / 'texture.tex').write_bytes(
            BFCodec(texture_key()).encipher(b'\1\2\3\4' + make_apple_png()))
        (bundle / 'DefaultSettings.plist').write_bytes(
            plistlib.dumps({
                'PrefTheme': 2,
                'PrefjubeatLabURL': BFCodec(lab_url_key()).encipher(b'https://example.invalid/')
            }))
        (bundle / 'en.lproj').mkdir()
        (bundle / 'en.lproj' / 'Localizable.strings').write_text('"Key" = "Value";\n')
        (bundle / 'PkgInfo').write_bytes(b'APPL????')
        (bundle / 'MapScore.cdm').write_bytes(_mapping_model())
        (bundle / 'SC_Info').mkdir()
        (bundle / 'Music').mkdir()
        (make_jbt()).replace(bundle / 'Music' / '100000201.jbt')
        marker_zip.replace(bundle / 'mk0026.zip')
        make_signed_bundle_executable(bundle / 'Example')
        if layout == 'app':
            return bundle
        return root

    return build


@pytest.fixture
def make_signed_bundle_executable(macho_arm64_bytes: bytes) -> Callable[[Path], None]:
    """
    Write the bundle's Mach-O executable.

    Returns
    -------
    collections.abc.Callable[[pathlib.Path], None]
        A callable taking the path to write.
    """
    def build(path: Path) -> None:
        path.write_bytes(macho_arm64_bytes)

    return build


@pytest.fixture
def macho_arm64_bytes() -> bytes:
    """
    Build a minimal thin ``arm64`` Mach-O image.

    Returns
    -------
    bytes
        The image.
    """
    segment = (b'__TEXT'.ljust(16, b'\0') +
               struct.pack('<QQQQiiII', 0x1000, 0x2000, 0, 0x2000, 7, 5, 0, 0))
    command = struct.pack('<II', 0x19, len(segment) + 8) + segment
    header = struct.pack('<IIIIIIII', 0xFEED_FACF, 0x0100_000C, 0, 2, 1, len(command), 0x0020_0085,
                         0)
    return header + command


@pytest.fixture
def make_ipa(tmp_path: Path, make_bundle: Callable[..., Path]) -> Callable[[], Path]:
    """
    Pack the bundle into an ``.ipa``.

    Returns
    -------
    collections.abc.Callable[[], pathlib.Path]
        A callable returning the written ``.ipa``.
    """
    def build() -> Path:
        root = make_bundle()
        path = tmp_path / 'Example.ipa'
        with zipfile.ZipFile(path, 'w') as archive:
            for item in sorted(root.rglob('*')):
                if item.is_file():
                    archive.write(item, item.relative_to(root).as_posix())
        return path

    return build


@pytest.fixture
def fake_pngdefry(tmp_path: Path) -> Path:
    """
    Stand in for ``pngdefry``, stripping a ``CgBI`` chunk and skipping anything without one.

    The real tool also byte-swaps and un-premultiplies, which nothing here depends on; what matters
    for the pipeline is that it writes into the directory it is given, and writes nothing at all
    for a PNG that was never Apple-optimised.

    Returns
    -------
    pathlib.Path
        The executable script.
    """
    path = tmp_path / 'pngdefry-stub'
    path.write_text("""#!/usr/bin/env python3
import pathlib
import sys

out = pathlib.Path(sys.argv[1][2:])
for name in sys.argv[2:]:
    source = pathlib.Path(name)
    data = source.read_bytes()
    if b'CgBI' not in data[:32]:
        continue
    start = data.index(b'CgBI') - 4
    (out / source.name).write_bytes(data[:start] + data[start + 16:])
""")
    path.chmod(0o755)
    return path


@pytest.fixture
def fake_ffmpeg(tmp_path: Path) -> Path:
    """
    Stand in for ``ffmpeg``, writing a WAV header wherever its output argument points.

    Returns
    -------
    pathlib.Path
        The executable script.
    """
    path = tmp_path / 'ffmpeg-stub'
    path.write_text("""#!/usr/bin/env python3
import pathlib
import sys

pathlib.Path(sys.argv[-1]).write_bytes(b'RIFF\\x24\\x00\\x00\\x00WAVEfmt ')
""")
    path.chmod(0o755)
    return path


@pytest.fixture
def failing_tool(tmp_path: Path) -> Path:
    """
    Stand in for a helper that always fails, for the error paths.

    Returns
    -------
    pathlib.Path
        The executable script.
    """
    path = tmp_path / 'failing-tool'
    path.write_text('#!/usr/bin/env python3\nimport sys\nsys.exit(3)\n')
    path.chmod(0o755)
    return path


@pytest.fixture
def make_lab_plist(tmp_path: Path) -> Callable[[Mapping[str, object]], Path]:
    """
    Write a property list holding the values given.

    Returns
    -------
    collections.abc.Callable[[collections.abc.Mapping[str, object]], pathlib.Path]
        A callable taking the mapping and returning the written property list.
    """
    def build(values: Mapping[str, object]) -> Path:
        path = tmp_path / 'Settings.plist'
        path.write_bytes(plistlib.dumps(dict(values)))
        return path

    return build


@pytest.fixture
def minimal_sinf() -> bytes:
    """
    Build a purchase record with only the atoms the reader needs to count it as one.

    Returns
    -------
    bytes
        The ``.sinf`` contents.
    """
    def atom(kind: bytes, body: bytes) -> bytes:
        return struct.pack('>I', len(body) + 8) + kind + body

    schi = atom(b'user', struct.pack('>I', 1234)) + atom(b'key ', struct.pack('>I', 6))
    return atom(b'sinf', atom(b'frma', b'game') + atom(b'schi', schi))


@pytest.fixture
def unpacked(tmp_path: Path, make_bundle: Callable[..., Path], fake_ffmpeg: Path,
             fake_pngdefry: Path) -> tuple[dict[str, Any], Path]:
    """
    Run the whole pipeline once over the synthetic bundle.

    Returns
    -------
    tuple[dict[str, Any], pathlib.Path]
        The per-action statistics and the converted bundle's root.
    """
    out = tmp_path / 'out'
    stats = unpack(make_bundle(), out, ffmpeg=fake_ffmpeg, pngdefry=fake_pngdefry, workers=1)
    return dict(stats), out / 'Example.app'


@pytest.fixture(autouse=True)
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
        pool.map = lambda fn, items, **_: [fn(item) for item in items]
        return pool

    return mocker.patch('dade.jubeatplus.pipeline.ProcessPoolExecutor', side_effect=factory)
