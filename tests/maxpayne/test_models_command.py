"""Tests for finding and reading the models a level's NPCs and pickups are drawn with."""
from __future__ import annotations

from typing import TYPE_CHECKING

from dade.maxpayne.commands.models import load_models
from dade.maxpayne.ldb import read_level

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _database(root: Path,
              model: bytes,
              *,
              textures: bool = True,
              script: str | None = None,
              image: bytes = b'\x89PNGfake') -> Path:
    """Lay out a game database holding one skin and one pickup."""
    skin = root / 'skins' / 'transit_cop'
    skin.mkdir(parents=True)
    (skin / 'transit_cop_l0.kfs').write_bytes(model)
    (skin / 'transit_cop_l1.kfs').write_bytes(model)
    shared = root / 'skins' / 'sharedtextures'
    shared.mkdir(parents=True)
    if textures:
        (shared / 'skin.png').write_bytes(image)
    items = root / 'level_items'
    (items / 'ammo_ingram').mkdir(parents=True)
    (items / 'ammo_ingram' / 'ammo_ingram_l0.kf2').write_bytes(model)
    if script is not None:
        (items / 'ammo_ingram.txt').write_text(script)
    return root


def test_load_models_finds_a_skin_and_a_pickup(tmp_path: Path, make_ldb: Callable[..., bytes],
                                               make_model: Callable[..., bytes]) -> None:
    root = _database(tmp_path, make_model(), script='[LOD]\nExportData = ammo_ingram_l0.kf2;\n')
    level = read_level(make_ldb())
    models = load_models(root, level)
    assert sorted(models) == ['character:transit_cop', 'item:ammo_ingram']
    assert models['character:transit_cop'].meshes[0].faces


def test_load_models_reads_the_images_along_the_search_path(
        tmp_path: Path, make_ldb: Callable[..., bytes], make_model: Callable[..., bytes]) -> None:
    # The model looks in its own `textures` first and the shared directory beside it second.
    root = _database(tmp_path, make_model())
    model = load_models(root, read_level(make_ldb()))['character:transit_cop']
    assert [t.path for t in model.textures] == ['skin.png']


def test_load_models_tolerates_a_missing_image(tmp_path: Path, make_ldb: Callable[..., bytes],
                                               make_model: Callable[..., bytes]) -> None:
    root = _database(tmp_path, make_model(), textures=False)
    assert load_models(root, read_level(make_ldb()))['character:transit_cop'].textures == ()


def test_load_models_prefers_the_nearest_level_of_detail(tmp_path: Path, make_ldb: Callable[...,
                                                                                            bytes],
                                                         make_model: Callable[..., bytes]) -> None:
    root = _database(tmp_path, make_model())
    (root / 'skins' / 'transit_cop' / 'transit_cop_l0.kfs').write_bytes(make_model(name='near'))
    assert load_models(root,
                       read_level(make_ldb()))['character:transit_cop'].meshes[0].name == 'near'


def test_load_models_falls_back_when_no_lod_zero_exists(tmp_path: Path, make_ldb: Callable[...,
                                                                                           bytes],
                                                        make_model: Callable[..., bytes]) -> None:
    root = _database(tmp_path, make_model())
    (root / 'skins' / 'transit_cop' / 'transit_cop_l0.kfs').unlink()
    assert 'character:transit_cop' in load_models(root, read_level(make_ldb()))


def test_load_models_skips_a_skin_with_no_model(tmp_path: Path, make_ldb: Callable[..., bytes],
                                                make_model: Callable[..., bytes]) -> None:
    root = _database(tmp_path, make_model())
    for path in (root / 'skins' / 'transit_cop').iterdir():
        path.unlink()
    assert 'character:transit_cop' not in load_models(root, read_level(make_ldb()))


def test_load_models_skips_a_missing_directory(tmp_path: Path, make_ldb: Callable[...,
                                                                                  bytes]) -> None:
    assert load_models(tmp_path, read_level(make_ldb())) == {}


def test_load_models_skips_a_pickup_whose_script_names_nothing(
        tmp_path: Path, make_ldb: Callable[..., bytes], make_model: Callable[..., bytes]) -> None:
    root = _database(tmp_path, make_model(), script='[Properties]\nTriggerRadius = 1;\n')
    assert 'item:ammo_ingram' not in load_models(root, read_level(make_ldb()))


def test_load_models_skips_a_pickup_whose_model_is_absent(tmp_path: Path, make_ldb: Callable[...,
                                                                                             bytes],
                                                          make_model: Callable[..., bytes]) -> None:
    root = _database(tmp_path, make_model(), script='ExportData = gone.kf2;\n')
    assert 'item:ammo_ingram' not in load_models(root, read_level(make_ldb()))


def test_load_models_skips_a_model_that_will_not_read(tmp_path: Path, make_ldb: Callable[...,
                                                                                         bytes],
                                                      make_model: Callable[..., bytes]) -> None:
    root = _database(tmp_path, make_model())
    (root / 'skins' / 'transit_cop' / 'transit_cop_l0.kfs').write_bytes(b'not a model')
    (root / 'skins' / 'transit_cop' / 'transit_cop_l1.kfs').unlink()
    assert 'character:transit_cop' not in load_models(root, read_level(make_ldb()))
