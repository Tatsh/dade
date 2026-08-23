from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from destin.incoming.commands.extract_pvr_pack import extract_pvr_pack
from destin.incoming.commands.ian2obj import ian2obj
from destin.incoming.test_utils import ian_model, mbin_pair, pvr_pack, pvrt_chunk

if TYPE_CHECKING:
    from click.testing import CliRunner
    from pytest_mock import MockerFixture

_VERTEX = (1.0, 2.0, 3.0, 0.0, 1.0, 0.0, 0.25, 0.75)
_ODL = 'objfile "obj.ian"\ntexture "tex.ppm"\n'


def _build_game(root: Path) -> Path:
    (root / 'pcobject').mkdir(parents=True)
    (root / 'ppm').mkdir()
    (root / 'asc').mkdir()
    model = root / 'pcobject' / 'obj.ian'
    model.write_bytes(ian_model([_VERTEX], [(0, 0, 0)]))
    (root / 'asc' / 'level.odl').write_text(_ODL, encoding='utf-8')
    Image.new('RGB', (2, 2)).save(root / 'ppm' / 'tex.ppm', 'PPM')
    return model


def _build_dc_game(root: Path) -> Path:
    (root / 'MODELS').mkdir(parents=True)
    (root / 'TEXTURES').mkdir()
    m_bin, ml_bin = mbin_pair(texture_index=0)
    model = root / 'MODELS' / 'AFRICA_M.BIN'
    model.write_bytes(m_bin)
    (root / 'MODELS' / 'AFRICA_ML.BIN').write_bytes(ml_bin)
    (root / 'TEXTURES' / 'AFRICA_T.PVR').write_bytes(pvr_pack([pvrt_chunk(2, 2)]))
    return model


def test_extract_pvr_pack_raw(runner: CliRunner, tmp_path: Path) -> None:
    pack = tmp_path / 'AFRICA_T.PVR'
    pack.write_bytes(pvr_pack([pvrt_chunk(2, 2), pvrt_chunk(4, 4)]))
    out = tmp_path / 'out'
    result = runner.invoke(extract_pvr_pack, [str(pack), str(out)])
    assert result.exit_code == 0
    assert len(list((out / 'AFRICA_T').glob('*.pvr'))) == 2
    assert 'Extracted 2' in result.output


def test_extract_pvr_pack_png(runner: CliRunner, tmp_path: Path, mocker: MockerFixture) -> None:
    pack = tmp_path / 'A_T.PVR'
    pack.write_bytes(pvr_pack([pvrt_chunk(2, 2)]))
    mocker.patch('destin.incoming.converters.images.find_spvr2png', return_value=Path('/spv'))

    def run(args: list[str], **_: object) -> object:
        raw_dir, dest = Path(args[2]), Path(args[4])
        for pvr in raw_dir.glob('*.pvr'):
            (dest / f'{pvr.stem}.png').write_bytes(b'PNG')
        return mocker.Mock()

    mocker.patch('destin.incoming.converters.images.sp.run', side_effect=run)
    out = tmp_path / 'out'
    result = runner.invoke(extract_pvr_pack, ['--png', str(pack), str(out)])
    assert result.exit_code == 0
    assert list((out / 'A_T').glob('*.png'))


def test_ian2obj_auto_texture(runner: CliRunner, tmp_path: Path) -> None:
    model = _build_game(tmp_path)
    out = tmp_path / 'out'
    result = runner.invoke(ian2obj, [str(model), str(out)])
    assert result.exit_code == 0
    assert (out / 'obj.obj').is_file()
    assert (out / 'obj.png').is_file()
    assert 'map_Kd obj.png' in (out / 'obj.mtl').read_text('utf-8')
    assert 'Wrote 3' in result.output


def test_ian2obj_explicit_game_root(runner: CliRunner, tmp_path: Path) -> None:
    root = tmp_path / 'game'
    model = _build_game(root)
    out = tmp_path / 'out'
    result = runner.invoke(ian2obj, ['--game-root', str(root), str(model), str(out)])
    assert result.exit_code == 0
    assert (out / 'obj.png').is_file()


