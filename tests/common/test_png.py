"""Tests for :py:mod:`destin.common.png`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct
import zlib

from PIL import Image
from destin.common.png import encode_rgb, write_rgb, write_rgba

if TYPE_CHECKING:
    from pathlib import Path

_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def test_encode_rgb_signature() -> None:
    assert encode_rgb(2, 2, bytes(12)).startswith(_SIGNATURE)


def test_encode_rgb_header_dimensions() -> None:
    data = encode_rgb(7, 5, bytes(7 * 5 * 3))
    assert data[12:16] == b'IHDR'
    assert struct.unpack_from('>II', data, 16) == (7, 5)
    assert data[24:29] == b'\x08\x02\x00\x00\x00'


def test_encode_rgb_ends_with_iend() -> None:
    assert encode_rgb(1, 1, b'\x00\x00\x00').endswith(b'IEND\xae\x42\x60\x82')


def test_encode_rgb_round_trips_scanlines() -> None:
    rgb = bytes(range(2 * 2 * 3))
    data = encode_rgb(2, 2, rgb)
    start = data.index(b'IDAT') + 4
    length = struct.unpack_from('>I', data, data.index(b'IDAT') - 4)[0]
    raw = zlib.decompress(data[start:start + length])
    # Every scanline is prefixed with filter type 0.
    assert raw == b'\x00' + rgb[0:6] + b'\x00' + rgb[6:12]


def test_write_rgb(tmp_path: Path) -> None:
    out = tmp_path / 'a.png'
    write_rgb(out, 2, 1, bytes(6))
    assert out.read_bytes() == encode_rgb(2, 1, bytes(6))


def test_write_rgba_matches_pillow(tmp_path: Path) -> None:
    pixels = bytes(range(2 * 3 * 4))
    out = tmp_path / 'rgba.png'
    write_rgba(out, 2, 3, pixels)
    reference = tmp_path / 'reference.png'
    Image.frombytes('RGBA', (2, 3), pixels).save(reference)
    assert out.read_bytes() == reference.read_bytes()


def test_write_rgba_round_trips(tmp_path: Path) -> None:
    pixels = bytes(range(2 * 3 * 4))
    out = tmp_path / 'rgba.png'
    write_rgba(out, 2, 3, pixels)
    with Image.open(out) as image:
        assert image.mode == 'RGBA'
        assert image.size == (2, 3)
        assert image.tobytes() == pixels
