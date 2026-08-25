"""Tests for :py:mod:`dade.i76.bwd2`."""
from __future__ import annotations

import struct

import pytest

from dade.i76.bwd2 import DEFAULT_CONTAINER_TAGS, ascii_strings, is_tag, walk, world_refs


@pytest.mark.parametrize('tag', [b'ABCD', b'A\x00\x00\x00', b'GRP ', b'abcd'])
def test_is_tag_accepts(tag: bytes) -> None:
    assert is_tag(tag)


@pytest.mark.parametrize('tag', [b'1234', b'\xffBCD', b'AB\xffD'])
def test_is_tag_rejects(tag: bytes) -> None:
    assert not is_tag(tag)


def test_ascii_strings_finds_runs() -> None:
    assert ascii_strings(b'ab\x00hello\x00xyz') == ('hello', 'xyz')


def test_ascii_strings_min_length() -> None:
    assert ascii_strings(b'ab\x00hello', min_length=2) == ('ab', 'hello')


def test_ascii_strings_drops_short_trailing_run() -> None:
    assert ascii_strings(b'hello\x00a', min_length=2) == ('hello',)


def test_walk_top_level(bwd2_container: bytes) -> None:
    chunks = walk(bwd2_container)
    assert len(chunks) == 1
    assert chunks[0].tag == 'BWD2'
    assert chunks[0].offset == 0


def test_walk_nests_containers(bwd2_container: bytes) -> None:
    leaf = walk(bwd2_container)[0].children[0].children[0]
    assert leaf.tag == 'LEAF'
    assert leaf.payload == b'abcdef'
    assert leaf.children == ()


def test_walk_container_payload_is_empty(bwd2_container: bytes) -> None:
    assert walk(bwd2_container)[0].payload == b''


def test_walk_respects_custom_container_tags(bwd2_container: bytes) -> None:
    # With no tags treated as containers, the outermost chunk becomes a leaf.
    chunks = walk(bwd2_container, set())
    assert chunks[0].children == ()
    assert chunks[0].payload.startswith(b'WDEF')


def test_walk_stops_on_malformed_header() -> None:
    good = b'LEAF' + struct.pack('<I', 10) + b'ab'
    assert len(walk(good + b'\xff\xff\xff\xff' + struct.pack('<I', 8), set())) == 1


def test_walk_stops_on_undersized_chunk() -> None:
    assert walk(b'LEAF' + struct.pack('<I', 4), set()) == ()


def test_default_container_tags_include_bwd2() -> None:
    assert 'BWD2' in DEFAULT_CONTAINER_TAGS


def test_world_refs(mission: bytes) -> None:
    assert world_refs(mission) == ('terrain.act', 'sky.map', 'horizon.hzd')


def test_world_refs_without_chunk() -> None:
    assert world_refs(b'no world chunk') == ()


def test_world_refs_skips_short_runs_and_runs_without_dots() -> None:
    body = b'ab\x00padding here\x00a.b\x00real.act\x00'
    data = b'WRLD' + struct.pack('<I', 8 + len(body)) + body
    assert world_refs(data) == ('real.act',)
