"""Tests for the ``destin i76`` commands."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from destin.i76.main import cli
import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner

_BUNDLE = b'first second! act'


def test_zfs_extract(runner: CliRunner, tmp_path: Path, zfsf_archive: bytes) -> None:
    (archive := tmp_path / 'a.zfs').write_bytes(zfsf_archive)
    result = runner.invoke(cli, ['zfs-extract', str(archive), str(tmp_path / 'out')])
    assert result.exit_code == 0
    assert 'Extracted 2 files' in result.output
    assert (tmp_path / 'out' / 'a.geo').read_bytes() == b'first'


def test_zfs_extract_rejects_non_archive(runner: CliRunner, tmp_path: Path) -> None:
    (archive := tmp_path / 'a.zfs').write_bytes(b'NOPE' + bytes(64))
    result = runner.invoke(cli, ['zfs-extract', str(archive), str(tmp_path / 'out')])
    assert result.exit_code == 1
    assert 'Not a ZFS archive' in result.output


def test_zfs_extract_missing_archive(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(cli, ['zfs-extract', str(tmp_path / 'nope.zfs'), str(tmp_path)])
    assert result.exit_code == 2


def test_zfs_list(runner: CliRunner, tmp_path: Path, zfsf_archive: bytes) -> None:
    (archive := tmp_path / 'a.zfs').write_bytes(zfsf_archive)
    result = runner.invoke(cli, ['zfs-list', str(archive)])
    assert result.exit_code == 0
    assert 'ZFSF, 3 entries' in result.output
    assert 'A.GEO' in result.output


def test_zfs_list_json(runner: CliRunner, tmp_path: Path, zfsf_archive: bytes) -> None:
    (archive := tmp_path / 'a.zfs').write_bytes(zfsf_archive)
    result = runner.invoke(cli, ['zfs-list', str(archive), '--json'])
    assert result.exit_code == 0
    assert '"name": "A.GEO"' in result.output


def test_zfs_list_rejects_non_archive(runner: CliRunner, tmp_path: Path) -> None:
    (archive := tmp_path / 'a.zfs').write_bytes(b'NOPE' + bytes(64))
    assert runner.invoke(cli, ['zfs-list', str(archive)]).exit_code == 1


def test_pak_extract(runner: CliRunner, tmp_path: Path, pix_text: str) -> None:
    (tmp_path / 'b.pix').write_text(pix_text)
    (pak := tmp_path / 'b.pak').write_bytes(_BUNDLE)
    result = runner.invoke(cli, ['pak-extract', str(pak), str(tmp_path / 'out')])
    assert result.exit_code == 0
    assert 'Extracted 3 members' in result.output


def test_pak_extract_without_index(runner: CliRunner, tmp_path: Path) -> None:
    (pak := tmp_path / 'b.pak').write_bytes(_BUNDLE)
    result = runner.invoke(cli, ['pak-extract', str(pak), str(tmp_path / 'out')])
    assert result.exit_code == 1
    assert 'No .pix index' in result.output


def test_decode_texture_map(runner: CliRunner, tmp_path: Path, map_texture: bytes,
                            palette: bytes) -> None:
    (texture := tmp_path / 'a.map').write_bytes(map_texture)
    (act := tmp_path / 'p.act').write_bytes(palette)
    result = runner.invoke(
        cli,
        ['decode-texture',
         str(texture), str(tmp_path / 'out'), '--palette',
         str(act)])
    assert result.exit_code == 0
    assert (tmp_path / 'out' / 'a.png').read_bytes().startswith(b'\x89PNG')


def test_decode_texture_vqm(runner: CliRunner, tmp_path: Path, vqm_texture: bytes, codebook: bytes,
                            palette: bytes) -> None:
    (texture := tmp_path / 'a.vqm').write_bytes(vqm_texture)
    (tmp_path / 'c.cbk').write_bytes(codebook)
    (act := tmp_path / 'p.act').write_bytes(palette)
    result = runner.invoke(
        cli, ['decode-texture',
              str(texture), str(tmp_path / 'out'), '-p',
              str(act)])
    assert result.exit_code == 0
    assert '8x8' in result.output


def test_decode_texture_vqm_missing_codebook(runner: CliRunner, tmp_path: Path, vqm_texture: bytes,
                                             palette: bytes) -> None:
    (texture := tmp_path / 'a.vqm').write_bytes(vqm_texture)
    (act := tmp_path / 'p.act').write_bytes(palette)
    result = runner.invoke(
        cli, ['decode-texture',
              str(texture), str(tmp_path / 'out'), '-p',
              str(act)])
    assert result.exit_code == 1
    assert 'Codebook c.cbk not found' in result.output


def test_decode_texture_unsupported(runner: CliRunner, tmp_path: Path, palette: bytes) -> None:
    (texture := tmp_path / 'a.xyz').write_bytes(b'data')
    (act := tmp_path / 'p.act').write_bytes(palette)
    result = runner.invoke(
        cli, ['decode-texture',
              str(texture), str(tmp_path / 'out'), '-p',
              str(act)])
    assert result.exit_code == 1
    assert 'Unsupported texture format' in result.output


def test_sdf2obj(runner: CliRunner, tmp_path: Path, sdf_model: bytes, geo_mesh: bytes) -> None:
    (model := tmp_path / 'm.sdf').write_bytes(sdf_model)
    (tmp_path / 'b.pak').write_bytes(geo_mesh)
    (tmp_path / 'b.pix').write_text(f'2\nroot.geo 0 {len(geo_mesh)}\nchild.geo 0 {len(geo_mesh)}\n')
    result = runner.invoke(cli, ['sdf2obj', str(model), str(tmp_path / 'out')])
    assert result.exit_code == 0
    assert (tmp_path / 'out' / 'm.obj').read_text().startswith('o m\n')


def test_sdf2obj_without_geometry(runner: CliRunner, tmp_path: Path, sdf_model: bytes) -> None:
    (model := tmp_path / 'm.sdf').write_bytes(sdf_model)
    result = runner.invoke(cli, ['sdf2obj', str(model), str(tmp_path / 'out')])
    assert result.exit_code == 1
    assert 'No geometry resolved' in result.output


def test_inspect_chunks(runner: CliRunner, tmp_path: Path, bwd2_container: bytes) -> None:
    (container := tmp_path / 'a.msn').write_bytes(bwd2_container)
    result = runner.invoke(cli, ['inspect-chunks', str(container)])
    assert result.exit_code == 0
    assert 'BWD2 (container)' in result.output
    assert 'LEAF' in result.output


def test_inspect_chunks_custom_tags(runner: CliRunner, tmp_path: Path,
                                    bwd2_container: bytes) -> None:
    (container := tmp_path / 'a.msn').write_bytes(bwd2_container)
    result = runner.invoke(cli, ['inspect-chunks', str(container), '--container-tags', 'NONE'])
    assert result.exit_code == 0
    assert '(container)' not in result.output


def test_unpack_i82sim_rejects_non_pe(runner: CliRunner, tmp_path: Path) -> None:
    (packed := tmp_path / 'a.dll').write_bytes(bytes(0x200))
    result = runner.invoke(cli, ['unpack-i82sim', str(packed), str(tmp_path / 'out.dll')])
    assert result.exit_code == 1
    assert 'Not a PE image' in result.output


def _write_horizon_fixture(tmp_path: Path, palette: bytes, hzd: bytes, mission: bytes) -> Path:
    root = tmp_path / 'zfs'
    root.mkdir()
    (root / 'horizon.hzd').write_bytes(hzd)
    (root / 'terrain.act').write_bytes(palette)
    strip = struct.pack('<II', 2, 2) + bytes([1, 2, 3, 4])
    (root / 'nhoriz3m.pak').write_bytes(strip * 3)
    (root /
     'nhoriz3m.pix').write_text('3\n' +
                                ''.join(f'nh_3_0{index + 1}.map {index * len(strip)} {len(strip)}\n'
                                        for index in range(3)))
    (msn := tmp_path / 'm01.msn').write_bytes(mission)
    return msn


def test_build_horizon(runner: CliRunner, tmp_path: Path, palette: bytes, hzd: bytes,
                       mission: bytes) -> None:
    msn = _write_horizon_fixture(tmp_path, palette, hzd, mission)
    result = runner.invoke(
        cli,
        ['build-horizon',
         str(msn), str(tmp_path / 'out'), '-g',
         str(tmp_path / 'zfs')])
    assert result.exit_code == 0
    assert '6x2 from 3 strips' in result.output
    assert (tmp_path / 'out' / 'm01.png').read_bytes().startswith(b'\x89PNG')


def test_build_horizon_without_hzd_reference(runner: CliRunner, tmp_path: Path) -> None:
    (msn := tmp_path / 'm.msn').write_bytes(b'no world chunk')
    (tmp_path / 'zfs').mkdir()
    result = runner.invoke(
        cli,
        ['build-horizon',
         str(msn), str(tmp_path / 'out'), '-g',
         str(tmp_path / 'zfs')])
    assert result.exit_code == 1
    assert 'references no .hzd' in result.output


def test_build_horizon_missing_strip_list(runner: CliRunner, tmp_path: Path,
                                          mission: bytes) -> None:
    (msn := tmp_path / 'm.msn').write_bytes(mission)
    (tmp_path / 'zfs').mkdir()
    result = runner.invoke(
        cli,
        ['build-horizon',
         str(msn), str(tmp_path / 'out'), '-g',
         str(tmp_path / 'zfs')])
    assert result.exit_code == 1
    assert 'not found' in result.output


def test_build_horizon_missing_bundle(runner: CliRunner, tmp_path: Path, hzd: bytes,
                                      mission: bytes) -> None:
    (msn := tmp_path / 'm.msn').write_bytes(mission)
    root = tmp_path / 'zfs'
    root.mkdir()
    (root / 'horizon.hzd').write_bytes(hzd)
    result = runner.invoke(cli, ['build-horizon', str(msn), str(tmp_path / 'out'), '-g', str(root)])
    assert result.exit_code == 1
    assert 'Bundle nhoriz3m not found' in result.output


@pytest.mark.parametrize('flag', ['-d', '--debug'])
def test_debug_flag_accepted(runner: CliRunner, tmp_path: Path, zfsf_archive: bytes,
                             flag: str) -> None:
    (archive := tmp_path / 'a.zfs').write_bytes(zfsf_archive)
    result = runner.invoke(cli, ['zfs-extract', str(archive), str(tmp_path / 'out'), flag])
    assert result.exit_code == 0


def test_unpack_i82sim(runner: CliRunner, tmp_path: Path, packed_dll: bytes) -> None:
    (packed := tmp_path / 'a.dll').write_bytes(packed_dll)
    result = runner.invoke(cli, ['unpack-i82sim', str(packed), str(out := tmp_path / 'out.dll')])
    assert result.exit_code == 0
    assert out.read_bytes()[0x1000:0x1010] == b'\xcd' * 16


def test_build_horizon_empty_strip_list(runner: CliRunner, tmp_path: Path, mission: bytes) -> None:
    (msn := tmp_path / 'm.msn').write_bytes(mission)
    root = tmp_path / 'zfs'
    root.mkdir()
    (root / 'horizon.hzd').write_bytes(b'nothing here')
    result = runner.invoke(cli, ['build-horizon', str(msn), str(tmp_path / 'out'), '-g', str(root)])
    assert result.exit_code == 1
    assert 'names no strips' in result.output


def test_build_horizon_no_strips_in_bundle(runner: CliRunner, tmp_path: Path, hzd: bytes,
                                           mission: bytes) -> None:
    (msn := tmp_path / 'm.msn').write_bytes(mission)
    root = tmp_path / 'zfs'
    root.mkdir()
    (root / 'horizon.hzd').write_bytes(hzd)
    (root / 'nhoriz3m.pak').write_bytes(b'unused')
    (root / 'nhoriz3m.pix').write_text('1\nother.map 0 6\n')
    result = runner.invoke(cli, ['build-horizon', str(msn), str(tmp_path / 'out'), '-g', str(root)])
    assert result.exit_code == 1
    assert 'None of the 3 strips' in result.output


def test_build_horizon_missing_palette(runner: CliRunner, tmp_path: Path, palette: bytes,
                                       hzd: bytes, mission: bytes) -> None:
    msn = _write_horizon_fixture(tmp_path, palette, hzd, mission)
    (tmp_path / 'zfs' / 'terrain.act').unlink()
    result = runner.invoke(
        cli,
        ['build-horizon',
         str(msn), str(tmp_path / 'out'), '-g',
         str(tmp_path / 'zfs')])
    assert result.exit_code == 1
    assert 'Palette terrain.act not found' in result.output


def test_build_horizon_palette_override(runner: CliRunner, tmp_path: Path, palette: bytes,
                                        hzd: bytes, mission: bytes) -> None:
    msn = _write_horizon_fixture(tmp_path, palette, hzd, mission)
    (tmp_path / 'zfs' / 'other.act').write_bytes(palette)
    result = runner.invoke(cli, [
        'build-horizon',
        str(msn),
        str(tmp_path / 'out'), '-g',
        str(tmp_path / 'zfs'), '-p', 'other.act'
    ])
    assert result.exit_code == 0


def test_stage_i82(runner: CliRunner, tmp_path: Path, i82_source: Path) -> None:
    result = runner.invoke(cli, ['stage-i82', str(i82_source), str(out := tmp_path / 'out')])
    assert result.exit_code == 0
    assert 'Staged 1 levels: lvl1.' in result.output
    assert (out / 'worlds' / 'lvl1.msa').is_file()
    assert (out / 'terrain' / 'lvl1.mrm').is_file()


def test_stage_i82_copies_textures(runner: CliRunner, tmp_path: Path, i82_source: Path) -> None:
    runner.invoke(cli, ['stage-i82', str(i82_source), str(out := tmp_path / 'out')])
    assert (out / 'tex' / 'wall.bmp').read_bytes() == b'wall'
    assert (out / 'tex' / 'road.bmp').read_bytes() == b'road'


def test_stage_i82_reports_missing_textures(runner: CliRunner, tmp_path: Path,
                                            i82_source: Path) -> None:
    result = runner.invoke(cli, ['stage-i82', str(i82_source), str(tmp_path / 'out')])
    # grass.tga is named by the terrain but is in no pool.
    assert 'Textures: 3 staged, 1 missing.' in result.output
    assert 'grass.tga' in result.output


def test_stage_i82_ignores_worlds_without_terrain(runner: CliRunner, tmp_path: Path,
                                                  i82_source: Path) -> None:
    runner.invoke(cli, ['stage-i82', str(i82_source), str(out := tmp_path / 'out')])
    assert not (out / 'worlds' / 'orphan.msa').exists()


def test_stage_i82_without_levels(runner: CliRunner, tmp_path: Path) -> None:
    (source := tmp_path / 'src').mkdir()
    (source / 'data').mkdir()
    (source / 'mrm').mkdir()
    result = runner.invoke(cli, ['stage-i82', str(source), str(tmp_path / 'out')])
    assert result.exit_code == 1
    assert 'No level under' in result.output


def test_stage_i82_custom_texture_pool(runner: CliRunner, tmp_path: Path, i82_source: Path) -> None:
    (pool := tmp_path / 'pool').mkdir()
    (pool / 'grass.tga').write_bytes(b'grass')
    result = runner.invoke(
        cli,
        ['stage-i82',
         str(i82_source),
         str(out := tmp_path / 'out'), '--texture-pool',
         str(pool)])
    assert result.exit_code == 0
    assert (out / 'tex' / 'grass.tga').read_bytes() == b'grass'


def test_stage_i82_every_texture_found(runner: CliRunner, tmp_path: Path, i82_source: Path) -> None:
    (pool := tmp_path / 'pool').mkdir()
    (pool / 'grass.tga').write_bytes(b'grass')
    result = runner.invoke(cli, [
        'stage-i82',
        str(i82_source),
        str(tmp_path / 'out'), '--texture-pool',
        str(i82_source / 'bmp'), '--texture-pool',
        str(i82_source / 'tga'), '--texture-pool',
        str(pool)
    ])
    assert result.exit_code == 0
    assert 'Textures: 4 staged, 0 missing.' in result.output
    assert 'Missing:' not in result.output


def test_stage_i82_objects(runner: CliRunner, tmp_path: Path, i82_source: Path) -> None:
    result = runner.invoke(
        cli, ['stage-i82-objects',
              str(i82_source), str(out := tmp_path / 'out')])
    assert result.exit_code == 0
    assert 'Levels: 1, .stf refs: 2, .vdf refs: 1.' in result.output
    assert (out / 'meshes' / 'tower.stf').is_file()
    assert (out / 'meshes' / 'car.vdf').is_file()
    assert (out / 'meshes' / 'sedan.cdf').is_file()


def test_stage_i82_objects_prefers_sbx_then_six(runner: CliRunner, tmp_path: Path,
                                                i82_source: Path) -> None:
    runner.invoke(cli, ['stage-i82-objects', str(i82_source), str(out := tmp_path / 'out')])
    assert (out / 'meshes' / 'tower.sbx').is_file()  # A .sbx exists, so it wins.
    assert (out / 'meshes' / 'sedan.six').is_file()  # Only a .six exists, so it is used.


def test_stage_i82_objects_copies_mesh_textures(runner: CliRunner, tmp_path: Path,
                                                i82_source: Path) -> None:
    runner.invoke(cli, ['stage-i82-objects', str(i82_source), str(out := tmp_path / 'out')])
    assert (out / 'objtex' / 'wall.bmp').read_bytes() == b'wall'
    assert (out / 'objtex' / 'body.tga').read_bytes() == b'body'


def test_stage_i82_objects_reports_missing_meshes(runner: CliRunner, tmp_path: Path,
                                                  i82_source: Path) -> None:
    result = runner.invoke(cli, ['stage-i82-objects', str(i82_source), str(tmp_path / 'out')])
    # The chassis names wheel.six, which is in no pool.
    assert 'wheel.sbx' in result.output


def test_stage_i82_objects_without_levels(runner: CliRunner, tmp_path: Path) -> None:
    (source := tmp_path / 'src').mkdir()
    (source / 'data').mkdir()
    (source / 'mrm').mkdir()
    result = runner.invoke(cli, ['stage-i82-objects', str(source), str(tmp_path / 'out')])
    assert result.exit_code == 1
    assert 'No level under' in result.output


def _objects_source(tmp_path: Path, world: bytes, mrm_terrain: bytes, files: dict[str,
                                                                                  bytes]) -> Path:
    """
    Build a minimal I82 extraction tree holding one level plus the given data files.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Directory to build under.
    world : bytes
        Contents of the level's ``.msa``.
    mrm_terrain : bytes
        Contents of the level's ``.mrm``.
    files : dict[str, bytes]
        Extra files to place in the ``data`` directory.

    Returns
    -------
    pathlib.Path
        Root of the tree.
    """
    root = tmp_path / 'src'
    for name in ('bmp', 'data', 'mrm', 'tga'):
        (root / name).mkdir(parents=True)
    (root / 'data' / 'lvl.msa').write_bytes(world)
    (root / 'mrm' / 'lvl.mrm').write_bytes(mrm_terrain)
    for name, payload in files.items():
        (root / 'data' / name).write_bytes(payload)
    return root


def test_stage_i82_objects_reports_missing_wrappers(runner: CliRunner, tmp_path: Path,
                                                    msa_world: bytes, mrm_terrain: bytes) -> None:
    source = _objects_source(tmp_path, msa_world, mrm_terrain, {})
    result = runner.invoke(cli, ['stage-i82-objects', str(source), str(tmp_path / 'out')])
    assert result.exit_code == 0
    assert 'Staged 0 .stf, 0 .vdf' in result.output
    assert 'car.vdf' in result.output


def test_stage_i82_objects_vehicle_without_chassis(runner: CliRunner, tmp_path: Path,
                                                   mrm_terrain: bytes) -> None:
    world = b'Object_Header {\nFile: car.vdf\n}\n'
    source = _objects_source(tmp_path, world, mrm_terrain, {'car.vdf': b'no chassis line\n'})
    result = runner.invoke(cli, ['stage-i82-objects', str(source), str(tmp_path / 'out')])
    assert result.exit_code == 0
    assert 'Staged 0 .stf, 0 .vdf, 0 meshes' in result.output


def test_stage_i82_objects_missing_chassis_file(runner: CliRunner, tmp_path: Path,
                                                mrm_terrain: bytes) -> None:
    world = b'Object_Header {\nFile: car.vdf\n}\n'
    source = _objects_source(tmp_path, world, mrm_terrain, {'car.vdf': b'Chassis = ghost\n'})
    result = runner.invoke(cli, ['stage-i82-objects', str(source), str(tmp_path / 'out')])
    assert result.exit_code == 0
    assert 'ghost.cdf' in result.output


def test_stage_i82_objects_chassis_without_assets(runner: CliRunner, tmp_path: Path,
                                                  mrm_terrain: bytes) -> None:
    world = b'Object_Header {\nFile: car.vdf\n}\n'
    source = _objects_source(tmp_path, world, mrm_terrain, {
        'car.vdf': b'Chassis = sedan\n',
        'sedan.cdf': b'Name = sedan\n'
    })
    result = runner.invoke(cli, ['stage-i82-objects', str(source), str(out := tmp_path / 'out')])
    assert result.exit_code == 0
    assert 'Staged 0 .stf, 1 .vdf, 0 meshes, 0 textures.' in result.output
    assert (out / 'meshes' / 'sedan.cdf').is_file()


def test_stage_i82_objects_reports_missing_textures(runner: CliRunner, tmp_path: Path,
                                                    mrm_terrain: bytes) -> None:
    world = b'Object_Header {\nFile: box.stf\n}\n'
    source = _objects_source(tmp_path, world, mrm_terrain, {
        'box.stf': b'Geometry_Files {\n  box.six\n}\n',
        'box.sbx': b'mesh\x00absent.bmp\x00'
    })
    result = runner.invoke(cli, ['stage-i82-objects', str(source), str(tmp_path / 'out')])
    assert result.exit_code == 0
    assert 'Missing 1 textures: absent.bmp' in result.output
