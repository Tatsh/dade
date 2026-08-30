from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from click.testing import CliRunner
import pytest

from dade.common.exceptions import InvalidFormatError
from dade.sopranos.main import (
    _prop_libraries,  # noqa: PLC2701
    archive_directory,
    iter_sources,
    sopranos,
)
from dade.sopranos.olv import Placement

from .conftest import (
    FORMAT_RGBA,
    build_archive,
    build_bank,
    build_geometry,
    build_image,
    build_level,
    build_library,
    build_section,
    mesh_packet,
    prop_packet,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture

_TRIANGLE = [(0.0, 0.0, 0.0, 0.25, 0.5), (1.0, 0.0, 0.0, 0.75, 0.5), (0.0, 1.0, 0.0, 0.25, 0.9)]
_PROP_TRIANGLE = [(0.0, 0.0, 0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 1.0, 0.0), (0.0, 1.0, 0.0, 0.0, 1.0)]
_FRAME = bytes([0x00, 0x00, *([0x11] * 14)])


@pytest.fixture
def runner() -> CliRunner:
    """
    Give a Click runner.

    Returns
    -------
    CliRunner
        The runner.
    """
    return CliRunner()


def geometry() -> bytes:
    """
    Give an ``.EGP2`` blob holding one textured triangle.

    Returns
    -------
    bytes
        The blob.
    """
    image = build_image('art/wall.tga', 2, 2, FORMAT_RGBA, bytes([200, 40, 40, 0x80]) * 4)
    return build_geometry([('art/wall.tga', 0)], [(1, [mesh_packet(_TRIANGLE)])], {0: 0}, [image])


def library() -> bytes:
    """
    Give an ``.SGP2`` library holding one object.

    Returns
    -------
    bytes
        The library.
    """
    return build_library(
        [build_section('lib/guy', [('a.tga',)], [('GUY', [(0, [prop_packet(_PROP_TRIANGLE)])])])])


def bank() -> bytes:
    """
    Give a ``.TEX2`` bank holding one image.

    Returns
    -------
    bytes
        The bank.
    """
    return build_bank([build_image('art/a.tga', 2, 2, FORMAT_RGBA, bytes([1, 2, 3, 255]) * 4)])


def bank_header(entries: list[tuple[int, int, int, int]]) -> bytes:
    """
    Give a ``.MSH`` header.

    Parameters
    ----------
    entries : list[tuple[int, int, int, int]]
        Each as ``(size, identifier, offset, rate)``.

    Returns
    -------
    bytes
        The header.
    """
    return bytes(8) + struct.pack('<I', len(entries)) + b''.join(
        struct.pack('<4I', *entry) for entry in entries)


def voice() -> bytes:
    """
    Give a ``.VO2`` file holding one block of dialogue.

    Returns
    -------
    bytes
        The file.
    """
    return b'AUDO' + bytes(4) + struct.pack('<I', 64 + len(_FRAME)) + bytes(4) + bytes(48) + _FRAME


@pytest.mark.parametrize(('name', 'expected'), [('DATA_P.FS', 'data'), ('MOVIES.FS', 'movies')])
def test_archive_directory_drops_the_region_suffix(*, expected: str, name: str) -> None:
    assert archive_directory(name) == expected


def test_iter_sources_searches_a_directory_however_it_is_cased(tmp_path: Path) -> None:
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'DATA_P.FS').write_bytes(b'a')
    (tmp_path / 'other.fs').write_bytes(b'b')
    (tmp_path / 'notes.txt').write_bytes(b'c')
    # Sorted by whole path, so a file at the top comes before one in a subdirectory.
    assert [name for _, name, _, _ in iter_sources([tmp_path])] == ['other.fs', 'DATA_P.FS']


