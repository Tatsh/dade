"""Tests for :mod:`dade.thps2pc.mesh`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json
import struct

import pytest

from dade.thps2pc import mesh
from dade.thps2pc.psx import Scene
from dade.thps2pc.test_utils import SectorSpec, face_record, psx_scene

if TYPE_CHECKING:
    from pathlib import Path

    from dade.thps2pc.typing import MeshManifest


def test_build_batches_groups_by_checksum(scene: Scene) -> None:
    batches = mesh.build_batches(scene, scene.texture_checksums())
    assert set(batches) == {'DEADBEEF', 'CAFEF00D'}


def test_build_batches_emits_two_triangles_per_quad(scene: Scene) -> None:
    batches = mesh.build_batches(scene, scene.texture_checksums())
    assert len(batches['CAFEF00D']) == 12
    assert len(batches['DEADBEEF']) == 6


def test_build_batches_carries_positions_and_uvs(scene: Scene) -> None:
    batches = mesh.build_batches(scene, scene.texture_checksums())
    first = batches['DEADBEEF'][1]
    assert (first.x, first.y, first.z) == (100, 0, 0)
    assert (first.u, first.v) == (1.0, 0.0)


def test_build_batches_falls_back_to_untextured_for_a_bad_index() -> None:
    record = face_record((0, 1, 2), texture_index=99, flags=0x11)
    parsed = Scene.parse(
        psx_scene(sectors=(SectorSpec(vertices=((0, 0, 0),) * 3, faces=(record,), count_b=0),)))
    assert set(mesh.build_batches(parsed, (1, 2))) == {mesh.UNTEXTURED_KEY}


def test_build_batches_skips_out_of_range_corners() -> None:
    record = face_record((0, 1, 9), flags=0x11)
    parsed = Scene.parse(
        psx_scene(sectors=(SectorSpec(vertices=((0, 0, 0),) * 3, faces=(record,), count_b=0),)))
    assert mesh.build_batches(parsed, ()) == {}


def test_pack_produces_interleaved_floats(scene: Scene) -> None:
    batches = mesh.build_batches(scene, scene.texture_checksums())
    blob, manifest = mesh.pack(batches, {'DEADBEEF'})
    total = sum(entry['vertex_count'] for entry in manifest['batches'])
    assert len(blob) == total * 5 * 4
    assert struct.unpack_from('<5f', blob, 0) == (0.0, 0.0, 0.0, 0.0, 0.0)


def test_pack_marks_unresolved_textures_as_null(scene: Scene) -> None:
    batches = mesh.build_batches(scene, scene.texture_checksums())
    _, manifest = mesh.pack(batches, {'DEADBEEF'})
    by_texture = {entry['texture'] for entry in manifest['batches']}
    assert by_texture == {'DEADBEEF', None}


def test_pack_offsets_are_contiguous(scene: Scene) -> None:
    batches = mesh.build_batches(scene, scene.texture_checksums())
    _, manifest = mesh.pack(batches, set())
    offset = 0
    for entry in manifest['batches']:
        assert entry['first_vertex'] == offset
        offset += entry['vertex_count']


def test_pack_records_the_scale(scene: Scene) -> None:
    _, manifest = mesh.pack(mesh.build_batches(scene, ()), set(), 0.5)
    assert manifest['scale'] == pytest.approx(0.5)


def test_write_manifest_uses_the_renderer_key_names(tmp_path: Path) -> None:
    manifest: MeshManifest = {
        'scale': 1.0,
        'batches': [{
            'texture': 'ABCD1234',
            'first_vertex': 0,
            'vertex_count': 3
        }]
    }
    dest = tmp_path / 'nested' / 'out.json'
    mesh.write_manifest(manifest, dest)
    payload = json.loads(dest.read_text())
    assert payload['batches'][0] == {'firstVertex': 0, 'texture': 'ABCD1234', 'vertexCount': 3}


def test_index_bitmaps_keys_on_upper_case_stems(tmp_path: Path) -> None:
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'abcd1234.bmp').write_bytes(b'BM')
    (tmp_path / 'ignore.png').write_bytes(b'')
    assert mesh.index_bitmaps((tmp_path,)) == {'ABCD1234': tmp_path / 'sub' / 'abcd1234.bmp'}


def test_index_bitmaps_ignores_missing_directories(tmp_path: Path) -> None:
    assert mesh.index_bitmaps((tmp_path / 'absent',)) == {}
