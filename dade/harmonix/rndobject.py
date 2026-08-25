"""
Extract metadata from FreQuency Harmonix ``Rnd`` scene-graph and data objects.

These objects are the building blocks of the games' arenas: scene-graph reference containers
(``.view``, ``.tnm``, ``.mmesh``, ``.lnm``, ``.arena``) that name other objects and carry 4x3
transforms, and leaf data objects (``.mat`` materials, ``.lit`` lights, ``.env`` environments, and
``.tmov`` texture movies). Each is parsed by extension to a JSON sidecar next to the original; the
original file is kept. Object names embedded in these files are NUL-terminated ASCII looked up by
the engine's ``RndString`` reader.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import math
import re
import struct

from dade.common.exceptions import InvalidFormatError
from dade.common.io import f32, read_cstring_at, u32
from dade.common.json import write_json

if TYPE_CHECKING:
    from pathlib import Path

    from .typing import (
        ArenaMeta,
        EnvironMeta,
        LightMeta,
        LnmMeta,
        MatMeta,
        MmeshMeta,
        MovieMeta,
        TnmMeta,
        ViewMeta,
    )

__all__ = ('EXTENSIONS', 'arena_to_json', 'convert', 'env_to_json', 'lit_to_json', 'lnm_to_json',
           'mat_to_json', 'mmesh_to_json', 'tmov_to_json', 'tnm_to_json', 'view_to_json')

log = logging.getLogger(__name__)

EXTENSIONS = frozenset(
    {'.view', '.tnm', '.mmesh', '.lnm', '.arena', '.mat', '.lit', '.env', '.tmov'})
"""File extensions handled by :py:func:`convert`.

:meta hide-value:
"""

_REF_EXT = ('.mesh', '.tnm', '.view', '.lit', '.lnm', '.mmesh', '.arena', '.mat', '.matAnim',
            '.tex', '.anim', '.char', '.part', '.grp', '.env', '.cam')
"""Object extensions a NUL-terminated name must end with to count as a reference.

:meta hide-value:
"""
_REF_RE = re.compile(rb'[ -~]{1,64}\x00')
"""Matches a printable, NUL-terminated candidate name of up to 64 characters.

:meta hide-value:
"""
_MAT_TEX_RE = re.compile(rb'\x01\x00\x00\x00([ -~]{1,120}?\.(?:tex|bmp))\x00')
"""Matches a ``.mat`` texture name preceded by its ``u32`` present-flag of ``1``.