def test_iter_sources_reads_archives_in_place_on_a_disc(tmp_path: Path,
                                                        mocker: MockerFixture) -> None:
    image = tmp_path / 'game.iso'
    image.write_bytes(b'x')
    mocker.patch('dade.sopranos.main.is_disc_image', return_value=True)
    mocker.patch('dade.sopranos.main.iter_disc_archives', return_value=[('DATA_P.FS', 2048, 512)])
    assert list(iter_sources([image])) == [(image, 'DATA_P.FS', 2048, 512)]


def test_iter_sources_takes_a_named_archive_as_it_is(tmp_path: Path, mocker: MockerFixture) -> None:
    archive = tmp_path / 'DATA_P.FS'
    archive.write_bytes(b'x')
    mocker.patch('dade.sopranos.main.is_disc_image', return_value=False)
    assert list(iter_sources([archive])) == [(archive, 'DATA_P.FS', 0, None)]


def test_list_prints_every_entry(runner: CliRunner, tmp_path: Path) -> None:
    archive = tmp_path / 'a.fs'
    archive.write_bytes(build_archive({'one.tex2': b'abc'}))
    result = runner.invoke(sopranos, ['list', str(archive)])
    assert result.exit_code == 0
    assert 'one.tex2' in result.output
    assert '1 file(s).' in result.output


def test_list_reports_an_archive_it_cannot_read(runner: CliRunner, tmp_path: Path) -> None:
    archive = tmp_path / 'a.fs'
    archive.write_bytes(b'nope')
    result = runner.invoke(sopranos, ['list', str(archive)])
    assert result.exit_code != 0
    assert 'Error' in result.output


def test_unpack_gives_each_archive_its_own_directory(runner: CliRunner, tmp_path: Path) -> None:
    archive = tmp_path / 'DATA_P.FS'
    archive.write_bytes(build_archive({'sub/one.tex2': b'abc'}))
    result = runner.invoke(sopranos, ['unpack', str(archive), '-o', str(tmp_path / 'out')])
    assert result.exit_code == 0
    assert (tmp_path / 'out' / 'data' / 'sub' / 'one.tex2').read_bytes() == b'abc'


def test_unpack_takes_several_archives_at_once(runner: CliRunner, tmp_path: Path) -> None:
    for name in ('A_P.FS', 'B_P.FS'):
        (tmp_path / name).write_bytes(build_archive({'one.bin': b'abc'}))
    result = runner.invoke(
        sopranos,
        ['unpack',
         str(tmp_path / 'A_P.FS'),
         str(tmp_path / 'B_P.FS'), '-o',
         str(tmp_path / 'out')])
    assert result.exit_code == 0
    assert 'Extracted 2 file(s)' in result.output


def test_unpack_complains_when_a_directory_holds_no_archives(runner: CliRunner,
                                                             tmp_path: Path) -> None:
    (tmp_path / 'empty').mkdir()
    result = runner.invoke(sopranos, ['unpack', str(tmp_path / 'empty')])
    assert result.exit_code != 0
    assert 'no .FS archives were found' in result.output


def test_unpack_reports_an_archive_it_cannot_read(runner: CliRunner, tmp_path: Path) -> None:
    archive = tmp_path / 'a.fs'
    archive.write_bytes(b'nope')
    result = runner.invoke(sopranos, ['unpack', str(archive), '-o', str(tmp_path / 'out')])
    assert result.exit_code != 0
    assert 'Error' in result.output


def test_unpack_converts_what_it_extracted(runner: CliRunner, tmp_path: Path) -> None:
    archive = tmp_path / 'DATA_P.FS'
    archive.write_bytes(
        build_archive({
            'cooked/p_bar/w_bar.egp2': geometry(),
            'cooked/p_bar/cast.sgp2': library(),
            'sound/hit.tex2': bank(),
            'sound/line.vo2': voice(),
        }))
    result = runner.invoke(
        sopranos, ['unpack', str(archive), '-o',
                   str(tmp_path / 'out'), '--convert'])
    assert result.exit_code == 0, result.output
    out = tmp_path / 'out' / 'data'
    assert (out / 'cooked' / 'p_bar' / 'w_bar.glb').is_file()
    assert (out / 'cooked' / 'p_bar' / 'w_bar.obj').is_file()
    assert (out / 'sound' / 'line.wav').is_file()
    assert 'Converted' in result.output


