from __future__ import annotations

from typing import TYPE_CHECKING, Any
import logging
import struct

import pytest

from dade.monopoly08.pipeline import StepStats, run

from .conftest import VgmPlan

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from .conftest import Builder

_GPU_DXT1 = 0x12
_WHITE_DXT1 = struct.pack('<HHI', 0xFFFF, 0x0000, 0)
_VERTEX_PAD = b'\x7f\x7f\xff\xff'
_MESH_BLOCK = (b''.join(
    struct.pack('>3f', *v) + _VERTEX_PAD
    for v in ((-1.5, 0.5, -2.5), (1.5, -0.5, -1.25), (0.5, 1.5, -3.0),
              (-0.5, -1.5, -2.0))) + struct.pack('>8H', 0, 1, 2, 3, 0xFFFF, 3, 2, 1))
_PLACE_BIN = (b'\x66\x60\x00\x01' + bytes(0x1C) + struct.pack('>2f', 1.0, 2.0))


def test_run_minimal_disc(make_big: Builder, serial_pool: Any, tmp_path: Path) -> None:
    root = tmp_path / 'disc'
    root.mkdir()
    (root / 'audio.big').write_bytes(make_big((('notes.txt', b'hello'),)))
    stats = run(root)
    assert stats['archives'] == StepStats(1, 0)
    assert stats['packs'] == StepStats(0, 0)
    assert stats['audio'] == StepStats(0, 0)
    assert stats['textures'] == StepStats(0, 0)
    assert (root / 'audio' / 'notes.txt').read_bytes() == b'hello'


def test_run_skips_movie_archives(make_big: Builder, caplog: pytest.LogCaptureFixture,
                                  serial_pool: Any, tmp_path: Path) -> None:
    root = tmp_path / 'disc'
    root.mkdir()
    for name in ('audio.big', 'movies.big'):
        (root / name).write_bytes(make_big((('notes.txt', b'hello'),)))
    with caplog.at_level(logging.INFO, logger='dade.monopoly08.pipeline'):
        stats = run(root, no_movies=True, workers=2)
    assert stats['archives'] == StepStats(1, 0)
    assert 'Skipping movie archive' in caplog.text
    assert not (root / 'movies').exists()


def test_run_converts_every_asset_group(caplog: pytest.LogCaptureFixture, fake_vgmstream: Any,
                                        make_big: Builder, make_mesh: Builder, make_rpk: Builder,
                                        make_schl: Builder, make_xmap: Builder, serial_pool: Any,
                                        tmp_path: Path) -> None:
    fake_vgmstream(VgmPlan(output=False))
    root = tmp_path / 'disc'
    root.mkdir()
    (root / 'default.xex').write_bytes(b'')
    (root / 'audio.big').write_bytes(make_big((('notes.txt', b'hello'),)))
    (root / 'ui.rpk').write_bytes(make_rpk(((0, 0, b'WXYZ\x00\x00\x00\x00'),)))
    (root / 'broken.rpk').write_bytes(b'NOPE' + bytes(12))
    (root / 'tex.xmap').write_bytes(make_xmap(4, 4, _GPU_DXT1, _WHITE_DXT1))
    (root / 'bad.xmap').write_bytes(b'NOPE' + bytes(60))
    (root / 'model.npm7').write_bytes(make_mesh(blocks=(_MESH_BLOCK,)))
    (root / 'place.bin').write_bytes(_PLACE_BIN)
    (root / 'bank.sdt').write_bytes(make_schl([b'first-unit', b'second-unit']))
    (root / 'bank_0000.wav').write_bytes(b'\x00' * 100)  # Already decoded, so it is skipped.
    with caplog.at_level(logging.WARNING, logger='dade.monopoly08.pipeline'):
        stats = run(root, workers=2)
    assert stats['archives'] == StepStats(1, 0)
    assert stats['packs'] == StepStats(1, 1)
    assert stats['audio'] == StepStats(1, 1)
    assert stats['textures'] == StepStats(1, 1)
    assert stats['meshes'] == StepStats(1, 0)
    assert stats['structured'] == StepStats(1, 0)
    assert (root / 'tex.png').is_file()
    assert (root / 'model.obj').is_file()
    assert (root / 'place.json').is_file()
    assert (root / 'ui' / '_manifest.tsv').is_file()
    assert 'Failed `' in caplog.text
    assert 'Audio stream failed' in caplog.text


def test_run_rejects_an_unrecognised_root(serial_pool: Any, tmp_path: Path) -> None:
    root = tmp_path / 'disc'
    root.mkdir()
    (root / 'readme.txt').write_bytes(b'')
    with pytest.raises(ValueError, match='no known platform marker'):
        run(root)


@pytest.mark.parametrize(('ok', 'fail'), [(3, 0), (0, 2)])
def test_step_stats_fields(ok: int, fail: int) -> None:
    stats = StepStats(ok, fail)
    assert (stats.ok, stats.fail) == (ok, fail)


def test_run_reports_every_step(make_big: Builder, serial_pool: Any, tmp_path: Path) -> None:
    root = tmp_path / 'disc'
    root.mkdir()
    (root / 'audio.big').write_bytes(make_big((('notes.txt', b'hello'),)))
    expected: Sequence[str] = ('archives', 'packs', 'audio', 'textures', 'meshes', 'structured')
    assert list(run(root)) == list(expected)
