"""Tests for :mod:`destin.xg2.main`."""
from __future__ import annotations

from typing import TYPE_CHECKING

from destin.xg2.main import cli
from destin.xg2.offsets import GAME_CODE_OFFSET, XG1_GAME_CODE, XG2_GAME_CODE
from destin.xg2.smf import GM_DRUM_MAP, split_tracks
from destin.xg2.typing import Texture
import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner
    from pytest_mock import MockerFixture

_COMMANDS = ('convert-midi', 'extract-xg1', 'extract-xg2', 'extract-xg2-pc', 'make-sf2',
             'montage-n64', 'montage-pc', 'unpack-xg1-rom', 'unpack-xg2-rom')


def _rom(code: bytes = XG2_GAME_CODE) -> bytes:
    rom = bytearray(b'\x00' * 0x1000)
    rom[GAME_CODE_OFFSET:GAME_CODE_OFFSET + 4] = code
    return bytes(rom)


@pytest.fixture(autouse=True)
def _quiet_logging(mocker: MockerFixture) -> None:
    mocker.patch('bascom.cli.setup_logging')


def test_group_lists_every_command(runner: CliRunner) -> None:
    result = runner.invoke(cli, ['-h'])
    assert result.exit_code == 0
    for name in _COMMANDS:
        assert name in result.output


@pytest.mark.parametrize('name', _COMMANDS)
def test_command_help(runner: CliRunner, name: str) -> None:
    result = runner.invoke(cli, [name, '-h'])
    assert result.exit_code == 0
    assert 'Usage:' in result.output


def test_extract_xg1(runner: CliRunner, tmp_path: Path, mocker: MockerFixture) -> None:
    rom = tmp_path / 'game.z64'
    rom.write_bytes(_rom(XG1_GAME_CODE))
    run = mocker.patch('destin.xg2.main.run_xg1',
                       return_value={
                           'boot': 1,
                           'mfs': 50,
                           'levels': 4,
                           'containers': 2,
                           'directory': 1,
                           'textures': 0,
                           'audio': 0
                       })
    result = runner.invoke(cli, ['extract-xg1', str(rom), str(tmp_path / 'out')])
    assert result.exit_code == 0
    assert 'mfs: 50' in result.output
    assert run.call_args.kwargs['convert'] is False


def test_extract_xg1_convert_flag(runner: CliRunner, tmp_path: Path, mocker: MockerFixture) -> None:
    rom = tmp_path / 'game.z64'
    rom.write_bytes(_rom(XG1_GAME_CODE))
    run = mocker.patch(
        'destin.xg2.main.run_xg1',
        return_value=dict.fromkeys(
            ('boot', 'mfs', 'levels', 'containers', 'directory', 'textures', 'audio'), 0))
    runner.invoke(cli, ['extract-xg1', str(rom), str(tmp_path / 'out'), '-c'])
    assert run.call_args.kwargs['convert'] is True


def test_extract_xg1_warns_on_the_wrong_game(runner: CliRunner, tmp_path: Path,
                                             mocker: MockerFixture,
                                             caplog: pytest.LogCaptureFixture) -> None:
    rom = tmp_path / 'game.z64'
    rom.write_bytes(_rom(b'ZZZZ'))
    mocker.patch('destin.xg2.main.run_xg1',
                 return_value=dict.fromkeys(
                     ('boot', 'mfs', 'levels', 'containers', 'directory', 'textures', 'audio'), 0))
    with caplog.at_level('WARNING'):
        runner.invoke(cli, ['extract-xg1', str(rom), str(tmp_path / 'out')])
    assert 'game code' in caplog.text


def test_extract_xg2(runner: CliRunner, tmp_path: Path, mocker: MockerFixture) -> None:
    rom = tmp_path / 'game.z64'
    rom.write_bytes(_rom())
    run = mocker.patch('destin.xg2.main.run_xg2',
                       return_value={
                           'levels': 8,
                           'sequences': 23,
                           'midis': 23,
                           'wavs': 5,
                           'soundfonts': 1,
                           'bmc': 100,
                           'shaw': 4,
                           'other': 106,
                           'textures': 0,
                           'rendered': 0
                       })
    result = runner.invoke(cli, ['extract-xg2', str(rom), str(tmp_path / 'out'), '-r', '32000'])
    assert result.exit_code == 0
    assert 'sequences: 23' in result.output
    assert run.call_args.kwargs['rate'] == 32000