def test_unpack_expands_a_level_before_converting_what_is_inside(runner: CliRunner,
                                                                 tmp_path: Path) -> None:
    archive = tmp_path / 'DATA_P.FS'
    archive.write_bytes(build_archive({'stage.lvl': build_level({'art.tex2': bank()})}))
    result = runner.invoke(
        sopranos, ['unpack', str(archive), '-o',
                   str(tmp_path / 'out'), '--convert'])
    assert result.exit_code == 0, result.output
    assert (tmp_path / 'out' / 'data' / 'stage' / 'a.png').is_file()


def test_unpack_converts_a_sound_bank_and_a_music_stream(runner: CliRunner, tmp_path: Path) -> None:
    archive = tmp_path / 'DATA_P.FS'
    archive.write_bytes(
        build_archive({
            'sfx.msh': bank_header([(len(_FRAME), 1, 0, 22050)]),
            'sfx.msb': _FRAME,
            'song.mih': bytes(8) + struct.pack('<4I', 1, 44100, 16, 1),
            'song.mib': _FRAME,
            'lonely.msh': bank_header([]),
        }))
    result = runner.invoke(
        sopranos, ['unpack', str(archive), '-o',
                   str(tmp_path / 'out'), '--convert'])
    assert result.exit_code == 0, result.output
    out = tmp_path / 'out' / 'data'
    assert (out / 'sfx_000.wav').is_file()
    assert (out / 'song.wav').is_file()


def test_unpack_stops_on_a_conversion_failure(runner: CliRunner, tmp_path: Path) -> None:
    archive = tmp_path / 'DATA_P.FS'
    archive.write_bytes(build_archive({'broken.tex2': b'nope'}))
    result = runner.invoke(
        sopranos, ['unpack', str(archive), '-o',
                   str(tmp_path / 'out'), '--convert'])
    assert result.exit_code != 0
    assert isinstance(result.exception, (InvalidFormatError, struct.error, ValueError))


def test_unpack_can_skip_a_conversion_failure(runner: CliRunner, tmp_path: Path) -> None:
    archive = tmp_path / 'DATA_P.FS'
    archive.write_bytes(build_archive({'broken.tex2': b'nope'}))
    result = runner.invoke(
        sopranos,
        ['unpack',
         str(archive), '-o',
         str(tmp_path / 'out'), '--convert', '--ignore-failures'])
    assert result.exit_code == 0, result.output
    assert 'Skipping' in result.output


def test_unpack_stops_on_a_level_it_cannot_expand(runner: CliRunner, tmp_path: Path) -> None:
    archive = tmp_path / 'DATA_P.FS'
    archive.write_bytes(build_archive({'broken.lvl': b'nope'}))
    result = runner.invoke(
        sopranos, ['unpack', str(archive), '-o',
                   str(tmp_path / 'out'), '--convert'])
    assert result.exit_code != 0


def test_unpack_can_skip_a_level_it_cannot_expand(runner: CliRunner, tmp_path: Path) -> None:
    archive = tmp_path / 'DATA_P.FS'
    archive.write_bytes(build_archive({'broken.lvl': b'nope'}))
    result = runner.invoke(
        sopranos,
        ['unpack',
         str(archive), '-o',
         str(tmp_path / 'out'), '--convert', '--ignore-failures'])
    assert result.exit_code == 0, result.output
    assert 'Skipping' in result.output


