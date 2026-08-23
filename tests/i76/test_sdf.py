"""Tests for :py:mod:`destin.i76.sdf`."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from destin.i76.sdf import (
    apply_transform,
    assemble,
    encode_obj,
    parse_sgeo,
    world_transform,
    write_obj,
)
from destin.i76.typing import Mesh

if TYPE_CHECKING:
    from pathlib import Path

_IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


def test_parse_sgeo_names_and_parents(sdf_model: bytes) -> None:
    parts = parse_sgeo(sdf_model)
    assert [(p.name, p.parent) for p in parts] == [('root', ''), ('child', 'root')]


def test_parse_sgeo_transforms(sdf_model: bytes) -> None:
    parts = parse_sgeo(sdf_model)
    assert parts[0].position == (1.0, 0.0, 0.0)
    assert parts[1].rotation == _IDENTITY


def test_parse_sgeo_without_chunk() -> None:
    assert parse_sgeo(b'no such chunk here') == ()


def test_apply_transform_identity() -> None:
    assert apply_transform(_IDENTITY, (0.0, 0.0, 0.0), (1.0, 2.0, 3.0)) == (1.0, 2.0, 3.0)


def test_apply_transform_translates() -> None:
    assert apply_transform(_IDENTITY, (1.0, 2.0, 3.0), (4.0, 5.0, 6.0)) == (5.0, 7.0, 9.0)


def test_world_transform_composes_parent(sdf_model: bytes) -> None:
    parts = {part.name: part for part in parse_sgeo(sdf_model)}
    _, position = world_transform(parts, 'child', {})
    # The child sits at x=2 under a root at x=1.
    assert position == (3.0, 0.0, 0.0)


def test_world_transform_uses_cache(sdf_model: bytes) -> None:
    parts = {part.name: part for part in parse_sgeo(sdf_model)}
    cache: dict[str, tuple[tuple[float, ...], tuple[float, float, float]]] = {}
    first = world_transform(parts, 'child', cache)
    assert 'child' in cache
    assert world_transform(parts, 'child', cache) == first


def test_assemble_skips_missing_geometry(sdf_model: bytes) -> None:
    mesh = assemble(sdf_model, lambda _: None)
    assert mesh.vertices == ()
    assert mesh.triangles == ()


def test_assemble_skips_geometry_that_cannot_be_parsed(sdf_model: bytes) -> None:
    assert assemble(sdf_model, lambda _: b'XXXX' + bytes(64)).vertices == ()


def test_assemble_triangulates_as_fans(sdf_model: bytes, geo_mesh: bytes) -> None:
    mesh = assemble(sdf_model, lambda _: geo_mesh)
    # Two parts, each five vertices; each quad becomes two triangles, two quads per part.
    assert len(mesh.vertices) == 10
    assert len(mesh.triangles) == 8
    assert mesh.triangles[0] == (0, 1, 2)
    assert mesh.triangles[1] == (0, 2, 3)


def test_assemble_offsets_indices_per_part(sdf_model: bytes, geo_mesh: bytes) -> None:
    mesh = assemble(sdf_model, lambda _: geo_mesh)
    # The second part's faces index into its own block of vertices.
    assert mesh.triangles[4] == (5, 6, 7)


def test_assemble_applies_world_transform(sdf_model: bytes, geo_mesh: bytes) -> None:
    mesh = assemble(sdf_model, lambda _: geo_mesh)
    assert mesh.vertices[0] == (1.0, 0.0, 0.0)
    assert mesh.vertices[5] == (3.0, 0.0, 0.0)


def test_write_obj(tmp_path: Path, sdf_model: bytes, geo_mesh: bytes) -> None:
    out = tmp_path / 'm.obj'
    write_obj(assemble(sdf_model, lambda _: geo_mesh), out, name='m')
    lines = out.read_text().splitlines()
    assert lines[0] == 'o m'
    assert lines[1] == 'v 1.000000 0.000000 0.000000'
    assert sum(1 for line in lines if line.startswith('v ')) == 10
    assert sum(1 for line in lines if line.startswith('f ')) == 8


def test_write_obj_indices_are_one_based(tmp_path: Path, sdf_model: bytes, geo_mesh: bytes) -> None:
    out = tmp_path / 'm.obj'
    write_obj(assemble(sdf_model, lambda _: geo_mesh), out)
    assert 'f 1 2 3' in out.read_text().splitlines()


@pytest.mark.parametrize('name', ['model', 'custom'])
def test_write_obj_object_name(tmp_path: Path, sdf_model: bytes, geo_mesh: bytes,
                               name: str) -> None:
    out = tmp_path / 'm.obj'
    write_obj(assemble(sdf_model, lambda _: geo_mesh), out, name=name)
    assert out.read_text().startswith(f'o {name}\n')


def test_encode_obj_is_pure(sdf_model: bytes, geo_mesh: bytes) -> None:
    text = encode_obj(assemble(sdf_model, lambda _: geo_mesh), name='m')
    assert text.startswith('o m\n')
    assert text.endswith('\n')


def test_encode_obj_matches_write_obj(tmp_path: Path, sdf_model: bytes, geo_mesh: bytes) -> None:
    mesh = assemble(sdf_model, lambda _: geo_mesh)
    write_obj(mesh, out := tmp_path / 'm.obj', name='m')
    assert out.read_text() == encode_obj(mesh, name='m')


def test_encode_obj_empty_mesh() -> None:
    assert encode_obj(Mesh((), ())) == 'o model\n'