def test_ian2obj_no_texture(runner: CliRunner, tmp_path: Path) -> None:
    model = tmp_path / 'arrow.ian'
    model.write_bytes(ian_model([_VERTEX], [(0, 0, 0)]))
    out = tmp_path / 'out'
    result = runner.invoke(ian2obj, ['--no-texture', str(model), str(out)])
    assert result.exit_code == 0
    assert (out / 'arrow.obj').is_file()
    assert 'map_Kd' not in (out / 'arrow.mtl').read_text('utf-8')


def test_ian2obj_no_game_root_found(runner: CliRunner, tmp_path: Path) -> None:
    model = tmp_path / 'lone.ian'
    model.write_bytes(ian_model([_VERTEX], [(0, 0, 0)]))
    out = tmp_path / 'out'
    result = runner.invoke(ian2obj, [str(model), str(out)])
    assert result.exit_code == 0
    assert (out / 'lone.obj').is_file()


def test_ian2obj_dc_auto_texture(runner: CliRunner, tmp_path: Path, mocker: MockerFixture) -> None:
    model = _build_dc_game(tmp_path)
    mocker.patch('destin.incoming.textures.find_spvr2png', return_value=Path('/spv'))

    def run(args: list[str], **_: object) -> object:
        raw_dir, dest = Path(args[2]), Path(args[4])
        for pvr in raw_dir.glob('*.pvr'):
            (dest / f'{pvr.stem}.png').write_bytes(b'PNG')
        return mocker.Mock()

    mocker.patch('destin.incoming.textures.sp.run', side_effect=run)
    out = tmp_path / 'out'
    result = runner.invoke(ian2obj, [str(model), str(out)])
    assert result.exit_code == 0
    assert (out / 'AFRICA_M' / 'AFRICA_M_000.obj').is_file()
    assert 'map_Kd AFRICA_M_000.png' in (out / 'AFRICA_M' / 'AFRICA_M_000.mtl').read_text('utf-8')
    assert (out / 'AFRICA_M' / 'AFRICA_M_000.png').is_file()


def test_ian2obj_dc_explicit_game_root(runner: CliRunner, tmp_path: Path,
                                       mocker: MockerFixture) -> None:
    root = tmp_path / 'game'
    model = _build_dc_game(root)
    mocker.patch('destin.incoming.textures.find_spvr2png', return_value=Path('/spv'))

    def run(args: list[str], **_: object) -> object:
        raw_dir, dest = Path(args[2]), Path(args[4])
        for pvr in raw_dir.glob('*.pvr'):
            (dest / f'{pvr.stem}.png').write_bytes(b'PNG')
        return mocker.Mock()

    mocker.patch('destin.incoming.textures.sp.run', side_effect=run)
    out = tmp_path / 'out'
    result = runner.invoke(ian2obj, ['--game-root', str(root), str(model), str(out)])
    assert result.exit_code == 0
    assert (out / 'AFRICA_M' / 'AFRICA_M_000.png').is_file()


def test_ian2obj_dc_no_texture(runner: CliRunner, tmp_path: Path) -> None:
    model = _build_dc_game(tmp_path)
    out = tmp_path / 'out'
    result = runner.invoke(ian2obj, ['--no-texture', str(model), str(out)])
    assert result.exit_code == 0
    assert (out / 'AFRICA_M' / 'AFRICA_M_000.obj').is_file()
    assert 'map_Kd' not in (out / 'AFRICA_M' / 'AFRICA_M_000.mtl').read_text('utf-8')


def test_ian2obj_dc_no_game_root_found(runner: CliRunner, tmp_path: Path) -> None:
    m_bin, ml_bin = mbin_pair(texture_index=0)
    model = tmp_path / 'AFRICA_M.BIN'
    model.write_bytes(m_bin)
    (tmp_path / 'AFRICA_ML.BIN').write_bytes(ml_bin)
    out = tmp_path / 'out'
    result = runner.invoke(ian2obj, [str(model), str(out)])
    assert result.exit_code == 0
    assert (out / 'AFRICA_M' / 'AFRICA_M_000.obj').is_file()
    assert 'map_Kd' not in (out / 'AFRICA_M' / 'AFRICA_M_000.mtl').read_text('utf-8')
