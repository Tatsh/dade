from __future__ import annotations

from typing import TYPE_CHECKING
import io
import json
import struct

from PIL import Image
import pytest

from dade.tgr.pe import Resource, iter_resources, save_icons, write_resources

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    _Tree = Mapping[int | str, Mapping[int | str, Mapping[int, bytes | None]]]

_RVA = 0x1000
_RAW = 0x200


def _directory(labels: list[int | str], strings: Mapping[str, int], targets: list[int]) -> bytes:
    named = sum(isinstance(label, str) for label in labels)
    out = struct.pack('<12xHH', named, len(labels) - named)
    for label, target in zip(labels, targets, strict=True):
        out += struct.pack('<II', 0x80000000 | strings[label] if isinstance(label, str) else label,
                           target)
    return out


def _resource_section(tree: _Tree) -> bytes:
    def size(count: int) -> int:
        return 16 + 8 * count

    names = [list(n) for n in tree.values()]
    languages = [list(lang.items()) for n in tree.values() for lang in n.values()]
    offset = size(len(tree))
    name_dirs = []
    for labels in names:
        name_dirs.append(offset)
        offset += size(len(labels))
    language_dirs = []
    for entries in languages:
        language_dirs.append(offset)
        offset += size(len(entries))
    leaves = []
    for entries in languages:
        leaves.append(offset)
        offset += 16 * len(entries)
    strings: dict[str, int] = {}
    for label in [*tree, *(label for labels in names for label in labels)]:
        if isinstance(label, str) and label not in strings:
            strings[label] = offset
            offset += 2 + 2 * len(label)
    section = bytearray(_directory(list(tree), strings, [0x80000000 | d for d in name_dirs]))
    position = 0
    for labels in names:
        section += _directory(
            labels, strings,
            [0x80000000 | d for d in language_dirs[position:position + len(labels)]])
        position += len(labels)
    for entries, leaf in zip(languages, leaves, strict=True):
        section += _directory([language for language, _ in entries], strings,
                              [leaf + 16 * i for i in range(len(entries))])
    data = b''
    for entries in languages:
        for _, payload in entries:
            data_offset = offset + 1024 + len(data)
            rva = 0xFFFF0000 if payload is None else _RVA + data_offset
            section += struct.pack('<IIII', rva, len(payload or b''), 0, 0)
            data += payload or b''
    for label in strings:
        section += struct.pack('<H', len(label)) + label.encode('utf-16-le')
    return bytes(section.ljust(offset + 1024, b'\0') + data)


def _pe(section: bytes, *, magic: int = 0x10B, rva: int = _RVA) -> bytes:
    header = 0x40
    optional = (96 if magic == 0x10B else 112) + 16 * 8
    image = bytearray(_RAW + len(section))
    image[0:2] = b'MZ'
    struct.pack_into('<I', image, 0x3C, header)
    image[header:header + 4] = b'PE\0\0'
    struct.pack_into('<H', image, header + 6, 1)
    struct.pack_into('<H', image, header + 20, optional)
    struct.pack_into('<H', image, header + 24, magic)
    struct.pack_into('<II', image, header + 24 + optional - 128 + 16, rva, len(section))
    table = header + 24 + optional
    image[table:table + 8] = b'.rsrc\0\0\0'
    struct.pack_into('<IIII', image, table + 8, len(section), _RVA, len(section), _RAW)
    image[_RAW:] = section
    return bytes(image)


def _png_icon(size: int) -> bytes:
    buffer = io.BytesIO()
    Image.new('RGBA', (size, size), (255, 0, 0, 255)).save(buffer, 'ICO', sizes=[(size, size)])
    data = buffer.getvalue()
    length, offset = struct.unpack_from('<II', data, 14)
    return data[offset:offset + length]


