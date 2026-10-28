"""
The resources of Windows programs and libraries, converted to files that open anywhere.

Icons and cursors become PNG, one for each size a group lists, bitmaps become PNG, string tables
become JSON, and every other resource is written as it is stored.
"""
from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING, NamedTuple
import io
import json
import struct

from PIL import Image
from PIL.IcoImagePlugin import IcoImageFile

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('Resource', 'iter_resources', 'save_icons', 'write_resources')

_MZ = b'MZ'
_PE = b'PE\0\0'
_RESOURCE_DIRECTORY = 2
_SUBDIRECTORY = 0x80000000
_TYPE_NAMES = {
    1: 'cursor',
    2: 'bitmap',
    3: 'icon',
    4: 'menu',
    5: 'dialog',
    6: 'string',
    7: 'font-directory',
    8: 'font',
    9: 'accelerator',
    10: 'data',
    11: 'message-table',
    12: 'group-cursor',
    14: 'group-icon',
    16: 'version',
    17: 'dialog-include',
    19: 'plug-and-play',
    20: 'vxd',
    21: 'animated-cursor',
    22: 'animated-icon',
    23: 'html',
    24: 'manifest'
}
_BITMAP_FILE_HEADER = struct.Struct('<2sIHHI')
_ICON_DIRECTORY = struct.Struct('<HHH')
_GROUP_ENTRY = struct.Struct('<BBBBHHIH')
_FILE_ENTRY = struct.Struct('<BBBBHHII')
_STRINGS_PER_BLOCK = 16
_DOS_HEADER_SIZE = 0x40
_PE_POINTER = 0x3C
_PE32 = 0x10B
_PE32_DIRECTORIES = 96
_PE32_PLUS_DIRECTORIES = 112
_PALETTED_BITS = 8
_BI_BITFIELDS = 3
_INFO_HEADER_SIZE = 40
_MASKS_SIZE = 12


class _RT(IntEnum):
    CURSOR = 1
    BITMAP = 2
    ICON = 3
    STRING = 6
    GROUP_CURSOR = 12
    GROUP_ICON = 14


class Resource(NamedTuple):
    """One resource of a program."""

    type_: int | str
    """The resource type, a number or a name."""
    name: int | str
    """The name of the resource, a number or a string."""
    language: int
    """The language identifier."""
    data: bytes
    """The bytes of the resource."""


def _sections(image: bytes, header: int) -> list[tuple[int, int, int]]:
    count = struct.unpack_from('<H', image, header + 6)[0]
    optional_size = struct.unpack_from('<H', image, header + 20)[0]
    table = header + 24 + optional_size
    sections = []
    for index in range(count):
        size, address, raw_size, raw = struct.unpack_from('<IIII', image, table + index * 40 + 8)
        sections.append((address, max(size, raw_size), raw))
    return sections


def _offset(sections: list[tuple[int, int, int]], rva: int) -> int | None:
    for address, size, raw in sections:
        if address <= rva < address + size:
            return raw + rva - address
    return None


def _label(image: bytes, root: int, entry: int) -> int | str:
    if entry & _SUBDIRECTORY:
        at = root + (entry & ~_SUBDIRECTORY)
        length = struct.unpack_from('<H', image, at)[0]
        return image[at + 2:at + 2 + length * 2].decode('utf-16-le')
    return entry


def _entries(image: bytes, root: int, directory: int) -> list[tuple[int | str, int]]:
    named, numbered = struct.unpack_from('<HH', image, directory + 12)
    return [(_label(image, root, label), target)
            for label, target in (struct.unpack_from('<II', image, directory + 16 + index * 8)
                                  for index in range(named + numbered))]


def iter_resources(image: bytes) -> list[Resource]:
    """
    Read every resource of a program or library.

    Parameters
    ----------
    image : bytes
        The file.

    Returns
    -------
    list[Resource]
        The resources, or an empty list when the file is not a PE image or has none.
    """
    if image[:2] != _MZ or len(image) < _DOS_HEADER_SIZE:
        return []
    header = struct.unpack_from('<I', image, _PE_POINTER)[0]
    if image[header:header + 4] != _PE:
        return []
    magic = struct.unpack_from('<H', image, header + 24)[0]
    directories = header + 24 + (_PE32_DIRECTORIES if magic == _PE32 else _PE32_PLUS_DIRECTORIES)
    rva = struct.unpack_from('<I', image, directories + _RESOURCE_DIRECTORY * 8)[0]
    sections = _sections(image, header)
    if rva == 0 or (root := _offset(sections, rva)) is None:
        return []
    resources = []
    for type_, types in _entries(image, root, root):
        for name, names in _entries(image, root, root + (types & ~_SUBDIRECTORY)):
            for language, leaf in _entries(image, root, root + (names & ~_SUBDIRECTORY)):
                data_rva, size = struct.unpack_from('<II', image, root + leaf)
                if (at := _offset(sections, data_rva)) is not None:
                    resources.append(Resource(type_, name, int(language), image[at:at + size]))
    return resources


