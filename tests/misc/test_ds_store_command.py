"""Tests for the ``dade misc ds-store`` command."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json
import struct

from dade.misc.commands.ds_store import ds_store

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner


def test_ds_store_writes_json(runner: CliRunner, ds_store_path: Path) -> None:
    result = runner.invoke(ds_store, (str(ds_store_path),))
    assert result.exit_code == 0
    converted = json.loads(result.output)
    assert converted['entries']['Photos']['Iloc'] == {
        'trailer': 'ffffffffffff0000',
        'x': 132,
        'y': 64
    }
    assert converted['structure']['directories']['DSDB']['records'] == 11


def test_ds_store_aborts_on_a_file_that_is_not_a_database(runner: CliRunner,
                                                          tmp_path: Path) -> None:
    path = tmp_path / '.DS_Store'
    path.write_bytes(struct.pack('>I4sIII', 1, b'Bud0', 0x2000, 8, 0x2000))
    result = runner.invoke(ds_store, (str(path),))
    assert result.exit_code == 1
    assert 'Not a Buddy allocator file' in result.output
