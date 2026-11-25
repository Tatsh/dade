from __future__ import annotations

from typing import TYPE_CHECKING
import json

import pytest

from dade.maxpayne.commands.models import read_model_file
from dade.maxpayne.commands.skin2glb import skin2glb
from dade.maxpayne.commands.utils import find_path
from dade.maxpayne.gltf import GLB_MAGIC

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from click.testing import CliRunner


def test_skin2glb_writes_a_rigged_character(runner: CliRunner, tmp_path: Path,
                                            make_character_database: Callable[..., Path]) -> None:
    database = make_character_database()
    out = tmp_path / 'out'
    result = runner.invoke(skin2glb, [str(database), '-o', str(out)])
    assert result.exit_code == 0, result.output
    assert 'transit_cop: 3 vertices, 2 bones, 2 clips (1 missing)' in result.output
    assert '1/1 skins converted' in result.output
    assert (out / 'transit_cop.glb').read_bytes()[:4] == GLB_MAGIC
    report = json.loads((out / 'transit_cop.json').read_text())
    assert report['skeleton'] == 'default_skeleton'
    assert report['skeleton_model'] == 'collision.kfs'
    assert report['weights'] == 'TRANSIT_COP_L0.SKD'
    assert report['missing_clips'] == ['anim/missing.kf2']
    assert report['bones'] == [{
        'name': 'Pelvis',
        'parent': ''
    }, {
        'name': 'Head',
        'parent': 'Pelvis'
    }]
    walk, stand = report['clips']
    assert walk['indices'] == ['CHARANIM_WALK', 'CHARANIM_WALK2']
    assert walk['name'] == 'walk'
    assert walk['duration'] == pytest.approx(2 / 30)
    assert stand['indices'] == ['CHARANIM_STAND']


def test_skin2glb_finds_a_second_game_skeleton(
        runner: CliRunner, tmp_path: Path, make_character_database: Callable[..., Path]) -> None:
    database = make_character_database(skeleton='male', scripted=False)
    result = runner.invoke(skin2glb, [str(database), '-o', str(tmp_path / 'out')])
    assert result.exit_code == 0, result.output
    report = json.loads((tmp_path / 'out' / 'transit_cop.json').read_text())
    assert report['skeleton_model'] == 'skeleton_male.kf2'
    assert [clip['name'] for clip in report['clips']] == ['walk']


def test_skin2glb_falls_back_when_the_skeleton_script_has_no_geometry(
        runner: CliRunner, tmp_path: Path, make_character_database: Callable[..., Path]) -> None:
    database = make_character_database()
    skeletons = database / 'skeletons'
    (skeletons / 'default_skeleton.txt').write_text('[Skeleton]\n{\n}\n')
    (skeletons / 'default_skeleton' / 'collision.kfs').rename(
        skeletons / 'default_skeleton' / 'skeleton_default_skeleton.kf2')
    result = runner.invoke(skin2glb, [str(database), '-o', str(tmp_path / 'out')])
    assert result.exit_code == 0, result.output
    report = json.loads((tmp_path / 'out' / 'transit_cop.json').read_text())
    assert report['skeleton_model'] == 'skeleton_default_skeleton.kf2'


def test_skin2glb_adds_every_clip_on_request(runner: CliRunner, tmp_path: Path,
                                             make_character_database: Callable[..., Path]) -> None:
    database = make_character_database()
    (database / 'skeletons' / 'default_skeleton' / 'anim' / 'notes.txt').write_text('')
    result = runner.invoke(skin2glb, [str(database), '-o', str(tmp_path / 'out'), '--all-clips'])
    assert result.exit_code == 0, result.output
    report = json.loads((tmp_path / 'out' / 'transit_cop.json').read_text())
    assert sorted(clip['name'] for clip in report['clips']) == ['extra', 'stand', 'walk']
    assert report['missing_clips'] == ['anim/broken.kf2', 'anim/missing.kf2']


def test_skin2glb_filters_by_skin(runner: CliRunner, tmp_path: Path,
                                  make_character_database: Callable[..., Path]) -> None:
    database = make_character_database()
    result = runner.invoke(skin2glb, [str(database), '-o', str(tmp_path), '-s', 'TRANSIT_COP'])
    assert '1/1 skins converted' in result.output
    result = runner.invoke(skin2glb, [str(database), '-o', str(tmp_path), '-s', 'nobody_here'])
    assert result.exit_code == 1
    assert 'No skin scripts found.' in result.output


