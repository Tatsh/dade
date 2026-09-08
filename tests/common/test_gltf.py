"""Tests for :mod:`dade.common.gltf`."""
from __future__ import annotations

from dade.common.gltf import GLBDocument


def test_use_records_an_extension_only_once() -> None:
    document = GLBDocument()
    document.use('KHR_materials_unlit')
    document.use('KHR_materials_unlit')
    assert document.extensions_used == ['KHR_materials_unlit']
