"""Tests for :mod:`destin.marmalade.resgroup`."""
from __future__ import annotations

import struct

from destin.marmalade.hashstring import iw_hash_string
from destin.marmalade.resgroup import is_resgroup, parse
from destin.marmalade.test_utils import build_resgroup
import pytest


def _group(sections: list[tuple[str, bytes]]) -> bytes:
    out = bytearray((0x3D, 0, 0, 0, 0, 0))
    for name, payload in sections:
        out += struct.pack('<II', iw_hash_string(name), len(payload) + 4) + payload
    out += struct.pack('<I', 0)
    return bytes(out)


def test_is_resgroup() -> None:
    assert is_resgroup(b'\x3d\x00\x00')
    assert not is_resgroup(b'\x00')
    assert not is_resgroup(b'')


def test_parse_name_and_resources() -> None:
    group = build_resgroup('demo', {'CIwModel': [b'\xde\xad', b'\xbe\xef']})
    parsed = parse(group)
    assert parsed.name == 'demo'
    bodies = [r.body for r in parsed.resources['CIwModel']]
    assert bodies == [b'\xde\xad', b'\xbe\xef']


def test_parse_resolves_known_class_name() -> None:
    group = build_resgroup('g', {'CIwTexture': [b'\x01']})
    assert 'CIwTexture' in parse(group).resources


def test_parse_reads_per_resource_name_hash() -> None:
    # names_omitted = 0 means each resource carries its own name hash before the in-group hash.
    payload = struct.pack('<I', 1)
    payload += struct.pack('<II', iw_hash_string('CIwTexture'), 1)
    payload += bytes((0, 1))  # names_omitted, has_size
    body = b'\xaa\xbb'
    size = 4 + 4 + 4 + len(body)
    payload += struct.pack('<III', size, 0x11112222, 0x33334444) + body
    resources = parse(_group([('ResGroupResources', payload)])).resources
    assert resources['CIwTexture'][0].name_hash == 0x11112222
    assert resources['CIwTexture'][0].body == b'\xaa\xbb'


def test_parse_rejects_missing_size_prefix() -> None:
    payload = struct.pack('<I', 1)
    payload += struct.pack('<II', iw_hash_string('CIwTexture'), 1)
    payload += bytes((1, 0))  # names_omitted, has_size = 0 -> unsupported
    with pytest.raises(ValueError, match=r'lack a size prefix'):
        parse(_group([('ResGroupResources', payload)]))


def test_parse_skips_unrecognised_section() -> None:
    group = _group([('SomeOtherSection', b'\x00\x00\x00\x00'), ('ResGroupMembers', b'demo\x00')])
    assert parse(group).name == 'demo'


def test_parse_rejects_non_group() -> None:
    with pytest.raises(ValueError, match=r'not an IwResGroup .*\.$'):
        parse(b'NOPE')
