"""CLI tests for the ``destin thps2pc`` commands."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json

import pytest

from destin.thps2pc.commands import render as render_commands
from destin.thps2pc.commands.convert_scene import convert_scene
from destin.thps2pc.commands.decode_textures import decode_textures
from destin.thps2pc.commands.dump_descriptors import dump_descriptors
from destin.thps2pc.commands.psx_info import psx_info
from destin.thps2pc.commands.render import (
    render_authoritative_command,
    render_layers_command,
    render_node_map_command,
    render_object_models_command,
    render_objects_command,
)
from destin.thps2pc.commands.unpack_pkr import unpack_pkr
from destin.thps2pc.test_utils import (
    SectorSpec,
    face_record,
    pkr_archive,
    psx_lighting,
    psx_scene,
    stored_file,
)

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner
    from pytest_mock import MockerFixture
    import click


@pytest.fixture(autouse=True)
def _no_subprocess(mocker: MockerFixture) -> None:
    mocker.patch('destin.thps2pc.imagemagick.sp.run')
    mocker.patch('destin.thps2pc.imagemagick.which', side_effect=lambda name: f'/usr/bin/{name}')


def test_unpack_pkr_lists_without_extracting(runner: CliRunner, pkr_bytes: bytes,
                                             tmp_path: Path) -> None:
    source = tmp_path / 'All.pkr'
    source.write_bytes(pkr_bytes)
    result = runner.invoke(unpack_pkr, [str(source), '--list'])
    assert result.exit_code == 0
    assert 'data/A.PSX' in result.output
    assert not (tmp_path / 'data').exists()


def test_unpack_pkr_extracts(runner: CliRunner, pkr_bytes: bytes, tmp_path: Path) -> None:
    source = tmp_path / 'All.pkr'
    source.write_bytes(pkr_bytes)
    result = runner.invoke(unpack_pkr, [str(source), str(tmp_path / 'out')])
    assert result.exit_code == 0
    assert (tmp_path / 'out' / 'data' / 'A.PSX').read_bytes() == b'AAAA'


def test_unpack_pkr_requires_a_destination(runner: CliRunner, pkr_bytes: bytes,
                                           tmp_path: Path) -> None:
    source = tmp_path / 'All.pkr'
    source.write_bytes(pkr_bytes)
    result = runner.invoke(unpack_pkr, [str(source)])
    assert result.exit_code == 2
    assert 'DESTDIR is required' in result.output


def test_unpack_pkr_rejects_a_non_pkr(runner: CliRunner, tmp_path: Path) -> None:
    source = tmp_path / 'bad.pkr'
    source.write_bytes(b'NOPE' + bytes(12))
    result = runner.invoke(unpack_pkr, [str(source), '--list'])
    assert result.exit_code == 1
    assert 'Bad magic' in result.output


def test_unpack_pkr_warns_on_a_child_count_mismatch(runner: CliRunner, tmp_path: Path) -> None:
    data = bytearray(pkr_archive((('d/', (stored_file('a.bin', b'a'),)),)))
    data[52:56] = (0).to_bytes(4, 'little')  # The directory's childCount.
    source = tmp_path / 'All.pkr'
    source.write_bytes(bytes(data))
    result = runner.invoke(unpack_pkr, [str(source), '--list'])
    assert result.exit_code == 0
    assert 'sum(childCount)=0 does not equal fileCount=1' in result.output


def test_unpack_pkr_rejects_an_escaping_entry(runner: CliRunner, tmp_path: Path) -> None:
    source = tmp_path / 'All.pkr'
    source.write_bytes(pkr_archive((('../escape/', (stored_file('x.bin', b'x'),)),)))
    result = runner.invoke(unpack_pkr, [str(source), str(tmp_path / 'out')])
    assert result.exit_code == 1
    assert 'Unsafe path in archive' in result.output


def test_psx_info_summarises(runner: CliRunner, scene_file: Path) -> None:
    result = runner.invoke(psx_info, [str(scene_file)])
    assert result.exit_code == 0
    assert 'sectors=2' in result.output
    assert 'verts=8' in result.output


def test_psx_info_rejects_a_short_file(runner: CliRunner, tmp_path: Path) -> None:
    bad = tmp_path / 'bad.psx'
    bad.write_bytes(b'\x00')
    result = runner.invoke(psx_info, [str(bad)])
    assert result.exit_code == 1
    assert 'too small' in result.output


def test_convert_scene_writes_a_mesh(runner: CliRunner, scene_file: Path, tmp_path: Path) -> None:
    out = tmp_path / 'out'
    result = runner.invoke(convert_scene, [str(scene_file), str(out), '--no-textures'])
    assert result.exit_code == 0
    assert (out / 'models' / 'S.bin').stat().st_size > 0
    manifest = json.loads((out / 'models' / 'S.json').read_text())
    assert manifest['scale'] == pytest.approx(1.0 / 256.0)
    assert 'firstVertex' in manifest['batches'][0]


def test_convert_scene_honours_the_name_option(runner: CliRunner, scene_file: Path,
                                               tmp_path: Path) -> None:
    out = tmp_path / 'out'
    result = runner.invoke(
        convert_scene,
        [str(scene_file), str(out), '--no-textures', '--name', 'Hangar'])
    assert result.exit_code == 0
    assert (out / 'models' / 'Hangar.bin').exists()


def test_convert_scene_converts_resolved_textures(runner: CliRunner, scene_file: Path,
                                                  tmp_path: Path, mocker: MockerFixture) -> None:
    textures = tmp_path / 'newtex'
    textures.mkdir()
    (textures / 'deadbeef.bmp').write_bytes(b'BM')
    convert = mocker.patch('destin.thps2pc.commands.convert_scene.convert')
    out = tmp_path / 'out'
    result = runner.invoke(
        convert_scene, [str(scene_file), str(out), '--texture-dir',
                        str(textures)])
    assert result.exit_code == 0
    assert convert.call_count == 1
    assert 'textures_resolved=1' in result.output


def test_convert_scene_reports_a_conversion_failure(runner: CliRunner, scene_file: Path,
                                                    tmp_path: Path, mocker: MockerFixture) -> None:
    textures = tmp_path / 'newtex'
    textures.mkdir()
    (textures / 'deadbeef.bmp').write_bytes(b'BM')
    mocker.patch('destin.thps2pc.commands.convert_scene.convert', side_effect=OSError('boom'))
    result = runner.invoke(
        convert_scene,
        [str(scene_file), str(tmp_path / 'out'), '--texture-dir',
         str(textures)])
    assert result.exit_code == 1


def test_convert_scene_skips_untextured_and_already_written_textures(runner: CliRunner,
                                                                     tmp_path: Path,
                                                                     mocker: MockerFixture) -> None:
    textured = face_record((0, 1, 2), texture_index=0, flags=0x11)
    untextured = face_record((0, 1, 2), flags=0x10)
    spec = SectorSpec(vertices=((0, 0, 0), (100, 0, 0), (0, 0, 100)),
                      faces=(textured, untextured),
                      count_b=0)
    source = tmp_path / 'S.PSX'
    source.write_bytes(psx_scene(sectors=(spec,), checksums=(0xDEADBEEF,)))
    out = tmp_path / 'out'
    (out / 'textures' / 'S').mkdir(parents=True)
    (out / 'textures' / 'S' / 'DEADBEEF.png').write_bytes(b'\x89PNG')
    convert = mocker.patch('destin.thps2pc.commands.convert_scene.convert')
    result = runner.invoke(convert_scene, [str(source), str(out)])
    assert result.exit_code == 0
    convert.assert_not_called()
    assert 'textures_resolved=1' in result.output
    assert 'untextured/placeholder verts=3' in result.output


def test_render_reports_a_write_failure(runner: CliRunner, scene_file: Path, tmp_path: Path,
                                        mocker: MockerFixture) -> None:
    mocker.patch('destin.thps2pc.commands.utils.write_image', side_effect=OSError('boom'))
    result = runner.invoke(render_authoritative_command, [
        str(scene_file),
        str(tmp_path / 'out.png'), '--width', '32', '--height', '32', '--padding', '2'
    ])
    assert result.exit_code == 1
    assert 'Could not write' in result.output


def test_render_object_models_reports_a_montage_failure(runner: CliRunner, scene_file: Path,
                                                        tmp_path: Path,
                                                        mocker: MockerFixture) -> None:
    mocker.patch('destin.thps2pc.commands.utils.montage', side_effect=OSError('boom'))
    result = runner.invoke(render_object_models_command, [
        str(scene_file),
        str(tmp_path / 'models'), '--suffix', '.ppm', '--size', '24', '--padding', '2'
    ])
    assert result.exit_code == 1
    assert 'Could not build' in result.output


def test_render_object_models_reports_an_empty_scene(runner: CliRunner, tmp_path: Path) -> None:
    empty = tmp_path / 'E.PSX'
    empty.write_bytes(psx_scene())
    result = runner.invoke(render_object_models_command,
                           [str(empty), str(tmp_path / 'models'), '--suffix', '.ppm'])
    assert result.exit_code == 0
    assert 'The scene holds no sectors.' in result.output


def test_render_node_map_annotates_with_a_detected_font(runner: CliRunner, scene_file: Path,
                                                        tmp_path: Path, mocker: MockerFixture,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    fonts = tmp_path / 'fonts' / 'truetype'
    fonts.mkdir(parents=True)
    (fonts / 'DejaVuSans.ttf').write_bytes(b'\x00')
    monkeypatch.setattr(render_commands, '_FONT_ROOT', tmp_path / 'fonts')
    write_image = mocker.patch('destin.thps2pc.commands.utils.write_image')
    result = runner.invoke(render_node_map_command, [
        str(scene_file),
        str(tmp_path / 'nodes.png'), '--width', '64', '--height', '64', '--padding', '2'
    ])
    assert result.exit_code == 0
    args = list(write_image.call_args.args[3])
    assert args[args.index('-font') + 1] == str(fonts / 'DejaVuSans.ttf')


@pytest.mark.parametrize('populate', [False, True])
def test_render_node_map_annotates_without_a_font(runner: CliRunner, scene_file: Path,
                                                  tmp_path: Path, mocker: MockerFixture,
                                                  monkeypatch: pytest.MonkeyPatch, *,
                                                  populate: bool) -> None:
    fonts = tmp_path / 'fonts'
    if populate:
        fonts.mkdir()
        (fonts / 'Cursive.ttf').write_bytes(b'\x00')
    monkeypatch.setattr(render_commands, '_FONT_ROOT', fonts)
    write_image = mocker.patch('destin.thps2pc.commands.utils.write_image')
    result = runner.invoke(render_node_map_command, [
        str(scene_file),
        str(tmp_path / 'nodes.png'), '--width', '64', '--height', '64', '--padding', '2'
    ])
    assert result.exit_code == 0
    args = list(write_image.call_args.args[3])
    assert '-annotate' in args
    assert '-font' not in args


def test_decode_textures_writes_ppm_without_imagemagick(runner: CliRunner, lighting_file: Path,
                                                        tmp_path: Path,
                                                        mocker: MockerFixture) -> None:
    run = mocker.patch('destin.thps2pc.imagemagick.sp.run')
    out = tmp_path / 'tex'
    result = runner.invoke(
        decode_textures,
        [str(lighting_file),
         str(out), '--suffix', '.ppm', '--tile-size', '', '--no-montage'])
    assert result.exit_code == 0
    assert (out / 'A1B2C3D4.ppm').exists()
    assert (out / '11223344.ppm').exists()
    run.assert_not_called()


def test_decode_textures_builds_contact_sheets(runner: CliRunner, lighting_file: Path,
                                               tmp_path: Path, mocker: MockerFixture) -> None:
    montage = mocker.patch('destin.thps2pc.commands.utils.montage')
    result = runner.invoke(
        decode_textures,
        [str(lighting_file),
         str(tmp_path / 'tex'), '--suffix', '.ppm', '--tile-size', ''])
    assert result.exit_code == 0
    assert montage.call_count == 1
    assert 'contact sheets' in result.output


def test_decode_textures_reports_when_nothing_decodes(runner: CliRunner, tmp_path: Path) -> None:
    empty = tmp_path / 'E_L.PSX'
    empty.write_bytes(psx_lighting())
    result = runner.invoke(decode_textures, [str(empty), str(tmp_path / 'tex'), '--suffix', '.ppm'])
    assert result.exit_code == 0
    assert 'No textures could be decoded.' in result.output


@pytest.mark.parametrize('command', [render_authoritative_command, render_layers_command])
def test_single_scene_renders_write_a_ppm(command: click.Command, runner: CliRunner,
                                          scene_file: Path, tmp_path: Path) -> None:
    output = tmp_path / 'out.ppm'
    result = runner.invoke(
        command,
        [str(scene_file),
         str(output), '--width', '48', '--height', '48', '--padding', '2'])
    assert result.exit_code == 0
    assert output.read_bytes().startswith(b'P6\n48 48\n255\n')


def test_render_authoritative_accepts_its_flags(runner: CliRunner, scene_file: Path,
                                                tmp_path: Path) -> None:
    output = tmp_path / 'out.ppm'
    result = runner.invoke(render_authoritative_command, [
        str(scene_file),
        str(output), '--no-placement', '--hide-nonrendered', '--width', '32', '--height', '32',
        '--padding', '2'
    ])
    assert result.exit_code == 0
    assert output.exists()


def test_render_node_map_uses_the_default_nodes(runner: CliRunner, scene_file: Path,
                                                tmp_path: Path) -> None:
    output = tmp_path / 'nodes.ppm'
    result = runner.invoke(render_node_map_command, [
        str(scene_file),
        str(output), '--no-labels', '--width', '64', '--height', '64', '--padding', '2'
    ])
    assert result.exit_code == 0
    assert 'with 17 nodes' in result.output


def test_render_node_map_loads_nodes_from_json(runner: CliRunner, scene_file: Path,
                                               tmp_path: Path) -> None:
    nodes = tmp_path / 'nodes.json'
    nodes.write_text(json.dumps([{'label': 'x', 'x': 0, 'z': 0}]))
    output = tmp_path / 'nodes.ppm'
    result = runner.invoke(render_node_map_command, [
        str(scene_file),
        str(output), '--nodes',
        str(nodes), '--no-labels', '--width', '64', '--height', '64', '--padding', '2'
    ])
    assert result.exit_code == 0
    assert 'with 1 nodes' in result.output


def test_render_node_map_annotates_labels(runner: CliRunner, scene_file: Path, tmp_path: Path,
                                          mocker: MockerFixture) -> None:
    write_image = mocker.patch('destin.thps2pc.commands.utils.write_image')
    mocker.patch('destin.thps2pc.commands.render._find_font', return_value=None)
    result = runner.invoke(render_node_map_command, [
        str(scene_file),
        str(tmp_path / 'nodes.png'), '--width', '64', '--height', '64', '--padding', '2'
    ])
    assert result.exit_code == 0
    args = list(write_image.call_args.args[3])
    assert '-annotate' in args
    assert '109' in args


def test_render_objects_parses_a_highlight(runner: CliRunner, scene_file: Path,
                                           tmp_path: Path) -> None:
    output = tmp_path / 'obj.ppm'
    result = runner.invoke(render_objects_command, [
        str(scene_file),
        str(scene_file),
        str(output), '--highlight', '0:FF0000', '--width', '48', '--height', '48', '--padding', '2'
    ])
    assert result.exit_code == 0
    assert bytes((255, 0, 0)) in output.read_bytes()


def test_render_objects_rejects_a_bad_highlight(runner: CliRunner, scene_file: Path,
                                                tmp_path: Path) -> None:
    result = runner.invoke(
        render_objects_command,
        [str(scene_file),
         str(scene_file),
         str(tmp_path / 'obj.ppm'), '--highlight', 'nonsense'])
    assert result.exit_code == 2
    assert 'expected SECTOR:RRGGBB' in result.output


def test_render_object_models_writes_tiles(runner: CliRunner, scene_file: Path,
                                           tmp_path: Path) -> None:
    out = tmp_path / 'models'
    result = runner.invoke(render_object_models_command, [
        str(scene_file),
        str(out), '--suffix', '.ppm', '--size', '24', '--padding', '2', '--no-montage'
    ])
    assert result.exit_code == 0
    assert (out / 's00.ppm').exists()
    assert (out / 's01.ppm').exists()


def test_render_object_models_builds_a_sheet(runner: CliRunner, scene_file: Path, tmp_path: Path,
                                             mocker: MockerFixture) -> None:
    montage = mocker.patch('destin.thps2pc.commands.utils.montage')
    result = runner.invoke(render_object_models_command, [
        str(scene_file),
        str(tmp_path / 'models'), '--suffix', '.ppm', '--size', '24', '--padding', '2'
    ])
    assert result.exit_code == 0
    args = montage.call_args.args[0]
    assert '-label' in args
    assert 's0 v4 f2' in args


def test_dump_descriptors_prints_a_report(runner: CliRunner, scene_file: Path) -> None:
    result = runner.invoke(dump_descriptors, [str(scene_file)])
    assert result.exit_code == 0
    assert '=== CHUNK LIST ===' in result.output


def test_dump_descriptors_writes_to_a_file(runner: CliRunner, scene_file: Path,
                                           tmp_path: Path) -> None:
    out = tmp_path / 'nested' / 'report.txt'
    result = runner.invoke(dump_descriptors, [str(scene_file), '--out', str(out)])
    assert result.exit_code == 0
    assert '=== CHUNK LIST ===' in out.read_text()
