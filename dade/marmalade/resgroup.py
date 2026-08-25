"""
IwResGroup (``.group.bin``) parser.

A ``CIwResGroup`` is Marmalade's serialised bundle of resources (textures, materials, models,
fonts). The file begins with a ``0x3d`` tag and is a list of sections::

    magic(0x3d) u8 + reserved u16
    repeat:
        u32 section_hash    (IwHashString of the section name)
        u32 size            (payload length + 4)
        payload[size - 4]
    terminated by a zero section hash

The ``ResGroupResources`` payload lists, per resource class::

    u32 num_types
    repeat num_types:
        u32 class_hash, u32 count, u8 names_omitted, u8 has_size
        repeat count:
            u32 size, [u32 name_hash if not names_omitted], u32 in_group_hash, body...

This module is sans-I/O: :func:`parse` turns ``bytes`` into a
:class:`~dade.marmalade.typing.ResGroup`.
"""
from __future__ import annotations

import logging
import struct

from dade.common.io import read_cstring

from .hashstring import iw_hash_string
from .typing import ResGroup, Resource

__all__ = ('GROUP_MAGIC', 'KNOWN_CLASSES', 'is_resgroup', 'parse')

log = logging.getLogger(__name__)

GROUP_MAGIC = 0x3D
"""First byte of every serialised IwResGroup.

:meta hide-value:
"""
KNOWN_CLASSES = ('CIwTexture', 'CIwMaterial', 'CIwModel', 'CIwGxFont', 'CIwResGroup', 'CIwResList',
                 'CIwResTemplate')
"""Resource class names whose IwHashString we recognise; others surface as ``class_<hash>``.

:meta hide-value:
"""
_CLASS_BY_HASH = {iw_hash_string(n): n for n in KNOWN_CLASSES}
_H_MEMBERS = iw_hash_string('ResGroupMembers')
_H_RESOURCES = iw_hash_string('ResGroupResources')


def is_resgroup(data: bytes) -> bool:
    """
    Return ``True`` if *data* looks like a serialised IwResGroup.

    Parameters
    ----------
    data : bytes
        Candidate ``.group.bin`` bytes.

    Returns
    -------
    bool
        Whether the first byte is :data:`GROUP_MAGIC`.
    """
    return bool(data) and data[0] == GROUP_MAGIC


def _parse_resources(payload: bytes) -> dict[str, list[Resource]]:
    """
    Parse a ``ResGroupResources`` payload into ``{class_name: [Resource, ...]}``.

    Parameters
    ----------
    payload : bytes
        The ``ResGroupResources`` section payload.

    Returns
    -------
    dict[str, list[Resource]]
        Resources grouped by class name, in file order.

    Raises
    ------
    ValueError
        If a resource class omits the per-resource size prefix (unsupported).
    """
    resources: dict[str, list[Resource]] = {}
    q = 0
    num_types = struct.unpack_from('<I', payload, q)[0]
    q += 4
    log.debug('Parsing ResGroupResources with %d resource type(s).', num_types)
    for _ in range(num_types):
        class_hash = struct.unpack_from('<I', payload, q)[0]
        count = struct.unpack_from('<I', payload, q + 4)[0]
        names_omitted, has_size = payload[q + 8], payload[q + 9]
        q += 10
        cname = _CLASS_BY_HASH.get(class_hash, f'class_{class_hash:08x}')
        log.debug(
            'Reading class %s (hash %#010x) with %d resource(s), names_omitted=%d, '
            'has_size=%d.', cname, class_hash, count, names_omitted, has_size)
        lst = resources.setdefault(cname, [])
        for _i in range(count):
            start = q
            if not has_size:
                msg = f'Resources of class {cname} lack a size prefix, which is unsupported.'
                raise ValueError(msg)
            size = struct.unpack_from('<I', payload, q)[0]
            q += 4
            name_hash: int | None = None
            if not names_omitted:
                name_hash = struct.unpack_from('<I', payload, q)[0]
                q += 4
            in_group_hash = struct.unpack_from('<I', payload, q)[0]
            q += 4
            body = payload[q:start + size]
            lst.append(Resource(name_hash if name_hash is not None else in_group_hash, body))
            q = start + size
    return resources


def parse(data: bytes) -> ResGroup:
    """
    Parse a ``.group.bin`` into its name and resources.

    Parameters
    ----------
    data : bytes
        Full ``.group.bin`` contents.

    Returns
    -------
    ResGroup
        The group name (if present) and a map of class name to resources.

    Raises
    ------
    ValueError
        If *data* is not a serialised IwResGroup.
    """
    if not is_resgroup(data):
        msg = 'Data is not an IwResGroup (.group.bin).'
        raise ValueError(msg)
    p = 6  # magic(1) + 3 padding + reserved u16 -> resources begin at 6
    name: str | None = None
    resources: dict[str, list[Resource]] = {}
    while True:
        section_hash = struct.unpack_from('<I', data, p)[0]
        p += 4
        if section_hash == 0:
            break
        size = struct.unpack_from('<I', data, p)[0]
        p += 4
        payload = data[p:p + size - 4]
        p += size - 4
        if section_hash == _H_MEMBERS:
            name = read_cstring(payload)
            log.debug('Group name is %s.', name)
        elif section_hash == _H_RESOURCES:
            resources = _parse_resources(payload)
        else:
            log.debug('Skipping unrecognised section %#010x (%d bytes).', section_hash, size)
    log.debug('Parsed group %r with %d resource class(es).', name, len(resources))
    return ResGroup(name=name, resources=resources)
