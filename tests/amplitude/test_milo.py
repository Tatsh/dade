from __future__ import annotations

from typing import TYPE_CHECKING
import json
import struct

from destin.amplitude import milo
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_SENTINEL = b'\xad\xde\xad\xde'


def _objects(count: int = 2) -> list[tuple[str, str, bytes]]:
    return [('RndMesh', f'obj{i}.mesh', bytes((i,)) * 8) for i in range(count)]


@pytest.mark.parametrize('magic', [0xCABEDEAF, 0xCBBEDEAF, 0xCCBEDEAF])
def test_milo_decompress(make_milo: Callable[..., bytes], magic: int) -> None:
    body, blocks = milo.milo_decompress(make_milo(_objects(), magic=magic))
    assert body is not None
    assert blocks == 1
    assert struct.unpack_from('<II', body, 0) == (10, 2)


@pytest.mark.parametrize('data', [b'', b'\x00' * 8, b'JUNKJUNK' + bytes(32)])
def test_milo_decompress_not_a_milo(data: bytes) -> None:
    assert milo.milo_decompress(data) == (None, 0)


def test_milo_decompress_stored_block() -> None:
    # A block that is not a valid compressed stream is taken verbatim.
    stored = b'STORED BLOCK CONTENT'
    data = (struct.pack('<4I', 0xCBBEDEAF, 0x14, 1, len(stored)) + struct.pack('<I', len(stored)) +
            stored)
    assert milo.milo_decompress(data) == (stored, 1)


def test_convert_decomposes_objects(make_milo: Callable[..., bytes], tmp_path: Path) -> None:
    source = tmp_path / 'scene.rnd'
    source.write_bytes(make_milo(_objects(3)))
    out = milo.convert(source)
    assert out == tmp_path / 'scene'
    assert not source.exists()
    manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['version'] == 10
    assert manifest['object_count'] == 3
    assert [entry['file']
            for entry in manifest['objects']] == ['obj0.mesh', 'obj1.mesh', 'obj2.mesh']
    assert (out / 'obj1.mesh').read_bytes() == b'\x01' * 8
    assert 'note' not in manifest


def test_convert_frequency_v6(make_milo: Callable[..., bytes], tmp_path: Path) -> None:
    source = tmp_path / 'arena.rnd'
    source.write_bytes(make_milo(_objects(2), version=6))
    out = milo.convert(source)
    assert out is not None
    manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['version'] == 6
    assert manifest['blocks'] == 1
    assert (out / 'obj0.mesh').read_bytes() == b'\x00' * 8


@pytest.mark.parametrize('names', [('dup.mesh', 'dup.mesh'), ('dup', 'dup')])
def test_convert_deduplicates_object_names(make_milo: Callable[..., bytes], tmp_path: Path,
                                           names: tuple[str, str]) -> None:
    source = tmp_path / 'scene.rnd'
    source.write_bytes(make_milo([('RndMesh', name, b'BODY') for name in names]))
    out = milo.convert(source)
    assert out is not None
    written = sorted(path.name for path in out.iterdir() if path.name != 'manifest.json')
    stem, dot, ext = names[0].rpartition('.')
    second = f'{stem}_1{dot}{ext}' if dot else f'{names[0]}_1'
    assert written == sorted((names[0], second))


def test_convert_keeps_unparsed_table_whole(make_milo: Callable[..., bytes],
                                            tmp_path: Path) -> None:
    # An implausible type-name length marks the whole object table as malformed.
    data = bytearray(make_milo([('RndMesh', 'a.mesh', b'BODY')], magic=0xCABEDEAF))
    struct.pack_into('<I', data, 0x14 + 8, 9999)
    source = tmp_path / 'scene.rnd'
    source.write_bytes(bytes(data))
    out = milo.convert(source)
    assert out is not None
    manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['note'] == 'object table unparsed; decompressed Milo kept whole'
    assert manifest['objects'] == []
    assert (out / 'scene.milo').is_file()


def test_convert_keeps_long_object_name_whole(make_milo: Callable[..., bytes],
                                              tmp_path: Path) -> None:
    # An implausible object-name length also marks the table as malformed.
    data = bytearray(make_milo([('RndMesh', 'a.mesh', b'BODY')], magic=0xCABEDEAF))
    struct.pack_into('<I', data, 0x14 + 8 + 4 + len('RndMesh'), 9999)
    source = tmp_path / 'scene.rnd'
    source.write_bytes(bytes(data))
    out = milo.convert(source)
    assert out is not None
    assert (out / 'scene.milo').is_file()


def test_convert_v6_without_separators(tmp_path: Path) -> None:
    # FreQuency entries may omit the 0x01 separator and the table-terminating sentinel.
    body = struct.pack('<II', 6, 1) + b'RndMesh\x00a.mesh\x00' + b'BODY' + _SENTINEL
    source = tmp_path / 'arena.rnd'
    source.write_bytes(body)
    out = milo.convert(source)
    assert out is not None
    assert (out / 'a.mesh').read_bytes() == b'BODY'


def test_convert_keeps_truncated_table_whole(tmp_path: Path) -> None:
    # The record table runs off the end of the directory, so nothing can be split out.
    body = struct.pack('<II', 10, 4) + struct.pack('<I', 4) + b'Rnd\x00'
    data = struct.pack('<4I', 0xCABEDEAF, 0x14, 1, len(body)) + bytes(4) + body
    source = tmp_path / 'scene.rnd'
    source.write_bytes(data)
    out = milo.convert(source)
    assert out is not None
    assert (out / 'scene.milo').is_file()


def test_convert_v6_rejects_unterminated_names(tmp_path: Path) -> None:
    body = struct.pack('<II', 6, 2) + b'RndMesh\x00a.mesh\x00\x01' + b'no terminator here'
    source = tmp_path / 'arena.rnd'
    source.write_bytes(body)
    out = milo.convert(source)
    assert out is not None
    assert (out / 'arena.milo').is_file()


def test_convert_v6_rejects_implausible_names(tmp_path: Path) -> None:
    body = struct.pack('<II', 6, 1) + b'R' * 300 + b'\x00a.mesh\x00\x01' + _SENTINEL
    source = tmp_path / 'arena.rnd'
    source.write_bytes(body)
    out = milo.convert(source)
    assert out is not None
    assert (out / 'arena.milo').is_file()


def test_convert_returns_none_for_non_milo(tmp_path: Path) -> None:
    source = tmp_path / 'plain.rnd'
    source.write_bytes(b'JUST SOME BYTES' + bytes(32))
    assert milo.convert(source) is None
    assert source.exists()


def test_convert_handles_empty_directory(tmp_path: Path) -> None:
    data = struct.pack('<4I', 0xCABEDEAF, 0x14, 1, 0) + bytes(4)
    source = tmp_path / 'empty.rnd'
    source.write_bytes(data)
    out = milo.convert(source)
    assert out is not None
    manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['version'] is None
    assert manifest['object_count'] == 0