def _group(resources: list[Resource], group: Resource, kind: int) -> bytes:
    images = {r.name: r.data for r in resources if r.type_ == kind}
    reserved, type_, count = _ICON_DIRECTORY.unpack_from(group.data)
    entries = [
        _GROUP_ENTRY.unpack_from(group.data, _ICON_DIRECTORY.size + index * _GROUP_ENTRY.size)
        for index in range(count)
    ]
    entries = [entry for entry in entries if entry[7] in images]
    header = _ICON_DIRECTORY.pack(reserved, type_, len(entries))
    offset = _ICON_DIRECTORY.size + _FILE_ENTRY.size * len(entries)
    table = b''
    payload = b''
    for width, height, colours, zero, group_planes, group_bits, _, identifier in entries:
        data = images[identifier]
        planes, bits = group_planes, group_bits
        if kind == _RT.CURSOR:
            planes, bits = struct.unpack_from('<HH', data)
            data = data[4:]
        table += _FILE_ENTRY.pack(width, height, colours, zero, planes, bits, len(data),
                                  offset + len(payload))
        payload += data
    return header + table + payload


def _bitmap(data: bytes) -> bytes:
    header_size, _, _, _, bits, compression, _, _, _, used = struct.unpack_from('<IiiHHIIiiI', data)
    colours = used or (1 << bits if bits <= _PALETTED_BITS else 0)
    masks = _MASKS_SIZE if compression == _BI_BITFIELDS and header_size == _INFO_HEADER_SIZE else 0
    start = _BITMAP_FILE_HEADER.size + header_size + masks + colours * 4
    return _BITMAP_FILE_HEADER.pack(b'BM', _BITMAP_FILE_HEADER.size + len(data), 0, 0, start) + data


def _strings(block: int, data: bytes) -> dict[int, str]:
    strings = {}
    position = 0
    for index in range(_STRINGS_PER_BLOCK):
        if position + 2 > len(data):
            break
        length = struct.unpack_from('<H', data, position)[0]
        position += 2
        if length:
            strings[(block - 1) * _STRINGS_PER_BLOCK + index] = data[position:position +
                                                                     length * 2].decode('utf-16-le')
        position += length * 2
    return strings


def save_icons(container: bytes, path: Path) -> int:
    """
    Write each image of an icon or cursor file as PNG.

    Parameters
    ----------
    container : bytes
        The ``.ico`` or ``.cur`` file.
    path : Path
        Destination, without a suffix. The size of each image is appended to its name.

    Returns
    -------
    int
        The number of images written.
    """
    icon = Image.open(io.BytesIO(container))
    images = ([icon.ico.getimage(size)
               for size in sorted(icon.ico.sizes())] if isinstance(icon, IcoImageFile) else [icon])
    path.parent.mkdir(parents=True, exist_ok=True)
    for image in images:
        image.convert('RGBA').save(path.with_name(f'{path.name}-{image.width}x{image.height}.png'))
    return len(images)


def write_resources(image: bytes, directory: Path) -> int:
    """
    Write the resources of a program or library to a directory.

    Parameters
    ----------
    image : bytes
        The file.
    directory : Path
        Destination. It is created only when there is a resource to write.

    Returns
    -------
    int
        The number of files written.
    """
    resources = iter_resources(image)
    written = 0
    strings: dict[int, str] = {}
    for resource in resources:
        kind = _TYPE_NAMES.get(resource.type_, str(resource.type_)) if isinstance(
            resource.type_, int) else resource.type_
        path = directory / kind / f'{resource.name}-{resource.language}'
        if resource.type_ not in {_RT.CURSOR, _RT.ICON}:
            path.parent.mkdir(parents=True, exist_ok=True)
        match resource.type_:
            case _RT.GROUP_ICON:
                written += save_icons(_group(resources, resource, _RT.ICON), path)
            case _RT.GROUP_CURSOR:
                written += save_icons(_group(resources, resource, _RT.CURSOR), path)
            case _RT.CURSOR | _RT.ICON:
                continue
            case _RT.BITMAP:
                Image.open(io.BytesIO(_bitmap(resource.data))).save(path.with_suffix('.png'))
                written += 1
            case _RT.STRING if isinstance(resource.name, int):
                strings.update(_strings(resource.name, resource.data))
            case _:
                path.with_suffix('.bin').write_bytes(resource.data)
                written += 1
    if strings:
        (directory / 'string').mkdir(parents=True, exist_ok=True)
        (directory / 'string' / 'strings.json').write_text(json.dumps(
            {
                str(k): v
                for k, v in sorted(strings.items())
            }, ensure_ascii=False, indent=2) + '\n',
                                                           encoding='utf-8')
        written += 1
    return written
