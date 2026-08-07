"""Tests for :py:mod:`destin.common.png`."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image
from destin.common.png import write_rgb, write_rgba

if TYPE_CHECKING:
    from pathlib import Path


def test_write_rgb_round_trips(tmp_path: Path) -> None:
    pixels = bytes(range(2 * 1 * 3))
    out = tmp_path / 'a.png'
    write_rgb(out, 2, 1, pixels)
    with Image.open(out) as image:
        assert image.mode == 'RGB'
        assert image.size == (2, 1)
        assert image.tobytes() == pixels


def test_write_rgb_forces_png_regardless_of_extension(tmp_path: Path) -> None:
    out = tmp_path / 'a.dat'
    write_rgb(out, 1, 1, b'\x01\x02\x03')
    with Image.open(out) as image:
        assert image.format == 'PNG'


def test_write_rgba_round_trips(tmp_path: Path) -> None:
    pixels = bytes(range(2 * 3 * 4))
    out = tmp_path / 'rgba.png'
    write_rgba(out, 2, 3, pixels)
    with Image.open(out) as image:
        assert image.mode == 'RGBA'
        assert image.size == (2, 3)
        assert image.tobytes() == pixels
