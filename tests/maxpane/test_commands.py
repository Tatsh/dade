from __future__ import annotations

from typing import TYPE_CHECKING
import json
import struct
import subprocess as sp

import pytest

from dade.common.tools import ToolNotFoundError
from dade.maxpane.commands.inspect_tags import inspect_tags
from dade.maxpane.commands.ldb2glb import ldb2glb
from dade.maxpane.commands.ldb_textures import ldb_textures
from dade.maxpane.commands.ras_extract import ras_extract
from dade.maxpane.commands.ras_list import ras_list
from dade.maxpane.commands.sources import NoArchivesFoundError, iter_archives
from dade.maxpane.main import cli
from dade.maxpane.memoryfile import BasicType

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from pathlib import Path

    from click.testing import CliRunner
    from pytest_mock import MockerFixture


class _StubImage:
    """Stands in for an ISO 9660 image so the source walk is tested without one."""
    def __init__(self, files: Mapping[str, bytes]) -> None:
        self._files = dict(files)

    def iter_files(self) -> Iterator[tuple[str, int]]:
        """
        Yield each file's path and size.

        Yields
        ------
        tuple[str, int]
            The path and size, sorted by path.
        """
        for path in sorted(self._files):
            yield path, len(self._files[path])

    def read_file(self, path: str) -> bytes:
        """
        Return a file's contents.

        Parameters
        ----------
        path : str
            The path to read.

        Returns
        -------
        bytes
            The contents.
        """
        return self._files[path]


def test_cli_lists_its_commands(runner: CliRunner) -> None:
    result = runner.invoke(cli, ('--help',))
    assert result.exit_code == 0
    assert 'ras-extract' in result.output
    assert 'ras-list' in result.output


def test_ras_list(runner: CliRunner, tmp_path: Path, make_ras: Callable[..., bytes]) -> None:
    archive = tmp_path / 'x_data.ras'
    archive.write_bytes(make_ras())
    result = runner.invoke(ras_list, (str(archive),))
    assert result.exit_code == 0
    assert 'v1.20, 2 members in 2 directories, intact' in result.output
    assert 'data/a.txt' in result.output


def test_ras_list_json(runner: CliRunner, tmp_path: Path, make_ras: Callable[..., bytes]) -> None:
    archive = tmp_path / 'x_data.ras'
    archive.write_bytes(make_ras())
    result = runner.invoke(ras_list, (str(archive), '--json'))
    assert result.exit_code == 0
    assert json.loads(result.output)['x_data.ras'][0]['path'] == 'data/a.txt'


def test_ras_list_reports_truncation(runner: CliRunner, tmp_path: Path,
                                     make_ras: Callable[..., bytes]) -> None:
    archive = tmp_path / 'x_data.ras'
    archive.write_bytes(make_ras()[:-1])
    assert 'TRUNCATED' in runner.invoke(ras_list, (str(archive),)).output


def test_ras_list_rejects_a_foreign_file(runner: CliRunner, tmp_path: Path) -> None:
    other = tmp_path / 'not.ras'
    other.write_bytes(b'\x00' * 4096)
    result = runner.invoke(ras_list, (str(other),))
    assert result.exit_code != 0


def test_ras_extract(runner: CliRunner, tmp_path: Path, make_ras: Callable[..., bytes]) -> None:
    archive = tmp_path / 'x_data.ras'
    archive.write_bytes(make_ras())
    out = tmp_path / 'out'
    result = runner.invoke(ras_extract, (str(archive), '-o', str(out)))
    assert result.exit_code == 0
    assert (out / 'data' / 'a.txt').read_bytes() == b'hello'
    assert (out / 'data' / 'b.bin').read_bytes() == b'world'


def test_ras_extract_filters_by_pattern(runner: CliRunner, tmp_path: Path,
                                        make_ras: Callable[..., bytes]) -> None:
    archive = tmp_path / 'x_data.ras'
    archive.write_bytes(make_ras())
    out = tmp_path / 'out'
    result = runner.invoke(ras_extract, (str(archive), '*.txt', '-o', str(out)))
    assert result.exit_code == 0
    assert (out / 'data' / 'a.txt').is_file()
    assert not (out / 'data' / 'b.bin').exists()


