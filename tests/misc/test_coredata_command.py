"""Tests for the ``destin misc coredata`` command."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json

from destin.misc.commands.coredata import coredata

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner


def test_coredata_writes_json(runner: CliRunner, mapping_model: Path) -> None:
    result = runner.invoke(coredata, (str(mapping_model),))
    assert result.exit_code == 0
    assert [m['name'] for m in json.loads(result.output)['entityMappings']] == [
        'ScoreToScore', 'RemoveLegacy'
    ]


def test_coredata_archive_mode(runner: CliRunner, mapping_model: Path) -> None:
    result = runner.invoke(coredata, (str(mapping_model), '--archive'))
    assert result.exit_code == 0
    assert json.loads(result.output)['$archiver'] == 'NSKeyedArchiver'


def test_coredata_sql(runner: CliRunner, mapping_model: Path) -> None:
    result = runner.invoke(coredata, (str(mapping_model), '--sql'))
    assert result.exit_code == 0
    assert result.output.startswith('-- Effective SQLite statements')
    assert 'CREATE TABLE ZSCORE (' in result.output


def test_coredata_sql_with_mom(runner: CliRunner, mapping_model: Path,
                               managed_object_model: Path) -> None:
    result = runner.invoke(coredata,
                           (str(mapping_model), '--sql', '--mom', str(managed_object_model)))
    assert result.exit_code == 0
    assert 'ZTITLE VARCHAR' in result.output


def test_coredata_aborts_on_a_foreign_file(runner: CliRunner, text_strings: Path) -> None:
    result = runner.invoke(coredata, (str(text_strings),))
    assert result.exit_code == 1
