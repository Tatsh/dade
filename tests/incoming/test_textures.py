from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image
from destin.incoming.test_utils import pvr_pack, pvrt_chunk
from destin.incoming.textures import find_level_pack, place_ian_texture, place_pack_textures

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

_ODL = (
    'objfile lod 1 "low/obj.ian"\n'  # skipped (lod variant)
    'texture "orphan.ppm"\n'  # no current objfile, ignored
    'objfile "obj.ian"\n'
    'texture "tex.ppm"\n')


def _build_pc_tree(root: Path, *, ppm_valid: bool = True, ppm_present: bool = True) -> Path:
    (root / 'pcobject').mkdir()
    (root / 'asc').mkdir()
    (root / 'ppm').mkdir()
    (root / 'other').mkdir()
    source = root / 'pcobject' / 'obj.ian'
    source.write_bytes(b'x')
    (root / 'asc' / 'level.odl').write_text(_ODL, encoding='utf-8')
    (root / 'asc' / 'notes.txt').write_text('ignored', encoding='utf-8')  # non-ODL skipped
    if ppm_present:
        target = root / 'ppm' / 'tex.ppm'
        if ppm_valid:
            Image.new('RGB', (2, 2)).save(target, 'PPM')
        else:
            target.write_bytes(b'not an image')
    Image.new('RGB', (2, 2)).save(root / 'other' / 'loose.ppm', 'PPM')  # ppm not under a ppm dir
    return source


def test_place_ian_texture(tmp_path: Path) -> None:
    source = _build_pc_tree(tmp_path)
    dest = tmp_path / 'out'
    dest.mkdir()
    assert place_ian_texture(source, tmp_path, dest) == 'obj.png'
    assert (dest / 'obj.png').is_file()


def test_place_ian_texture_not_referenced(tmp_path: Path) -> None:
    _build_pc_tree(tmp_path)
    other = tmp_path / 'pcobject' / 'unknown.ian'
    other.write_bytes(b'x')
    assert place_ian_texture(other, tmp_path, tmp_path) is None


def test_place_ian_texture_missing_ppm(tmp_path: Path) -> None:
    source = _build_pc_tree(tmp_path, ppm_present=False)
    assert place_ian_texture(source, tmp_path, tmp_path) is None


def test_place_ian_texture_corrupt_ppm(tmp_path: Path) -> None:
    source = _build_pc_tree(tmp_path, ppm_valid=False)
    dest = tmp_path / 'out'
    dest.mkdir()
    assert place_ian_texture(source, tmp_path, dest) is None


def test_place_ian_texture_source_outside_root(tmp_path: Path) -> None:
    root = tmp_path / 'root'
    root.mkdir()
    _build_pc_tree(root)
    outside = tmp_path / 'obj.ian'  # not under root; relative_to raises ValueError
    outside.write_bytes(b'x')
    dest = tmp_path / 'out'
    dest.mkdir()
    assert place_ian_texture(outside, root, dest) == 'obj.png'


def test_place_pack_textures(tmp_path: Path, mocker: MockerFixture) -> None:
    pack = tmp_path / 'AFRICA_T.PVR'
    pack.write_bytes(pvr_pack([pvrt_chunk(2, 2), pvrt_chunk(4, 4)]))
    mocker.patch('destin.incoming.textures.find_spvr2png', return_value=Path('/spv'))

    def run(args: list[str], **_: object) -> object:
        raw_dir, dest = Path(args[2]), Path(args[4])
        for pvr in raw_dir.glob('*.pvr'):
            (dest / f'{pvr.stem}.png').write_bytes(b'PNG')
        return mocker.Mock()

    mocker.patch('destin.incoming.textures.sp.run', side_effect=run)
    out = tmp_path / 'out'
    out.mkdir()
    result = place_pack_textures(pack, {0, 1, 99}, out, 'AFRICA_M')
    assert result == {0: 'AFRICA_M_tex0.png', 1: 'AFRICA_M_tex1.png'}


def test_place_pack_textures_partial(tmp_path: Path, mocker: MockerFixture) -> None:
    pack = tmp_path / 'A_T.PVR'
    pack.write_bytes(pvr_pack([pvrt_chunk(2, 2), pvrt_chunk(4, 4)]))
    mocker.patch('destin.incoming.textures.find_spvr2png', return_value=Path('/spv'))

    def run(args: list[str], **_: object) -> object:
        raw_dir, dest = Path(args[2]), Path(args[4])
        first = min(raw_dir.glob('*.pvr'))  # convert only the first texture
        (dest / f'{first.stem}.png').write_bytes(b'PNG')
        return mocker.Mock()

    mocker.patch('destin.incoming.textures.sp.run', side_effect=run)
    out = tmp_path / 'out'
    out.mkdir()
    assert len(place_pack_textures(pack, {0, 1}, out, 'P')) == 1


def test_place_pack_textures_no_match(tmp_path: Path, mocker: MockerFixture) -> None:
    pack = tmp_path / 'A_T.PVR'
    pack.write_bytes(pvr_pack([pvrt_chunk(2, 2)]))
    run = mocker.patch('destin.incoming.textures.sp.run')
    out = tmp_path / 'out'
    out.mkdir()
    assert place_pack_textures(pack, {99}, out, 'P') == {}
    run.assert_not_called()


def test_find_level_pack(tmp_path: Path) -> None:
    (tmp_path / 'TEXTURES').mkdir()
    pack = tmp_path / 'TEXTURES' / 'AFRICA_T.PVR'
    pack.write_bytes(b'x')
    assert find_level_pack(tmp_path, 'AFRICA') == pack


def test_find_level_pack_missing(tmp_path: Path) -> None:
    assert find_level_pack(tmp_path, 'AFRICA') is None