def _place_level(root: Path, *, olv: bytes, shared: str = 'p_cbar', variant: str = 'p_bar') -> Path:
    cooked = root / 'cooked'
    (cooked / shared).mkdir(parents=True)
    (cooked / variant).mkdir(parents=True)
    (cooked / shared / 'objects.OLV').write_bytes(olv)
    (cooked / shared / 'shared.SGP2').write_bytes(library())
    (cooked / variant / 'cast.sgp2').write_bytes(library())
    path = cooked / variant / 'w_bar.egp2'
    path.write_bytes(geometry())
    return path


def test_prop_libraries_are_offered_to_the_level_that_owns_them(tmp_path: Path,
                                                                mocker: MockerFixture) -> None:
    placements = (Placement('iGuy', 'guy', 1.0, 2.0, 3.0, 0.0),)
    mocker.patch('dade.sopranos.main.read_placements', return_value=placements)
    path = _place_level(tmp_path, olv=b'olv')
    # A second variant of the same level, which also carries part of the cast.
    other = tmp_path / 'cooked' / 'p_bar_hub'
    other.mkdir()
    (other / 'more.SGP2').write_bytes(library())
    libraries, found = _prop_libraries(path)
    assert len(libraries) == 3
    assert found == placements


def test_prop_libraries_are_empty_when_no_shared_directory_matches(tmp_path: Path) -> None:
    path = _place_level(tmp_path, olv=b'olv', shared='p_cdiner')
    assert _prop_libraries(path) == ((), ())


def test_prop_libraries_are_empty_without_a_placement_file(tmp_path: Path) -> None:
    path = _place_level(tmp_path, olv=b'olv')
    (tmp_path / 'cooked' / 'p_cbar' / 'objects.OLV').unlink()
    assert _prop_libraries(path) == ((), ())


def test_prop_libraries_skip_a_directory_holding_no_library(tmp_path: Path,
                                                            mocker: MockerFixture) -> None:
    mocker.patch('dade.sopranos.main.read_placements', return_value=())
    path = _place_level(tmp_path, olv=b'olv')
    (tmp_path / 'cooked' / 'p_cbar' / 'shared.SGP2').unlink()
    libraries, _ = _prop_libraries(path)
    assert len(libraries) == 1


def test_prop_libraries_ignore_a_stray_file_named_like_a_level(tmp_path: Path,
                                                               mocker: MockerFixture) -> None:
    mocker.patch('dade.sopranos.main.read_placements', return_value=())
    path = _place_level(tmp_path, olv=b'olv')
    (tmp_path / 'cooked' / 'p_cbar_notes').write_bytes(b'x')
    assert len(_prop_libraries(path)[0]) == 2


def test_level_splits_a_container(runner: CliRunner, tmp_path: Path) -> None:
    source = tmp_path / 'stage.lvl'
    source.write_bytes(build_level({'art.tex2': b'abc'}))
    result = runner.invoke(sopranos, ['level', str(source), '-o', str(tmp_path / 'out')])
    assert result.exit_code == 0
    assert '1 sub-asset(s)' in result.output


def test_level_defaults_to_a_directory_beside_the_input(runner: CliRunner, tmp_path: Path) -> None:
    source = tmp_path / 'stage.lvl'
    source.write_bytes(build_level({'art.tex2': b'abc'}))
    assert runner.invoke(sopranos, ['level', str(source)]).exit_code == 0
    assert (tmp_path / 'stage' / 'art.tex2').is_file()


def test_level_reports_a_container_it_cannot_read(runner: CliRunner, tmp_path: Path) -> None:
    source = tmp_path / 'stage.lvl'
    source.write_bytes(b'nope')
    result = runner.invoke(sopranos, ['level', str(source)])
    assert result.exit_code != 0
    assert 'Error' in result.output


def test_texture_converts_a_bank(runner: CliRunner, tmp_path: Path) -> None:
    source = tmp_path / 'art.tex2'
    source.write_bytes(bank())
    result = runner.invoke(sopranos, ['texture', str(source), '-o', str(tmp_path / 'out')])
    assert result.exit_code == 0
    assert (tmp_path / 'out' / 'a.png').is_file()


