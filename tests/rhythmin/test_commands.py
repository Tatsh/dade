"""Tests for the ``destin rhythmin`` commands."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json

import pytest

from destin.rhythmin.commands.dump_chara import dump_chara
from destin.rhythmin.commands.dump_idx import dump_idx
from destin.rhythmin.commands.dump_map import dump_map
from destin.rhythmin.commands.dump_sheet import dump_sheet
from destin.rhythmin.commands.extract_dialogue import extract_dialogue
from destin.rhythmin.main import main, rhythmin

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner
    from pytest_mock import MockerFixture


def test_group_lists_every_command(runner: CliRunner) -> None:
    result = runner.invoke(rhythmin, ('--help',))
    assert result.exit_code == 0
    for name in ('dump-chara', 'dump-idx', 'dump-map', 'dump-sheet', 'extract-dialogue'):
        assert name in result.output


def test_dump_chara(runner: CliRunner, chara_file: Path, chara_json: dict[str, object]) -> None:
    result = runner.invoke(dump_chara, (str(chara_file),))
    assert result.exit_code == 0
    assert json.loads(result.output) == chara_json


def test_dump_chara_raw(runner: CliRunner, chara_file: Path) -> None:
    result = runner.invoke(dump_chara, (str(chara_file), '--raw'))
    assert result.exit_code == 0
    assert result.stdout_bytes.startswith(b'{"Chara"')


def test_dump_chara_aborts_on_a_bad_payload(runner: CliRunner, tmp_path: Path) -> None:
    path = tmp_path / 'bad.chr'
    path.write_bytes(b'\0' * 16)
    result = runner.invoke(dump_chara, (str(path),))
    assert result.exit_code == 1
    assert 'Bad length trailer' in result.output


def test_dump_chara_aborts_when_the_plaintext_is_not_json(runner: CliRunner,
                                                          tmp_path: Path) -> None:
    from destin.rhythmin.bfcodec import encipher
    path = tmp_path / 'notjson.chr'
    path.write_bytes(encipher(b'not json at all'))
    result = runner.invoke(dump_chara, (str(path),))
    assert result.exit_code == 1
    assert 'Pass --raw' in result.output


def test_dump_idx(runner: CliRunner, aep_index_file: Path) -> None:
    result = runner.invoke(dump_idx, (str(aep_index_file),))
    assert result.exit_code == 0
    rendered = json.loads(result.output)
    assert rendered['groupId'] == 7
    assert len(rendered['frameEntries']) == 4


def test_dump_idx_names(runner: CliRunner, aep_index_file: Path) -> None:
    result = runner.invoke(dump_idx, (str(aep_index_file), '--names'))
    assert result.exit_code == 0
    assert 'frameEntries' not in json.loads(result.output)


def test_dump_idx_layer(runner: CliRunner, aep_index_file: Path) -> None:
    result = runner.invoke(dump_idx, (str(aep_index_file), '--layer', 'STAR'))
    assert result.exit_code == 0
    rendered = json.loads(result.output)
    assert rendered['ordinal'] == 1
    assert rendered['entryIndex'] == 2
    assert [entry['type'] for entry in rendered['entries']] == [3, -1]


def test_dump_idx_layer_aborts_on_an_unknown_layer(runner: CliRunner, aep_index_file: Path) -> None:
    result = runner.invoke(dump_idx, (str(aep_index_file), '--layer', 'NOPE'))
    assert result.exit_code == 1
    assert 'is not a layer name' in result.output


def test_dump_idx_find(runner: CliRunner, aep_index_file: Path) -> None:
    result = runner.invoke(dump_idx, (str(aep_index_file), '--find', 'JACKET00'))
    assert result.exit_code == 0
    rendered = json.loads(result.output)
    assert rendered['locations'][0]['block'] == 'user'
    assert len(rendered['groupEntries']) == 1


def test_dump_idx_aborts_on_a_short_file(runner: CliRunner, tmp_path: Path) -> None:
    path = tmp_path / 'short.idx'
    path.write_bytes(b'\0' * 8)
    result = runner.invoke(dump_idx, (str(path),))
    assert result.exit_code == 1


def test_dump_map(runner: CliRunner, treasure_map_file: Path) -> None:
    result = runner.invoke(dump_map, (str(treasure_map_file),))
    assert result.exit_code == 0
    rendered = json.loads(result.output)
    assert rendered['square_count'] == 4
    assert rendered['main_title'] == '探検航海'


def test_dump_map_ascii(runner: CliRunner, treasure_map_file: Path) -> None:
    result = runner.invoke(dump_map, (str(treasure_map_file), '--ascii'))
    assert result.exit_code == 0
    assert 'S---T---W' in result.output


def test_dump_map_image(runner: CliRunner, treasure_map_file: Path, tmp_path: Path) -> None:
    out = tmp_path / 'board.png'
    result = runner.invoke(dump_map, (str(treasure_map_file), '--image', str(out)))
    assert result.exit_code == 0
    assert out.is_file()


def test_dump_map_aborts_on_a_short_file(runner: CliRunner, tmp_path: Path) -> None:
    path = tmp_path / 'short.map'
    path.write_bytes(b'\0' * 16)
    result = runner.invoke(dump_map, (str(path),))
    assert result.exit_code == 1
    assert 'Too short for a map file' in result.output


def test_dump_sheet_standard(runner: CliRunner, orb_package: Path) -> None:
    result = runner.invoke(dump_sheet, (str(orb_package), 'n'))
    assert result.exit_code == 0
    rendered = json.loads(result.output)
    assert rendered['format'] == 'standard'
    assert rendered['title'] == 'テスト'
    assert rendered['artist'] == 'ピノキオP'  # noqa: RUF001
    assert rendered['level'] == 3


def test_dump_sheet_arcade(runner: CliRunner, acv_package: Path) -> None:
    result = runner.invoke(dump_sheet, (str(acv_package), 'ex'))
    assert result.exit_code == 0
    rendered = json.loads(result.output)
    assert rendered['format'] == 'arcade'
    assert rendered['artist'] == 'ビタミンポップ'
    assert rendered['level'] == 38


def test_dump_sheet_summary(runner: CliRunner, acv_package: Path) -> None:
    result = runner.invoke(dump_sheet, (str(acv_package), 'ex', '--summary'))
    assert result.exit_code == 0
    assert 'units' not in json.loads(result.output)


def test_dump_sheet_raw(runner: CliRunner, acv_package: Path, arcade_chart_bytes: bytes) -> None:
    result = runner.invoke(dump_sheet, (str(acv_package), 'ex', '--raw'))
    assert result.exit_code == 0
    assert result.stdout_bytes == arcade_chart_bytes


@pytest.mark.parametrize('direction', ['auto', 'bottom-up', 'top-down'])
def test_dump_sheet_image(runner: CliRunner, acv_package: Path, tmp_path: Path,
                          direction: str) -> None:
    out = tmp_path / f'chart-{direction}.png'
    result = runner.invoke(dump_sheet,
                           (str(acv_package), 'ex', '--image', str(out), '--direction', direction))
    assert result.exit_code == 0
    assert out.is_file()


def test_dump_sheet_aborts_on_an_absent_difficulty(runner: CliRunner, orb_package: Path) -> None:
    result = runner.invoke(dump_sheet, (str(orb_package), 'h'))
    assert result.exit_code == 1
    assert 'sheet_h' in result.output


def test_dump_sheet_rejects_an_unknown_suffix(runner: CliRunner, orb_package: Path) -> None:
    assert runner.invoke(dump_sheet, (str(orb_package), 'zz')).exit_code == 2


def test_extract_dialogue_empty(runner: CliRunner, tmp_path: Path) -> None:
    out = tmp_path / 'empty.inc'
    result = runner.invoke(extract_dialogue, (str(out),))
    assert result.exit_code == 0
    assert 'static const char *const kCharGroup6Slot0[41] = {0};' in out.read_text()


def test_extract_dialogue_from_a_binary(runner: CliRunner, macho_image_all_pools: bytes,
                                        tmp_path: Path) -> None:
    binary = tmp_path / 'PopnRhythmin'
    binary.write_bytes(macho_image_all_pools)
    out = tmp_path / 'pools.inc'
    result = runner.invoke(extract_dialogue, (str(out), '--binary', str(binary)))
    assert result.exit_code == 0
    header = out.read_text()
    assert 'static const char *const kCharGroup6Slot0[41] = {' in header
    assert '"message 0",' in header
    assert '"message 329",' in header


def test_extract_dialogue_binary_format(runner: CliRunner, tmp_path: Path) -> None:
    out = tmp_path / 'pools.bin'
    result = runner.invoke(extract_dialogue, (str(out), '--format', 'binary'))
    assert result.exit_code == 0
    # Six empty pools, each just its int32 entry count.
    assert out.stat().st_size == 4 * 6


def test_extract_dialogue_aborts_on_a_64_bit_binary(runner: CliRunner, tmp_path: Path) -> None:
    binary = tmp_path / 'PopnRhythmin'
    binary.write_bytes(b'\xcf\xfa\xed\xfe' + b'\0' * 64)
    result = runner.invoke(extract_dialogue, (str(tmp_path / 'out.inc'), '-b', str(binary)))
    assert result.exit_code == 1
    assert 'Not a 32-bit Mach-O image' in result.output


def test_the_group_entry_point(mocker: MockerFixture) -> None:
    group = mocker.patch('destin.rhythmin.main.rhythmin')
    main()
    group.assert_called_once_with()
