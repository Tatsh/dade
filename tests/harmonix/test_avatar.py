from __future__ import annotations

from typing import TYPE_CHECKING, Any
import json
import struct

import numpy as np
import pytest

from dade.harmonix import avatar

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_SIZES = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}
_TYPES = {5126: '<f4', 5123: '<u2', 5125: '<u4'}


def _read_glb(path: Path) -> tuple[dict[str, Any], bytes]:
    data = path.read_bytes()
    length = struct.unpack_from('<I', data, 12)[0]
    return json.loads(data[20:20 + length]), data[28 + length:]


def _accessor(document: dict[str, Any], blob: bytes, index: int) -> np.ndarray:
    accessor = document['accessors'][index]
    view = document['bufferViews'][accessor['bufferView']]
    width = _SIZES[accessor['type']]
    values = np.frombuffer(blob, _TYPES[accessor['componentType']], accessor['count'] * width,
                           view['byteOffset'])
    return values.reshape(accessor['count'], width).astype(np.float64)


def _channel(document: dict[str, Any], blob: bytes, animation: str, node: str,
             path: str) -> tuple[np.ndarray, np.ndarray]:
    names = [entry.get('name') for entry in document['nodes']]
    clip = next(entry for entry in document['animations'] if entry['name'] == animation)
    channel = next(entry for entry in clip['channels'] if entry['target'] == {
        'node': names.index(node),
        'path': path
    })
    sampler = clip['samplers'][channel['sampler']]
    return (_accessor(document, blob,
                      sampler['input'])[:, 0], _accessor(document, blob, sampler['output']))


def test_export_default_avatar(make_avatar_tree: Callable[..., Path], tmp_path: Path) -> None:
    root = make_avatar_tree(tmp_path)
    out = avatar.export_default_avatar(root, bpm=60.0)
    assert out == root / 'freqmaker' / 'avatar_default.glb'
    document, blob = _read_glb(out)
    names = [node['name'] for node in document['nodes']]
    assert names[0] == 'avatar'
    assert document['nodes'][0]['rotation'] == pytest.approx([-(0.5 ** 0.5), 0.0, 0.0, 0.5 ** 0.5])
    assert names[1:15] == [
        'pelvis', 'torso_joint', 'torso', 'larm_u_joint', 'rarm_u_joint', 'instr_joint',
        'head_joint', 'instr_00', 'larm_u', 'larm_l', 'larm_h', 'rarm_u', 'rarm_l', 'rarm_h'
    ]
    assert names[15:] == ['skin', 'torso', 'larm_skin', 'rarm_skin']
    skin = document['skins'][0]
    assert skin['joints'] == list(range(1, 15))
    # The forearm and the hand hang from the socket, as ``ArmPart::Rebuild`` arranges them.
    assert document['nodes'][4]['children'] == [9, 10, 11]
    assert document['nodes'][10]['translation'] == pytest.approx([2.0, 0.0, 0.0])
    # The mirrored, half-turned head joint survives the decomposition.
    assert document['nodes'][7]['scale'] == pytest.approx([1.0, 1.0, -1.0])
    assert document['nodes'][7]['rotation'] == pytest.approx([0.0, 0.0, 1.0, 0.0], abs=1e-6)
    inverse = _accessor(document, blob, skin['inverseBindMatrices']).reshape(-1, 4, 4)
    assert inverse[0, 3] == pytest.approx([0.0, 0.0, -10.0, 1.0])
    assert (inverse[:, :, 3] == (0.0, 0.0, 0.0, 1.0)).all()
    lower = document['meshes'][0]['primitives']
    assert len(lower) == 1  # The hidden, missing, empty, and boneless draws are dropped.
    weights = _accessor(document, blob, lower[0]['attributes']['WEIGHTS_0'])
    joints = _accessor(document, blob, lower[0]['attributes']['JOINTS_0'])
    assert weights[0] == pytest.approx([0.5, 0.5, 0.0, 0.0])
    assert joints[0].tolist() == [0.0, 1.0, 0.0, 0.0]
    arm = document['meshes'][2]['primitives'][0]
    assert _accessor(document, blob,
                     arm['attributes']['WEIGHTS_0'])[0] == pytest.approx([0.5, 0.25, 0.25, 0.0])
    positions = _accessor(document, blob, arm['attributes']['POSITION'])
    assert positions[1] == pytest.approx([7.0, 2.0, 17.0])  # The vertex placed by its owner.
    assert [image['name'] for image in document['images']] == ['skin', 'larm_skin', 'rarm_skin']
    assert 'baseColorTexture' not in document['materials'][1]['pbrMetallicRoughness']


