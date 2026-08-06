"""
EA RenderWare-era mesh containers (Monopoly 2008) to Wavefront OBJ + JSON.

These are the per-platform variants of the same 3D mesh container shipped with
Monopoly 2008:

    .npm7  Xbox 360   (big-endian)
    .ppm7  PS3        (big-endian)
    .rpm7  Wii        (big-endian)
    .spm7  PS2        (little-endian, VIF-packed geometry)

The container is a header (file size, a 3x4 transform matrix, a bounding box), a
section table of ``[count, offset]`` slots, an offset-table of material/texture
names, and GPU-packed vertex/index geometry. On NPM7/PPM7/RPM7 the geometry is
one or more ``PH`` (0x5048) submesh blocks; on SPM7 it is a VIF command stream.

:py:func:`convert` writes BOTH ``<stem>.obj`` (+ ``<stem>.mtl`` when materials
are present) and ``<stem>.json`` (metadata) next to the source.

Status (honest, current state):

* Xbox 360 **NPM7** is the correct reference decode.
* PS2 **SPM7** is VIF-decoded and front-correct, with residual strip-restart
  spikes (per-vertex ADC restart flags are not decoded yet, so a restart inside
  a batch can leave one long triangle; those are dropped with an adaptive edge
  gate, which can also nick thin parts).
* PS3 **PPM7** ``.obj`` is **NOT yet correct**: the vertex-data offset within
  the PH block differs from NPM7 (known TODO), so the PPM7 ``.obj`` may be
  garbage. Its ``.json`` metadata is fine.
* Wii **RPM7** shares the big-endian PH path with NPM7.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, TypedDict
import json
import math
import re
import struct

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ('EXTENSIONS', 'convert')

EXTENSIONS = frozenset({'.npm7', '.ppm7', '.rpm7', '.spm7'})
"""File extensions handled by this module.

:meta hide-value:
"""

_NAME_TOKEN_RE = re.compile(rb'[A-Za-z][A-Za-z0-9_]{3,}')
"""Matches ASCII name-like tokens (e.g. ``wt_deco_base_01_nm``).

:meta hide-value:
"""
_MAP_SUFFIX_RE = re.compile(r'(.*)_(cm|nm|sm)$')
"""Splits a texture name into its base and ``cm``/``nm``/``sm`` map suffix.

:meta hide-value:
"""

_MIN_NAME_LEN = 6
"""Minimum length of a token accepted as a material/texture name.

:meta hide-value:
"""
_MIN_INDEX_BYTES = 6
"""Minimum index-buffer size (one triangle is three ``u16`` indices).

:meta hide-value:
"""
_MIN_GEOMETRY_BYTES = 16
"""Minimum span between a PH vertex offset and the index buffer to decode.

:meta hide-value:
"""
_STRIP_RESTART = 0xFFFF
"""``u16`` sentinel that restarts a triangle strip.

:meta hide-value:
"""
_LARGE_U16 = 0x4000
"""Threshold above which a ``u16`` is treated as vertex data rather than an index.

:meta hide-value:
"""
_IDENTITY_TOLERANCE = 1e-4
"""Tolerance for treating the header diagonal as identity (float32 positions).

:meta hide-value:
"""
_MAX_FINITE_COORD = 1e30
"""Absolute coordinate magnitude above which a vertex component is clamped to zero.

:meta hide-value:
"""
_SECTION_TABLE_END = 0xC8
"""End offset of the header section table.

:meta hide-value:
"""
_VIF_UNPACK_CMD = 0x60
"""VIF command code (after masking with ``0xE0``) for an UNPACK.

:meta hide-value:
"""
_VIF_STMASK_CMD = 0x20
"""VIF command code for STMASK (followed by one data word).

:meta hide-value:
"""
_VIF_VN_VECTOR3 = 2
"""VIF UNPACK ``vn`` code selecting three components per element (V3).

:meta hide-value:
"""
_PH_MARKER = b'PH'
"""Two-byte submesh marker (``0x50 0x48``) on the big-endian PH geometry path.

