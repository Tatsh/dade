"""Tests for :mod:`destin.thps2pc.analysis`."""
from __future__ import annotations

from destin.thps2pc import analysis
from destin.thps2pc.psx import Scene
from destin.thps2pc.test_utils import SectorSpec, psx_scene


def test_sector_bounds_computes_a_centroid_and_extent(scene: Scene) -> None:
    bounds = analysis.sector_bounds(scene)
    assert len(bounds) == 2
    assert bounds[0].vertex_count == 4
    assert bounds[0].extent == (100, 0, 100)
    assert bounds[0].centroid == (50, 0, 50)


def test_sector_bounds_reports_zeroes_for_an_empty_sector() -> None:
    parsed = Scene.parse(psx_scene(sectors=(SectorSpec(vertices=(), faces=(), count_b=0),)))
    assert analysis.sector_bounds(parsed)[0] == analysis.SectorBounds((0, 0, 0), (0, 0, 0), 0)


def test_describe_reports_the_table_sizes(scene: Scene) -> None:
    report = '\n'.join(analysis.describe(scene))
    assert 'numMeshSections=2 numSectors=2' in report


def test_describe_includes_every_section(scene: Scene) -> None:
    report = '\n'.join(analysis.describe(scene))
    for heading in ('Are sector centroids near the origin', 'Descriptor[i] against the centroid',
                    'Does a descriptor position equal', 'flags_18 value distribution',
                    'flags_1a value distribution', 'bytes_20 distribution', '=== CHUNK LIST ==='):
        assert heading in report


def test_describe_lists_the_chunk_list(scene: Scene) -> None:
    report = '\n'.join(analysis.describe(scene))
    assert 'id=0x52454948' in report
    assert 'id=-1' in report


def test_describe_counts_local_looking_sectors(scene: Scene) -> None:
    report = '\n'.join(analysis.describe(scene))
    assert f'|centroid| < {analysis.LOCAL_THRESHOLD} on all axes: 2/2' in report


def test_describe_handles_a_scene_without_sectors() -> None:
    parsed = Scene.parse(psx_scene())
    report = '\n'.join(analysis.describe(parsed))
    assert 'numMeshSections=0 numSectors=0' in report
    assert 'median' not in report
