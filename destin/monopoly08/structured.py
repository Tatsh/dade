"""
Structured EA RenderWare/EAGL-era resource converters for Monopoly 2008.

This module consolidates the per-format converters for the structured (record-based) EA resources
shipped in the Monopoly 2008 (Xbox 360) build. These are RenderWare / EAGL-era assets:

* ``.bin`` — generic record container. The ``.bin`` extension covers MANY unrelated formats; each
  file is sniffed by its magic (and, for headerless variants, its shape) and routed to a per-family
  decoder. Each emitted JSON carries a ``"format"`` tag and a ``"_confidence"`` field so
  honestly-decoded parts are distinguishable from best-effort structural dumps.
* ``.anim`` — big-endian RenderWare ``ANIM`` keyframe animation curves.
* ``.mixr`` — big-endian FourCC-chunked RenderWare Audio Core mixer graph.
* ``.pamc`` — big-endian theme palette/colour-remap table.
* ``.vanb`` — big-endian hash-named node graph (frontend UI value/animation bank).
* ``.fntx`` — little-endian bitmap font texture; converted to a grayscale PNG atlas.

Public API:

* :data:`EXTENSIONS` — the set of handled file extensions.
* :func:`convert` — dispatch by extension, write the output (``.json`` for most, ``.png`` for
  ``.fntx``) next to the source, and return the output path.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any
import json
import math
import re
import struct

from PIL import Image
import numpy as np

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ('EXTENSIONS', 'convert', 'convert_anim', 'convert_bin', 'convert_fntx', 'convert_mixr',
           'convert_pamc', 'convert_vanb')

_TRANSFORM_FLOATS = 12
"""Number of floats in a 3x4 placement transform matrix.

:meta hide-value:
"""
_MIN_HASH = 0x01000000
"""Lowest value accepted as a plausible 32-bit name hash.

:meta hide-value:
"""
_MAX_HASH = 0xFFFFFFFE
"""Highest value accepted as a plausible 32-bit name hash.

:meta hide-value:
"""
_MIN_TOC_SIZE = 16
"""Minimum byte length for a file to plausibly be a TOC bundle.

:meta hide-value:
"""
_MAX_TOC_ENTRIES = 8192
"""Maximum entry count accepted for a TOC bundle.

:meta hide-value:
"""
_CFG0666_MARKER = 0x0D
"""Third byte marking an ``06660d0x`` property/config block.

:meta hide-value:
"""
_MIN_SCRIPT_SIZE = 0x14
"""Minimum byte length for the script-record predicate.

:meta hide-value:
"""
_SCRIPT_MARKER = 0x05
"""Byte at offset ``0x10`` marking a script record.

:meta hide-value:
"""
_MIN_BLOB_SIZE = 0x10
"""Minimum byte length for the generic blob predicate.

:meta hide-value:
"""
_MIN_SANE_FLOAT = 1e-6
"""Smallest absolute float magnitude kept when interpreting a word as a float.

:meta hide-value:
"""
_MAX_SANE_FLOAT = 1e9
"""Largest absolute float magnitude kept when interpreting a word as a float.

:meta hide-value:
"""
_MIN_PRINTABLE_CP = 32
"""Lowest code point rendered as a character in a font glyph dump.

:meta hide-value:
"""
_MAX_CODEPOINT = 0x10000
"""Exclusive upper bound of the basic multilingual plane.