:meta hide-value:
"""


def _endian(b: bytes) -> str:
    # magic -> byte order. NPM7/PPM7/RPM7 (Xbox360/PS3/Wii) are big-endian; SPM7
    # (PS2) is the same container/geometry little-endian. The `PH` submesh marker
    # (0x50 0x48) is a literal 2-byte tag and is NOT byte-reversed on PS2.
    return '<' if b[:4] == b'SPM7' else '>'


def _dist(a: Sequence[float], b: Sequence[float]) -> float:
    return float(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5)


def _flush(strip: Sequence[int], tris: list[tuple[int, int, int]]) -> None:
    for i in range(len(strip) - 2):
        a, c, d = strip[i], strip[i + 1], strip[i + 2]
        if a in {c, d} or c == d:
            continue  # degenerate (strip stitching)
        tris.append((a, d, c) if (i & 1) else (a, c, d))


def _material_names(b: bytes) -> list[str]:
    seen: list[str] = []
    for m in _NAME_TOKEN_RE.finditer(b):
        s = m.group().decode('latin1')
        if ('_' in s or len(s) >= _MIN_NAME_LEN) and s not in seen:
            seen.append(s)
    return seen


def _write_mtl(names: Sequence[str], path: Path) -> list[str]:
    bases: dict[str, dict[str, str]] = {}  # base name -> {suffix: texname}
    for n in names:
        if m := _MAP_SUFFIX_RE.match(n):
            bases.setdefault(m.group(1), {})[m.group(2)] = n
        else:
            bases.setdefault(n, {})['cm'] = n
    lines: list[str] = []
    for base, maps in bases.items():
        lines.extend((f'newmtl {base}\n', 'Kd 0.8 0.8 0.8\n'))
        if 'cm' in maps:
            lines.append(f'map_Kd {maps["cm"]}.png\n')
        if 'nm' in maps:
            lines.append(f'map_Bump {maps["nm"]}.png\n')
        if 'sm' in maps:
            lines.append(f'map_Ns {maps["sm"]}.png\n')
        lines.append('\n')
    path.write_text(''.join(lines), encoding='utf-8')
    return list(bases.keys())


class _Submesh(TypedDict):
    """One decoded submesh: its world-space positions and triangle list."""

    verts: list[tuple[float, ...]]
    """World-space vertex positions, one ``(x, y, z)`` tuple per vertex."""
    tris: list[tuple[int, int, int]]
    """Triangles as zero-based indices into :py:attr:`verts`."""


def _parse_spm7(b: bytes) -> list[_Submesh]:
    # PS2 SPM7 geometry is VIF-packed, not raw PH vertex buffers. Each draw batch
    # is `UNPACK V3-16 (positions) / S-16 / V2-16 (uv) / V3-8 (normal) / MSCAL`.
    # We walk the VIF stream and take the V3-16 batches as triangle strips.
    #
    # Dequantisation: positions are u16 scaled by the header matrix diagonal
    # (diag@0x20/0x34/0x48) and offset so the mesh fills its bounding box
    # (min@0x60/max@0x70). The offset isn't stored, so we recover it from the
    # mesh's own u16 range: pos = bmin + (u16 - umin) * (bmax-bmin)/(umax-umin).
    # (Using a fixed 0..0xFFFF range instead flattens the mesh, since the u16
    # only span a sub-range -- most visibly in the shallow Z axis.)
    #
    # Strip-restart (ADC) flags aren't decoded yet, so a restart inside a batch
    # leaves one long triangle; those are dropped with a per-strip adaptive edge
    # gate.
    bmin = struct.unpack_from('<3f', b, 0x60)
    bmax = struct.unpack_from('<3f', b, 0x70)
    o = struct.unpack_from('<I', b, 0x0C)[0]  # geometry offset
    end = len(b)
    raw: list[list[tuple[int, int, int]]] = []  # list of [(u16,u16,u16), ...] per batch
    while o + 4 <= end:
        num = b[o + 2]
        cmd = b[o + 3]
        if (cmd & 0xE0) == _VIF_UNPACK_CMD:  # VIF UNPACK
            vn = (cmd >> 2) & 3
            vl = cmd & 3
            esz = {0: 1, 1: 2, 2: 3, 3: 4}[vn] * {0: 4, 1: 2, 2: 1, 3: 2}[vl]
            data = o + 4
            if vn == _VIF_VN_VECTOR3 and vl == 1 and num > 0:  # V3-16 = positions
                us = struct.unpack_from(f'<{num * 3}H', b, data)
                raw.append([(us[i * 3], us[i * 3 + 1], us[i * 3 + 2]) for i in range(num)])
            o = (data + esz * num + 3) & ~3
        elif cmd == _VIF_STMASK_CMD:  # STMASK + 1 data word
            o += 8
        elif cmd in {0x30, 0x31}:  # STROW / STCOL + 4 data words
            o += 20
        else:  # NOP / STCYCL / MSCAL / base / offset / ...
            o += 4
    if not raw:
        return []
    return _spm7_geometry(raw, bmin, bmax)


def _spm7_geometry(raw: Sequence[Sequence[tuple[int, int, int]]], bmin: Sequence[float],
                   bmax: Sequence[float]) -> list[_Submesh]:
    # Dequantise each V3-16 batch into world-space positions and triangulate it.
    umin = [min(v[k] for s in raw for v in s) for k in range(3)]
    umax = [max(v[k] for s in raw for v in s) for k in range(3)]
    sc = [(bmax[k] - bmin[k]) / (umax[k] - umin[k]) if umax[k] > umin[k] else 0.0 for k in range(3)]

    def deq(u: Sequence[int]) -> tuple[float, ...]:
        return tuple(bmin[k] + (u[k] - umin[k]) * sc[k] for k in range(3))

    diag = float(sum((bmax[k] - bmin[k]) ** 2 for k in range(3)) ** 0.5)
    submeshes: list[_Submesh] = []
    for s in raw:
        verts = [deq(u) for u in s]
        # Each batch is a triangle strip, but per-vertex strip-restart (ADC) flags
        # aren't decoded yet, so a restart inside a batch would stitch one long
        # triangle across the model. Drop triangles whose longest edge exceeds
        # both an absolute gate (catches the big cross-model "blades") and a
        # per-strip adaptive gate (catches local jumps without nuking the
        # gavel/thin parts).
        edges = [_dist(verts[i], verts[i + 1]) for i in range(len(verts) - 1)]
        med = sorted(edges)[len(edges) // 2] if edges else 0.0
        gate = min(0.06 * diag if diag else 1e9, max(10 * med, 1e-6))
        tris: list[tuple[int, int, int]] = []
        for i in range(len(verts) - 2):
            p0, p1, p2 = verts[i], verts[i + 1], verts[i + 2]
            if max(_dist(p0, p1), _dist(p1, p2), _dist(p0, p2)) > gate:
                continue
            tris.append((i, i + 2, i + 1) if (i & 1) else (i, i + 1, i + 2))
        submeshes.append({'verts': verts, 'tris': tris})
    return submeshes


class _MeshHeader(NamedTuple):
    """Decoded header fields shared by the big-endian PH geometry readers."""

    b: bytes
    """Full container buffer the offsets index into."""
    en: str
    """Struct byte-order prefix (``'<'`` PS2, ``'>'`` otherwise)."""
    float_pos: bool
    """Whether positions are stored as float32 (an identity header diagonal)."""
    qscale: tuple[float, ...]
    """Per-axis ``u16`` position scale."""
    pivot: tuple[float, ...]
    """Position pivot/translation added after scaling."""
    bmin: tuple[float, ...]
    """Bounding-box minimum corner."""
    bmax: tuple[float, ...]
    """Bounding-box maximum corner."""
    bspan: float
    """Largest bounding-box axis span (at least ``1.0``)."""


def _u16(hdr: _MeshHeader, o: int) -> int:
    return int(struct.unpack_from(hdr.en + 'H', hdr.b, o)[0])


def _f32(hdr: _MeshHeader, o: int) -> float:
    return float(struct.unpack_from(hdr.en + 'f', hdr.b, o)[0])


def _mesh_header(b: bytes) -> _MeshHeader:
    # Header transform: 3x4 row-major matrix at 0x20, pivot/translation at 0x50.
    # Quantized (u16) positions dequantize as raw*diag + pivot. Float32 meshes
    # carry an identity matrix (diag == 1.0, pivot == 0), so the same formula is
    # a no-op and we read positions as float directly.
    en = _endian(b)

    def f32(o: int) -> float:
        return float(struct.unpack_from(en + 'f', b, o)[0])

    diag = (f32(0x20), f32(0x34), f32(0x48))
    pivot = (f32(0x50), f32(0x54), f32(0x58))
    float_pos = abs(diag[0] - 1.0) < _IDENTITY_TOLERANCE  # identity diagonal => float32 positions
    # The matrix diagonal is the u16 position scale, but two conventions exist:
    # Xbox360 NPM7 pre-divides it (diag ~= range/65535, |diag| << 1) so a u16 maps
    # as raw*diag; PS3 PPM7 stores the full range (diag ~= 27, |diag| >= 1) so it
    # maps as raw/65535*diag. Pick per-axis by magnitude.
    qscale = tuple(d / 65535.0 if abs(d) >= 1.0 else d for d in diag)
    bmin = (f32(0x60), f32(0x64), f32(0x68))
    bmax = (f32(0x70), f32(0x74), f32(0x78))
    bspan = max(bmax[k] - bmin[k] for k in range(3)) or 1.0
    return _MeshHeader(b, en, float_pos, qscale, pivot, bmin, bmax, bspan)


def _decode_pos(hdr: _MeshHeader, o: int) -> tuple[float, ...]:
    # A single vertex position at offset ``o``, float32 or dequantized u16.
    if hdr.float_pos:
        return (_f32(hdr, o), _f32(hdr, o + 4), _f32(hdr, o + 8))
    return (_u16(hdr, o) * hdr.qscale[0] + hdr.pivot[0],
            _u16(hdr, o + 2) * hdr.qscale[1] + hdr.pivot[1],
            _u16(hdr, o + 4) * hdr.qscale[2] + hdr.pivot[2])


def _in_bbox_frac(hdr: _MeshHeader, vo: int, stride: int, vcount: int) -> float:
    # Fraction of decoded vertices that fall within the header bounding box
    # (+10% margin). The wrong stride reads index/garbage as positions, which
    # lands far outside the bbox -- so this rejects bad stride guesses.
    n = min(vcount, 24)
    if n <= 0:
        return 0.0
    ok = 0
    for i in range(n):
        p = _decode_pos(hdr, vo + i * stride)
        m = 0.1 * hdr.bspan
        if all(hdr.bmin[k] - m <= p[k] <= hdr.bmax[k] + m for k in range(3)):
            ok += 1
    return ok / n


def _strips(hdr: _MeshHeader, idx_off: int, end: int, vcount: int) -> list[tuple[int, int, int]]:
    tris: list[tuple[int, int, int]] = []
    cur: list[int] = []
    o = idx_off
    while o + 2 <= end:
        v = _u16(hdr, o)
        o += 2
        if v == _STRIP_RESTART or v >= vcount:
            _flush(cur, tris)
            cur = []
        else:
            cur.append(v)
    _flush(cur, tris)
    return tris


def _find_geometry(hdr: _MeshHeader, vo: int, nxt: int) -> tuple[int, int, int, int] | None:
    # Resolve (stride, vertexCount, indexStart, indexEnd) for a PH block.
    #
    # The index strips follow the vertex buffer. Find where vertex data ends
    # (last 'large' u16 that isn't a 0xFFFF restart), then choose the stride
    # whose vertexCount = (indexStart-vo)/stride most tightly exceeds the max
    # index (the highest vertex is referenced, so max index == vertexCount-1).
    iend = nxt
    while iend - 2 >= vo and _u16(hdr, iend - 2) == 0:
        iend -= 2  # trim trailing zero padding
    if iend - vo < _MIN_GEOMETRY_BYTES:
        return None
    last_big = vo - 2
    for o in range(vo, iend, 2):
        v = _u16(hdr, o)
        if v >= _LARGE_U16 and v != _STRIP_RESTART:
            last_big = o
    istart0 = last_big + 2  # index buffer starts at or after this offset

    def maxidx(s: int) -> int:
        return max((_u16(hdr, s + i * 2)
                    for i in range((iend - s) // 2) if _u16(hdr, s + i * 2) != _STRIP_RESTART),
                   default=0)

    best: tuple[tuple[float, int], int, int, int] | None = None
    for s in (16, 24, 12, 20, 28, 32, 8):
        v = max(1, math.ceil((istart0 - vo) / s))
        istart = vo + v * s
        if istart > iend - 4:
            continue
        m = maxidx(istart)
        if m < v and iend - istart >= _MIN_INDEX_BYTES:
            # Rank first by how well the decoded vertices fit the bbox (a
            # wrong stride scatters them outside it), then by tight index fit.
            frac = _in_bbox_frac(hdr, vo, s, v)
            score = (-round(frac, 2), v - m)
            if best is None or score < best[0]:
                best = (score, s, v, istart)
    if best is None:
        return None
    return best[1], best[2], best[3], iend


def _parse(b: bytes) -> list[_Submesh]:
    if b[:4] == b'SPM7':
        return _parse_spm7(b)
    hdr = _mesh_header(b)
    ph = [i for i in range(len(b) - 1) if b[i:i + 2] == _PH_MARKER]
    ph.append(len(b))
    submeshes: list[_Submesh] = []
    for k in range(len(ph) - 1):
        start, nxt = ph[k], ph[k + 1]
        vo = start + 0x50
        g = _find_geometry(hdr, vo, nxt)
        if g is None:
            continue
        stride, vcount, istart, iend = g
        # 16-bit positions dequantized by the header matrix (qscale handles the
        # pre-divided vs full-range diag conventions; see _mesh_header).
        verts = [_decode_pos(hdr, vo + i * stride) for i in range(vcount)]
        submeshes.append({'verts': verts, 'tris': _strips(hdr, istart, iend, vcount)})
    return submeshes


def _parse_meta(b: bytes) -> dict[str, object]:
    # NPM7 (Xbox360), PPM7 (PS3) and RPM7 (Wii) are the same big-endian mesh
    # container; SPM7 (PS2) is the same container little-endian. They differ only
    # in the 4-byte magic and (for SPM7) the byte order, which we switch on below.
    magic = b[:4]
    if magic not in {b'NPM7', b'PPM7', b'RPM7', b'SPM7'}:
        msg = f'not NPM7/PPM7/RPM7/SPM7 ({magic!r})'
        raise ValueError(msg)
    en = '<' if magic == b'SPM7' else '>'

    # rebind the readers to this file's endianness for the rest of _parse_meta()
    def u32(o: int) -> int:
        return int(struct.unpack_from(en + 'I', b, o)[0])

    def f32(o: int) -> float:
        return float(struct.unpack_from(en + 'f', b, o)[0])

    file_size = u32(4)
    matrix_off = u32(8)
    geom_off = u32(0x0C)
    # 3x4 row-major transform matrix at 0x20 (12 floats)
    matrix = [[round(f32(0x20 + (r * 4 + c) * 4), 6) for c in range(4)] for r in range(3)]

    # bounding info at 0x50: pivot, min, max (each a vec4; w=1)
    def vec4(o: int) -> list[float]:
        return [round(f32(o + i * 4), 6) for i in range(4)]

    bbox = {'pivot': vec4(0x50), 'min': vec4(0x60), 'max': vec4(0x70)}
    # section table at 0x80: [count, offset] slots up to the first data offset
    sections: list[dict[str, int]] = []
    o = 0x80
    first_data = min((u32(0x80 + i * 8 + 4) for i in range(9) if u32(0x80 + i * 8 + 4) != 0),
                     default=_SECTION_TABLE_END)
    while o + 8 <= first_data and o < _SECTION_TABLE_END:
        sections.append({'count': u32(o), 'offset': u32(o + 4)})
        o += 8
    # material/texture names: ascii name-like tokens (e.g. wt_deco_base_01_nm)
    names: list[dict[str, object]] = []
    for m in _NAME_TOKEN_RE.finditer(b):
        s = m.group().decode('latin1')
        if '_' in s or len(s) >= _MIN_NAME_LEN:  # filter out short codey noise
            names.append({'offset': m.start(), 'name': s})
    return {
        'format': magic.decode('latin1'),
        'fileSize': file_size,
        'matrixOffset': matrix_off,
        'geometryOffset': geom_off,
        'transform': matrix,
        'bounds': bbox,
        'sectionTable': sections,
        'materialNames': names,
        'note': 'GPU-packed vertex/index geometry not decoded; see FORMATS.md',
    }


def _write_obj(submeshes: Sequence[_Submesh],
               path: Path,
               name: str = 'mesh',
               mtl: str | None = None,
               mats: Sequence[str] | None = None) -> Path:
    base = 1
    lines: list[str] = [f'# Monopoly 2008 mesh -> OBJ ({name})\n']
    if mtl:
        lines.append(f'mtllib {mtl}\n')
    for si, sm in enumerate(submeshes):
        lines.append(f'o submesh_{si}\n')
        # best-effort submesh->material assignment (exact mapping not yet reversed)
        if mats:
            lines.append(f'usemtl {mats[min(si, len(mats) - 1)]}\n')
        for v in sm['verts']:
            x, y, z = (
                c if c == c and abs(c) < _MAX_FINITE_COORD else 0.0  # noqa: PLR0124
                for c in v)
            lines.append(f'v {x:.6f} {y:.6f} {z:.6f}\n')
        lines.extend(f'f {base + t[0]} {base + t[1]} {base + t[2]}\n' for t in sm['tris'])
        base += len(sm['verts'])
    path.write_text(''.join(lines), encoding='utf-8')
    return path


def convert(path: str | Path) -> tuple[Path, Path, int, int]:
    """
    Convert an EA mesh (``.npm7``/``.ppm7``/``.spm7``/``.rpm7``) to OBJ + JSON.

    Writes ``<stem>.obj`` (plus ``<stem>.mtl`` when materials are present) and
    ``<stem>.json`` next to the source file. Dispatch is by the 4-byte magic;
    the underlying parsers already handle all four platform variants.

    Parameters
    ----------
    path : str | Path
        Path to the source mesh file.

    Returns
    -------
    tuple[pathlib.Path, pathlib.Path, int, int]
        ``(obj_path, json_path, n_verts, n_tris)``: the written OBJ and JSON
        paths followed by the total vertex and triangle counts.
    """
    src = Path(path)
    b = src.read_bytes()
    stem = src.with_suffix('')

    # OBJ (+ MTL) geometry.
    sm = _parse(b)
    mats: list[str] | None = None
    mtl_name: str | None = None
    if names := _material_names(b):
        mtl_path = stem.with_suffix('.mtl')
        mats = _write_mtl(names, mtl_path)
        mtl_name = mtl_path.name
    obj_path = stem.with_suffix('.obj')
    _write_obj(sm, obj_path, src.name, mtl_name, mats)

    # JSON metadata.
    json_path = stem.with_suffix('.json')
    meta = _parse_meta(b)
    json_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding='utf-8')

    n_verts = sum(len(s['verts']) for s in sm)
    n_tris = sum(len(s['tris']) for s in sm)
    return obj_path, json_path, n_verts, n_tris
