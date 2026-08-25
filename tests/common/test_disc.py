from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dade.common.disc import iter_ark_bytes, materialize, open_image
from dade.common.exceptions import InvalidFormatError
from dade.common.iso9660 import Iso9660Image

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@pytest.mark.asyncio
async def test_materialize_iso_extracts(make_iso9660: Callable[..., bytes], tmp_path: Path) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_bytes(make_iso9660(top_data=b'TOP', ark_data=b'ARK DATA'))
    out = tmp_path / 'out'
    await materialize(iso, out)
    assert (out / 'TOP.DAT').read_bytes() == b'TOP'
    assert (out / 'GEN' / 'MAIN.ARK').read_bytes() == b'ARK DATA'


@pytest.mark.asyncio
async def test_materialize_cuebin_extracts(make_cuebin: Callable[..., Path],
                                           make_iso9660: Callable[...,
                                                                  bytes], tmp_path: Path) -> None:
    cue = make_cuebin(make_iso9660(ark_data=b'ARK DATA'))
    out = tmp_path / 'out'
    await materialize(cue, out)
    assert (out / 'GEN' / 'MAIN.ARK').read_bytes() == b'ARK DATA'


@pytest.mark.asyncio
async def test_materialize_directory_copies(tmp_path: Path) -> None:
    source = tmp_path / 'game'
    (source / 'GEN').mkdir(parents=True)
    (source / 'GEN' / 'MAIN.ARK').write_bytes(b'ARK DATA')
    out = tmp_path / 'out'
    await materialize(source, out)
    assert (out / 'GEN' / 'MAIN.ARK').read_bytes() == b'ARK DATA'
    assert (source / 'GEN' / 'MAIN.ARK').is_file()  # The source is left untouched.


def test_iter_ark_bytes_directory(tmp_path: Path) -> None:
    (tmp_path / 'GEN').mkdir()
    (tmp_path / 'GEN' / 'MAIN.ARK').write_bytes(b'AAA')
    (tmp_path / 'B.ark').write_bytes(b'BBB')
    (tmp_path / 'notes.txt').write_bytes(b'ignored')
    assert sorted(iter_ark_bytes(tmp_path)) == [b'AAA', b'BBB']


def test_iter_ark_bytes_image(make_iso9660: Callable[..., bytes], tmp_path: Path) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_bytes(make_iso9660(ark_data=b'ARK DATA'))
    assert list(iter_ark_bytes(iso)) == [b'ARK DATA']


def test_open_image_iso(make_iso9660: Callable[..., bytes], tmp_path: Path) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_bytes(make_iso9660())
    image = open_image(iso)
    assert isinstance(image, Iso9660Image)
    assert image.contains('GEN/MAIN.ARK')


def test_open_image_cuebin(make_cuebin: Callable[..., Path], make_iso9660: Callable[...,
                                                                                    bytes]) -> None:
    cue = make_cuebin(make_iso9660())
    assert open_image(cue).contains('GEN/MAIN.ARK')


def test_open_image_invalid_raises(tmp_path: Path) -> None:
    junk = tmp_path / 'not-a-disc.iso'
    junk.write_bytes(b'this is not an ISO 9660 image')
    with pytest.raises(InvalidFormatError):
        open_image(junk)
