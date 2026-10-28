from __future__ import annotations

from typing import TYPE_CHECKING
import contextlib
import struct

from PIL import Image
import pytest

from dade.tgr.model import CAR_BASE, TRACK_BASE
from dade.tgr.pc import CueTrack, decode_img, extract_disc, parse_cue, read_pod

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture

_SECTOR = 2352


def _pointer(base: int, offset: int) -> int:
    return 0x80000000 | (base + offset)


def _draw(base: int, vertices: int) -> bytes:
    return (struct.pack('>II', 0x04 << 24 | 3 << 10, _pointer(base, vertices)) +
            struct.pack('>II', 0xBF << 24, 2 << 8 | 4) + b'\xb8' + bytes(7) + b''.join(
                struct.pack('>hhhHhhBBBB', x, y, z, 0, 0, 0, 0, 0, 127, 255)
                for x, y, z in ((0, 0, 0), (255, 0, 0), (0, 0, 255))))


def _car() -> bytes:
    data = bytearray(0x300)
    struct.pack_into('>I', data, 0x14, _pointer(CAR_BASE, 0x200))
    struct.pack_into('>I', data, 0xBC, _pointer(CAR_BASE, 0x280))
    data[0x280:0x2C8] = _draw(CAR_BASE, 0x298)
    return bytes(data)


