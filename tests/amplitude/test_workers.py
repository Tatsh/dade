from __future__ import annotations

from concurrent.futures import Future
from typing import TYPE_CHECKING, Any
import logging
import logging.handlers

from destin.amplitude import workers
from typing_extensions import Self
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pytest_mock import MockerFixture


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


def test_run_pool_sequential_counts(tmp_path: Path) -> None:
    items = [tmp_path / f'{i}.bin' for i in range(3)]
    outcome = workers.run_pool(_identity, items, jobs=1, ignore_failures=False, label='test')
    assert outcome == (3, 0)


def test_run_pool_skips_not_counted(tmp_path: Path) -> None:
    outcome = workers.run_pool(_skip, [tmp_path / 'a', tmp_path / 'b'],
                               jobs=1,
                               ignore_failures=False,
                               label='test')
    assert outcome == (0, 0)


def test_run_pool_empty() -> None:
    outcome = workers.run_pool(_identity, [], jobs=4, ignore_failures=False, label='test')
    assert outcome == (0, 0)


def test_run_pool_raises_without_ignore(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='boom'):
        workers.run_pool(_boom, [tmp_path / 'a', tmp_path / 'b'],
                         jobs=1,
                         ignore_failures=False,
                         label='test')


def test_run_pool_ignores_failures(tmp_path: Path) -> None:
    outcome = workers.run_pool(_boom, [tmp_path / 'a', tmp_path / 'b'],
                               jobs=1,
                               ignore_failures=True,
                               label='test')
    assert outcome == (0, 2)


def test_run_pool_parallel(tmp_path: Path) -> None:
    # ``convert_file`` is a real importable module function, so it survives pickling to a worker;
    # files with no converter return ``None`` without any I/O.
    items = [tmp_path / 'a.zzz', tmp_path / 'b.zzz']
    outcome = workers.run_pool(workers.convert_file,
                               items,
                               jobs=2,
                               ignore_failures=False,
                               label='test')
    assert outcome == (0, 0)


class _InlineExecutor:
    """A stand-in pool that runs the initialiser and every task in this process."""
    def __init__(self, *, max_workers: int, initializer: Callable[..., None],
                 initargs: tuple[Any, ...]) -> None:
        self._root = logging.getLogger().handlers
        initializer(*initargs)

    def __enter__(self) -> Self:
        return self

    @staticmethod
    def submit(func: Callable[[Any], Any], item: Any) -> Future[Any]:
        """
        Run ``func`` immediately and return an already-settled future.

        Parameters
        ----------
        func : collections.abc.Callable[[typing.Any], typing.Any]
            The task to run.
        item : typing.Any
            The work item.

        Returns
        -------
        concurrent.futures.Future[typing.Any]
            A future already holding the result or the raised exception.
        """
        future: Future[Any] = Future()
        try:
            future.set_result(func(item))
        except BaseException as e:  # noqa: BLE001
            future.set_exception(e)
        return future

    def shutdown(self, *, wait: bool = True, cancel_futures: bool = False) -> None:
        """
        Restore the logging handlers the initialiser replaced.

        Parameters
        ----------
        wait : bool
            Ignored; the tasks already ran.
        cancel_futures : bool
            Ignored; the tasks already ran.
        """
        logging.getLogger().handlers = self._root


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


def test_run_pool_parallel_counts_results(make_hmx_bitmap: Callable[..., bytes],
                                          tmp_path: Path) -> None:
    for name in ('a', 'b'):
        (tmp_path / f'{name}.bmp').write_bytes(make_hmx_bitmap(4, 4, bpp=8))
    outcome = workers.run_pool(workers.convert_file,
                               sorted(tmp_path.glob('*.bmp')),
                               jobs=2,
                               ignore_failures=False,
                               label='convert')
    assert outcome == (2, 0)


def test_run_pool_parallel_reinjects_worker_logs(make_hmx_bitmap: Callable[..., bytes],
                                                 caplog: pytest.LogCaptureFixture,
                                                 tmp_path: Path) -> None:
    for name in ('a', 'b'):
        (tmp_path / f'{name}.bmp').write_bytes(make_hmx_bitmap(4, 4, bpp=8))
    with caplog.at_level(logging.DEBUG, logger='destin.amplitude.bitmap'):
        workers.run_pool(workers.convert_file,
                         sorted(tmp_path.glob('*.bmp')),
                         jobs=2,
                         ignore_failures=False,
                         label='convert')
    assert any('HMX 4x4' in record.getMessage() for record in caplog.records)


def test_run_pool_parallel_raises_without_ignore(tmp_path: Path) -> None:
    # A directory named like a bitmap cannot be read, so the converter raises in the worker.
    for name in ('a', 'b'):
        (tmp_path / f'{name}.bmp').mkdir()
    with pytest.raises(OSError, match='Is a directory'):
        workers.run_pool(workers.convert_file,
                         sorted(tmp_path.glob('*.bmp')),
                         jobs=2,
                         ignore_failures=False,
                         label='convert')


def test_run_pool_parallel_ignores_failures(tmp_path: Path) -> None:
    for name in ('a', 'b'):
        (tmp_path / f'{name}.bmp').mkdir()
    outcome = workers.run_pool(workers.convert_file,
                               sorted(tmp_path.glob('*.bmp')),
                               jobs=2,
                               ignore_failures=True,
                               label='convert')
    assert outcome == (0, 2)


def test_run_pool_initialises_workers(mocker: MockerFixture, tmp_path: Path) -> None:
    # The pool initialiser routes each worker's root logger through the shared queue.
    mocker.patch('destin.amplitude.workers.ProcessPoolExecutor', _InlineExecutor)
    handlers: list[list[logging.Handler]] = []

    def record(item: Path) -> Path:
        handlers.append(logging.getLogger().handlers)
        return item

    outcome = workers.run_pool(record, [tmp_path / 'a', tmp_path / 'b'],
                               jobs=2,
                               ignore_failures=False,
                               label='test')
    assert outcome == (2, 0)
    assert all(
        isinstance(handler, logging.handlers.QueueHandler) for batch in handlers
        for handler in batch)
