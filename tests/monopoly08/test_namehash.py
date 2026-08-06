from __future__ import annotations

from pathlib import Path
import runpy

from destin.monopoly08 import namehash
from destin.monopoly08.namehash import GROUND_TRUTH, name_hash
import pytest

_MODULE_PATH = str(Path(namehash.__file__))


@pytest.mark.parametrize(('name', 'expected'), GROUND_TRUTH)
def test_name_hash_matches_ground_truth(name: str, expected: int) -> None:
    assert name_hash(name) == expected


def test_name_hash_includes_extension_when_not_stopping() -> None:
    assert name_hash('BtnAccept.xmap', stop_at_extension=False) != name_hash('BtnAccept.xmap')


@pytest.mark.parametrize(('name', 'expected'), [('', 0), ('a', 0x61), ('A', 0x61),
                                                ('.anything', 0)])
def test_name_hash_simple_inputs(name: str, expected: int) -> None:
    assert name_hash(name) == expected


def test_name_hash_folds_the_high_nibble() -> None:
    # A long name drives the hash past 0x0FFFFFFF so the top-nibble fold runs.
    assert name_hash('abcdefghijklmnop') == 0x0BB9A310


def test_module_entry_point_verifies_ground_truth(capsys: pytest.CaptureFixture[str]) -> None:
    runpy.run_path(_MODULE_PATH, run_name='__main__')
    assert f'OK: {len(GROUND_TRUTH)}' in capsys.readouterr().out


def test_module_entry_point_reports_a_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    # Forcing every character to the same code point makes the computed hashes disagree with the
    # ground truth without touching the module itself.
    monkeypatch.setattr('builtins.ord', lambda _: 0x61)
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_path(_MODULE_PATH, run_name='__main__')
    monkeypatch.undo()  # `re` needs the real `ord` to compile the assertion below.
    assert 'expected 0479f5c4' in str(excinfo.value)
