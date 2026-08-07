from __future__ import annotations

from typing import TYPE_CHECKING

from destin.common.disc import mount, mount_sync, open_image
from destin.common.iso9660 import Iso9660Image
from destin.common.typing import InvalidFormatError
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def test_mount_sync_directory_returns_source(tmp_path: Path) -> None:
    with mount_sync(tmp_path) as root:
        assert root == tmp_path


def test_mount_sync_iso_extracts(make_iso9660: Callable[..., bytes], tmp_path: Path) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_bytes(make_iso9660(top_data=b'TOP', ark_data=b'ARK DATA'))
    with mount_sync(iso) as root:
        assert root != iso
        assert (root / 'TOP.DAT').read_bytes() == b'TOP'
        assert (root / 'GEN' / 'MAIN.ARK').read_bytes() == b'ARK DATA'


def test_mount_sync_removes_temporary_directory(make_iso9660: Callable[..., bytes],
                                                tmp_path: Path) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_bytes(make_iso9660())
    with mount_sync(iso) as root:
        mount_point = root
    assert not mount_point.exists()


def test_mount_sync_cuebin_extracts(make_cuebin: Callable[..., Path],
                                    make_iso9660: Callable[..., bytes]) -> None:
    cue = make_cuebin(make_iso9660(ark_data=b'ARK DATA'))
    with mount_sync(cue) as root:
        assert (root / 'GEN' / 'MAIN.ARK').read_bytes() == b'ARK DATA'


@pytest.mark.asyncio
async def test_mount_directory_returns_source(tmp_path: Path) -> None:
    async with mount(tmp_path) as root:
        assert root == tmp_path


@pytest.mark.asyncio
async def test_mount_iso_extracts(make_iso9660: Callable[..., bytes], tmp_path: Path) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_bytes(make_iso9660(top_data=b'TOP', ark_data=b'ARK DATA'))
    async with mount(iso) as root:
        mount_point = root
        assert (root / 'GEN' / 'MAIN.ARK').read_bytes() == b'ARK DATA'
    assert not mount_point.exists()


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