:meta hide-value:
"""

# =========================================================================== #
#  .bin  — generic record container (magic-sniffing dispatch)                 #
# =========================================================================== #
#
# Families (see FORMATS.md "`.bin` files"):
#   66600001  place    object placement/instance (hashes + 3x4 transform)   [high]
#   "  XT"    text     localized UTF-16BE string table                      [high]
#   "0:..EOF" fontlist "index:name" font list                               [high]
#   cc030000  namesle  little-endian scene/state name table                 [high]
#   46456ee7  feng     FrontEnd GUI (FEng) compiled screen                  [medium]
#   " STV"    stv      float sample stream (vertices/curves)                [medium]
#   0001000x  rec      versioned hash record table                          [medium]
#   06660d0x  cfg      property/config block                                [medium]
#   46580b00  fx       environment FX parameter block (160 B)               [low]
#   " BBB"    bbb      offset-table container                               [low]
#   00000xxx  toc      hash->offset resource bundle table                   [medium]
#   (other)   unknown  header + hex preview                                 [none]

#: Matches a run of printable ASCII at least ``minlen`` bytes long (the length is substituted at
#: call time). See :py:func:`_cstrings`.
_CSTRINGS_RE = b'[ -~]{%d,}'
#: Matches FEng four-character chunk tags that are not part of a longer printable run.
_FENG_TAG_RE = re.compile(rb'(?<![ -~])[A-Za-z][A-Za-z][A-Za-z][A-Za-z0-9](?=[ -~]|\x00)')
#: Matches the ``index:`` prefix of a fontlist file.
_FONTLIST_RE = re.compile(rb'\d+:')

#: Function that decodes the body of a sniffed ``.bin`` file into a JSON-serialisable mapping.
BinDecoder = Callable[[bytes], dict[str, Any]]


def _u32(b: bytes, o: int) -> int:
    return int(struct.unpack_from('>I', b, o)[0])


def _u32le(b: bytes, o: int) -> int:
    return int(struct.unpack_from('<I', b, o)[0])


def _f32(b: bytes, o: int) -> float:
    return float(struct.unpack_from('>f', b, o)[0])


def _hx(v: int) -> str:
    return f'0x{v:08x}'


def _floats(b: bytes, start: int, end: int) -> list[float]:
    end -= (end - start) % 4
    return [round(_f32(b, o), 6) for o in range(start, end, 4)]


def _cstrings(b: bytes, minlen: int = 3) -> list[str]:
    return [m.group().decode('latin1') for m in re.finditer(_CSTRINGS_RE % minlen, b)]


# ---------------------------------------------------------------- decoders ---


def _dec_place(b: bytes) -> dict[str, Any]:
    """
    66600001 — object placement/instance: hashes + a 3x4 transform matrix.

    Parameters
    ----------
    b : bytes
        The file's raw bytes.

    Returns
    -------
    dict[str, Any]
        The decoded JSON-serialisable record.
    """
    fl = _floats(b, 0x20, len(b))
    transform = ([fl[i:i + 4] for i in range(0, _TRANSFORM_FLOATS, 4)]
                 if len(fl) >= _TRANSFORM_FLOATS else None)
    return {
        'format': 'place',
        '_confidence': 'high',
        'version': _u32(b, 4),
        'size': _u32(b, 8),
        'selfHash': _hx(_u32(b, 0x14)),
        'dataOffset': _u32(b, 0x18),
        'refHash': _hx(_u32(b, 0x1C)),
        'transform3x4': transform,
        'extraFloats': fl[12:],
    }


def _dec_text(b: bytes) -> dict[str, Any]:
    """
    '  XT' — localized UTF-16BE string table.

    Records are [a:u32][b:u32][hash:u32][byteLen:u32] then byteLen bytes of UTF-16BE payload
    (terminated by NUL + the 0x2A2A '**' marker). The very first record's ``a`` slot holds the file
    magic.

    Parameters
    ----------
    b : bytes
        The file's raw bytes.

    Returns
    -------
    dict[str, Any]
        The decoded JSON-serialisable record.
    """
    recs = []
    o = 0
    while o + 16 <= len(b):
        h = _u32(b, o + 8)
        ln = _u32(b, o + 12)
        o += 16
        if ln == 0 or o + ln > len(b):
            break
        payload = b[o:o + ln]
        o += ln
        # payload is UTF-16BE text + NUL terminator + 0x2A2A "**" marker; cut at the first aligned
        # NUL pair before decoding.
        cut = len(payload)
        for i in range(0, len(payload) - 1, 2):
            if payload[i:i + 2] == b'\x00\x00':
                cut = i
                break
        text = payload[:cut].decode('utf-16-be', 'replace')
        recs.append({'hash': _hx(h), 'text': text})
    return {'format': 'text', '_confidence': 'high', 'count': len(recs), 'strings': recs}


def _dec_fontlist(b: bytes) -> dict[str, Any]:
    """
    'index:name' lines terminated by EOF (e.g. font assignments).

    Parameters
    ----------
    b : bytes
        The file's raw bytes.

    Returns
    -------
    dict[str, Any]
        The decoded JSON-serialisable record.
    """
    body = b.split(b'EOF')[0]
    entries = {}
    for part in body.split(b'\x00'):
        s = part.decode('latin1', 'replace').strip()
        if ':' in s:
            idx, _, name = s.partition(':')
            entries[idx] = name
    return {'format': 'fontlist', '_confidence': 'high', 'entries': entries}


def _dec_namesle(b: bytes) -> dict[str, Any]:
    """
    cc030000 — little-endian scene/state name table.

    Parameters
    ----------
    b : bytes
        The file's raw bytes.

    Returns
    -------
    dict[str, Any]
        The decoded JSON-serialisable record.
    """
    return {
        'format': 'namesle',
        '_confidence': 'high',
        'header': [_u32le(b, o) for o in range(0, 16, 4)],
        'names': _cstrings(b, 3)
    }


def _dec_feng(b: bytes) -> dict[str, Any]:
    """
    46456ee7 — FrontEnd GUI (FEng) compiled screen.

    Parameters
    ----------
    b : bytes
        The file's raw bytes.

    Returns
    -------
    dict[str, Any]
        The decoded JSON-serialisable record.
    """
    tags = _FENG_TAG_RE.findall(b)
    resources = [s for s in _cstrings(b, 4) if '.' in s or '\\' in s or s.endswith('Mono')]
    return {
        'format': 'feng',
        '_confidence': 'medium',
        'size': _u32(b, 4),
        'chunkTags': sorted({t.decode('latin1')
                             for t in tags}),
        'resources': resources[:200]
    }


def _dec_stv(b: bytes) -> dict[str, Any]:
    """
    ' STV' — float sample stream.

    Parameters
    ----------
    b : bytes
        The file's raw bytes.

    Returns
    -------
    dict[str, Any]
        The decoded JSON-serialisable record.
    """
    n = _u32(b, 0x0C)
    return {
        'format': 'stv',
        '_confidence': 'medium',
        'hash': _hx(_u32(b, 8)),
        'sampleCount': n,
        'floats': _floats(b, 0x10, len(b))
    }


def _dec_rec0001(b: bytes) -> dict[str, Any]:
    """
    0001000x — versioned hash-record table (structure partial).

    Parameters
    ----------
    b : bytes
        The file's raw bytes.

    Returns
    -------
    dict[str, Any]
        The decoded JSON-serialisable record.
    """
    words = [_u32(b, o) for o in range(0, min(len(b), 0x40), 4)]
    return {
        'format': 'rec',
        '_confidence': 'medium',
        'version': _hx(_u32(b, 0)),
        'hashes': [_hx(w) for w in words if _MIN_HASH <= w <= _MAX_HASH],
        'headerWords': words
    }


def _dec_cfg0666(b: bytes) -> dict[str, Any]:
    """
    06660d0x — property/config block (shared type hash 0x2ea8fb98).

    Parameters
    ----------
    b : bytes
        The file's raw bytes.

    Returns
    -------
    dict[str, Any]
        The decoded JSON-serialisable record.
    """
    return {
        'format': 'cfg',
        '_confidence': 'medium',
        'variant': _hx(_u32(b, 0)),
        'size': _u32(b, 4),
        'count': _u32(b, 8),
        'typeHash': _hx(_u32(b, 0x10)),
        'headerWords': [_u32(b, o) for o in range(0, min(len(b), 0x30), 4)]
    }


def _dec_fx(b: bytes) -> dict[str, Any]:
    """
    46580b00 — environment FX parameter block (fixed 160 B).

    Parameters
    ----------
    b : bytes
        The file's raw bytes.

    Returns
    -------
    dict[str, Any]
        The decoded JSON-serialisable record.
    """
    return {
        'format': 'fx',
        '_confidence': 'low',
        'size': _u32(b, 4),
        'count': _u32(b, 8),
        'words': [_u32(b, o) for o in range(0, len(b), 4)],
        'floats': _floats(b, 0, len(b))
    }


def _dec_bbb(b: bytes) -> dict[str, Any]:
    """
    ' BBB' — offset-table container (structure partial).

    Parameters
    ----------
    b : bytes
        The file's raw bytes.

    Returns
    -------
    dict[str, Any]
        The decoded JSON-serialisable record.
    """
    return {
        'format': 'bbb',
        '_confidence': 'low',
        'size': _u32(b, 8),
        'headerWords': [_u32(b, o) for o in range(0, min(len(b), 0x40), 4)],
        'strings': _cstrings(b, 4)
    }


def _looks_like_toc(b: bytes) -> bool:
    """
    Report whether ``b`` looks like a hash->offset TOC bundle.

    Parameters
    ----------
    b : bytes
        The file's raw bytes.

    Returns
    -------
    bool
        ``True`` if ``b`` plausibly decodes as a TOC bundle.
    """
    if len(b) < _MIN_TOC_SIZE or b[:2] != b'\x00\x00':
        return False
    cnt = _u32(b, 0)
    if not (1 <= cnt <= _MAX_TOC_ENTRIES) or 8 + cnt * 8 > len(b):
        return False
    prev = -1
    valid = 0
    for i in range(cnt):
        off = _u32(b, 8 + i * 8 + 4)
        if off <= prev or off > len(b):
            break
        prev = off
        valid += 1
    return valid >= max(2, cnt // 2)


def _dec_toc(b: bytes) -> dict[str, Any]:
    """
    00000xxx — hash->offset resource bundle table (payloads not decoded).

    Parameters
    ----------
    b : bytes
        The file's raw bytes.

    Returns
    -------
    dict[str, Any]
        The decoded JSON-serialisable record.
    """
    cnt = _u32(b, 0)
    entries = []
    prev = -1
    for i in range(cnt):
        h = _u32(b, 8 + i * 8)
        off = _u32(b, 8 + i * 8 + 4)
        if off <= prev or off > len(b):
            break
        prev = off
        entries.append({'hash': _hx(h), 'offset': off})
    return {
        'format': 'toc',
        '_confidence': 'medium',
        'declaredCount': cnt,
        'word1': _u32(b, 4),
        'decodedEntries': len(entries),
        'entries': entries,
        'note': 'embedded sub-resource payloads not decoded'
    }


def _dec_script(b: bytes) -> dict[str, Any]:
    """
    [count][0][val][hash] header + a bytecode stream.

    Opcodes start at 0x10, with the first opcode 0x05. The instruction set is not disassembled.

    Parameters
    ----------
    b : bytes
        The file's raw bytes.

    Returns
    -------
    dict[str, Any]
        The decoded JSON-serialisable record.
    """
    return {
        'format': 'script',
        '_confidence': 'low',
        'headerWord0': _u32(b, 0),
        'value': _hx(_u32(b, 8)),
        'codeHash': _hx(_u32(b, 0x0C)),
        'codeSize': len(b) - 0x10,
        'opcodePreview': b[0x10:0x40].hex(),
        'note': 'compiled script/bytecode; opcodes not disassembled'
    }


def _dec_blob(b: bytes) -> dict[str, Any]:
    """
    00000000 — generic container ([0][0][...]); content not decoded.

    Parameters
    ----------
    b : bytes
        The file's raw bytes.

    Returns
    -------
    dict[str, Any]
        The decoded JSON-serialisable record.
    """
    return {
        'format': 'blob',
        '_confidence': 'low',
        'size': len(b),
        'headerWords': [_u32(b, o) for o in range(0, min(len(b), 0x20), 4)],
        'strings': _cstrings(b, 4)[:40],
        'note': 'container payload not decoded'
    }


def _dec_unknown(b: bytes) -> dict[str, Any]:
    """
    (other) — unrecognised file: header words plus a hex preview.

    Parameters
    ----------
    b : bytes
        The file's raw bytes.

    Returns
    -------
    dict[str, Any]
        The decoded JSON-serialisable record.
    """
    return {
        'format': 'unknown',
        '_confidence': 'none',
        'magic': b[:4].hex(),
        'size': len(b),
        'headerWords': [_u32(b, o) for o in range(0, min(len(b), 0x40), 4)],
        'headPreview': b[:64].hex(),
        'strings': _cstrings(b, 5)[:20]
    }


def _detect(b: bytes) -> BinDecoder:
    """
    Pick the ``.bin`` decoder for ``b`` by sniffing its magic and shape.

    Parameters
    ----------
    b : bytes
        The file's raw bytes.

    Returns
    -------
    BinDecoder
        The decoder for the first matching family, or :py:func:`_dec_unknown`.
    """
    # Ordered (predicate, decoder) table: the first matching predicate wins. The leading u32 of the
    # count-prefixed families is data, not a magic, so those are sniffed by shape.
    rules: tuple[tuple[Callable[[bytes], object], BinDecoder], ...] = (
        (lambda d: d[:4] == b'\x66\x60\x00\x01', _dec_place),
        (lambda d: d[:4] == b'  XT', _dec_text),
        (lambda d: d[:4] == b' STV', _dec_stv),
        (lambda d: d[:4] == b' BBB', _dec_bbb),
        (lambda d: d[:4] == b'\x46\x45\x6e\xe7', _dec_feng),
        (lambda d: d[:4] == b'\x46\x58\x0b\x00', _dec_fx),
        (lambda d: d[:2] == b'\x06\x66' and d[2] == _CFG0666_MARKER, _dec_cfg0666),
        (lambda d: d[:3] == b'\x00\x01\x00', _dec_rec0001),
        (lambda d: d[:4] == b'\xcc\x03\x00\x00', _dec_namesle),
        (lambda d: bool(_FONTLIST_RE.match(d)) and b'EOF' in d[-8:], _dec_fontlist),
        (lambda d: (len(d) >= _MIN_SCRIPT_SIZE and _u32(d, 4) == 0 and _u32(d, 0) != 0 and d[0x10]
                    == _SCRIPT_MARKER), _dec_script),
        (lambda d: len(d) >= _MIN_BLOB_SIZE and _u32(d, 0) == 0 and _u32(d, 4) == 0, _dec_blob),
        (_looks_like_toc, _dec_toc),
    )
    return next((dec for pred, dec in rules if pred(b)), _dec_unknown)


def convert_bin(path: str | Path, out: str | Path | None = None) -> tuple[Path, dict[str, Any]]:
    """
    Convert a sniffed ``.bin`` record container to JSON.

    Parameters
    ----------
    path : str | Path
        Path to the ``.bin`` file to convert.
    out : str | Path | None
        Output path. Defaults to ``path`` with a ``.json`` suffix.

    Returns
    -------
    tuple[Path, dict[str, Any]]
        The output path and the decoded mapping that was written.
    """
    path = Path(path)
    b = path.read_bytes()
    data = _detect(b)(b)
    out = Path(out) if out is not None else path.with_suffix('.json')
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    return out, data


# =========================================================================== #
#  .anim  — big-endian RenderWare ANIM keyframe animation                     #
# =========================================================================== #


def _anim_u32(b: bytes, o: int) -> int:
    return int(struct.unpack('>I', b[o:o + 4])[0])


def _anim_f32(b: bytes, o: int) -> float:
    return float(struct.unpack('>f', b[o:o + 4])[0])


def _anim_round(x: float, nd: int = 6) -> float:
    # Keep JSON tidy: round, and turn -0.0 into 0.0.
    r = round(x, nd)
    return 0.0 if r == 0 else r


def _anim_parse(b: bytes) -> dict[str, Any]:
    if b[:4] != b'ANIM':
        msg = f'not an ANIM file (magic={b[:4]!r})'
        raise ValueError(msg)
    version = _anim_f32(b, 0x04)
    duration = _anim_f32(b, 0x0C)
    channel_count = _anim_u32(b, 0x10)
    channels = []
    for i in range(channel_count):
        rec = 0x14 + i * 12
        name_off = _anim_u32(b, rec)
        name_hash = _anim_u32(b, rec + 4)
        kf_off = _anim_u32(b, rec + 8)
        name = b[name_off:b.index(b'\x00', name_off)].decode('latin1')
        count = _anim_u32(b, kf_off)
        keys = []
        base = kf_off + 60
        for k in range(count):
            o = base + k * 24
            keys.append({
                'time':
                    _anim_round(_anim_f32(b, o)),
                'value':
                    _anim_round(_anim_f32(b, o + 4)),
                'inTangent': [_anim_round(_anim_f32(b, o + 8)),
                              _anim_round(_anim_f32(b, o + 12))],
                'outTangent': [
                    _anim_round(_anim_f32(b, o + 16)),
                    _anim_round(_anim_f32(b, o + 20))
                ],
            })
        node, _, prop = name.partition('.')
        channels.append({
            'name': name,
            'node': node,
            'property': prop,
            'nameHash': f'0x{name_hash:08x}',
            'keyframeCount': count,
            'keyframes': keys,
        })
    return {
        'format': 'ANIM',
        'version': _anim_round(version, 3),
        'duration': _anim_round(duration),
        'channelCount': channel_count,
        'channels': channels,
    }


def _anim_to_json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def convert_anim(path: str | Path, out: str | Path | None = None) -> tuple[Path, dict[str, Any]]:
    """
    Convert a big-endian RenderWare ``.anim`` keyframe animation to JSON.

    Parameters
    ----------
    path : str | Path
        Path to the ``.anim`` file to convert.
    out : str | Path | None
        Output path. Defaults to ``path`` with a ``.json`` suffix.

    Returns
    -------
    tuple[Path, dict[str, Any]]
        The output path and the decoded mapping that was written.
    """
    path = Path(path)
    data = _anim_parse(path.read_bytes())
    text = _anim_to_json(data)
    out = Path(out) if out is not None else path.with_suffix('.json')
    out.write_text(text + '\n', encoding='utf-8')
    return out, data


# =========================================================================== #
#  .mixr  — big-endian FourCC-chunked RenderWare Audio Core mixer graph       #
# =========================================================================== #


def _mixr_u32(b: bytes, o: int) -> int:
    return int(struct.unpack_from('>I', b, o)[0])


def _mixr_f32(b: bytes, o: int) -> float:
    return float(struct.unpack_from('>f', b, o)[0])


def _mixr_cstr(b: bytes, o: int) -> str:
    return b[o:b.index(b'\x00', o)].decode('latin1')


def _mixr_parse(b: bytes) -> dict[str, Any]:
    if b[:4] != b'MIXR':
        msg = f'not MIXR ({b[:4]!r})'
        raise ValueError(msg)
    chunks: dict[str, tuple[int, int]] = {}
    o = 8
    while o + 8 <= len(b):
        tag = b[o:o + 4].decode('latin1')
        size = _mixr_u32(b, o + 4)
        chunks[tag] = (o, size)
        o += size

    # STRT: [hdr u32][count u32] then count*[hash u32][offset u32(rel chunk start)]
    names: dict[int, str] = {}
    if 'STRT' in chunks:
        off, _size = chunks['STRT']
        count = _mixr_u32(b, off + 12)
        for i in range(count):
            eo = off + 16 + i * 8
            names[_mixr_u32(b, eo)] = _mixr_cstr(b, off + _mixr_u32(b, eo + 4))

    def nm(h: int) -> str:
        return names.get(h, f'#{h:08x}')

    out: dict[str, Any] = {
        'format': 'MIXR',
        'names': dict(sorted((f'0x{h:08x}', n) for h, n in names.items())),
    }

    if 'INFO' in chunks:
        o, _ = chunks['INFO']
        c = o + 8
        out['info'] = {
            'project': nm(_mixr_u32(b, c)),
            'version': _mixr_u32(b, c + 4),
            'name2': nm(_mixr_u32(b, c + 8)),
            'gain': round(_mixr_f32(b, c + 12), 6)
        }

    # FRDS: [hdr][count] then count*[nodeHash][gain f32][u32] -> the mix levels
    if 'FRDS' in chunks:
        o, _ = chunks['FRDS']
        c = o + 8
        count = _mixr_u32(b, c + 4)
        out['faders'] = {
            nm(_mixr_u32(b, c + 8 + i * 12)): round(_mixr_f32(b, c + 8 + i * 12 + 4), 6)
            for i in range(count)
        }

    # FTRE: records [nodeHash][u32][u32] directly (no [hdr][count] prefix)
    if 'FTRE' in chunks:
        o, size = chunks['FTRE']
        c = o + 8
        n = (size - 8) // 12
        out['faderTree'] = [{
            'node': nm(_mixr_u32(b, c + i * 12)),
            'a': _mixr_u32(b, c + i * 12 + 4),
            'b': _mixr_u32(b, c + i * 12 + 8)
        } for i in range(n)]

    # DTRE / PSET: [hdr][count] then count*[hash][u32][u32] index records
    for tag, key in (('DTRE', 'nodeTree'), ('PSET', 'pluginSet')):
        if tag in chunks:
            o, _ = chunks[tag]
            c = o + 8
            count = _mixr_u32(b, c + 4)
            out[key] = [{
                'name': nm(_mixr_u32(b, c + 8 + i * 12)),
                'a': _mixr_u32(b, c + 8 + i * 12 + 4),
                'b': _mixr_u32(b, c + 8 + i * 12 + 8)
            } for i in range(count)]

    out['_chunks'] = {t: {'offset': o, 'size': s} for t, (o, s) in chunks.items()}
    return out


def convert_mixr(path: str | Path, out: str | Path | None = None) -> tuple[Path, dict[str, Any]]:
    """
    Convert a big-endian ``.mixr`` RenderWare Audio Core mixer graph to JSON.

    Parameters
    ----------
    path : str | Path
        Path to the ``.mixr`` file to convert.
    out : str | Path | None
        Output path. Defaults to ``path`` with a ``.json`` suffix.

    Returns
    -------
    tuple[Path, dict[str, Any]]
        The output path and the decoded mapping that was written.
    """
    path = Path(path)
    data = _mixr_parse(path.read_bytes())
    out = Path(out) if out is not None else path.with_suffix('.json')
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    return out, data


# =========================================================================== #
#  .pamc  — big-endian theme palette/colour-remap table                       #
# =========================================================================== #


def _pamc_u32(b: bytes, o: int) -> int:
    return int(struct.unpack_from('>I', b, o)[0])


def _pamc_parse(b: bytes) -> dict[str, Any]:
    if b[:4] != b'PAMC':
        msg = f'not PAMC ({b[:4]!r})'
        raise ValueError(msg)
    version = _pamc_u32(b, 4)
    count = _pamc_u32(b, 8)
    remaps = []
    for i in range(count):
        o = 0x0C + i * 8
        key = b[o:o + 3]
        new = b[o + 3:o + 6]
        marker = b[o + 6:o + 8]
        remaps.append({
            'key': f'#{key[0]:02X}{key[1]:02X}{key[2]:02X}',
            'replacement': f'#{new[0]:02X}{new[1]:02X}{new[2]:02X}',
            'marker': f'0x{marker[0]:02X}{marker[1]:02X}',
        })
    return {'format': 'PAMC', 'version': version, 'count': count, 'remaps': remaps}


def convert_pamc(path: str | Path, out: str | Path | None = None) -> tuple[Path, dict[str, Any]]:
    """
    Convert a big-endian ``.pamc`` theme palette/colour-remap table to JSON.

    Parameters
    ----------
    path : str | Path
        Path to the ``.pamc`` file to convert.
    out : str | Path | None
        Output path. Defaults to ``path`` with a ``.json`` suffix.

    Returns
    -------
    tuple[Path, dict[str, Any]]
        The output path and the decoded mapping that was written.
    """
    path = Path(path)
    data = _pamc_parse(path.read_bytes())
    out = Path(out) if out is not None else path.with_suffix('.json')
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    return out, data


# =========================================================================== #
#  .vanb  — big-endian hash-named node graph (frontend UI value/anim bank)    #
# =========================================================================== #

#: Sentinel u32 used by ``.vanb`` to mark an absent child/sibling offset.
_VANB_NONE = 0xFFFFFFFF


def _vanb_u32(b: bytes, o: int) -> int:
    return int(struct.unpack_from('>I', b, o)[0])


def _vanb_off(v: int) -> int | None:
    return None if v == _VANB_NONE else v


def _vanb_as_float(v: int) -> float | None:
    """
    Float interpretation of a u32 ref, if it looks like a sane finite value.

    Parameters
    ----------
    v : int
        The packed u32 reference value.

    Returns
    -------
    float | None
        The rounded float interpretation, or ``None`` if it is not a sane finite value.
    """
    f = struct.unpack('>f', struct.pack('>I', v))[0]
    return round(f, 6) if math.isfinite(f) and _MIN_SANE_FLOAT < abs(f) < _MAX_SANE_FLOAT else None


def _vanb_parse(b: bytes) -> dict[str, Any]:
    if b[:4] != b'VANB':
        msg = f'not VANB ({b[:4]!r})'
        raise ValueError(msg)
    version = _vanb_u32(b, 4)
    nodes = []
    o = 8
    while o + 8 <= len(b):
        node_off = o
        name_hash = _vanb_u32(b, o)
        count = _vanb_u32(b, o + 4)
        o += 8
        entries = []
        for _ in range(count):
            tag = _vanb_u32(b, o)
            ref = _vanb_u32(b, o + 4)
            o += 8
            e: dict[str, Any] = {'tag': tag, 'ref': f'0x{ref:08x}'}
            fv = _vanb_as_float(ref)
            if fv is not None:
                e['refFloat'] = fv
            entries.append(e)
        child = _vanb_u32(b, o)
        sibling = _vanb_u32(b, o + 4)
        o += 8
        nodes.append({
            'offset': node_off,
            'hash': f'0x{name_hash:08x}',
            'entries': entries,
            'child': _vanb_off(child),
            'sibling': _vanb_off(sibling),
        })
    return {
        'format': 'VANB',
        'version': version,
        'nodeCount': len(nodes),
        'bytesConsumed': o,
        'fileSize': len(b),
        'nodes': nodes
    }


def convert_vanb(path: str | Path, out: str | Path | None = None) -> tuple[Path, dict[str, Any]]:
    """
    Convert a big-endian ``.vanb`` hash-named node graph to JSON.

    Parameters
    ----------
    path : str | Path
        Path to the ``.vanb`` file to convert.
    out : str | Path | None
        Output path. Defaults to ``path`` with a ``.json`` suffix.

    Returns
    -------
    tuple[Path, dict[str, Any]]
        The output path and the decoded mapping that was written.
    """
    path = Path(path)
    data = _vanb_parse(path.read_bytes())
    out = Path(out) if out is not None else path.with_suffix('.json')
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    return out, data


# =========================================================================== #
#  .fntx  — little-endian bitmap font texture -> grayscale PNG atlas          #
# =========================================================================== #

#: Atlas width in pixels; verified: the atlas renders clean at 256px wide, 8-bit.
_FNTX_ATLAS_WIDTH = 256


def _fntx_u16(b: bytes, o: int) -> int:
    return int(struct.unpack_from('<H', b, o)[0])


def _fntx_parse(b: bytes) -> dict[str, Any]:
    if b[:4] != b'FntX':
        msg = f'not a FntX file (magic={b[:4]!r})'
        raise ValueError(msg)
    table_region = _fntx_u16(b, 0x08)  # glyph-table region, 16-byte units
    glyph_count = _fntx_u16(b, 0x0A)
    atlas_off = 0x80 + table_region * 16
    glyphs = []
    for i in range(glyph_count):
        o = 0x80 + i * 16
        cp = _fntx_u16(b, o)
        glyphs.append({
            'codepoint': cp,
            'char': chr(cp) if _MIN_PRINTABLE_CP <= cp < _MAX_CODEPOINT else None,
            'width': b[o + 2],
            'height': b[o + 3],
            'atlasX': _fntx_u16(b, o + 4),
            'atlasY': _fntx_u16(b, o + 6),
            'advance': _fntx_u16(b, o + 14),
        })
    rem = len(b) - atlas_off
    height = rem // _FNTX_ATLAS_WIDTH  # floor drops the sub-256B EAGL64 trailer
    atlas = np.frombuffer(b[atlas_off:atlas_off + _FNTX_ATLAS_WIDTH * height],
                          dtype=np.uint8).reshape(height, _FNTX_ATLAS_WIDTH)
    return {
        'glyphCount': glyph_count,
        'atlasWidth': _FNTX_ATLAS_WIDTH,
        'atlasHeight': height,
        'glyphs': glyphs,
        'atlas': atlas,
    }


def convert_fntx(path: str | Path,
                 out_png: str | Path | None = None,
                 *,
                 write_glyphs: bool = False) -> tuple[Path, dict[str, Any]]:
    """
    Convert a little-endian ``.fntx`` bitmap font texture to a grayscale PNG atlas.

    Parameters
    ----------
    path : str | Path
        Path to the ``.fntx`` file to convert.
    out_png : str | Path | None
        Output PNG path. Defaults to ``path`` with a ``.png`` suffix.
    write_glyphs : bool
        When true, also write a ``.glyphs.json`` sidecar with the glyph metrics table.

    Returns
    -------
    tuple[Path, dict[str, Any]]
        The output PNG path and the parsed font info (including the atlas array).
    """
    path = Path(path)
    info = _fntx_parse(path.read_bytes())
    out_png = Path(out_png) if out_png is not None else path.with_suffix('.png')
    Image.fromarray(info['atlas'], 'L').save(out_png)
    if write_glyphs:
        side = path.with_suffix('.glyphs.json')
        meta = {k: info[k] for k in ('glyphCount', 'atlasWidth', 'atlasHeight')}
        meta['glyphs'] = info['glyphs']
        side.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')
    return out_png, info


# =========================================================================== #
#  Public dispatch                                                            #
# =========================================================================== #

#: Maps each handled extension to the converter that writes its output.
_CONVERTERS: dict[str, Callable[[str | Path], tuple[Path, dict[str, Any]]]] = {
    '.bin': convert_bin,
    '.anim': convert_anim,
    '.mixr': convert_mixr,
    '.pamc': convert_pamc,
    '.vanb': convert_vanb,
    '.fntx': convert_fntx,
}

#: The set of file extensions handled by :func:`convert`.
EXTENSIONS = frozenset(_CONVERTERS)


def convert(path: str | Path) -> Path:
    """
    Convert a structured EA resource to JSON (or PNG for ``.fntx``).

    Dispatches by the file's extension to the matching converter, writes the output next to the
    source file, and returns the output path.

    Parameters
    ----------
    path : str | Path
        Path to the resource to convert. The extension must be a member of :data:`EXTENSIONS`.

    Returns
    -------
    Path
        The path of the written output file.

    Raises
    ------
    ValueError
        If the file's extension is not handled.
    """
    path = Path(path)
    ext = path.suffix.lower()
    converter = _CONVERTERS.get(ext)
    if converter is None:
        msg = f'unhandled extension {ext!r} for {str(path)!r}'
        raise ValueError(msg)
    return converter(path)[0]
