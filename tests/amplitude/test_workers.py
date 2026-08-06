from __future__ import annotations

from typing import TYPE_CHECKING

from destin.amplitude import workers
import pytest

if TYPE_CHECKING:
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
