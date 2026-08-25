from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import subprocess as sp

from PIL import Image
import pytest

from dade.incoming.converters import ConversionError
from dade.incoming.converters.images import (
    ppm_to_png,
    pvr_pack_to_files,
    pvr_pack_to_png,
    spvr2png_converter,
)
from dade.incoming.test_utils import pvr_pack, pvrt_chunk

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def _fake_spvr2png_dir(args: list[str]) -> None:
    raw_dir, dest = Path(args[2]), Path(args[4])
    for pvr in raw_dir.glob('*.pvr'):
        (dest / f'{pvr.stem}.png').write_bytes(b'PNG')


def test_ppm_to_png(tmp_path: Path) -> None:
    source = tmp_path / 'a.ppm'
    Image.new('RGB', (2, 2), (1, 2, 3)).save(source, 'PPM')
    out = ppm_to_png(source, tmp_path)
    assert out == tmp_path / 'a.png'
    with Image.open(out) as image:
        assert image.size == (2, 2)


def test_ppm_to_png_error(tmp_path: Path) -> None:
    source = tmp_path / 'b.ppm'
    source.write_bytes(b'not an image')
    with pytest.raises(ConversionError, match='Failed to convert'):
        ppm_to_png(source, tmp_path)


def test_spvr2png_converter(tmp_path: Path, mocker: MockerFixture) -> None:
    mocker.patch('dade.incoming.converters.images.find_spvr2png', return_value=Path('/spv'))
    mocker.patch('dade.incoming.converters.images.sp.run')
    source = tmp_path / 't.pvr'
    source.write_bytes(b'x')
    assert spvr2png_converter(source, tmp_path) == tmp_path / 't.png'


def test_spvr2png_converter_failure(tmp_path: Path, mocker: MockerFixture) -> None:
    mocker.patch('dade.incoming.converters.images.find_spvr2png', return_value=Path('/spv'))
    error = sp.CalledProcessError(1, ['spv'])
    error.stderr = b'bad pixel format'
    mocker.patch('dade.incoming.converters.images.sp.run', side_effect=error)
    source = tmp_path / 't.pvr'
    source.write_bytes(b'x')
    with pytest.raises(ConversionError, match='spvr2png failed'):
        spvr2png_converter(source, tmp_path)


def test_pvr_pack_to_png(tmp_path: Path, mocker: MockerFixture) -> None:
    mocker.patch('dade.incoming.converters.images.find_spvr2png', return_value=Path('/spv'))
    mocker.patch('dade.incoming.converters.images.sp.run',
                 side_effect=lambda args, **_: _fake_spvr2png_dir(args))
    source = tmp_path / 'AFRICA_T.PVR'
    source.write_bytes(pvr_pack([pvrt_chunk(2, 2), pvrt_chunk(4, 4)]))
    outputs = pvr_pack_to_png(source, tmp_path)
    assert len(outputs) == 2
    assert (tmp_path / 'AFRICA_T').is_dir()


def test_pvr_pack_to_png_parse_error(tmp_path: Path) -> None:
    source = tmp_path / 'x.pvr'
    source.write_bytes(b'\x00\x00')
    with pytest.raises(ConversionError, match='Failed to parse'):
        pvr_pack_to_png(source, tmp_path)


def test_pvr_pack_to_files(tmp_path: Path) -> None:
    source = tmp_path / 'AFRICA_T.PVR'
    source.write_bytes(pvr_pack([pvrt_chunk(2, 2), pvrt_chunk(4, 4)]))
    outputs = pvr_pack_to_files(source, tmp_path)
    assert len(outputs) == 2
    assert all(p.suffix == '.pvr' and p.is_file() for p in outputs)
    assert (tmp_path / 'AFRICA_T').is_dir()


def test_pvr_pack_to_files_parse_error(tmp_path: Path) -> None:
    source = tmp_path / 'x.pvr'
    source.write_bytes(b'\x00\x00')
    with pytest.raises(ConversionError, match='Failed to parse'):
        pvr_pack_to_files(source, tmp_path)
