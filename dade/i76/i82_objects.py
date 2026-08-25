"""
Reader for the Interstate '82 object reference graph.

Levels place objects through text records. A static object is an ``Object_Header`` block naming a
``.stf`` wrapper, whose ``Geometry_Files`` block names a ``.six`` mesh; the binary mesh itself is
the matching ``.sbx``, falling back to the ``.six``. A vehicle is an ``Object_Header`` naming a
``.vdf``, whose ``Chassis`` names a ``.cdf`` carrying the same ``Geometry_Files`` block plus a
``Wheels`` block and a ``Stock_Paint`` texture.

Material textures are not listed in the text records; they are ``.bmp`` and ``.tga`` names embedded
in the binary mesh, so they are recovered by scanning it.
"""
from __future__ import annotations

import logging
import re

__all__ = ('chassis_name', 'geometry_files', 'mesh_textures', 'placement_refs', 'stock_paint',
           'wheel_meshes')

log = logging.getLogger(__name__)

_OBJECT_RE = re.compile(r'Object_Header\s*\{([\s\S]*?)\n\}')
"""Matches one object placement block.

:meta hide-value:
"""
_FILE_RE = re.compile(r'File:\s*([^\s]+)')
"""Matches the file a placement block refers to.

:meta hide-value:
"""
_GEOMETRY_RE = re.compile(r'Geometry_Files\s*\{([\s\S]*?)\}')
"""Matches the geometry block of a ``.stf`` or ``.cdf``.

:meta hide-value:
"""
_SIX_RE = re.compile(r'[A-Za-z0-9_]+\.six', re.IGNORECASE)
"""Matches a mesh name inside a geometry or wheels block.

:meta hide-value:
"""
_MESH_TEXTURE_RE = re.compile(rb'[A-Za-z0-9_]+\.(?:bmp|tga)', re.IGNORECASE)
"""Matches a texture name embedded in a binary mesh.

:meta hide-value:
"""
_CHASSIS_RE = re.compile(r'Chassis\s*=\s*(\S+)', re.IGNORECASE)
"""Matches a vehicle's chassis reference.

:meta hide-value:
"""
_PAINT_RE = re.compile(r'Stock_Paint\s*=\s*(\S+)', re.IGNORECASE)
"""Matches a chassis's stock paint texture.

:meta hide-value:
"""
_WHEELS_RE = re.compile(r'Wheels\s*\{([\s\S]*?)\}', re.IGNORECASE)
"""Matches a chassis's wheels block.

:meta hide-value:
"""


def placement_refs(msa: bytes, suffix: str) -> tuple[str, ...]:
    """
    Collect the files a world places, filtered by extension.

    Parameters
    ----------
    msa : bytes
        Contents of the ``.msa`` world.
    suffix : str
        Extension to keep, including the leading dot, for example ``'.stf'``.

    Returns
    -------
    tuple[str, ...]
        Unique lowercased file names, sorted.
    """
    text = msa.decode('latin1', 'replace')
    refs = {
        found.group(1).lower()
        for block in _OBJECT_RE.finditer(text)
        if (found := _FILE_RE.search(block.group(1))) and found.group(1).lower().endswith(suffix)
    }
    return tuple(sorted(refs))


def geometry_files(text: str) -> tuple[str, ...]:
    """
    Read the mesh names out of a ``Geometry_Files`` block.

    Parameters
    ----------
    text : str
        Contents of a ``.stf`` or ``.cdf``.

    Returns
    -------
    tuple[str, ...]
        Mesh names in block order. Empty when there is no geometry block.
    """
    if (block := _GEOMETRY_RE.search(text)) is None:
        return ()
    return tuple(_SIX_RE.findall(block.group(1)))


def wheel_meshes(text: str) -> tuple[str, ...]:
    """
    Read the mesh names out of a ``Wheels`` block.

    Parameters
    ----------
    text : str
        Contents of a ``.cdf``.

    Returns
    -------
    tuple[str, ...]
        Mesh names in block order. Empty when there is no wheels block.
    """
    if (block := _WHEELS_RE.search(text)) is None:
        return ()
    return tuple(_SIX_RE.findall(block.group(1)))


def chassis_name(text: str) -> str | None:
    """
    Read a vehicle's chassis reference, normalised to a ``.cdf`` file name.

    Parameters
    ----------
    text : str
        Contents of a ``.vdf``.

    Returns
    -------
    str | None
        The lowercased chassis file name, or ``None`` when the vehicle names none.
    """
    if (found := _CHASSIS_RE.search(text)) is None:
        return None
    name = found.group(1).lower()
    return name if name.endswith('.cdf') else f'{name}.cdf'


def stock_paint(text: str) -> str | None:
    """
    Read a chassis's stock paint texture.

    Parameters
    ----------
    text : str
        Contents of a ``.cdf``.

    Returns
    -------
    str | None
        The lowercased texture name, or ``None`` when the chassis names none.
    """
    if (found := _PAINT_RE.search(text)) is None:
        return None
    return found.group(1).lower()


def mesh_textures(mesh: bytes) -> tuple[str, ...]:
    """
    Recover the texture names embedded in a binary mesh's material table.

    Parameters
    ----------
    mesh : bytes
        Contents of the ``.sbx`` or ``.six`` mesh.

    Returns
    -------
    tuple[str, ...]
        Unique lowercased texture names, sorted.
    """
    return tuple(
        sorted({match.decode('latin1').lower()
                for match in _MESH_TEXTURE_RE.findall(mesh)}))