def test_export_default_avatar_animations(make_avatar_tree: Callable[..., Path],
                                          tmp_path: Path) -> None:
    out = avatar.export_default_avatar(make_avatar_tree(tmp_path), bpm=60.0)
    assert out is not None
    document, blob = _read_glb(out)
    assert [clip['name'] for clip in document['animations']] == ['clip', 'clip_0', 'copy']
    clip, copy = document['animations'][0], document['animations'][2]
    assert clip['samplers'] == copy['samplers']
    times, pelvis = _channel(document, blob, 'clip', 'pelvis', 'translation')
    assert times.tolist() == pytest.approx([0.0, 20 / 480, 40 / 480])
    assert pelvis[:, 2] == pytest.approx([10.0, 10.5, 11.0])
    _, torso = _channel(document, blob, 'clip', 'torso', 'rotation')
    assert (np.sum(torso[1:] * torso[:-1], axis=1) >= 0).all()
    assert np.linalg.norm(torso, axis=1) == pytest.approx(1.0)
    times, _ = _channel(document, blob, 'clip_0', 'torso', 'rotation')
    assert times[-1] == pytest.approx(60 / 480)
    for side in ('larm', 'rarm'):
        _, elbow = _channel(document, blob, 'clip', f'{side}_l', 'translation')
        _, wrist = _channel(document, blob, 'clip', f'{side}_h', 'translation')
        _, upper = _channel(document, blob, 'clip', f'{side}_u', 'rotation')
        assert np.linalg.norm(elbow, axis=1) == pytest.approx(2.0)
        assert np.linalg.norm(wrist - elbow, axis=1) == pytest.approx(2.0)
        assert np.linalg.norm(upper, axis=1) == pytest.approx(1.0)


@pytest.mark.parametrize(('hands', 'right_pole'), [(('r', 't'), False), (('t', 'r'), True)])
def test_export_default_avatar_hand_keys(make_avatar_tree: Callable[..., Path], tmp_path: Path,
                                         hands: tuple[str, str], *, right_pole: bool) -> None:
    root = make_avatar_tree(tmp_path, hands=hands, right_pole=right_pole)
    out = avatar.export_default_avatar(root)
    assert out is not None
    document, blob = _read_glb(out)
    _, elbow = _channel(document, blob, 'clip', 'rarm_l', 'translation')
    assert np.isfinite(elbow).all()


def test_export_default_avatar_without_instrument(make_avatar_tree: Callable[..., Path],
                                                  tmp_path: Path) -> None:
    root = make_avatar_tree(tmp_path, omit=frozenset({7}), hands=('t', 't'))
    out = avatar.export_default_avatar(root)
    assert out is not None
    document, blob = _read_glb(out)
    # The hand keys are taken in the scene's space, out of reach, and the forearm stretches to them.
    _, elbow = _channel(document, blob, 'clip', 'larm_l', 'translation')
    _, wrist = _channel(document, blob, 'clip', 'larm_h', 'translation')
    assert np.linalg.norm(wrist - elbow, axis=1) == pytest.approx(2.0)
    assert (np.linalg.norm(elbow, axis=1) > 2.0).all()


def test_export_default_avatar_without_sockets(make_avatar_tree: Callable[...,
                                                                          Path], tmp_path: Path,
                                               caplog: pytest.LogCaptureFixture) -> None:
    root = make_avatar_tree(tmp_path, omit=frozenset({3, 4}), incomplete=True)
    out = avatar.export_default_avatar(root)
    assert out is not None
    document, _ = _read_glb(out)
    assert document['nodes'][0]['children'] == [1, 2, 5]  # Each part hangs from the root.
    assert document['nodes'][2]['children'] == [3]  # No socket, and the arm chain is retained.
    assert 'incomplete' in caplog.text


def test_export_default_avatar_without_tracks(make_avatar_tree: Callable[..., Path],
                                              tmp_path: Path) -> None:
    root = make_avatar_tree(tmp_path, omit=frozenset({0, 1}), tracks=False)
    out = avatar.export_default_avatar(root)
    assert out is not None
    document, _ = _read_glb(out)
    assert 'animations' not in document


def test_export_default_avatar_pal_config(make_avatar_tree: Callable[..., Path],
                                          tmp_path: Path) -> None:
    root = make_avatar_tree(tmp_path, config='gen/cfg_freq2euro.txt.bin')
    assert avatar.export_default_avatar(root) is not None


@pytest.mark.parametrize('options', [{
    'scenes': False
}, {
    'base_rnd': False
}, {
    'config': 'gen/other.txt.bin'
}])
def test_export_default_avatar_nothing_to_export(make_avatar_tree: Callable[..., Path],
                                                 tmp_path: Path, options: dict[str, Any]) -> None:
    root = make_avatar_tree(tmp_path, **options)
    assert avatar.export_default_avatar(root) is None
    assert not (root / 'freqmaker' / 'avatar_default.glb').exists()


def test_export_default_avatar_missing_base(make_avatar_tree: Callable[..., Path],
                                            tmp_path: Path) -> None:
    root = make_avatar_tree(tmp_path)
    for path in (root / 'freqmaker' / 'fullfreq').iterdir():
        path.unlink()
    (root / 'freqmaker' / 'fullfreq').rmdir()
    assert avatar.export_default_avatar(root) is None


def test_export_default_avatar_config_without_db(make_dtb: Callable[..., bytes],
                                                 tmp_path: Path) -> None:
    (tmp_path / 'gen').mkdir()
    (tmp_path / 'gen' / 'freq2_config.txt.bin').write_bytes(make_dtb([['version', 1]]))
    assert avatar.export_default_avatar(tmp_path) is None
