from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

from dade.common.exceptions import InvalidFormatError
from dade.harmonix.rnd import read_mesh, read_trans_anim

if TYPE_CHECKING:
    from collections.abc import Callable

_IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)


def test_read_mesh_rigid(make_v14_mesh: Callable[..., bytes]) -> None:
    mesh = read_mesh(
        make_v14_mesh(handles=('child.mesh',), draws=('lod.mesh',), owner='parent.mesh'))
    assert mesh.transform.revision == 0
    assert mesh.transform.local == _IDENTITY
    assert mesh.transform.children == ('child.mesh',)
    assert mesh.transform.billboard == 0
    assert mesh.showing
    assert mesh.draws == ('lod.mesh',)
    assert mesh.material == 'ship.mat'
    assert mesh.transform_owner == 'parent.mesh'
    assert mesh.vertices[1].position == (1.0, 2.0, 3.0)
    assert mesh.vertices[1].normal == (0.0, 1.0, 0.0)
    assert mesh.vertices[2].uv == (0.5, 0.25)
    assert mesh.faces == ((0, 1, 2),)
    assert mesh.edges == ((0, 1),)
    assert mesh.bones is None


@pytest.mark.parametrize('transform_version', [1, 3, 5])
def test_read_mesh_skinned(make_v14_mesh: Callable[..., bytes], transform_version: int) -> None:
    bind = (*_IDENTITY[:9], 1.0, 2.0, 3.0)
    mesh = read_mesh(
        make_v14_mesh(transform_version=transform_version,
                      weights=(0.25, 0.5),
                      bones=('a.mesh', 'b.mesh', bind, _IDENTITY)))
    assert mesh.transform.revision == transform_version
    assert mesh.vertices[0].weights == (0.25, 0.5)
    assert mesh.bones is not None
    assert mesh.bones.names == ('a.mesh', 'b.mesh')
    assert mesh.bones.binds == (bind, _IDENTITY)


@pytest.mark.parametrize(('data', 'message'), [
    (struct.pack('<I', 10), 'revision 10'),
    (struct.pack('<II', 14, 0), 'Truncated'),
    (struct.pack('<II', 14, 0) + bytes(96) + struct.pack('<II', 1, 0x10000), 'string length'),
])
def test_read_mesh_rejects(data: bytes, message: str) -> None:
    with pytest.raises(InvalidFormatError, match=message):
        read_mesh(data)


def test_read_mesh_rejects_trailing_bytes(make_v14_mesh: Callable[..., bytes]) -> None:
    with pytest.raises(InvalidFormatError, match='1 trailing bytes'):
        read_mesh(make_v14_mesh() + b'\0')


def test_read_trans_anim(make_trans_anim: Callable[..., bytes]) -> None:
    anim = read_trans_anim(
        make_trans_anim(rotations=(((0.0, 0.0, 0.0, 1.0), 2.0),),
                        translations=(((1.0, 2.0, 3.0), 4.0),),
                        filters=((0, bytes(8)), (1, bytes(9)), (4, bytes(12))),
                        translation_interpolation=1))
    assert [item.type for item in anim.filters] == [0, 1, 4]
    assert anim.anims == ('other.tnm',)
    assert anim.showing
    assert anim.draws == ()
    assert anim.target == 'bone.mesh'
    assert anim.rotation_keys[0].value == (0.0, 0.0, 0.0, 1.0)
    assert anim.rotation_keys[0].frame == pytest.approx(2.0)
    assert anim.translation_keys[0].value == (1.0, 2.0, 3.0)
    assert anim.frames_owner == 'owner.tnm'
    assert anim.translation_interpolation == 1
    assert anim.repeat_translation
    assert anim.scale_keys[0].value == (1.0, 1.0, 1.0)
    assert anim.scale_interpolation == 7
    assert not anim.follow_path


def test_read_trans_anim_rejects_revision(make_trans_anim: Callable[..., bytes]) -> None:
    with pytest.raises(InvalidFormatError, match='revision 2'):
        read_trans_anim(make_trans_anim(revision=2))


def test_read_trans_anim_rejects_filter(make_trans_anim: Callable[..., bytes]) -> None:
    with pytest.raises(InvalidFormatError, match='filter type 9'):
        read_trans_anim(make_trans_anim(filters=((9, b''),)))
