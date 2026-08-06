"""Tests for :mod:`destin.marmalade.model`."""
from __future__ import annotations

from destin.marmalade.model import decode_model
from destin.marmalade.test_utils import build_model
import pytest


def test_decode_geometry() -> None:
    verts = [(0, 0, 0), (10, 0, 0), (0, 10, 0)]
    tris = [(0, 1, 2)]
    model = decode_model(build_model(verts, tris))
    assert model.vertices == verts
    assert model.triangles == tris


def test_degenerate_triangle_dropped() -> None:
    # A triangle with two shared indices has zero area and must be filtered out.
    verts = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    model = decode_model(build_model(verts, [(0, 0, 1)]))
    assert model.triangles == []


def test_to_obj() -> None:
    obj = decode_model(build_model([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])).to_obj()
    assert 'v 0 0 0' in obj
    assert 'f 1 2 3' in obj


def test_decode_uvs() -> None:
    verts = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    model = decode_model(build_model(verts, [(0, 1, 2)], uvs=[(4096, 0), (0, 4096), (2048, 2048)]))
    assert model.uvs == [(1.0, 0.0), (0.0, 1.0), (0.5, 0.5)]


def test_to_obj_with_uvs_emits_texture_indices() -> None:
    verts = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    obj = decode_model(build_model(verts, [(0, 1, 2)], uvs=[(0, 0)] * 3)).to_obj()
    assert 'vt 0.00000 0.00000' in obj
    assert 'f 1/1 2/2 3/3' in obj


def test_missing_block_raises() -> None:
    with pytest.raises(ValueError, match=r'Verts or GLTriList block\.$'):
        decode_model(b'\x00' * 64)
