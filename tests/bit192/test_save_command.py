"""CLI tests for the ``tonesphere save`` sub-commands."""
from __future__ import annotations

from typing import TYPE_CHECKING

from destin.bit192.commands.save import device_id, generate, unlock_all, unlock_dlc, unlock_songs

if TYPE_CHECKING:
    from pathlib import Path
    from unittest.mock import MagicMock

    from click.testing import CliRunner
    from pytest_mock import MockerFixture


def _save_file_mock(mocker: MockerFixture,
                    *,
                    device_id: str = 'dev1',
                    song_count: int = 1023,
                    packs: list[str] | None = None) -> MagicMock:
    sf: MagicMock = mocker.MagicMock()
    sf.device_id = device_id
    sf.unlock_all_songs.return_value = song_count
    sf.unlock_all_dlc.return_value = packs if packs is not None else ['vvv', 'empy']
    return sf


def test_device_id_found(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    save_path = tmp_path / 'save.bin'
    save_path.write_bytes(b'\x00')
    sf = _save_file_mock(mocker, device_id='abc123')
    mocker.patch('destin.bit192.commands.save.SaveFile.load', return_value=sf)
    result = runner.invoke(device_id, [str(save_path)])
    assert result.exit_code == 0
    assert 'Device ID: abc123' in result.output


def test_device_id_absent(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    save_path = tmp_path / 'save.bin'
    save_path.write_bytes(b'\x00')
    sf = _save_file_mock(mocker, device_id='')
    mocker.patch('destin.bit192.commands.save.SaveFile.load', return_value=sf)
    result = runner.invoke(device_id, [str(save_path)])
    assert result.exit_code == 0
    assert 'No device id is cached' in result.output


def test_unlock_dlc_all_packs(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    save_path = tmp_path / 'save.bin'
    save_path.write_bytes(b'\x00')
    sf = _save_file_mock(mocker, packs=['darksphere', 'vvv'])
    load = mocker.patch('destin.bit192.commands.save.SaveFile.load', return_value=sf)
    result = runner.invoke(unlock_dlc, [str(save_path)])
    assert result.exit_code == 0
    assert 'Unlocked darksphere, vvv' in result.output
    load.assert_called_once_with(save_path)
    sf.unlock_all_dlc.assert_called_once_with()
    sf.unlock_dlc.assert_not_called()
    sf.save.assert_called_once_with(save_path)


def test_unlock_dlc_specific_packs(runner: CliRunner, mocker: MockerFixture,
                                   tmp_path: Path) -> None:
    save_path = tmp_path / 'save.bin'
    save_path.write_bytes(b'\x00')
    out_path = tmp_path / 'save.new'
    sf = _save_file_mock(mocker)
    mocker.patch('destin.bit192.commands.save.SaveFile.load', return_value=sf)
    result = runner.invoke(unlock_dlc,
                           [str(save_path), '-p', 'vvv', '-p', 'empy', '-o',
                            str(out_path)])
    assert result.exit_code == 0
    assert 'Unlocked vvv, empy' in result.output
    sf.unlock_all_dlc.assert_not_called()
    assert [c.args[0] for c in sf.unlock_dlc.call_args_list] == ['vvv', 'empy']
    sf.save.assert_called_once_with(out_path)


def test_unlock_dlc_rejects_unknown_pack(runner: CliRunner, mocker: MockerFixture,
                                         tmp_path: Path) -> None:
    save_path = tmp_path / 'save.bin'
    save_path.write_bytes(b'\x00')
    load = mocker.patch('destin.bit192.commands.save.SaveFile.load')
    result = runner.invoke(unlock_dlc, [str(save_path), '-p', 'not-a-pack'])
    assert result.exit_code == 2
    load.assert_not_called()


def test_unlock_songs_success(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    save_path = tmp_path / 'save.bin'
    save_path.write_bytes(b'\x00')
    sf = _save_file_mock(mocker, song_count=1023)
    load = mocker.patch('destin.bit192.commands.save.SaveFile.load', return_value=sf)
    result = runner.invoke(unlock_songs, [str(save_path)])
    assert result.exit_code == 0
    assert 'Set 1023 song unlock flags' in result.output
    assert str(save_path) in result.output
    load.assert_called_once_with(save_path)
    sf.unlock_all_songs.assert_called_once_with()
    sf.save.assert_called_once_with(save_path)


def test_unlock_songs_out_option(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    save_path = tmp_path / 'save.bin'
    save_path.write_bytes(b'\x00')
    out_path = tmp_path / 'save.new'
    sf = _save_file_mock(mocker)
    mocker.patch('destin.bit192.commands.save.SaveFile.load', return_value=sf)
    result = runner.invoke(unlock_songs, [str(save_path), '-o', str(out_path)])
    assert result.exit_code == 0
    sf.save.assert_called_once_with(out_path)


def test_unlock_songs_missing_path(runner: CliRunner, mocker: MockerFixture) -> None:
    load = mocker.patch('destin.bit192.commands.save.SaveFile.load')
    result = runner.invoke(unlock_songs, ['does-not-exist.bin'])
    assert result.exit_code == 2
    load.assert_not_called()


def test_unlock_all_success(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    save_path = tmp_path / 'save.bin'
    save_path.write_bytes(b'\x00')
    sf = _save_file_mock(mocker, song_count=1023, packs=['vvv', 'empy'])
    load = mocker.patch('destin.bit192.commands.save.SaveFile.load', return_value=sf)
    result = runner.invoke(unlock_all, [str(save_path)])
    assert result.exit_code == 0
    assert 'Set 1023 song flags' in result.output
    assert 'vvv, empy' in result.output
    assert str(save_path) in result.output
    load.assert_called_once_with(save_path)
    sf.unlock_all_songs.assert_called_once_with()
    sf.unlock_all_dlc.assert_called_once_with()
    sf.save.assert_called_once_with(save_path)


def test_unlock_all_out_option(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    save_path = tmp_path / 'save.bin'
    save_path.write_bytes(b'\x00')
    out_path = tmp_path / 'save.new'
    sf = _save_file_mock(mocker)
    mocker.patch('destin.bit192.commands.save.SaveFile.load', return_value=sf)
    result = runner.invoke(unlock_all, [str(save_path), '-o', str(out_path)])
    assert result.exit_code == 0
    sf.save.assert_called_once_with(out_path)


def test_unlock_all_missing_path(runner: CliRunner, mocker: MockerFixture) -> None:
    load = mocker.patch('destin.bit192.commands.save.SaveFile.load')
    result = runner.invoke(unlock_all, ['does-not-exist.bin'])
    assert result.exit_code == 2
    load.assert_not_called()


def test_generate_success(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    out_path = tmp_path / 'gen.bin'
    sf = _save_file_mock(mocker, song_count=1023, packs=['vvv', 'empy'])
    blank = mocker.patch('destin.bit192.commands.save.SaveFile.blank', return_value=sf)
    result = runner.invoke(generate, [str(out_path), '--device-id', 'iOS'])
    assert result.exit_code == 0
    assert 'Generated' in result.output
    blank.assert_called_once_with()
    sf.set_device_id.assert_called_once_with('iOS')
    sf.unlock_all_songs.assert_called_once_with()
    sf.unlock_all_dlc.assert_called_once_with()
    sf.save.assert_called_once_with(out_path)


def test_generate_no_dlc(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    out_path = tmp_path / 'gen.bin'
    sf = _save_file_mock(mocker)
    mocker.patch('destin.bit192.commands.save.SaveFile.blank', return_value=sf)
    result = runner.invoke(generate, [str(out_path), '--no-dlc'])
    assert result.exit_code == 0
    assert 'DLC skipped' in result.output
    sf.unlock_all_songs.assert_called_once_with()
    sf.unlock_all_dlc.assert_not_called()
    sf.save.assert_called_once_with(out_path)


def test_generate_from_save_copies_device_id(runner: CliRunner, mocker: MockerFixture,
                                             tmp_path: Path) -> None:
    src = tmp_path / 'src.bin'
    src.write_bytes(b'\x00')
    out_path = tmp_path / 'gen.bin'
    existing = _save_file_mock(mocker, device_id='copied-id')
    generated = _save_file_mock(mocker)
    mocker.patch('destin.bit192.commands.save.SaveFile.load', return_value=existing)
    mocker.patch('destin.bit192.commands.save.SaveFile.blank', return_value=generated)
    result = runner.invoke(generate, [str(out_path), '--from-save', str(src)])
    assert result.exit_code == 0
    generated.set_device_id.assert_called_once_with('copied-id')


def test_generate_warns_without_device_id(runner: CliRunner, mocker: MockerFixture,
                                          tmp_path: Path) -> None:
    out_path = tmp_path / 'gen.bin'
    sf = _save_file_mock(mocker, device_id='')
    mocker.patch('destin.bit192.commands.save.SaveFile.blank', return_value=sf)
    result = runner.invoke(generate, [str(out_path)])
    assert result.exit_code == 0
    assert 'no device id was set' in result.output
