"""Tests for :py:mod:`destin.jubeatplus.images`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import subprocess as sp

import pytest

from destin.common.bfcodec import BFCodec
from destin.jubeatplus.cipher import bgm_key, texture_key
from destin.jubeatplus.images import PNG_MAGIC, decipher_image, defry_png, write_defried_png

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def test_decipher_image_drops_the_header(make_png: Callable[..., bytes]) -> None:
    png = make_png()
    enciphered = BFCodec(texture_key()).encipher(b'\x9d\xf2\x5b\x0a' + png)
    assert decipher_image(enciphered) == png


def test_decipher_image_takes_another_key(make_png: Callable[..., bytes]) -> None:
    png = make_png()
    enciphered = BFCodec(bgm_key()).encipher(b'\0\0\0\0' + png)
    assert decipher_image(enciphered, bgm_key()).startswith(PNG_MAGIC)


def test_decipher_image_accepts_a_payload_that_is_only_a_header() -> None:
    # Four bytes is the shortest plaintext that is not too short, and it leaves nothing behind.
    assert decipher_image(BFCodec(texture_key()).encipher(b'\1\2\3\4')) == b''


def test_decipher_image_rejects_a_payload_with_no_header() -> None:
    with pytest.raises(ValueError, match='Too short for the 4-byte image header'):
        decipher_image(BFCodec(texture_key()).encipher(b'ab'))


def test_decipher_image_rejects_a_bad_trailer() -> None:
    with pytest.raises(ValueError, match='Bad length trailer'):
        decipher_image(b'\0' * 32)


def test_defry_png_converts_an_apple_png(tmp_path: Path, fake_pngdefry: Path,
                                         make_apple_png: Callable[..., bytes]) -> None:
    source = tmp_path / 'in.png'
    source.write_bytes(make_apple_png())
    destination = tmp_path / 'out.png'
    assert defry_png(source, destination, fake_pngdefry) is True
    assert b'CgBI' not in destination.read_bytes()


def test_defry_png_leaves_an_ordinary_png_alone(tmp_path: Path, fake_pngdefry: Path,
                                                make_png: Callable[..., bytes]) -> None:
    source = tmp_path / 'in.png'
    source.write_bytes(make_png())
    assert defry_png(source, tmp_path / 'out.png', fake_pngdefry) is False
    assert not (tmp_path / 'out.png').exists()


def test_defry_png_cleans_up_after_a_failure(tmp_path: Path, failing_tool: Path,
                                             make_png: Callable[..., bytes]) -> None:
    source = tmp_path / 'in.png'
    source.write_bytes(make_png())
    with pytest.raises(sp.CalledProcessError):
        defry_png(source, tmp_path / 'out.png', failing_tool)
    assert not (tmp_path / '.out.png.defry').exists()


def test_write_defried_png_copies_an_ordinary_png(tmp_path: Path, fake_pngdefry: Path,
                                                  make_png: Callable[..., bytes]) -> None:
    source = tmp_path / 'in.png'
    source.write_bytes(make_png())
    destination = tmp_path / 'out.png'
    assert write_defried_png(source, destination, fake_pngdefry) == destination
    assert destination.read_bytes() == source.read_bytes()


def test_write_defried_png_in_place(tmp_path: Path, fake_pngdefry: Path,
                                    make_png: Callable[..., bytes]) -> None:
    path = tmp_path / 'both.png'
    path.write_bytes(make_png())
    assert write_defried_png(path, path, fake_pngdefry) == path
    assert path.read_bytes().startswith(PNG_MAGIC)