def test_ras_extract_rejects_a_foreign_file(runner: CliRunner, tmp_path: Path) -> None:
    other = tmp_path / 'not.ras'
    other.write_bytes(b'\x00' * 4096)
    assert runner.invoke(ras_extract, (str(other), '-o', str(tmp_path / 'out'))).exit_code != 0


def test_inspect_tags(runner: CliRunner, tmp_path: Path) -> None:
    asset = tmp_path / 'level.ldb'
    asset.write_bytes(
        bytes((BasicType.ARRAY,)) + bytes((BasicType.INT16,)) + b'\x01\x00' +
        bytes((BasicType.VECTOR3,)) + struct.pack('<3f', 1.0, 2.0, 3.0))
    result = runner.invoke(inspect_tags, (str(asset),))
    assert result.exit_code == 0
    assert 'ARRAY' in result.output
    assert 'VECTOR3' in result.output
    assert 'walked to 17 (100.00%)' in result.output


def test_inspect_tags_reports_where_it_stopped(runner: CliRunner, tmp_path: Path) -> None:
    asset = tmp_path / 'level.ldb'
    asset.write_bytes(bytes((BasicType.INT8,)) + b'\x01' + bytes((BasicType.STRING,)) + b'name')
    result = runner.invoke(inspect_tags, (str(asset),))
    assert result.exit_code == 0
    assert 'Stopped on 0x0d at offset 2.' in result.output


def test_inspect_tags_unwraps_first(runner: CliRunner, tmp_path: Path,
                                    make_lzss: Callable[[bytes], bytes]) -> None:
    payload = bytes((BasicType.INT8,)) + b'\x07'
    stream = make_lzss(payload)
    asset = tmp_path / 'level.ldb'
    asset.write_bytes(b'RA->' + struct.pack('<II', len(payload), len(stream)) + stream)
    result = runner.invoke(inspect_tags, (str(asset),))
    assert result.exit_code == 0
    assert 'Unwrapped: lzss.' in result.output


def test_inspect_tags_limit(runner: CliRunner, tmp_path: Path) -> None:
    asset = tmp_path / 'level.ldb'
    asset.write_bytes((bytes((BasicType.INT8,)) + b'\x01') * 5)
    result = runner.invoke(inspect_tags, (str(asset), '-n', '2'))
    assert result.exit_code == 0
    assert result.output.count('INT8') == 3  # Two listed values plus the histogram line.


def test_iter_archives_scans_a_directory_recursively(tmp_path: Path,
                                                     make_ras: Callable[..., bytes]) -> None:
    (tmp_path / 'levels').mkdir()
    (tmp_path / 'levels' / 'x_level1.ras').write_bytes(make_ras())
    (tmp_path / 'mod.MPM').write_bytes(make_ras())
    (tmp_path / 'readme.txt').write_bytes(b'ignored')
    assert sorted(
        label for label, _ in iter_archives(tmp_path)) == ['levels/x_level1.ras', 'mod.MPM']


def test_iter_archives_raises_when_nothing_is_found(tmp_path: Path) -> None:
    (tmp_path / 'readme.txt').write_bytes(b'nothing here')
    with pytest.raises(NoArchivesFoundError, match='No RAS archives found'):
        list(iter_archives(tmp_path))


def test_iter_archives_reads_loose_archives_from_an_image(tmp_path: Path, mocker: MockerFixture,
                                                          make_ras: Callable[..., bytes]) -> None:
    archive = make_ras()
    mocker.patch('dade.maxpane.commands.sources.open_image',
                 return_value=_StubImage({
                     'DISK1/LEVELS/X_LEVEL1.RAS': archive,
                     'DISK1/SETUP.EXE': b'stub'
                 }))
    image = tmp_path / 'disc.iso'
    image.write_bytes(b'not a ras')
    assert [label for label, _ in iter_archives(image)] == ['DISK1/LEVELS/X_LEVEL1.RAS']


