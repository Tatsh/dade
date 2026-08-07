from __future__ import annotations

from typing import TYPE_CHECKING
import json
import struct

from destin.harmonix import video
from destin.harmonix.typing import InvalidFormatError
import pytest

if TYPE_CHECKING:
    from pathlib import Path


def _ipu(width: int = 512, height: int = 448, frames: int = 900) -> bytes:
    return b'ipum' + bytes(4) + struct.pack('<HHI', width, height, frames) + bytes(16)


def test_ipu_to_json() -> None:
    meta = video.ipu_to_json(_ipu())
    assert meta == {'magic': 'ipum', 'width': 512, 'height': 448, 'frame_count': 900}


@pytest.mark.parametrize('data', [b'JUNK' + bytes(32), b'ipum' + bytes(4)])
def test_ipu_to_json_not_an_ipu(data: bytes) -> None:
    with pytest.raises(InvalidFormatError, match='Not a PS2 IPU'):
        video.ipu_to_json(data)


def test_convert_writes_sidecar(tmp_path: Path) -> None:
    source = tmp_path / 'intro.ipu'
    source.write_bytes(_ipu())
    out = video.convert(source)
    assert out == tmp_path / 'intro.ipu.json'
    assert source.exists()  # The raw video is kept.
    assert json.loads(out.read_text(encoding='utf-8'))['frame_count'] == 900


def test_convert_returns_none_on_junk(tmp_path: Path) -> None:
    source = tmp_path / 'intro.ipu'
    source.write_bytes(b'JUNK' + bytes(32))
    assert video.convert(source) is None
    assert not (tmp_path / 'intro.ipu.json').exists()
