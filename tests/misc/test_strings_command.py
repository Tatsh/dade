"""Tests for the ``destin misc strings`` command."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json
import plistlib

from destin.misc.commands.strings import strings

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner


def test_strings_writes_json(runner: CliRunner, compiled_strings: Path) -> None:
    result = runner.invoke(strings, (str(compiled_strings),))
    assert result.exit_code == 0
    assert json.loads(result.output) == {'ok': 'OK', 'cancel': 'キャンセル'}


def test_strings_reads_the_text_form(runner: CliRunner, text_strings: Path) -> None:
    result = runner.invoke(strings, (str(text_strings),))
    assert result.exit_code == 0
    assert json.loads(result.output)['quote'] == 'say "hi"'


def test_strings_aborts_on_a_plist_that_is_not_a_table(runner: CliRunner, tmp_path: Path) -> None:
    path = tmp_path / 'List.strings'
    path.write_bytes(plistlib.dumps([1, 2], fmt=plistlib.FMT_BINARY))
    result = runner.invoke(strings, (str(path),))
    assert result.exit_code == 1
    assert 'root is not a dictionary' in result.output