:meta hide-value:
"""

_HEADER_SIZE = 8  # Minimum bytes for a scene-graph container (version plus one more field).
_REF_MIN_LEN = 3  # Shortest plausible reference name.
_MATRIX_SIZE = 48  # Twelve 32-bit floats: a 4x3 row-major transform.
_MATRIX_FLOATS = 12
_BASIS_MAX = 1.5  # A basis-row component never exceeds this in an orthonormal-ish matrix.
_BASIS_MIN_LEN = 0.8  # A basis row's length stays within these bounds.
_BASIS_MAX_LEN = 1.3

_MAT_VERSIONS = frozenset({2, 3, 7})  # Recognised Rnd::Mat versions.
_MAT_BLEND_OFFSET = 8

_LIT_SIZE = 200  # A Rnd::Light is exactly this many bytes.
_LIT_VERSION = 1
_LIT_LOCAL_XFM_OFFSET = 0x08
_LIT_WORLD_XFM_OFFSET = 0x38
_LIT_COLOR_OFFSET = 0x7C
_LIT_CONE_OUTER_OFFSET = 0xAC
_LIT_CONE_INNER_OFFSET = 0xB0
_LIT_RANGE_OFFSET = 0xB4
_LIT_INTENSITY_OFFSET = 0xB8
_LIT_TYPE_OFFSET = 0xC4

_ENV_VERSION = 0
_ENV_LIGHT_COUNT_OFFSET = 13  # The u32 light count sits thirteen bytes into the header.
_ENV_NAMES_OFFSET = 17  # The NUL-terminated light names begin immediately after the count.
_ENV_FOG_BLOCK_SIZE = 48  # Ambient, fog scalars, fog colour, and fog mode.
_FOG_MODES = ('none', 'vert_exp', 'vert_exp2', 'vert_linear', 'pixel_exp', 'pixel_exp2',
              'pixel_linear')

_MOVIE_VERSION = 2
_MOVIE_FLAG_OFFSET = 8
_MOVIE_FLAG_TIMED = 1
_MOVIE_BODY_OFFSET = 12


def _read_floats(data: bytes, offset: int, count: int) -> list[float]:
    return [float(x) for x in struct.unpack_from(f'<{count}f', data, offset)]


def _scan_refs(data: bytes) -> list[str]:
    # Ordered, deduplicated NUL-terminated names ending in a known object extension.
    out: list[str] = []
    seen: set[str] = set()
    for match in _REF_RE.finditer(data):
        name = match.group()[:-1].decode('latin-1')
        if len(name) >= _REF_MIN_LEN and name.endswith(_REF_EXT) and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _all_matrices(data: bytes) -> list[list[float]]:
    # Every 4x3 row-major transform whose three basis rows are roughly unit length.
    out: list[list[float]] = []
    offset = 0
    while offset <= len(data) - _MATRIX_SIZE:
        values = _read_floats(data, offset, _MATRIX_FLOATS)
        rows = (values[0:3], values[3:6], values[6:9])
        if all(all(abs(x) <= _BASIS_MAX and not math.isnan(x) for x in row) for row in rows):
            lengths = [math.sqrt(sum(x * x for x in row)) for row in rows]
            if all(_BASIS_MIN_LEN < length < _BASIS_MAX_LEN for length in lengths):
                out.append(values)
                offset += _MATRIX_SIZE
                continue
        offset += 4
    return out


_HEADER_TOO_SHORT = 'Not a `Rnd` scene-graph object (too short).'


def view_to_json(data: bytes) -> ViewMeta:
    """
    Decode a ``Rnd::View`` (``.view``) scene-graph node.

    Parameters
    ----------
    data : bytes
        The ``.view`` file contents.

    Returns
    -------
    ViewMeta
        The node's version, references, first mesh reference, and best transform.

    Raises
    ------
    InvalidFormatError
        If the data is shorter than the object header.
    """
    if len(data) < _HEADER_SIZE:
        raise InvalidFormatError(_HEADER_TOO_SHORT)
    references = _scan_refs(data)
    matrices = _all_matrices(data)
    return {
        'version': u32(data, 0),
        'references': references,
        'mesh': next((ref for ref in references if ref.endswith('.mesh')), None),
        'transform': matrices[0] if matrices else None,
    }


def tnm_to_json(data: bytes) -> TnmMeta:
    """
    Decode a ``Rnd::Trans`` named-mesh group (``.tnm``).

    Parameters
    ----------
    data : bytes
        The ``.tnm`` file contents.

    Returns
    -------
    TnmMeta
        The group's version, references, mesh and child-``.tnm`` references, and transforms.

    Raises
    ------
    InvalidFormatError
        If the data is shorter than the object header.
    """
    if len(data) < _HEADER_SIZE:
        raise InvalidFormatError(_HEADER_TOO_SHORT)
    references = _scan_refs(data)
    return {
        'version': u32(data, 0),
        'references': references,
        'mesh_refs': [ref for ref in references if ref.endswith('.mesh')],
        'tnm_refs': [ref for ref in references if ref.endswith('.tnm')],
        'transforms': _all_matrices(data),
    }


def mmesh_to_json(data: bytes) -> MmeshMeta:
    """
    Decode a ``Rnd::MultiMesh`` (``.mmesh``) instanced-mesh object.

    Parameters
    ----------
    data : bytes
        The ``.mmesh`` file contents.

    Returns
    -------
    MmeshMeta
        The object's version, references, first mesh reference, and instance transforms.

    Raises
    ------
    InvalidFormatError
        If the data is shorter than the object header.
    """
    if len(data) < _HEADER_SIZE:
        raise InvalidFormatError(_HEADER_TOO_SHORT)
    references = _scan_refs(data)
    return {
        'version': u32(data, 0),
        'references': references,
        'mesh': next((ref for ref in references if ref.endswith('.mesh')), None),
        'instance_transforms': _all_matrices(data),
    }


def lnm_to_json(data: bytes) -> LnmMeta:
    """
    Decode a ``Rnd::LightNamedMesh`` light group (``.lnm``).

    Parameters
    ----------
    data : bytes
        The ``.lnm`` file contents.

    Returns
    -------
    LnmMeta
        The group's version, references, ``.lit`` references, and transforms.

    Raises
    ------
    InvalidFormatError
        If the data is shorter than the object header.
    """
    if len(data) < _HEADER_SIZE:
        raise InvalidFormatError(_HEADER_TOO_SHORT)
    references = _scan_refs(data)
    return {
        'version': u32(data, 0),
        'references': references,
        'lit_refs': [ref for ref in references if ref.endswith('.lit')],
        'transforms': _all_matrices(data),
    }


def arena_to_json(data: bytes) -> ArenaMeta:
    """
    Decode a ``Rnd::Arena`` scene (``.arena``).

    Parameters
    ----------
    data : bytes
        The ``.arena`` file contents.

    Returns
    -------
    ArenaMeta
        The scene's version, references, and ``.view`` references.

    Raises
    ------
    InvalidFormatError
        If the data is shorter than the object header.
    """
    if len(data) < _HEADER_SIZE:
        raise InvalidFormatError(_HEADER_TOO_SHORT)
    references = _scan_refs(data)
    return {
        'version': u32(data, 0),
        'references': references,
        'view_refs': [ref for ref in references if ref.endswith('.view')],
    }


def mat_to_json(data: bytes) -> MatMeta:
    """
    Decode a ``Rnd::Mat`` material (``.mat``).

    The header is ``u32 version, u32 stageVersion, u32 blendMode``; each texture reference is a
    NUL-terminated ``.tex``/``.bmp`` name immediately preceded by a ``u32`` present-flag of ``1``.

    Parameters
    ----------
    data : bytes
        The ``.mat`` file contents.

    Returns
    -------
    MatMeta
        The material's version, blend mode, and texture references.

    Raises
    ------
    InvalidFormatError
        If the version is not ``2``, ``3``, or ``7``.
    """
    if len(data) < _HEADER_SIZE + 4 or u32(data, 0) not in _MAT_VERSIONS:
        msg = 'Not a `Rnd::Mat` material.'
        raise InvalidFormatError(msg)
    textures = [match.group(1).decode('latin-1') for match in _MAT_TEX_RE.finditer(data)]
    return {
        'version': u32(data, 0),
        'blend_mode': u32(data, _MAT_BLEND_OFFSET),
        'textures': textures or None,
    }


def lit_to_json(data: bytes) -> LightMeta:
    """
    Decode a ``Rnd::Light`` (``.lit``); the object is always exactly 200 bytes.

    Parameters
    ----------
    data : bytes
        The ``.lit`` file contents.

    Returns
    -------
    LightMeta
        The light's type, colour, cone angles, range, intensity, and both transforms.

    Raises
    ------
    InvalidFormatError
        If the data is not 200 bytes or its version is not ``1``.
    """
    if len(data) != _LIT_SIZE or u32(data, 0) != _LIT_VERSION:
        msg = 'Not a `Rnd::Light`.'
        raise InvalidFormatError(msg)
    return {
        'version': u32(data, 0),
        'type': u32(data, _LIT_TYPE_OFFSET),
        'color': _read_floats(data, _LIT_COLOR_OFFSET, 3),
        'cone_outer': f32(data, _LIT_CONE_OUTER_OFFSET),
        'cone_inner': f32(data, _LIT_CONE_INNER_OFFSET),
        'range': f32(data, _LIT_RANGE_OFFSET),
        'intensity': f32(data, _LIT_INTENSITY_OFFSET),
        'local_xfm': _read_floats(data, _LIT_LOCAL_XFM_OFFSET, _MATRIX_FLOATS),
        'world_xfm': _read_floats(data, _LIT_WORLD_XFM_OFFSET, _MATRIX_FLOATS),
    }


def env_to_json(data: bytes) -> EnvironMeta:
    """
    Decode a ``Rnd::Environ`` (``.env``).

    After the ``u32`` version and a ``u32`` light count at offset ``13`` come the NUL-terminated
    ``.lit`` light names, then a 48-byte fog block (ambient colour, fog scalars, fog colour, and
    fog mode). When the trailing block is not exactly 48 bytes the fog fields are omitted and only
    the version and lights are returned.

    Parameters
    ----------
    data : bytes
        The ``.env`` file contents.

    Returns
    -------
    EnvironMeta
        The environment's version, light references, and (when present) fog parameters.

    Raises
    ------
    InvalidFormatError
        If the data is shorter than the header or its version is not ``0``.
    """
    if len(data) < _ENV_NAMES_OFFSET or u32(data, 0) != _ENV_VERSION:
        msg = 'Not a `Rnd::Environ`.'
        raise InvalidFormatError(msg)
    light_count = u32(data, _ENV_LIGHT_COUNT_OFFSET)
    offset = _ENV_NAMES_OFFSET
    lights: list[str] = []
    for _ in range(light_count):
        name, offset = read_cstring_at(data, offset)
        lights.append(name)
    meta: EnvironMeta = {'version': _ENV_VERSION, 'lights': lights}
    if len(data) - offset != _ENV_FOG_BLOCK_SIZE:
        return meta
    fog_mode = u32(data, offset + 44)
    meta['ambient'] = _read_floats(data, offset, 4)
    meta['fog_start'] = f32(data, offset + 16)
    meta['fog_end'] = f32(data, offset + 20)
    meta['fog_density'] = f32(data, offset + 24)
    meta['fog_color'] = _read_floats(data, offset + 28, 4)
    meta['fog_mode'] = _FOG_MODES[fog_mode] if fog_mode < len(_FOG_MODES) else str(fog_mode)
    return meta


def tmov_to_json(data: bytes) -> MovieMeta:
    """
    Decode a ``Rnd::Movie`` (``.tmov``) texture movie.

    The header is ``u32 version, u32, u32 flag``. When ``flag`` is ``1`` the body holds a timed
    block (a ``u32``, a start ``f32`` of ``1.0``, the ``fps`` ``f32``, and a ``u32``); otherwise it
    holds a single ``u32``. The NUL-terminated ``.gif`` movie name follows, then a ``u32`` frame
    count, a ``u32``, and the NUL-terminated ``.tex`` target name.

    Parameters
    ----------
    data : bytes
        The ``.tmov`` file contents.

    Returns
    -------
    MovieMeta
        The movie's version, frame rate, movie and texture names, and frame count.

    Raises
    ------
    InvalidFormatError
        If the version is not ``2``.
    """
    if len(data) < _MOVIE_BODY_OFFSET or u32(data, 0) != _MOVIE_VERSION:
        msg = 'Not a `Rnd::Movie`.'
        raise InvalidFormatError(msg)
    offset = _MOVIE_BODY_OFFSET
    fps: float | None = None
    if u32(data, _MOVIE_FLAG_OFFSET) == _MOVIE_FLAG_TIMED:
        fps = f32(data, offset + 8)  # After the leading u32 and the start f32.
        offset += 16
    else:
        offset += 4
    movie: str | None = None
    frames: int | None = None
    tex: str | None = None
    if offset < len(data):
        movie, offset = read_cstring_at(data, offset)
    if offset + _HEADER_SIZE <= len(data):
        frames = u32(data, offset)
        offset += _HEADER_SIZE  # The frame count plus a trailing u32.
        tex, offset = read_cstring_at(data, offset)
    return {
        'version': _MOVIE_VERSION,
        'fps': fps,
        'movie': movie,
        'frames': frames,
        'tex': tex,
    }


_PARSERS = {
    '.view': view_to_json,
    '.tnm': tnm_to_json,
    '.mmesh': mmesh_to_json,
    '.lnm': lnm_to_json,
    '.arena': arena_to_json,
    '.mat': mat_to_json,
    '.lit': lit_to_json,
    '.env': env_to_json,
    '.tmov': tmov_to_json,
}


def convert(path: Path) -> Path | None:
    """
    Write a ``Rnd`` object metadata sidecar (``<name>.json``); the original file is kept.

    Parameters
    ----------
    path : pathlib.Path
        The ``Rnd`` object file.

    Returns
    -------
    pathlib.Path | None
        The written JSON path, or ``None`` if the file does not match its expected format.
    """
    parser = _PARSERS.get(path.suffix.lower())
    if parser is None:
        return None
    try:
        meta = parser(path.read_bytes())
    except InvalidFormatError:
        return None
    out = path.with_name(f'{path.name}.json')
    write_json(out, meta, ensure_ascii=False, trailing_newline=False)
    log.debug('Rnd object `%s`: version %s -> `%s`.', path.name, meta['version'], out.name)
    return out
