"""CLI tests for the ``tonesphere decrypt-cz`` command."""
from __future__ import annotations

from typing import TYPE_CHECKING

from destin.bit192.commands.decrypt_cz import decrypt_cz

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner
    from pytest_mock import MockerFixture


def test_decrypt_cz_writes_derbh(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    source = tmp_path / 'in.cz'
    source.write_bytes(b'cipher')
    dest = tmp_path / 'out.dz'
    mocker.patch('destin.bit192.cz.decrypt', return_value=b'DTRZ\x00\x01\x02')
    result = runner.invoke(decrypt_cz, [str(source), str(dest)])
    assert result.exit_code == 0
    assert f'Decrypted {source.name}' in result.output
    assert dest.read_bytes() == b'DTRZ\x00\x01\x02'
    assert 'Warning' not in result.output


def test_decrypt_cz_warns_on_non_derbh(runner: CliRunner, mocker: MockerFixture,
                                       tmp_path: Path) -> None:
    source = tmp_path / 'in.cz'
    source.write_bytes(b'cipher')
    dest = tmp_path / 'out.dz'
    mocker.patch('destin.bit192.cz.decrypt', return_value=b'\x00\x01\x02\x03\x04')
    result = runner.invoke(decrypt_cz, [str(source), str(dest)])
    assert result.exit_code == 0
    assert 'Warning' in result.output
    assert dest.read_bytes() == b'\x00\x01\x02\x03\x04'


def test_decrypt_cz_missing_source(runner: CliRunner, mocker: MockerFixture,
                                   tmp_path: Path) -> None:
    decrypt = mocker.patch('destin.bit192.cz.decrypt')
    result = runner.invoke(decrypt_cz, [str(tmp_path / 'nope.cz'), str(tmp_path / 'out.dz')])
    assert result.exit_code == 2
    decrypt.assert_not_called()
