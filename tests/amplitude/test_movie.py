from __future__ import annotations

from typing import TYPE_CHECKING
import json
import struct

from destin.amplitude import movie
from destin.amplitude.typing import InvalidFormatError
import pytest

if TYPE_CHECKING:
    from pathlib import Path


def _movs(version: int = 8, *, body: bytes = b'') -> bytes:
    return b'MOVS' + struct.pack('<5I', 0, version, 0, 2, 60) + body


def _animated(width: int = 320, height: int = 240) -> bytes:
    track = b'MOVT' + bytes(4) + b'RLE8' + struct.pack('<HH', width, height) + bytes(4)
    return _movs(8, body=track)


def _soundbank(banks: int = 3) -> bytes:
    return _movs(16, body=b'SNDH' + struct.pack('<I', banks) + bytes(4))


def test_mmv_to_json_animated_texture() -> None:
    meta = movie.mmv_to_json(_animated())
    assert meta['magic'] == 'MOVS'
    assert meta['type'] == 'animated_texture'
    assert meta['codec'] == 'RLE8'
    assert (meta['width'], meta['height']) == (320, 240)
    assert meta['version'] == 8
    assert meta['track_count'] == 2
    assert meta['tick_rate'] == 60


def test_mmv_to_json_soundbank_movie() -> None:
    meta = movie.mmv_to_json(_soundbank())
    assert meta['type'] == 'soundbank_movie'
    assert meta['bank_count'] == 3
    assert meta['version'] == 16


def test_mmv_to_json_unknown() -> None:
    meta = movie.mmv_to_json(_movs(1, body=bytes(16)))
    assert meta['type'] == 'unknown'
    assert 'width' not in meta
    assert 'bank_count' not in meta


@pytest.mark.parametrize('data', [b'JUNK' + bytes(32), b'MOVS' + bytes(8)])
def test_mmv_to_json_not_a_movie(data: bytes) -> None:
    with pytest.raises(InvalidFormatError, match='Not a `MOVS` movie'):
        movie.mmv_to_json(data)


def test_convert_writes_sidecar(tmp_path: Path) -> None:
    source = tmp_path / 'intro.mmv'
    source.write_bytes(_animated())
    out = movie.convert(source)
    assert out == tmp_path / 'intro.mmv.json'
    assert source.exists()  # The raw movie is kept.
    assert json.loads(out.read_text(encoding='utf-8'))['type'] == 'animated_texture'


def test_convert_returns_none_on_junk(tmp_path: Path) -> None:
    source = tmp_path / 'intro.mmv'
    source.write_bytes(b'JUNK' + bytes(32))
    assert movie.convert(source) is None
    assert not (tmp_path / 'intro.mmv.json').exists()
