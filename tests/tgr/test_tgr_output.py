from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image

from dade.tgr.f3dex import Corner, Material, Triangle
from dade.tgr.model import Part
from dade.tgr.output import ffmpeg, write_model, write_png, write_sky
from dade.tgr.texture import FMT_RGBA, SIZ_16B, TextureKey

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture

_IDENTITY = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
_RED = (255, 0, 0, 255)
_BLUE = (0, 0, 255, 255)


def test_write_png_upright(tmp_path: Path) -> None:
    path = tmp_path / 'a' / 'image.png'
    write_png(path, 2, 1, bytes(_RED + _BLUE))
    with Image.open(path) as image:
        assert image.size == (2, 1)
        assert image.getpixel((0, 0)) == _RED


def test_write_png_turned_and_mirrored(tmp_path: Path) -> None:
    path = tmp_path / 'image.png'
    write_png(path, 2, 1, bytes(_RED + _BLUE), (1, True))
    with Image.open(path) as image:
        assert image.size == (1, 2)
        assert image.getpixel((0, 0)) == _BLUE
        assert image.getpixel((0, 1)) == _RED


def test_write_sky_puts_the_first_row_at_the_bottom(tmp_path: Path) -> None:
    path = tmp_path / 'sky.png'
    palette = b'\x00\x01\xf8\x01' + bytes(28)
    write_sky(path, palette, b'\x11' * 16 + bytes(2032))
    with Image.open(path) as image:
        assert image.size == (32, 128)
        assert image.getpixel((0, 127)) == _RED
        assert image.getpixel((0, 0)) == (0, 0, 0, 255)


def test_write_model(tmp_path: Path) -> None:
    key = TextureKey(0, -1, FMT_RGBA, SIZ_16B, 2, 1, 0)
    corners = (Corner((0.0, 0.0, 0.0), (0.0, 1.0),
                      (0, 0, 127, 255)), Corner((1.0, 0.0, 0.0), (1.0, 1.0), (0, 0, 127, 255)),
               Corner((0.0, 0.0, 1.0), (0.0, 0.0), (0, 0, 127, 255)))
    parts = [Part('a', (Triangle(Material(key, lit=True, two_sided=False), corners),), _IDENTITY)]
    path = tmp_path / 'out' / 'model.glb'
    assert write_model(path, b'\xf8\x01\xf8\x01', parts) == 1
    assert path.read_bytes()[:4] == b'glTF'
    assert (tmp_path / 'out' / 'model' / '000000.png').is_file()


def test_ffmpeg(tmp_path: Path, mocker: MockerFixture) -> None:
    run = mocker.patch('dade.tgr.output.sp.run')
    destination = tmp_path / 'music' / 'song.wav'
    ffmpeg(tmp_path / 'ffmpeg', tmp_path / 'song.xm', destination, '-ar', '44100')
    run.assert_called_once_with(
        (str(tmp_path / 'ffmpeg'), '-hide_banner', '-loglevel', 'error', '-y', '-ar', '44100', '-i',
         str(tmp_path / 'song.xm'), str(destination)),
        check=True)
    assert destination.parent.is_dir()
