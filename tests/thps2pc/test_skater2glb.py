"""CLI tests for ``dade thps2pc skater2glb``."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json
import struct

from dade.thps2pc.commands.skater2glb import skater2glb
from dade.thps2pc.test_utils import SectorSpec, psx_scene, skater_clips

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner

_ZERO = b'\x0f'


def _header(prefix: str, *parts: str) -> str:
    return ''.join(f'#define {prefix.upper()}PART_{prefix.upper()}_{part.upper()}\t\t{index}\n'
                   for index, part in enumerate(parts))


def _model(*, parents: tuple[int, ...] = (0, 0), chunk: tuple[int, bytes] | None = None) -> bytes:
    hierarchy = (0x52454948, struct.pack(f'<{len(parents)}H', *parents))
    chunks = [hierarchy] if chunk is None else [hierarchy, chunk]
    return psx_scene(sectors=tuple(SectorSpec(((0, 0, 0),), (), 0) for _ in parents), chunks=chunks)


def _clips(count: int = 1) -> tuple[int, bytes]:
    return 0x2C, skater_clips(tuple((1, (_ZERO,) * 12) for _ in range(count)))


def _pose() -> tuple[int, bytes]:
    frame = struct.pack('<12h', 4096, 0, 0, 0, 4096, 0, 0, 0, 4096, 0, 0, 0) * 2
    return 0x2A, struct.pack('<III', 1, 12, 1) + frame


def _write(directory: Path, stem: str, model: bytes, header: str | None) -> Path:
    path = directory / f'{stem}.PSX'
    path.write_bytes(model)
    if header is not None:
        (directory / f'{stem}.PSH').write_text(header)
    return path


def _animations(path: Path) -> list[str]:
    data = path.read_bytes()
    document = json.loads(data[20:20 + struct.unpack_from('<I', data, 12)[0]])
    return [animation['name'] for animation in document.get('animations', [])]


def test_skater2glb_converts_a_directory(runner: CliRunner, tmp_path: Path) -> None:
    data = tmp_path / 'data'
    data.mkdir()
    _write(data, 'SK2ANIM', _model(chunk=_clips(2)), _header('sk2anim', 'pelvis', 'head'))
    _write(data, 'HAWK', _model(chunk=_clips()), _header('hawk', 'pelvis', 'head'))
    _write(data, 'HAWK2', _model(chunk=_pose()), _header('hawk2', 'head', 'pelvis'))
    _write(data, 'BUS', _model(chunk=_pose()), _header('bus', 'body', 'wheel'))
    _write(data, 'EMPTY', _model(), _header('empty', 'pelvis', 'head'))
    _write(data, 'LEVEL', psx_scene(sectors=(SectorSpec(((0, 0, 0),), (), 0),)), '')
    _write(data, 'SHORT', _model(chunk=_clips()), _header('short', 'pelvis'))
    _write(data, 'LOOSE', _model(chunk=_clips()), None)
    out = tmp_path / 'out'
    result = runner.invoke(skater2glb, [str(data), '-o', str(out)])
    assert result.exit_code == 0, result.output
    assert 'Wrote 5 GLB files.' in result.output
    assert _animations(out / 'HAWK.glb') == ['clip_000']
    assert _animations(out / 'HAWK2.glb') == ['clip_000', 'clip_001']
    assert _animations(out / 'BUS.glb') == ['pose_000']
    assert _animations(out / 'SK2ANIM.glb') == ['clip_000', 'clip_001']
    assert _animations(out / 'EMPTY.glb') == ['clip_000', 'clip_001']
    assert not (out / 'LOOSE.glb').exists()
    assert not (out / 'LEVEL.glb').exists()
    assert not (out / 'SHORT.glb').exists()


def test_skater2glb_reports_a_model_without_a_header(runner: CliRunner, tmp_path: Path) -> None:
    model = _write(tmp_path, 'LOOSE', _model(chunk=_clips()), None)
    result = runner.invoke(skater2glb, [str(model), '-o', str(tmp_path / 'out')])
    assert result.exit_code == 0
    assert 'no .PSH header beside it' in result.output
    assert 'Wrote 0 GLB files.' in result.output


def test_skater2glb_uses_the_given_clips(runner: CliRunner, tmp_path: Path) -> None:
    shared = _write(tmp_path, 'MOVES', _model(chunk=_clips(3)), _header('moves', 'pelvis', 'head'))
    model = _write(tmp_path, 'HAWK2', _model(chunk=_pose()), _header('hawk2', 'pelvis', 'head'))
    out = tmp_path / 'out'
    result = runner.invoke(skater2glb, [str(model), '-o', str(out), '--clips', str(shared)])
    assert result.exit_code == 0, result.output
    assert len(_animations(out / 'HAWK2.glb')) == 3


def test_skater2glb_keeps_poses_when_the_shared_clips_are_unusable(runner: CliRunner,
                                                                   tmp_path: Path) -> None:
    model = _write(tmp_path, 'HAWK2', _model(chunk=_pose()), _header('hawk2', 'pelvis', 'head'))
    out = tmp_path / 'out'
    _write(tmp_path, 'SK2ANIM', _model(chunk=_clips()), None)
    assert runner.invoke(skater2glb, [str(model), '-o', str(out)]).exit_code == 0
    assert _animations(out / 'HAWK2.glb') == ['pose_000']
    empty = _write(tmp_path, 'EMPTY', _model(), _header('empty', 'pelvis', 'head'))
    result = runner.invoke(skater2glb, [str(empty), '-o', str(out)])
    assert result.exit_code == 0
    assert 'Wrote 0 GLB files.' in result.output
    (tmp_path / 'SK2ANIM.PSX').write_bytes(psx_scene(sectors=(SectorSpec(((0, 0, 0),), (), 0),)))
    (tmp_path / 'SK2ANIM.PSH').write_text(_header('sk2anim', 'pelvis'))
    assert runner.invoke(skater2glb, [str(model), '-o', str(out)]).exit_code == 0
    assert _animations(out / 'HAWK2.glb') == ['pose_000']


def test_skater2glb_keeps_several_poses_and_reads_header_parents(runner: CliRunner,
                                                                 tmp_path: Path) -> None:
    frame = struct.pack('<12h', 4096, 0, 0, 0, 4096, 0, 0, 0, 4096, 0, 0, 0) * 2
    poses = (0x2A, struct.pack('<5I', 2, 20, 1, 20 + len(frame), 1) + frame * 2)
    model = psx_scene(sectors=(SectorSpec(((0, 0, 0),), (), 0), SectorSpec(((0, 0, 0),), (), 0)),
                      chunks=(poses,))
    header = ('#define RASTAPART_RASTA_PELVIS\t\t0\n//   parent: Scene Root\n'
              '#define RASTAPART_RASTA_HEAD\t\t1\n//   parent: rasta_pelvis\n')
    _write(tmp_path, 'SK2ANIM', _model(chunk=_clips(3)), _header('sk2anim', 'pelvis', 'head'))
    path = _write(tmp_path, 'RASTA', model, header)
    out = tmp_path / 'out'
    assert runner.invoke(skater2glb, [str(path), '-o', str(out)]).exit_code == 0
    assert _animations(out / 'RASTA.glb') == ['pose_000', 'pose_001']
