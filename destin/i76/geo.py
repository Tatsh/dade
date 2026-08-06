"""
Parser for the ``.geo`` mesh format.

Reverse-engineered from ``ParseGeoModel`` at ``0x446c90``. The file opens with a nine-dword header
whose seventh and eighth fields are the vertex and face counts. Vertex positions follow as packed
triples of floats, then an equally long run of normals. Each face record carries its vertex count
at offset 4, and its vertex indices begin at offset ``0x37`` with a stride of ``0x10``.
"""
from __future__ import annotations

import logging
import struct

from .typing import GeoModel

__all__ = ('MAGIC', 'parse')

log = logging.getLogger(__name__)

MAGIC = b'OEG.'
"""Magic at the start of a ``.geo`` file, being ``.GEO`` as a little-endian dword.

:meta hide-value:
"""

_FACE_INDEX_OFFSET = 0x37
"""Offset from the start of a face record at which its vertex indices begin.

:meta hide-value:
"""
_FACE_INDEX_STRIDE = 0x10
"""Stride in bytes between consecutive vertex indices in a face record.

:meta hide-value:
"""


def parse(data: bytes) -> GeoModel | None:
    """
    Parse a ``.geo`` mesh.

    Parameters
    ----------
    data : bytes
        Contents of the ``.geo`` file.

    Returns
    -------
    GeoModel | None
        The parsed mesh, or ``None`` when the magic does not match.
    """
    if data[:4] != MAGIC:
        return None
    header = struct.unpack_from('<9i', data, 0)
    vertex_count, face_count = header[6], header[7]
    vertices = tuple(
        struct.unpack_from('<3f', data, 9 * 4 + index * 12) for index in range(vertex_count))
    # Faces start after the header and both the position and normal arrays.
    position = (9 + vertex_count * 6) * 4
    faces: list[tuple[int, ...]] = []
    for _ in range(face_count):
        face_vertex_count = struct.unpack_from('<i', data, position + 4)[0]
        base = position + _FACE_INDEX_OFFSET
        faces.append(
            tuple(
                struct.unpack_from('<i', data, base + index * _FACE_INDEX_STRIDE)[0]
                for index in range(face_vertex_count)))
        position = base + face_vertex_count * _FACE_INDEX_STRIDE
    return GeoModel(vertices, face_count, tuple(faces))