def _dib(size: int, *, doubled: bool = False) -> bytes:
    buffer = io.BytesIO()
    Image.new('L', (size, size), 128).save(buffer, 'BMP')
    dib = bytearray(buffer.getvalue()[14:])
    if doubled:
        struct.pack_into('<i', dib, 8, size * 2)
        dib += bytes(size * size)
    return bytes(dib)


def _group(kind: int, *entries: tuple[int, int, int, int]) -> bytes:
    return struct.pack('<HHH', 0, kind, len(entries)) + b''.join(
        struct.pack('<BBBBHHIH', size, size, 0, 0, planes, bits, 0, identifier)
        for size, planes, bits, identifier in entries)


def _strings(*values: str) -> bytes:
    return b''.join(struct.pack('<H', len(v)) + v.encode('utf-16-le') for v in values)


def _tree() -> _Tree:
    return {
        1: {
            2: {
                1033: struct.pack('<HH', 1, 1) + _dib(8, doubled=True)
            }
        },
        2: {
            4: {
                1033: _dib(4)
            }
        },
        3: {
            1: {
                1033: _png_icon(16)
            }
        },
        6: {
            2: {
                1033: _strings('Hello', '', 'World')
            },
            3: {
                1033: _strings(*'abcdefghijklmnop')
            },
            'NAMED': {
                1033: b'raw'
            }
        },
        12: {
            3: {
                1033: _group(2, (8, 1, 1, 2))
            }
        },
        14: {
            'MAINICON': {
                1033: _group(1, (16, 1, 32, 1), (32, 1, 32, 99))
            }
        },
        16: {
            1: {
                1033: b'version'
            }
        },
        'CUSTOM': {
            7: {
                0: b'custom',
                1: None
            }
        }
    }


@pytest.mark.parametrize('magic', [0x10B, 0x20B])
def test_iter_resources(magic: int) -> None:
    resources = iter_resources(_pe(_resource_section(_tree()), magic=magic))
    assert Resource('CUSTOM', 7, 0, b'custom') in resources
    assert Resource(16, 1, 1033, b'version') in resources
    assert any(r.name == 'MAINICON' for r in resources)
    assert len(resources) == 10


@pytest.mark.parametrize('image', [
    b'',
    b'MZ' + bytes(0x3A) + struct.pack('<I', 0x40) + b'XX\0\0' + bytes(0x40),
    _pe(b'', rva=0),
    _pe(_resource_section({}), rva=0x8000),
])
def test_iter_resources_without_resources(image: bytes) -> None:
    assert iter_resources(image) == []


def test_write_resources(tmp_path: Path) -> None:
    out = tmp_path / 'game.exe.resources'
    assert write_resources(_pe(_resource_section(_tree())), out) == 7
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file()) == [
        'CUSTOM/7-0.bin', 'bitmap/4-1033.png', 'group-cursor/3-1033-8x8.png',
        'group-icon/MAINICON-1033-16x16.png', 'string/NAMED-1033.bin', 'string/strings.json',
        'version/1-1033.bin'
    ]
    strings = json.loads((out / 'string' / 'strings.json').read_text(encoding='utf-8'))
    assert len(strings) == 18
    assert (strings['16'], strings['18'], strings['32'], strings['47']) == ('Hello', 'World', 'a',
                                                                            'p')
    with Image.open(out / 'bitmap' / '4-1033.png') as bitmap:
        assert bitmap.size == (4, 4)


def test_write_resources_not_a_program(tmp_path: Path) -> None:
    assert write_resources(b'not a program', tmp_path / 'out') == 0
    assert not (tmp_path / 'out').exists()


def test_save_icons(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    Image.new('RGBA', (32, 32)).save(buffer, 'ICO', sizes=[(16, 16), (32, 32)])
    assert save_icons(buffer.getvalue(), tmp_path / 'icons' / 'app') == 2
    assert sorted(
        p.name for p in (tmp_path / 'icons').iterdir()) == ['app-16x16.png', 'app-32x32.png']