def test_texture_defaults_to_beside_the_input(runner: CliRunner, tmp_path: Path) -> None:
    source = tmp_path / 'art.tex2'
    source.write_bytes(bank())
    assert runner.invoke(sopranos, ['texture', str(source)]).exit_code == 0
    assert (tmp_path / 'a.png').is_file()


def test_texture_reports_a_bank_it_cannot_read(runner: CliRunner, tmp_path: Path) -> None:
    source = tmp_path / 'art.tex2'
    source.write_bytes(b'nope')
    result = runner.invoke(sopranos, ['texture', str(source)])
    assert result.exit_code != 0
    assert 'Error' in result.output


def test_mesh_writes_an_obj(runner: CliRunner, tmp_path: Path) -> None:
    source = tmp_path / 'w.egp2'
    source.write_bytes(geometry())
    result = runner.invoke(sopranos, ['mesh', str(source), '-o', str(tmp_path / 'out')])
    assert result.exit_code == 0
    assert (tmp_path / 'out' / 'w.obj').is_file()


def test_mesh_defaults_to_beside_the_input(runner: CliRunner, tmp_path: Path) -> None:
    source = tmp_path / 'w.egp2'
    source.write_bytes(geometry())
    assert runner.invoke(sopranos, ['mesh', str(source)]).exit_code == 0
    assert (tmp_path / 'w.obj').is_file()


def test_gltf_writes_a_level(runner: CliRunner, tmp_path: Path) -> None:
    source = tmp_path / 'w.egp2'
    source.write_bytes(geometry())
    result = runner.invoke(sopranos, ['gltf', str(source), '-o', str(tmp_path / 'out')])
    assert result.exit_code == 0
    assert (tmp_path / 'out' / 'w.glb').is_file()


def test_gltf_writes_a_prop_library(runner: CliRunner, tmp_path: Path) -> None:
    source = tmp_path / 'cast.sgp2'
    source.write_bytes(library())
    assert runner.invoke(sopranos, ['gltf', str(source)]).exit_code == 0
    assert (tmp_path / 'cast_props.glb').is_file()


def test_audio_converts_a_sound_bank(runner: CliRunner, tmp_path: Path) -> None:
    (tmp_path / 'sfx.msb').write_bytes(_FRAME)
    header = tmp_path / 'sfx.msh'
    header.write_bytes(bank_header([(len(_FRAME), 1, 0, 22050)]))
    result = runner.invoke(sopranos, ['audio', str(header), '-o', str(tmp_path / 'out')])
    assert result.exit_code == 0
    assert (tmp_path / 'out' / 'sfx_000.wav').is_file()


def test_audio_converts_a_music_stream(runner: CliRunner, tmp_path: Path) -> None:
    (tmp_path / 'song.mib').write_bytes(_FRAME)
    header = tmp_path / 'song.mih'
    header.write_bytes(bytes(8) + struct.pack('<4I', 1, 44100, 16, 1))
    assert runner.invoke(sopranos, ['audio', str(header)]).exit_code == 0
    assert (tmp_path / 'song.wav').is_file()


def test_audio_refuses_a_file_it_does_not_handle(runner: CliRunner, tmp_path: Path) -> None:
    source = tmp_path / 'line.vo2'
    source.write_bytes(voice())
    result = runner.invoke(sopranos, ['audio', str(source)])
    assert result.exit_code != 0
    assert 'not a .MSH or .MIH file' in result.output


def test_audio_reports_a_missing_body(runner: CliRunner, tmp_path: Path) -> None:
    header = tmp_path / 'sfx.msh'
    header.write_bytes(bank_header([(len(_FRAME), 1, 0, 22050)]))
    result = runner.invoke(sopranos, ['audio', str(header)])
    assert result.exit_code != 0
    assert 'Error' in result.output
