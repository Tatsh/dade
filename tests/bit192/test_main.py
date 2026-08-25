"""Tests for the ``tonesphere`` root group and console-script entry point."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dade.bit192.main import main, tonesphere

if TYPE_CHECKING:
    from click.testing import CliRunner


def test_tonesphere_help_lists_subcommands(runner: CliRunner) -> None:
    result = runner.invoke(tonesphere, ['--help'])
    assert result.exit_code == 0
    assert 'Tone Sphere' in result.output
    for name in ('decrypt-cz', 'extract', 'save'):
        assert name in result.output


def test_main_invokes_group(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('sys.argv', ['tonesphere', '--help'])
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 0
