"""Tests for :mod:`dade.xg2.skeleton`."""
from __future__ import annotations

import struct

from dade.xg2.skeleton import (
    BONE_RECORD_SIZE,
    SKELETON_MAGIC,
    SKELETON_POINTER,
    demo,
    parse_skeleton,
)

_SEGMENT_5 = 0x05000000


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


def test_demo_without_a_reference_model() -> None:
    demo()
