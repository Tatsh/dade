from __future__ import annotations

from typing import TYPE_CHECKING
import struct
import zlib

from PIL import Image

from dade.tgr.model import CAR_BASE, TRACK_BASE
from dade.tgr.n64 import MENU_IMAGES, extract_rom
from dade.tgr.rom import Release

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture

_MENU_TITLE = 0x0DADE0


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


def _track(*, sky: bool = True) -> bytes:
    data = bytearray(0x300)
    struct.pack_into('>I', data, 4, 0x230)
    struct.pack_into('>I', data, 0x50, _pointer(TRACK_BASE, 0x2A0) if sky else 0)
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


def _asset(data: bytes) -> bytes:
    stream = zlib.compress(data)
    return struct.pack('>III', 12 + len(stream), len(data), len(stream)) + stream


def _rom(path: Path) -> Path:
    image = bytearray(0xE0000)
    image[0:4] = b'\x80\x37\x12\x40'
    image[0x1000:0x1008] = b'Car One\0'
    image[0x1040:0x1048] = b'Track A\0'
    struct.pack_into('>I', image, 0x2000, 0x80200000)
    struct.pack_into('>I', image, 0x2014, 0x4000)
    struct.pack_into('>I', image, 0x3000, 0x80200040)
    struct.pack_into('>I', image, 0x3014, 0x6000)
    struct.pack_into('>I', image, 0x301C, 0x9000)
    image[0x9000:0x9004] = b'\x00\x01\xf8\x01'
    xm = b'Extended Module: '
    for offset, data in ((0x4000, _car()), (0x5000, _car()), (0x6000, _track()),
                         (0x8000, _track(sky=False)), (0x9020, bytes(2048)),
                         (0xA000, xm + b'Song Title'.ljust(20) + bytes(8)),
                         (0xB000, xm + bytes(28)), (0xC000, _part_model()),
                         (0xD000, b'random data'), (_MENU_TITLE, bytes(280 * 34 * 2))):
        asset = _asset(data)
        image[offset:offset + len(asset)] = asset
    path.write_bytes(image)
    return path


def _release(region: str) -> Release:
    return Release(region, '', 0x4000, 0x2000, 0x3000)


def test_menu_images_are_known() -> None:
    assert _MENU_TITLE in MENU_IMAGES


def test_extract_rom_us(tmp_path: Path, mocker: MockerFixture) -> None:
    mocker.patch('dade.tgr.n64.identify', return_value=_release('us'))
    run = mocker.patch('dade.tgr.output.sp.run')
    counts = extract_rom(_rom(tmp_path / 'rom.z64'), tmp_path / 'out')
    assert counts == {'cars': 2, 'tracks': 2, 'models': 1, 'music': 2, 'images': 2, 'other': 1}
    root = tmp_path / 'out' / 'us'
    for name in ('cars/car-one.glb', 'cars/005000.glb', 'tracks/track-a.glb',
                 'tracks/track-a-sky.glb', 'tracks/008000.glb', 'sky/track-a-day.png',
                 'music/00a000-song-title.xm', 'music/00b000.xm', 'models/00c000.glb',
                 'other/00d000.bin', 'images/menu-title.png'):
        assert (root / name).is_file(), name
    with Image.open(root / 'images' / 'menu-title.png') as menu:
        assert menu.size == (280, 34)
    assert (root / 'other' / '00d000.bin').read_bytes() == b'random data'
    run.assert_not_called()


def test_extract_rom_renders_music(tmp_path: Path, mocker: MockerFixture) -> None:
    mocker.patch('dade.tgr.n64.identify', return_value=_release('jp'))
    run = mocker.patch('dade.tgr.output.sp.run')
    counts = extract_rom(_rom(tmp_path / 'rom.z64'), tmp_path / 'out', tmp_path / 'ffmpeg')
    assert counts['images'] == 1
    assert counts['other'] == 2
    assert (tmp_path / 'out' / 'jp' / 'other' / f'{_MENU_TITLE:06x}.bin').is_file()
    assert [c.args[0][-1] for c in run.call_args_list] == [
        str(tmp_path / 'out' / 'jp' / 'music' / '00a000-song-title.wav'),
        str(tmp_path / 'out' / 'jp' / 'music' / '00b000.wav')
    ]
