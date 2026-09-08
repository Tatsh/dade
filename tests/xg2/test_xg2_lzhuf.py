"""Tests for :mod:`dade.xg2.lzhuf`."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import runpy

import pytest

from dade.common.exceptions import SelfCheckFailed
from dade.xg2 import lzhuf
from dade.xg2.lzhuf import (
    POSITION_CODES,
    POSITION_LENGTHS,
    LzhufError,
    decompress_lzhuf,
    demo,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

_MODULE_PATH = str(Path(lzhuf.__file__))


def _codes(**changes: int) -> tuple[int, ...]:
    values = list(POSITION_CODES)
    for index, value in changes.items():
        values[int(index)] = value
    return tuple(values)


def test_demo_holds() -> None:
    demo()


def test_module_entry_point_runs(capsys: pytest.CaptureFixture[str]) -> None:
    runpy.run_path(_MODULE_PATH, run_name='__main__')
    assert 'tables and tree bookkeeping hold' in capsys.readouterr().out


@pytest.mark.parametrize(('attr', 'value', 'match'),
                         [('POSITION_CODES', POSITION_CODES[:-1], 'code table holds'),
                          ('POSITION_LENGTHS', POSITION_LENGTHS[:-1], 'length table holds'),
                          ('POSITION_CODES', _codes(**{'0': 1}), 'First position code'),
                          ('POSITION_CODES', _codes(**{'255': 0}), 'Last position code'),
                          ('POSITION_LENGTHS', (3,) * 256, 'Position code lengths'),
                          ('POSITION_CODES', _codes(**{'100': 0}), 'wrong length')])
def test_demo_reports_a_broken_table(mocker: MockerFixture, attr: str, value: tuple[int, ...],
                                     match: str) -> None:
    mocker.patch(f'dade.xg2.lzhuf.{attr}', value)
    with pytest.raises(SelfCheckFailed, match=match):
        demo()


def test_position_tables_cover_every_byte() -> None:
    assert len(POSITION_CODES) == 256
    assert len(POSITION_LENGTHS) == 256
    assert POSITION_CODES[0] == 0
    assert POSITION_CODES[-1] == 0x3F
    assert set(POSITION_LENGTHS) == {3, 4, 5, 6, 7, 8}


def test_decompress_produces_the_declared_size() -> None:
    assert len(decompress_lzhuf(b'\x00' * 0x400, 0, 64)) == 64


def test_decompress_reorders_the_adaptive_tree() -> None:
    # A long stream of every byte value drives the adaptive tree through the reorderings that a run
    # of one symbol never triggers.
    assert len(decompress_lzhuf(bytes(range(256)) * 24, 0, 3000)) == 3000


def test_decompress_honours_the_fill_byte() -> None:
    assert len(decompress_lzhuf(b'\xff' * 0x400, 0, 32, fill=0x20)) == 32


def test_decompress_raises_when_the_stream_runs_out() -> None:
    with pytest.raises(LzhufError, match='short of'):
        decompress_lzhuf(b'', 0, 1)


def test_decompress_of_a_zero_size_is_empty() -> None:
    assert decompress_lzhuf(b'\x00' * 16, 0, 0) == b''