def test_extract_xg2_rejects_a_bad_rate(runner: CliRunner, tmp_path: Path) -> None:
    rom = tmp_path / 'game.z64'
    rom.write_bytes(_rom())
    result = runner.invoke(cli, ['extract-xg2', str(rom), str(tmp_path / 'out'), '-r', '0'])
    assert result.exit_code != 0


def test_extract_xg2_pc(runner: CliRunner, tmp_path: Path, mocker: MockerFixture) -> None:
    data1 = tmp_path / 'data1'
    data1.mkdir()
    mocker.patch('destin.xg2.main.run_pc',
                 return_value={
                     'containers': 3,
                     'raw': 1,
                     'textures': 12,
                     'wavs': 7,
                     'bitmaps': 2
                 })
    result = runner.invoke(cli, ['extract-xg2-pc', str(data1), str(tmp_path / 'out')])
    assert result.exit_code == 0
    assert 'textures: 12' in result.output


def test_extract_xg2_pc_requires_a_directory(runner: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / 'file.bin'
    target.write_bytes(b'')
    result = runner.invoke(cli, ['extract-xg2-pc', str(target), str(tmp_path / 'out')])
    assert result.exit_code != 0


@pytest.mark.parametrize(('command', 'patched'), [('unpack-xg1-rom', 'destin.xg2.main.unpack_xg1'),
                                                  ('unpack-xg2-rom', 'destin.xg2.main.unpack_xg2')])
def test_unpack_commands(runner: CliRunner, tmp_path: Path, mocker: MockerFixture, command: str,
                         patched: str) -> None:
    rom = tmp_path / 'game.z64'
    rom.write_bytes(_rom())
    unpack = mocker.patch(patched, return_value={'files': 42, 'bytes': 1024})
    result = runner.invoke(cli, [command, str(rom), str(tmp_path / 'out'), '-p', 'pre'])
    assert result.exit_code == 0
    assert 'mfs files: 42' in result.output
    assert unpack.call_args.args[2] == 'pre'


def test_convert_midi_faithful(runner: CliRunner, tmp_path: Path, midi_file: bytes) -> None:
    source = tmp_path / 'in.mid'
    source.write_bytes(midi_file)
    out = tmp_path / 'out.mid'
    result = runner.invoke(cli, ['convert-midi', str(source), str(out)])
    assert result.exit_code == 0
    assert len(split_tracks(out.read_bytes())[1]) == 2


def test_convert_midi_generic_remaps_drums(runner: CliRunner, tmp_path: Path,
                                           midi_file: bytes) -> None:
    source = tmp_path / 'in.mid'
    source.write_bytes(midi_file)
    out = tmp_path / 'out.mid'
    runner.invoke(cli, ['convert-midi', str(source), str(out), '-m', 'generic'])
    assert bytes([0x99, GM_DRUM_MAP[36], 90]) in split_tracks(out.read_bytes())[1][1]


def test_convert_midi_rejects_an_unknown_mode(runner: CliRunner, tmp_path: Path,
                                              midi_file: bytes) -> None:
    source = tmp_path / 'in.mid'
    source.write_bytes(midi_file)
    result = runner.invoke(cli, ['convert-midi', str(source), str(tmp_path / 'o.mid'), '-m', 'zz'])
    assert result.exit_code != 0


def test_make_sf2(runner: CliRunner, tmp_path: Path, mocker: MockerFixture) -> None:
    rom = tmp_path / 'game.z64'
    rom.write_bytes(_rom())
    build = mocker.patch('destin.xg2.main.build_combined', return_value=b'RIFF')
    out = tmp_path / 'bank.sf2'
    result = runner.invoke(
        cli,
        ['make-sf2',
         str(rom),
         str(out), '--melodic-bank', '0x710710', '--drum-bank', '0x6B0800'])
    assert result.exit_code == 0
    assert out.read_bytes() == b'RIFF'
    assert build.call_args.args[1:3] == (0x710710, 0x6B0800)


def test_make_sf2_requires_the_melodic_bank(runner: CliRunner, tmp_path: Path) -> None:
    rom = tmp_path / 'game.z64'
    rom.write_bytes(_rom())
    result = runner.invoke(cli, ['make-sf2', str(rom), str(tmp_path / 'b.sf2')])
    assert result.exit_code != 0


def test_make_sf2_aborts_on_a_bad_offset(runner: CliRunner, tmp_path: Path) -> None:
    rom = tmp_path / 'game.z64'
    rom.write_bytes(_rom())
    result = runner.invoke(
        cli, ['make-sf2',
              str(rom), str(tmp_path / 'b.sf2'), '--melodic-bank', 'nonsense'])
    assert result.exit_code != 0


def test_make_sf2_aborts_when_the_bank_will_not_parse(runner: CliRunner, tmp_path: Path,
                                                      mocker: MockerFixture) -> None:
    rom = tmp_path / 'game.z64'
    rom.write_bytes(_rom())
    mocker.patch('destin.xg2.main.build_combined', side_effect=ValueError('no bank'))
    result = runner.invoke(
        cli,
        ['make-sf2', str(rom), str(tmp_path / 'b.sf2'), '--melodic-bank', '0'])
    assert result.exit_code != 0


def test_montage_n64(runner: CliRunner, tmp_path: Path, mocker: MockerFixture) -> None:
    rom = tmp_path / 'game.z64'
    rom.write_bytes(_rom())
    mocker.patch('destin.xg2.main.iter_n64_model_blobs', return_value=[('mfs/file000', b'\x00')])
    mocker.patch('destin.xg2.main.collect_textures', return_value=[])
    out = tmp_path / 'sheet.png'
    result = runner.invoke(cli, ['montage-n64', str(rom), str(out)])
    assert result.exit_code == 0
    assert out.is_file()
    assert '0 textures' in result.output


def test_montage_pc_writes_an_index(runner: CliRunner, tmp_path: Path,
                                    mocker: MockerFixture) -> None:
    data1 = tmp_path / 'data1'
    data1.mkdir()
    mocker.patch('destin.xg2.main.iter_pc_model_blobs', return_value=[])
    index = tmp_path / 'index.txt'
    result = runner.invoke(
        cli, ['montage-pc', str(data1),
              str(tmp_path / 'sheet.png'), '-i',
              str(index)])
    assert result.exit_code == 0
    assert not index.read_text()


def test_montage_rejects_a_bad_cell(runner: CliRunner, tmp_path: Path) -> None:
    rom = tmp_path / 'game.z64'
    rom.write_bytes(_rom())
    result = runner.invoke(cli, ['montage-n64', str(rom), str(tmp_path / 's.png'), '--cell', '0'])
    assert result.exit_code != 0


def test_commands_reject_a_missing_rom(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(cli, ['extract-xg2', str(tmp_path / 'nope.z64'), str(tmp_path / 'out')])
    assert result.exit_code != 0


def test_group_is_named_cli() -> None:
    assert cli.name == 'cli'


def test_montage_n64_labels_each_texture(runner: CliRunner, tmp_path: Path,
                                         mocker: MockerFixture) -> None:
    rom = tmp_path / 'game.z64'
    rom.write_bytes(_rom())
    mocker.patch('destin.xg2.main.iter_n64_model_blobs', return_value=[('mfs/file000', b'\x00')])
    mocker.patch('destin.xg2.main.collect_textures',
                 return_value=[Texture('ci8', 0x40, 8, 8, b'\xff' * (8 * 8 * 4))])
    index = tmp_path / 'index.txt'
    result = runner.invoke(
        cli, ['montage-n64', str(rom),
              str(tmp_path / 'sheet.png'), '-i',
              str(index)])
    assert result.exit_code == 0
    assert '1 textures' in result.output
    assert 'mfs/file000#0000040' in index.read_text()


def test_montage_pc_labels_each_texture(runner: CliRunner, tmp_path: Path,
                                        mocker: MockerFixture) -> None:
    data1 = tmp_path / 'data1'
    data1.mkdir()
    mocker.patch('destin.xg2.main.iter_pc_model_blobs', return_value=[('bike.cmp', b'\x00')])
    mocker.patch('destin.xg2.main.collect_textures',
                 return_value=[Texture('ci8', 0x80, 8, 8, b'\xff' * (8 * 8 * 4))])
    result = runner.invoke(cli, ['montage-pc', str(data1), str(tmp_path / 'sheet.png')])
    assert result.exit_code == 0
    assert '1 textures' in result.output
