"""Tests for :mod:`dade.common.gltf`."""
from __future__ import annotations

import json
import struct

from dade.common.gltf import GLBDocument


def test_use_records_an_extension_only_once() -> None:
    document = GLBDocument()
    document.use('KHR_materials_unlit')
    document.use('KHR_materials_unlit')
    assert document.extensions_used == ['KHR_materials_unlit']


def test_finish_omits_empty_materials() -> None:
    data = GLBDocument().finish('scene')
    document = json.loads(data[20:20 + struct.unpack_from('<I', data, 12)[0]])
    assert 'materials' not in document


def test_add_image_uri_reuses_sampler() -> None:
    document = GLBDocument()

    assert document.add_image_uri('one.png', 'one') == 0
    assert document.add_image_uri('two.png', 'two') == 1
    assert len(document.samplers) == 1
    assert document.images == [{'uri': 'one.png', 'name': 'one'}, {'uri': 'two.png', 'name': 'two'}]