def test_skin2glb_aborts_without_a_skins_directory(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(skin2glb, [str(tmp_path)])
    assert result.exit_code == 1


def test_skin2glb_skips_a_script_that_is_not_a_character(
        runner: CliRunner, tmp_path: Path, make_character_database: Callable[..., Path]) -> None:
    database = make_character_database()
    (database / 'skins' / 'notes.txt').write_text('[Properties]\nMaximumHealth = 2;\n')
    result = runner.invoke(skin2glb, [str(database), '-o', str(tmp_path / 'out')])
    assert '1/2 skins converted' in result.output


def test_skin2glb_skips_a_character_without_its_skeleton(
        runner: CliRunner, tmp_path: Path, make_character_database: Callable[..., Path]) -> None:
    database = make_character_database()
    (database / 'skeletons' / 'default_skeleton' / 'collision.kfs').unlink()
    result = runner.invoke(skin2glb, [str(database), '-o', str(tmp_path / 'out')])
    assert '0/1 skins converted' in result.output
    assert not (tmp_path / 'out').exists()


def test_skin2glb_skips_a_skeleton_that_is_not_there(
        runner: CliRunner, tmp_path: Path, make_character_database: Callable[..., Path]) -> None:
    database = make_character_database()
    script = database / 'skins' / 'transit_cop.txt'
    script.write_text(script.read_text().replace('"default_skeleton"', 'ghost'))
    result = runner.invoke(skin2glb, [str(database), '-o', str(tmp_path / 'out')])
    assert '0/1 skins converted' in result.output


def test_skin2glb_skips_a_character_without_its_directory(
        runner: CliRunner, tmp_path: Path, make_character_database: Callable[..., Path]) -> None:
    database = make_character_database()
    (database / 'skins' / 'transit_cop.txt').rename(database / 'skins' / 'other.txt')
    result = runner.invoke(skin2glb, [str(database), '-o', str(tmp_path / 'out')])
    assert '0/1 skins converted' in result.output


def test_skin2glb_skips_unreadable_weights(runner: CliRunner, tmp_path: Path,
                                           make_character_database: Callable[..., Path]) -> None:
    database = make_character_database(weights=b'\x00')
    result = runner.invoke(skin2glb, [str(database), '-o', str(tmp_path / 'out')])
    assert '0/1 skins converted' in result.output


def test_skin2glb_skips_an_unreadable_model(runner: CliRunner, tmp_path: Path,
                                            make_character_database: Callable[..., Path]) -> None:
    database = make_character_database(model=b'\x00')
    result = runner.invoke(skin2glb, [str(database), '-o', str(tmp_path / 'out')])
    assert '0/1 skins converted' in result.output


def test_skin2glb_skips_an_unreadable_skeleton(
        runner: CliRunner, tmp_path: Path, make_character_database: Callable[..., Path]) -> None:
    database = make_character_database()
    (database / 'skeletons' / 'default_skeleton' / 'collision.kfs').write_bytes(b'\x00')
    result = runner.invoke(skin2glb, [str(database), '-o', str(tmp_path / 'out')])
    assert '0/1 skins converted' in result.output


def test_skin2glb_skips_a_skin_without_faces(runner: CliRunner, tmp_path: Path,
                                             make_character_database: Callable[..., Path],
                                             make_model: Callable[..., bytes]) -> None:
    database = make_character_database(model=make_model(faces=()))
    result = runner.invoke(skin2glb, [str(database), '-o', str(tmp_path / 'out')])
    assert '0/1 skins converted' in result.output


def test_find_path_ignores_case(tmp_path: Path) -> None:
    (tmp_path / 'Skins' / 'SharedTextures').mkdir(parents=True)
    (tmp_path / 'Skins' / 'SharedTextures' / 'Face.DDS').write_bytes(b'')
    found = find_path(tmp_path / 'Skins' / 'cop', '..\\sharedtextures/./face.dds')
    assert found == tmp_path / 'Skins' / 'SharedTextures' / 'Face.DDS'
    assert find_path(tmp_path, 'skins/missing.dds') is None
    assert find_path(tmp_path, 'skins/sharedtextures/face.dds/inner') is None


def test_read_model_file_skips_a_directory_with_the_image_name(
        tmp_path: Path, make_model: Callable[..., bytes]) -> None:
    (tmp_path / 'skin' / 'textures' / 'skin.png').mkdir(parents=True)
    (tmp_path / 'sharedtextures').mkdir()
    (tmp_path / 'sharedtextures' / 'skin.png').write_bytes(b'\x89PNG')
    (tmp_path / 'skin' / 'model.kfs').write_bytes(make_model())
    model = read_model_file(tmp_path / 'skin' / 'model.kfs')
    assert model is not None
    assert [t.data for t in model.textures] == [b'\x89PNG']
