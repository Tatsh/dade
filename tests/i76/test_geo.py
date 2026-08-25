"""Tests for :py:mod:`dade.i76.geo`."""
from __future__ import annotations

import pytest

from dade.i76.geo import parse


def test_parse_vertex_positions(geo_mesh: bytes) -> None:
    model = parse(geo_mesh)
    assert model is not None
    assert model.vertices[0] == (0.0, 0.0, 0.0)
    assert model.vertices[4] == (4.0, 8.0, 12.0)


def test_parse_face_count(geo_mesh: bytes) -> None:
    model = parse(geo_mesh)
    assert model is not None
    assert model.face_count == 2
    assert len(model.faces) == 2


def test_parse_face_indices(geo_mesh: bytes) -> None:
    model = parse(geo_mesh)
    assert model is not None
    assert model.faces == ((0, 1, 2, 3), (0, 1, 2, 3))


@pytest.mark.parametrize('data', [b'', b'XXXX', b'GEO.' + bytes(64)])
def test_parse_rejects_bad_magic(data: bytes) -> None:
    assert parse(data) is None
