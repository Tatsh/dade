"""Configuration for Pytest."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, NoReturn
import contextlib
import os
import struct

from click.testing import CliRunner
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from pytest_mock import MockerFixture

_BLOCK_SIZE = 2048
_ROOT_LBA = 18
_GEN_LBA = 19
_TOP_DATA_LBA = 20
_ARK_DATA_LBA = 21
_TOTAL_SECTORS = 22

_SETUP_LOGGING_BINDINGS = (
    'bascom.cli',
    'destin.bitrock.commands.crack',
)
"""Modules that import :py:func:`bascom.setup_logging` and are neutralised during tests.

:meta hide-value:
"""

if os.getenv('_PYTEST_RAISE', '0') != '0':  # pragma no cover

    @pytest.hookimpl(tryfirst=True)
    def pytest_exception_interact(call: pytest.CallInfo[None]) -> NoReturn:
        assert call.excinfo is not None
        raise call.excinfo.value

    @pytest.hookimpl(tryfirst=True)
    def pytest_internalerror(excinfo: pytest.ExceptionInfo[BaseException]) -> NoReturn:
        raise excinfo.value


@pytest.fixture(autouse=True)
def _isolate_setup_logging(mocker: MockerFixture) -> None:
    """
    Stop the command callbacks from configuring global logging during the test run.

    Each game's command layer calls :py:func:`bascom.setup_logging`, which replaces the root
    logger's handlers. Now that the suites share one process, the configuration installed by the
    first suite to run would otherwise remove the handler :py:func:`caplog` relies on and hide log
    records from every suite that runs later. Patching the imported name in each module keeps the
    suites independent while still recording the calls.
    """
    for binding in _SETUP_LOGGING_BINDINGS:
        with contextlib.suppress(AttributeError, ImportError):
            mocker.patch(f'{binding}.setup_logging')


@pytest.fixture(autouse=True)
def recover_stale_process_cwd(request: pytest.FixtureRequest) -> None:
    """
    Recover when the process cwd was removed mid-session.

    Gentoo Portage test phases often run pytest with aggressive temporary-directory retention.
    The process working directory can then point at a path that no longer exists, so
    ``Path.cwd()`` raises ``FileNotFoundError`` before ``monkeypatch.chdir`` can save the
    prior cwd.
    """
    try:
        Path.cwd()
    except FileNotFoundError:
        os.chdir(Path(request.config.rootpath))


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def make_lzss() -> Callable[[bytes], bytes]:
    """
    Build an LZSS stream of literals only.

    Returns
    -------
    collections.abc.Callable[[bytes], bytes]
        A callable turning a payload into a stream that decodes back to it.
    """
    def build(payload: bytes) -> bytes:
        out = bytearray()
        for i in range(0, len(payload), 8):
            out.append(0xFF)  # Eight literal flags.
            out += payload[i:i + 8]
        return bytes(out)

    return build


def _iso_record(identifier: bytes, extent: int, size: int, *, is_dir: bool) -> bytes:
    length = 33 + len(identifier)
    if length % 2:
        length += 1
    record = bytearray(length)
    record[0] = length
    struct.pack_into('<I', record, 2, extent)
    struct.pack_into('>I', record, 6, extent)
    struct.pack_into('<I', record, 10, size)
    struct.pack_into('>I', record, 14, size)
    record[25] = 0x02 if is_dir else 0x00
    record[32] = len(identifier)
    record[33:33 + len(identifier)] = identifier
    return bytes(record)


def _iso_extent(records: Iterable[bytes]) -> bytes:
    extent = bytearray(_BLOCK_SIZE)
    position = 0
    for record in records:
        extent[position:position + len(record)] = record
        position += len(record)
    return bytes(extent)


def _iso_wrap_sectors(iso: bytes, mode: str) -> bytes:
    match mode.upper():
        case 'MODE1/2352':
            prefix, suffix = 16, 288
        case 'MODE2/2352':
            prefix, suffix = 24, 280
        case _:  # MODE1/2048.
            prefix, suffix = 0, 0
    return b''.join(
        bytes(prefix) + iso[start:start + _BLOCK_SIZE] + bytes(suffix)
        for start in range(0, len(iso), _BLOCK_SIZE))


@pytest.fixture
def make_iso9660() -> Callable[..., bytes]:
    """
    Build a minimal valid ISO 9660 image.

    The image has a top-level file ``TOP.DAT`` and a ``GEN`` subdirectory holding ``MAIN.ARK``.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking keyword ``top_data`` and ``ark_data`` values.
    """
    def build(*, top_data: bytes = b'TOP DATA', ark_data: bytes = b'ARK DATA') -> bytes:
        image = bytearray(_TOTAL_SECTORS * _BLOCK_SIZE)
        pvd = bytearray(_BLOCK_SIZE)
        pvd[0:6] = b'\x01CD001'
        pvd[6] = 1
        struct.pack_into('<H', pvd, 128, _BLOCK_SIZE)
        struct.pack_into('>H', pvd, 130, _BLOCK_SIZE)
        root_record = _iso_record(b'\x00', _ROOT_LBA, _BLOCK_SIZE, is_dir=True)
        pvd[156:156 + len(root_record)] = root_record
        image[16 * _BLOCK_SIZE:17 * _BLOCK_SIZE] = pvd
        terminator = bytearray(_BLOCK_SIZE)
        terminator[0:6] = b'\xffCD001'
        terminator[6] = 1
        image[17 * _BLOCK_SIZE:18 * _BLOCK_SIZE] = terminator
        image[_ROOT_LBA * _BLOCK_SIZE:(_ROOT_LBA + 1) * _BLOCK_SIZE] = _iso_extent(
            (_iso_record(b'\x00', _ROOT_LBA, _BLOCK_SIZE,
                         is_dir=True), _iso_record(b'\x01', _ROOT_LBA, _BLOCK_SIZE, is_dir=True),
             _iso_record(b'GEN', _GEN_LBA, _BLOCK_SIZE, is_dir=True),
             _iso_record(b'TOP.DAT;1', _TOP_DATA_LBA, len(top_data), is_dir=False)))
        image[_GEN_LBA * _BLOCK_SIZE:(_GEN_LBA + 1) * _BLOCK_SIZE] = _iso_extent(
            (_iso_record(b'\x00', _GEN_LBA, _BLOCK_SIZE,
                         is_dir=True), _iso_record(b'\x01', _ROOT_LBA, _BLOCK_SIZE, is_dir=True),
             _iso_record(b'MAIN.ARK;1', _ARK_DATA_LBA, len(ark_data), is_dir=False)))
        image[_TOP_DATA_LBA * _BLOCK_SIZE:_TOP_DATA_LBA * _BLOCK_SIZE + len(top_data)] = top_data
        image[_ARK_DATA_LBA * _BLOCK_SIZE:_ARK_DATA_LBA * _BLOCK_SIZE + len(ark_data)] = ark_data
        return bytes(image)

    return build


@pytest.fixture
def make_cuebin(tmp_path: Path) -> Callable[..., Path]:
    """
    Wrap ISO 9660 bytes into a cue/bin pair on disk.

    Returns
    -------
    collections.abc.Callable[..., pathlib.Path]
        A callable taking the ISO bytes and a keyword ``mode``, returning the ``.cue`` path.
    """
    def build(iso: bytes, *, mode: str = 'MODE1/2352') -> Path:
        (tmp_path / 'image.bin').write_bytes(_iso_wrap_sectors(iso, mode))
        cue = tmp_path / 'image.cue'
        cue.write_text(
            f'REM GENERATED\nFILE "image.bin" BINARY\n  TRACK 01 {mode}\n    INDEX 01 00:00:00\n')
        return cue

    return build
