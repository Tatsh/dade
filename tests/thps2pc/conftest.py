"""Shared pytest configuration for the ``thps2pc`` tests."""
from __future__ import annotations

from typing import TYPE_CHECKING

from destin.thps2pc.psx import Scene
from destin.thps2pc.test_utils import (
    SectorSpec,
    TextureSpec,
    face_record,
    pkr_archive,
    psx_lighting,
    psx_scene,
    stored_file,
)
import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture

_TRIANGLE = face_record((0, 1, 2), texture_index=0, uvs=((0, 0), (128, 0), (0, 128)), flags=0x11)
_QUAD = face_record((0, 1, 2, 3),
                    texture_index=1,
                    uvs=((0, 0), (64, 0), (0, 64), (64, 64)),
                    flags=0x01,
                    length=8)


@pytest.fixture(autouse=True)
def _isolate_command_logging(mocker: MockerFixture) -> None:
    """Stop command callbacks from configuring real logging during the test run."""
    mocker.patch('bascom.cli.setup_logging')


@pytest.fixture
def pkr_bytes() -> bytes:
    """
    Build a small stored-method pack holding three files across two directories.

    Returns
    -------
    bytes
        The complete pack.
    """
    return pkr_archive(((
        'data/',
        (stored_file('A.PSX', b'AAAA'), stored_file('B.PSX', b'BB')),
    ), ('newtex/', (stored_file('C.BMP', b'CCCCCC'),))))


@pytest.fixture
def scene_bytes() -> bytes:
    """
    Build a scene with two sectors, two descriptors, a chunk, and two texture checksums.

    Returns
    -------
    bytes
        The complete scene.
    """
    sector = SectorSpec(vertices=((0, 0, 0), (100, 0, 0), (0, 0, 100), (100, 0, 100)),
                        faces=(_TRIANGLE, _QUAD),
                        count_b=1)
    return psx_scene(sectors=(sector, sector),
                     descriptors=((0, (0, 0, 0)), (1, (500, 0, 500))),
                     chunks=((0x52454948, b'\x00' * 4),),
                     checksums=(0xDEADBEEF, 0xCAFEF00D))


@pytest.fixture
def scene(scene_bytes: bytes) -> Scene:
    """
    Parse the scene built by :py:func:`scene_bytes`.

    Parameters
    ----------
    scene_bytes : bytes
        The scene to parse.

    Returns
    -------
    Scene
        The parsed scene.
    """
    return Scene.parse(scene_bytes)


@pytest.fixture
def lighting_bytes() -> bytes:
    """
    Build a lighting file with a 4-bit texture, an 8-bit texture, and one unresolvable palette.

    Returns
    -------
    bytes
        The complete lighting file.
    """
    return psx_lighting(checksums=(0xA1B2C3D4, 0x11223344),
                        cluts_16={7: (0x7C00, 0x03E0, 0x001F, 0x0000)},
                        cluts_256={9: (0x0000, 0x7FFF)},
                        instances=(TextureSpec(clut_id=7,
                                               height=2,
                                               num_colors=0x10,
                                               page=0,
                                               pixels=bytes((0x10, 0x32)),
                                               width=2),
                                   TextureSpec(clut_id=9,
                                               height=1,
                                               num_colors=256,
                                               page=1,
                                               pixels=bytes((1, 0)),
                                               width=2),
                                   TextureSpec(clut_id=404,
                                               height=1,
                                               num_colors=256,
                                               page=0,
                                               pixels=b'\x00',
                                               width=1)))


@pytest.fixture
def scene_file(scene_bytes: bytes, tmp_path: Path) -> Path:
    """
    Write the shared scene to a temporary file.

    Parameters
    ----------
    scene_bytes : bytes
        The scene to write.
    tmp_path : pathlib.Path
        Directory the scene is written into.

    Returns
    -------
    pathlib.Path
        Path to the written scene.
    """
    path = tmp_path / 'S.PSX'
    path.write_bytes(scene_bytes)
    return path


@pytest.fixture
def lighting_file(lighting_bytes: bytes, tmp_path: Path) -> Path:
    """
    Write the shared lighting file to a temporary file.

    Parameters
    ----------
    lighting_bytes : bytes
        The lighting file to write.
    tmp_path : pathlib.Path
        Directory the file is written into.

    Returns
    -------
    pathlib.Path
        Path to the written lighting file.
    """
    path = tmp_path / 'S_L.PSX'
    path.write_bytes(lighting_bytes)
    return path