def test_iter_archives_unshields_a_cabinet_on_an_image(tmp_path: Path, mocker: MockerFixture,
                                                       make_ras: Callable[..., bytes]) -> None:
    staged: dict[str, list[str]] = {}

    def fake_unshield(cabinet: Path, output_dir: Path) -> None:
        staged['siblings'] = sorted(path.name for path in cabinet.parent.iterdir())
        (output_dir / 'x_data.ras').write_bytes(make_ras())

    mocker.patch('dade.maxpane.commands.sources.run_unshield', side_effect=fake_unshield)
    mocker.patch('dade.maxpane.commands.sources.open_image',
                 return_value=_StubImage({
                     'DISK1/DATA1.CAB': b'ISc(',
                     'DISK1/DATA1.HDR': b'hdr',
                     'DISK1/DATA2.CAB': b'vol',
                     'DISK1/LEVELS/X_LEVEL1.RAS': make_ras(),
                     'DISK1/SETUP.EXE': b'stub'
                 }))
    image = tmp_path / 'disc.iso'
    image.write_bytes(b'not a ras')
    labels = [label for label, _ in iter_archives(image)]
    assert labels == ['DISK1/LEVELS/X_LEVEL1.RAS', 'x_data.ras']
    assert staged['siblings'] == ['DATA1.CAB', 'DATA1.HDR', 'DATA2.CAB']


def test_iter_archives_skips_a_cabinet_without_unshield(tmp_path: Path,
                                                        mocker: MockerFixture) -> None:
    mocker.patch('dade.maxpane.commands.sources.run_unshield',
                 side_effect=ToolNotFoundError('missing'))
    cabinet = tmp_path / 'data1.cab'
    cabinet.write_bytes(b'ISc(')
    with pytest.raises(NoArchivesFoundError):
        list(iter_archives(cabinet))


def test_iter_archives_skips_a_cabinet_unshield_cannot_read(tmp_path: Path,
                                                            mocker: MockerFixture) -> None:
    mocker.patch('dade.maxpane.commands.sources.run_unshield',
                 side_effect=sp.CalledProcessError(1, 'unshield'))
    cabinet = tmp_path / 'data1.cab'
    cabinet.write_bytes(b'ISc(')
    with pytest.raises(NoArchivesFoundError):
        list(iter_archives(cabinet))


def test_iter_archives_reads_a_cabinet(tmp_path: Path, mocker: MockerFixture,
                                       make_ras: Callable[..., bytes]) -> None:
    def fake_unshield(cabinet: Path, output_dir: Path) -> None:
        (output_dir / 'x_data.ras').write_bytes(make_ras())

    mocker.patch('dade.maxpane.commands.sources.run_unshield', side_effect=fake_unshield)
    cabinet = tmp_path / 'data1.cab'
    cabinet.write_bytes(b'ISc(')
    assert [label for label, _ in iter_archives(cabinet)] == ['x_data.ras']


def test_ldb2glb(runner: CliRunner, tmp_path: Path, make_ldb: Callable[..., bytes]) -> None:
    level = tmp_path / 'Part1_Level6.ldb'
    level.write_bytes(make_ldb())
    out = tmp_path / 'out'
    result = runner.invoke(ldb2glb, (str(level), '-o', str(out)))
    assert result.exit_code == 0
    assert (out / 'Part1_Level6.glb').read_bytes()[:4] == b'glTF'
    assert ('1 meshes, 1 props, 42 faces, 1 images, 2 placements (0 modelled), 0 clips'
            in result.output)


def test_ldb2glb_draws_the_placements_from_a_database(runner: CliRunner, tmp_path: Path,
                                                      make_ldb: Callable[..., bytes],
                                                      make_model: Callable[..., bytes]) -> None:
    level = tmp_path / 'Part1_Level6.ldb'
    level.write_bytes(make_ldb())
    database = tmp_path / 'database'
    skin = database / 'skins' / 'transit_cop'
    skin.mkdir(parents=True)
    (skin / 'transit_cop_l0.kfs').write_bytes(make_model())
    result = runner.invoke(ldb2glb, (str(level), '-o', str(tmp_path / 'out'), '-D', str(database)))
    assert result.exit_code == 0
    assert '2 placements (1 modelled)' in result.output


def test_ldb2glb_accepts_a_compressed_level(runner: CliRunner, tmp_path: Path,
                                            make_ldb: Callable[..., bytes],
                                            make_lzss: Callable[[bytes], bytes]) -> None:
    payload = make_ldb()
    stream = make_lzss(payload)
    level = tmp_path / 'wrapped.ldb'
    level.write_bytes(b'RA->' + struct.pack('<II', len(payload), len(stream)) + stream)
    assert runner.invoke(ldb2glb, (str(level), '-o', str(tmp_path / 'o'))).exit_code == 0