def _track() -> bytes:
    data = bytearray(0x300)
    struct.pack_into('>II', data, 0, len(data), 0x230)
    struct.pack_into('>I', data, 0x50, _pointer(TRACK_BASE, 0x2A0))
    struct.pack_into('>II', data, 0x60, _pointer(TRACK_BASE, 0x240), 1)
    struct.pack_into('>16f', data, 0x240, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
    struct.pack_into('>I', data, 0x284, _pointer(TRACK_BASE, 0x2A0))
    data[0x2A0:0x2E8] = _draw(TRACK_BASE, 0x2B8)
    return bytes(data)


def _part_model() -> bytes:
    data = bytearray(0x80)
    struct.pack_into('>IIIH2x3f', data, 0, 1, 0, 0x20, 0, 0.0, 0.0, 0.0)
    data[0x20:0x68] = _draw(0, 0x38)
    return bytes(data)


def _pod(entries: dict[str, bytes]) -> bytes:
    directory = 16 + sum(map(len, entries.values()))
    body = b''
    table = b''
    for name, data in entries.items():
        table += struct.pack('<iIBB2x64s', 16 + len(body), len(data), 0, 0, name.encode())
        body += data
    return struct.pack('<4siii', b'POD\0', 1, len(entries), directory) + body + table


def _program() -> bytes:
    def directory(identifier: int, target: int) -> bytes:
        return struct.pack('<12xHHII', 0, 1, identifier, target)

    section = (directory(16, 0x80000018) + directory(1, 0x80000030) + directory(1033, 0x48) +
               struct.pack('<IIII', 0x1058, 4, 0, 0) + b'data')
    image = bytearray(0x200 + len(section))
    image[0:2] = b'MZ'
    struct.pack_into('<I', image, 0x3C, 0x40)
    image[0x40:0x44] = b'PE\0\0'
    struct.pack_into('<H12xH2xH', image, 0x46, 1, 224, 0x10B)
    struct.pack_into('<II', image, 0x40 + 24 + 96 + 16, 0x1000, len(section))
    struct.pack_into('<8sIIII', image, 0x40 + 24 + 224, b'.rsrc', len(section), 0x1000,
                     len(section), 0x200)
    image[0x200:] = section
    return bytes(image)


def _img(width: int, height: int, *values: int) -> bytes:
    return struct.pack(f'<ii4x{len(values)}H', width, height, *values)


def _disc(root: Path) -> Path:
    root.mkdir()
    Image.new('RGB', (2, 2), (0, 255, 0)).save(root / 'IMAGE.BMP')
    Image.new('RGBA', (16, 16)).save(root / 'icon.ico', sizes=[(16, 16)])
    (root / 'splash.img').write_bytes(_img(1, 1, 0xFC00))
    (root / 'sky.ci4').write_bytes(bytes(2048))
    (root / 'sky.lut4').write_bytes(bytes(32))
    (root / 'alone.ci4').write_bytes(b'ci4')
    (root / 'single.lut4').write_bytes(b'lut4')
    (root / 'data.pod').write_bytes(_pod({'model.bin': _part_model(), 'notes.txt': b'notes'}))
    (root / 'game.exe').write_bytes(_program())
    (root / 'plain.dll').write_bytes(b'not a program')
    (root / 'car.rca').write_bytes(b'RCar'.ljust(0x8000, b'\0') + _car())
    (root / 'bad.rca').write_bytes(b'XCar')
    (root / 'track.trk').write_bytes(_track() + bytes(64))
    (root / 'clear.trk').write_bytes(_track()[:0x50] + bytes(4) + _track()[0x54:])
    (root / 'bad.trk').write_bytes(b'\0\0\0\x08junkjunk')
    (root / 'sub').mkdir()
    (root / 'sub' / 'readme.txt').write_text('hello', encoding='utf-8')
    return root


def test_parse_cue(tmp_path: Path) -> None:
    (tmp_path / 'one.bin').write_bytes(bytes(6 * _SECTOR))
    (tmp_path / 'two.bin').write_bytes(bytes(3 * _SECTOR))
    cue = tmp_path / 'disc.cue'
    cue.write_text(
        'INDEX 01 00:00:00\n'
        'FILE "one.bin" BINARY\n'
        '  TRACK 01 MODE1/2352\n'
        '    INDEX 01 00:00:00\n'
        '  TRACK 02 AUDIO\n'
        '    INDEX 00 00:00:01\n'
        '    INDEX 01 00:00:02\n'
        '  TRACK 03 audio\n'
        '    INDEX 01 00:00:04\n'
        'FILE two.bin BINARY\n'
        '  TRACK 04 AUDIO\n'
        '    INDEX 01 00:00:00\n',
        encoding='latin-1')
    assert parse_cue(cue) == [
        CueTrack(2, tmp_path / 'one.bin', 2 * _SECTOR, 4 * _SECTOR),
        CueTrack(3, tmp_path / 'one.bin', 4 * _SECTOR, 6 * _SECTOR),
        CueTrack(4, tmp_path / 'two.bin', 0, 3 * _SECTOR)
    ]


def test_decode_img() -> None:
    assert decode_img(_img(2, 1, 0xFC00, 0x001F)) == (2, 1, bytes((255, 0, 0, 255, 0, 0, 255, 0)))


def test_read_pod() -> None:
    assert read_pod(_pod({'a.bin': b'one', 'b.bin': b'two'})) == {'a.bin': b'one', 'b.bin': b'two'}


def test_read_pod_rejects_other_files() -> None:
    assert read_pod(b'ZIP\0' + bytes(12)) == {}


def test_extract_disc_directory(tmp_path: Path) -> None:
    out = tmp_path / 'out'
    counts = extract_disc(_disc(tmp_path / 'disc'), out, tmp_path / 'ffmpeg')
    assert counts == {'cars': 1, 'tracks': 2, 'images': 5, 'programs': 1, 'other': 7, 'music': 0}
    for name in ('IMAGE.png', 'icon-16x16.png', 'splash.png', 'sky.png', 'alone.ci4', 'single.lut4',
                 'data/model.bin', 'data/model.glb', 'data/notes.txt', 'game.exe',
                 'game.exe.resources/version/1-1033.bin', 'plain.dll', 'car.glb', 'bad.rca',
                 'track.glb', 'track-sky.glb', 'bad.trk', 'sub/readme.txt'):
        assert (out / name).is_file(), name
    assert not (out / 'plain.dll.resources').exists()
    assert (out / 'clear.glb').is_file()
    assert not (out / 'clear-sky.glb').exists()
    with Image.open(out / 'splash.png') as splash:
        assert splash.getpixel((0, 0)) == (255, 0, 0, 255)


@pytest.mark.parametrize('name', ['disc.cue', 'disc.bin'])
def test_extract_disc_rips_cd_audio(tmp_path: Path, mocker: MockerFixture, name: str) -> None:
    root = tmp_path / 'files'
    root.mkdir()
    (root / 'readme.txt').write_text('hello', encoding='utf-8')
    pcm = bytes(range(256)) * 10
    (tmp_path / 'disc.bin').write_bytes(bytes(_SECTOR) + pcm)
    (tmp_path / 'disc.cue').write_text(
        'FILE "disc.bin" BINARY\n  TRACK 01 MODE1/2352\n    INDEX 01 00:00:00\n'
        '  TRACK 02 AUDIO\n    INDEX 01 00:00:01\n',
        encoding='latin-1')
    as_directory = mocker.patch('dade.tgr.pc.as_directory',
                                return_value=contextlib.nullcontext(root))
    run = mocker.patch('dade.tgr.pc.sp.run')
    out = tmp_path / 'out'
    counts = extract_disc(tmp_path / name, out, tmp_path / 'ffmpeg')
    assert counts['music'] == 1
    assert counts['other'] == 1
    as_directory.assert_called_once_with(tmp_path / name)
    run.assert_called_once_with(
        (str(tmp_path / 'ffmpeg'), '-hide_banner', '-loglevel', 'error', '-y', '-f', 's16le', '-ar',
         '44100', '-ac', '2', '-i', 'pipe:0', str(out / 'music' / 'track02.flac')),
        check=True,
        input=pcm)


def test_extract_disc_without_ffmpeg_skips_audio(tmp_path: Path, mocker: MockerFixture) -> None:
    root = tmp_path / 'files'
    root.mkdir()
    (tmp_path / 'disc.cue').write_text('', encoding='latin-1')
    mocker.patch('dade.tgr.pc.as_directory', return_value=contextlib.nullcontext(root))
    run = mocker.patch('dade.tgr.pc.sp.run')
    assert extract_disc(tmp_path / 'disc.cue', tmp_path / 'out')['music'] == 0
    run.assert_not_called()
