"""Tests for :py:mod:`dade.common.apple_png`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct
import subprocess as sp
import zlib

import pytest

from dade.common.apple_png import (
    CGBI_CHUNK_TYPE,
    PNG_MAGIC,
    defry_png,
    is_apple_optimized,
    write_defried_png,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture


def _chunk(kind: bytes, body: bytes) -> bytes:
    return (struct.pack('>I', len(body)) + kind + body +
            struct.pack('>I',
                        zlib.crc32(kind + body) & 0xFFFF_FFFF))


def _png(*, cgbi: bool = False) -> bytes:
    body = (_chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 0, 0, 0, 0)) +
            _chunk(b'IDAT', zlib.compress(b'\0\xff')) + _chunk(b'IEND', b''))
    return PNG_MAGIC + (_chunk(CGBI_CHUNK_TYPE, bytes(4)) if cgbi else b'') + body


def test_an_apple_optimized_png_is_recognised() -> None:
    assert is_apple_optimized(_png(cgbi=True))


def test_an_ordinary_png_is_not() -> None:
    assert not is_apple_optimized(_png())


def test_something_that_is_not_a_png_is_not() -> None:
    assert not is_apple_optimized(b'not a png at all')


def test_a_buffer_too_short_to_tell_is_not() -> None:
    assert not is_apple_optimized(PNG_MAGIC)
    assert not is_apple_optimized(b'')


def test_defry_png_moves_what_the_tool_wrote(tmp_path: Path, mocker: MockerFixture) -> None:
    source = tmp_path / 'in.png'
    source.write_bytes(_png(cgbi=True))
    destination = tmp_path / 'out.png'

    def run(args: tuple[str, ...], **_: object) -> object:
        out = next(a[2:] for a in args if a.startswith('-o'))
        (tmp_path / out / source.name).write_bytes(b'converted')
        return mocker.Mock(returncode=0)

    mocker.patch('dade.common.apple_png.sp.run', side_effect=run)
    assert defry_png(source, destination, tmp_path / 'pngdefry')
    assert destination.read_bytes() == b'converted'


def test_defry_png_reports_when_the_tool_wrote_nothing(tmp_path: Path,
                                                       mocker: MockerFixture) -> None:
    source = tmp_path / 'in.png'
    source.write_bytes(_png())
    mocker.patch('dade.common.apple_png.sp.run', return_value=mocker.Mock(returncode=0))
    assert not defry_png(source, tmp_path / 'out.png', tmp_path / 'pngdefry')


def test_defry_png_cleans_up_when_the_tool_fails(tmp_path: Path, mocker: MockerFixture) -> None:
    source = tmp_path / 'in.png'
    source.write_bytes(_png(cgbi=True))
    destination = tmp_path / 'out.png'
    mocker.patch('dade.common.apple_png.sp.run', side_effect=sp.CalledProcessError(1, 'pngdefry'))
    with pytest.raises(sp.CalledProcessError):
        defry_png(source, destination, tmp_path / 'pngdefry')
    assert not (destination.parent / f'.{destination.name}.defry').exists()


def test_write_defried_png_copies_an_ordinary_png(tmp_path: Path, mocker: MockerFixture) -> None:
    source = tmp_path / 'in.png'
    plain = _png()
    source.write_bytes(plain)
    destination = tmp_path / 'out.png'
    mocker.patch('dade.common.apple_png.defry_png', return_value=False)
    assert write_defried_png(source, destination, tmp_path / 'pngdefry') == destination
    assert destination.read_bytes() == plain


def test_write_defried_png_leaves_an_in_place_conversion_alone(tmp_path: Path,
                                                               mocker: MockerFixture) -> None:
    path = tmp_path / 'same.png'
    plain = _png()
    path.write_bytes(plain)
    mocker.patch('dade.common.apple_png.defry_png', return_value=False)
    assert write_defried_png(path, path, tmp_path / 'pngdefry') == path
    assert path.read_bytes() == plain


def test_write_defried_png_keeps_a_conversion(tmp_path: Path, mocker: MockerFixture) -> None:
    source = tmp_path / 'in.png'
    source.write_bytes(_png(cgbi=True))
    destination = tmp_path / 'out.png'
    mocker.patch('dade.common.apple_png.defry_png', return_value=True)
    assert write_defried_png(source, destination, tmp_path / 'pngdefry') == destination