def test_ldb2glb_searches_a_directory(runner: CliRunner, tmp_path: Path,
                                      make_ldb: Callable[..., bytes]) -> None:
    (tmp_path / 'levels').mkdir()
    (tmp_path / 'levels' / 'a.ldb').write_bytes(make_ldb())
    result = runner.invoke(ldb2glb, (str(tmp_path), '-o', str(tmp_path / 'out')))
    assert result.exit_code == 0
    assert '1/1 levels converted' in result.output


def test_ldb2glb_without_any_levels(runner: CliRunner, tmp_path: Path) -> None:
    (tmp_path / 'empty').mkdir()
    result = runner.invoke(ldb2glb, (str(tmp_path / 'empty'),))
    assert result.exit_code != 0
    assert 'No .ldb files found.' in result.output


def test_ldb2glb_aborts_on_a_bad_level(runner: CliRunner, tmp_path: Path) -> None:
    level = tmp_path / 'bad.ldb'
    level.write_bytes(b'\x14\x02\x14\x02')
    assert runner.invoke(ldb2glb, (str(level), '-o', str(tmp_path / 'o'))).exit_code != 0


def test_ldb2glb_can_skip_a_bad_level(runner: CliRunner, tmp_path: Path,
                                      make_ldb: Callable[..., bytes]) -> None:
    (tmp_path / 'good.ldb').write_bytes(make_ldb())
    (tmp_path / 'bad.ldb').write_bytes(b'\x14\x02\x14\x02')
    result = runner.invoke(ldb2glb,
                           (str(tmp_path), '-o', str(tmp_path / 'out'), '--ignore-failures'))
    assert result.exit_code == 0
    assert '1/2 levels converted' in result.output


def test_ldb_textures(runner: CliRunner, tmp_path: Path, make_ldb: Callable[..., bytes]) -> None:
    level = tmp_path / 'a.ldb'
    level.write_bytes(make_ldb(textures=(('X:\\PROJECTS\\T\\WALL.TGA', 0, b'\x00\x01'),)))
    out = tmp_path / 'tex'
    result = runner.invoke(ldb_textures, (str(level), '-o', str(out)))
    assert result.exit_code == 0
    assert (out / 'PROJECTS' / 'T' / 'WALL.TGA').read_bytes() == b'\x00\x01'
    assert '1 images written' in result.output


def test_ldb_textures_flat(runner: CliRunner, tmp_path: Path, make_ldb: Callable[...,
                                                                                 bytes]) -> None:
    level = tmp_path / 'a.ldb'
    level.write_bytes(make_ldb(textures=(('X:\\PROJECTS\\T\\WALL.TGA', 0, b'\x00\x01'),)))
    out = tmp_path / 'tex'
    assert runner.invoke(ldb_textures, (str(level), '-o', str(out), '--flat')).exit_code == 0
    assert (out / 'WALL.TGA').is_file()


def test_ldb_textures_bare_name(runner: CliRunner, tmp_path: Path,
                                make_ldb: Callable[..., bytes]) -> None:
    level = tmp_path / 'a.ldb'
    level.write_bytes(make_ldb(textures=(('C:\\', 0, b'\x00'),)))
    out = tmp_path / 'tex'
    assert runner.invoke(ldb_textures, (str(level), '-o', str(out))).exit_code == 0
    assert (out / 'texture').is_file()


def test_ldb_textures_without_any_levels(runner: CliRunner, tmp_path: Path) -> None:
    (tmp_path / 'empty').mkdir()
    result = runner.invoke(ldb_textures, (str(tmp_path / 'empty'),))
    assert result.exit_code != 0
    assert 'No .ldb files found.' in result.output


def test_ldb_textures_aborts_on_a_bad_level(runner: CliRunner, tmp_path: Path) -> None:
    level = tmp_path / 'bad.ldb'
    level.write_bytes(b'\x14\x02\x14\x02')
    assert runner.invoke(ldb_textures, (str(level), '-o', str(tmp_path / 'o'))).exit_code != 0
