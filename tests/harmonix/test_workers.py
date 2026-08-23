from __future__ import annotations

from typing import TYPE_CHECKING
import logging

import pytest

from destin.harmonix import workers

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _identity(item: Path) -> Path:
    return item


def _skip(_item: Path) -> None:
    return None


def _boom(_item: Path) -> None:
    msg = 'boom'
    raise ValueError(msg)


@pytest.mark.parametrize(('name', 'expected'), [('song.mid', True), ('tex.abm', True),
                                                ('scene.rnd', False), ('notes.txt', False)])
def test_has_converter(name: str, expected: bool) -> None:  # noqa: FBT001
    assert workers.has_converter(name) is expected


def test_convert_file_no_match(tmp_path: Path) -> None:
    assert workers.convert_file(tmp_path / 'unknown.zzz') is None


@pytest.mark.asyncio
async def test_run_pool_sequential_counts(tmp_path: Path) -> None:
    items = [tmp_path / f'{i}.bin' for i in range(3)]
    outcome = await workers.run_pool(_identity, items, jobs=1, ignore_failures=False, label='test')
    assert outcome == (3, 0)


@pytest.mark.asyncio
async def test_run_pool_default_jobs(tmp_path: Path) -> None:
    # ``jobs=0`` falls back to the CPU count for the semaphore size.
    items = [tmp_path / f'{i}.bin' for i in range(3)]
    outcome = await workers.run_pool(_identity, items, jobs=0, ignore_failures=False, label='test')
    assert outcome == (3, 0)


@pytest.mark.asyncio
async def test_run_pool_skips_not_counted(tmp_path: Path) -> None:
    outcome = await workers.run_pool(_skip, [tmp_path / 'a', tmp_path / 'b'],
                                     jobs=1,
                                     ignore_failures=False,
                                     label='test')
    assert outcome == (0, 0)


@pytest.mark.asyncio
async def test_run_pool_empty() -> None:
    outcome = await workers.run_pool(_identity, [], jobs=4, ignore_failures=False, label='test')
    assert outcome == (0, 0)


@pytest.mark.asyncio
async def test_run_pool_raises_without_ignore(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='boom'):
        await workers.run_pool(_boom, [tmp_path / 'a', tmp_path / 'b'],
                               jobs=1,
                               ignore_failures=False,
                               label='test')


@pytest.mark.asyncio
async def test_run_pool_ignores_failures(tmp_path: Path) -> None:
    outcome = await workers.run_pool(_boom, [tmp_path / 'a', tmp_path / 'b'],
                                     jobs=1,
                                     ignore_failures=True,
                                     label='test')
    assert outcome == (0, 2)


@pytest.mark.asyncio
async def test_run_pool_parallel(tmp_path: Path) -> None:
    # ``convert_file`` is a real importable module function; files with no converter return
    # ``None`` without any I/O.
    items = [tmp_path / 'a.zzz', tmp_path / 'b.zzz']
    outcome = await workers.run_pool(workers.convert_file,
                                     items,
                                     jobs=2,
                                     ignore_failures=False,
                                     label='test')
    assert outcome == (0, 0)


def test_decompose_milo_file(make_milo: Callable[..., bytes], tmp_path: Path) -> None:
    source = tmp_path / 'scene.rnd'
    source.write_bytes(make_milo([('RndMesh', 'a.mesh', b'BODY')]))
    assert workers.decompose_milo_file(source) == tmp_path / 'scene'


def test_decompose_milo_file_not_a_milo(tmp_path: Path) -> None:
    source = tmp_path / 'scene.rnd'
    source.write_bytes(b'JUNK' + bytes(32))
    assert workers.decompose_milo_file(source) is None


def test_split_bank_file_bnk(tmp_path: Path, make_samp_bank: Callable[..., bytes],
                             make_vag: Callable[..., bytes]) -> None:
    bnk = tmp_path / 'song.bnk'
    bnk.write_bytes(make_samp_bank((('kick', 22050, 0),)))
    (tmp_path / 'song.nse').write_bytes(make_vag(2, flag=0))
    assert workers.split_bank_file(bnk) == tmp_path / 'song'


def test_split_bank_file_hd(tmp_path: Path, make_sd_bank: Callable[..., bytes],
                            make_vag: Callable[..., bytes]) -> None:
    hd = tmp_path / 'bank.hd'
    hd.write_bytes(make_sd_bank(((0, 22050, 0),), bd_size=32))
    (tmp_path / 'bank.bd').write_bytes(make_vag(2, flag=0))
    assert workers.split_bank_file(hd) == tmp_path / 'bank'


def test_str_to_wav_file(tmp_path: Path) -> None:
    src = tmp_path / 'song.str'
    src.write_bytes(bytes(4096))
    dst = tmp_path / 'out' / 'nested' / 'song.wav'
    assert workers.str_to_wav_file((src, dst)) == dst
    assert dst.read_bytes()[:4] == b'RIFF'


def test_convert_file_routes_by_extension(make_hmx_bitmap: Callable[..., bytes],
                                          tmp_path: Path) -> None:
    source = tmp_path / 'logo.bmp'
    source.write_bytes(make_hmx_bitmap(4, 4, bpp=8))
    assert workers.convert_file(source) == tmp_path / 'logo.png'


@pytest.mark.asyncio
async def test_run_pool_parallel_counts_results(make_hmx_bitmap: Callable[..., bytes],
                                                tmp_path: Path) -> None:
    for name in ('a', 'b'):
        (tmp_path / f'{name}.bmp').write_bytes(make_hmx_bitmap(4, 4, bpp=8))
    outcome = await workers.run_pool(workers.convert_file, [tmp_path / 'a.bmp', tmp_path / 'b.bmp'],
                                     jobs=2,
                                     ignore_failures=False,
                                     label='convert')
    assert outcome == (2, 0)


@pytest.mark.asyncio
async def test_run_pool_parallel_propagates_worker_logs(make_hmx_bitmap: Callable[..., bytes],
                                                        caplog: pytest.LogCaptureFixture,
                                                        tmp_path: Path) -> None:
    for name in ('a', 'b'):
        (tmp_path / f'{name}.bmp').write_bytes(make_hmx_bitmap(4, 4, bpp=8))
    with caplog.at_level(logging.DEBUG, logger='destin.harmonix.bitmap'):
        await workers.run_pool(workers.convert_file, [tmp_path / 'a.bmp', tmp_path / 'b.bmp'],
                               jobs=2,
                               ignore_failures=False,
                               label='convert')
    assert any('HMX 4x4' in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_run_pool_parallel_raises_without_ignore(tmp_path: Path) -> None:
    # A directory named like a bitmap cannot be read, so the converter raises in the worker.
    for name in ('a', 'b'):
        (tmp_path / f'{name}.bmp').mkdir()
    with pytest.raises(OSError, match='Is a directory'):
        await workers.run_pool(workers.convert_file, [tmp_path / 'a.bmp', tmp_path / 'b.bmp'],
                               jobs=2,
                               ignore_failures=False,
                               label='convert')


@pytest.mark.asyncio
async def test_run_pool_parallel_ignores_failures(tmp_path: Path) -> None:
    for name in ('a', 'b'):
        (tmp_path / f'{name}.bmp').mkdir()
    outcome = await workers.run_pool(workers.convert_file, [tmp_path / 'a.bmp', tmp_path / 'b.bmp'],
                                     jobs=2,
                                     ignore_failures=True,
                                     label='convert')
    assert outcome == (0, 2)
