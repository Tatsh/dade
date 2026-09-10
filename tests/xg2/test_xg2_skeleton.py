"""Tests for :mod:`dade.xg2.skeleton`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import runpy
import struct

import pytest

from dade.common.exceptions import SelfCheckFailed
from dade.xg2.skeleton import (
    BONE_RECORD_SIZE,
    SKELETON_MAGIC,
    SKELETON_POINTER,
    Bone,
    Skeleton,
    demo,
    parse_skeleton,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

_SEGMENT_5 = 0x05000000


def _demo_skeleton(*,
                   count: int = 27,
                   root_dof: int = 6,
                   first_name: str = 'lhipjoint',
                   first_dof: int = 0,
                   extra_dof: int = 61) -> Skeleton:
    first = Bone(first_name, -1, first_dof, root_dof, (0.0, 0.0, 0.0), ())
    rest = [
        Bone(f'b{i}', 0, extra_dof if i == 0 else 0, 0, (0.0, 0.0, 0.0), ())
        for i in range(count - 1)
    ]
    return Skeleton(root_dof, [first, *rest])


def _model(bones: list[tuple[str, int, int]],
           *,
           root_dof: int = 6,
           magic: bytes = SKELETON_MAGIC) -> bytes:
    """
    Build a rider model carrying one skeleton.

    Returns
    -------
    bytes
        A payload whose header points at the skeleton the way a real rider's does.
    """
    header = bytearray(0x20)
    records = bytearray(magic + struct.pack('>2H', len(bones), root_dof))
    records += bytes(BONE_RECORD_SIZE - len(records))
    for _, parent, dof in bones:
        record = bytearray(BONE_RECORD_SIZE)
        struct.pack_into('>h', record, 0, parent)
        record[2] = dof
        records += record
    names = b''.join(name.encode() + b'\x00' for name, _, _ in bones)
    struct.pack_into('<I', header, SKELETON_POINTER, _SEGMENT_5 | len(header))
    return bytes(header + records + names)


_SIMPLE = [('lhipjoint', -1, 0), ('lfemur', 0, 3), ('ltibia', 1, 1)]


def test_parse_skeleton_reads_the_bones() -> None:
    skeleton = parse_skeleton(_model(_SIMPLE))
    assert skeleton is not None
    assert [bone.name for bone in skeleton.bones] == ['lhipjoint', 'lfemur', 'ltibia']
    assert [bone.parent for bone in skeleton.bones] == [-1, 0, 1]
    assert [bone.dof for bone in skeleton.bones] == [0, 3, 1]


def test_parse_skeleton_numbers_the_channels_after_the_root() -> None:
    """A bone's curves begin where the previous bone's end, the root's coming first."""
    skeleton = parse_skeleton(_model(_SIMPLE))
    assert skeleton is not None
    assert [bone.channel for bone in skeleton.bones] == [6, 6, 9]
    assert skeleton.channels == 10


def test_parse_skeleton_rejects_a_foreign_region() -> None:
    assert parse_skeleton(_model(_SIMPLE, magic=b'JUNK')) is None


def test_parse_skeleton_rejects_a_truncated_model() -> None:
    assert parse_skeleton(_model(_SIMPLE)[:0x40]) is None


def test_parse_skeleton_rejects_missing_names() -> None:
    """The names are what the records are matched against, so a short block is not usable."""
    model = _model(_SIMPLE)
    assert parse_skeleton(model[:model.rindex(b'ltibia')]) is None


def test_parse_skeleton_rejects_a_model_shorter_than_its_header() -> None:
    assert parse_skeleton(b'\x00' * 16) is None


def test_parse_skeleton_rejects_a_bone_count_of_zero() -> None:
    assert parse_skeleton(_model([])) is None


def test_parse_skeleton_rejects_records_that_run_past_the_model() -> None:
    assert parse_skeleton(_model(_SIMPLE)[:0x100]) is None


def test_demo_without_a_reference_model(mocker: MockerFixture,
                                        capsys: pytest.CaptureFixture[str]) -> None:
    mocker.patch('pathlib.Path.is_file', return_value=False)
    demo()
    assert 'nothing to check' in capsys.readouterr().out


def test_module_entry_point_runs(mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    mocker.patch('pathlib.Path.is_file', return_value=False)
    runpy.run_module('dade.xg2.skeleton', run_name='__main__')
    assert 'nothing to check' in capsys.readouterr().out


def test_demo_accepts_a_matching_skeleton(mocker: MockerFixture,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    mocker.patch('pathlib.Path.is_file', return_value=True)
    mocker.patch('pathlib.Path.read_bytes', return_value=b'model')
    mocker.patch('dade.xg2.archive.parse_archive', return_value=object())
    mocker.patch('dade.xg2.archive.decode_entries', return_value=[(0, b'model')])
    mocker.patch('dade.xg2.skeleton.parse_skeleton', return_value=_demo_skeleton())
    demo()
    assert '27 bones, 67 channels' in capsys.readouterr().out


@pytest.mark.parametrize(('skeleton', 'match'),
                         [(None, 'includes no skeleton'), (_demo_skeleton(count=26), 'expected 27'),
                          (_demo_skeleton(extra_dof=60), 'expected 67'),
                          (_demo_skeleton(first_name='wrong'), 'expected lhipjoint'),
                          (_demo_skeleton(first_dof=1, extra_dof=60), 'expected none')])
def test_demo_reports_a_wrong_skeleton(mocker: MockerFixture, skeleton: Skeleton | None,
                                       match: str) -> None:
    mocker.patch('pathlib.Path.is_file', return_value=True)
    mocker.patch('pathlib.Path.read_bytes', return_value=b'model')
    mocker.patch('dade.xg2.archive.parse_archive', return_value=object())
    mocker.patch('dade.xg2.archive.decode_entries', return_value=[(0, b'model')])
    mocker.patch('dade.xg2.skeleton.parse_skeleton', return_value=skeleton)
    with pytest.raises(SelfCheckFailed, match=match):
        demo()
