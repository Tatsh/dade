"""Tests for :py:mod:`destin.i76.i82_objects`."""
from __future__ import annotations

from destin.i76.i82_objects import (
    chassis_name,
    geometry_files,
    mesh_textures,
    placement_refs,
    stock_paint,
    wheel_meshes,
)
import pytest


def test_placement_refs_static(msa_world: bytes) -> None:
    assert placement_refs(msa_world, '.stf') == ('crate.stf', 'tower.stf')


def test_placement_refs_vehicles(msa_world: bytes) -> None:
    assert placement_refs(msa_world, '.vdf') == ('car.vdf',)


def test_placement_refs_are_unique_and_sorted() -> None:
    world = b'Object_Header {\nFile: B.STF\n}\nObject_Header {\nFile: a.stf\n}\n'
    assert placement_refs(world, '.stf') == ('a.stf', 'b.stf')


def test_placement_refs_without_matches(msa_world: bytes) -> None:
    assert placement_refs(msa_world, '.xyz') == ()


def test_geometry_files() -> None:
    assert geometry_files('Geometry_Files {\n  body.six\n  lod.six\n}') == ('body.six', 'lod.six')


def test_geometry_files_without_block() -> None:
    assert geometry_files('nothing here') == ()


def test_wheel_meshes() -> None:
    assert wheel_meshes('Wheels {\n  wheel.six\n}') == ('wheel.six',)


def test_wheel_meshes_without_block() -> None:
    assert wheel_meshes('nothing here') == ()


@pytest.mark.parametrize(('text', 'expected'), [('Chassis = body.cdf', 'body.cdf'),
                                                ('Chassis = BODY', 'body.cdf'),
                                                ('chassis=Body.CDF', 'body.cdf')])
def test_chassis_name(text: str, expected: str) -> None:
    assert chassis_name(text) == expected


def test_chassis_name_absent() -> None:
    assert chassis_name('no chassis line') is None


def test_stock_paint() -> None:
    assert stock_paint('Stock_Paint = Red.TGA') == 'red.tga'


def test_stock_paint_absent() -> None:
    assert stock_paint('no paint line') is None


def test_mesh_textures_are_unique_and_sorted() -> None:
    assert mesh_textures(b'\x00WALL.BMP\x00body.tga\x00wall.bmp\x00') == ('body.tga', 'wall.bmp')


def test_mesh_textures_without_matches() -> None:
    assert mesh_textures(bytes(32)) == ()
