from __future__ import annotations

from typing import TYPE_CHECKING, Any
import json
import struct

from PIL import Image
import pytest

from dade.monopoly08.structured import (
    EXTENSIONS,
    convert,
    convert_anim,
    convert_bin,
    convert_fntx,
    convert_mixr,
    convert_pamc,
    convert_vanb,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

# --------------------------------------------------------------------------- #
# .bin builders                                                                #
# --------------------------------------------------------------------------- #


def _place(floats: Sequence[float], tail: bytes = b'') -> bytes:
    head = bytearray(0x20)
    head[0:4] = b'\x66\x60\x00\x01'
    struct.pack_into('>I', head, 4, 3)
    struct.pack_into('>I', head, 8, 0x60)
    struct.pack_into('>I', head, 0x14, 0xAABBCCDD)
    struct.pack_into('>I', head, 0x18, 0x20)
    struct.pack_into('>I', head, 0x1C, 0x11223344)
    return bytes(head) + struct.pack(f'>{len(floats)}f', *floats) + tail


def _text(records: Sequence[tuple[int, bytes]]) -> bytes:
    out = bytearray()
    for name_hash, payload in records:
        out += struct.pack('>IIII', 0, 0, name_hash, len(payload)) + payload
    out[0:4] = b'  XT'
    return bytes(out)


def _padded(body: bytes, size: int) -> bytes:
    return body.ljust(size, b'\x00')


def _toc(count: int, offsets: Sequence[int], word1: int = 1, size: int = 64) -> bytes:
    out = bytearray(struct.pack('>II', count, word1))
    for i, offset in enumerate(offsets):
        out += struct.pack('>II', 0x1000 + i, offset)
    return _padded(bytes(out), size)


# --------------------------------------------------------------------------- #
# .anim / .mixr / .pamc / .vanb / .fntx builders                               #
# --------------------------------------------------------------------------- #


def _anim(channels: Sequence[tuple[str, Sequence[tuple[float, ...]]]]) -> bytes:
    header = bytearray(0x14 + len(channels) * 12)
    header[0:4] = b'ANIM'
    struct.pack_into('>f', header, 0x04, 1.5)
    struct.pack_into('>f', header, 0x0C, 2.25)
    struct.pack_into('>I', header, 0x10, len(channels))
    names = bytearray()
    for name, _keys in channels:
        names += name.encode() + b'\x00'
    kf_base = len(header) + len(names)
    blocks = bytearray()
    name_off = len(header)
    for i, (name, keys) in enumerate(channels):
        struct.pack_into('>III', header, 0x14 + i * 12, name_off, 0xABCDEF01, kf_base + len(blocks))
        name_off += len(name) + 1
        block = bytearray(60)
        struct.pack_into('>I', block, 0, len(keys))
        for key in keys:
            block += struct.pack('>6f', *key)
        blocks += block
    return bytes(header + names + blocks)


def _chunk(tag: bytes, body: bytes) -> bytes:
    return tag + struct.pack('>I', 8 + len(body)) + body


def _strt(names: Mapping[int, str]) -> bytes:
    entries = bytearray(struct.pack('>II', 0, len(names)) + b'\x00' * (len(names) * 8))
    strings = bytearray()
    string_base = 8 + len(entries)
    for i, (name_hash, name) in enumerate(names.items()):
        struct.pack_into('>II', entries, 8 + i * 8, name_hash, string_base + len(strings))
        strings += name.encode() + b'\x00'
    return _chunk(b'STRT', bytes(entries + strings))


def _indexed(tag: bytes, records: Sequence[tuple[int, int, int]]) -> bytes:
    body = bytearray(struct.pack('>II', 0, len(records)))
    for a, b, c in records:
        body += struct.pack('>III', a, b, c)
    return _chunk(tag, bytes(body))


def _faders(records: Sequence[tuple[int, float]]) -> bytes:
    body = bytearray(struct.pack('>II', 0, len(records)))
    for name_hash, gain in records:
        body += struct.pack('>IfI', name_hash, gain, 0)
    return _chunk(b'FRDS', bytes(body))


def _mixr(*chunks: bytes) -> bytes:
    joined = b''.join(chunks)
    return b'MIXR' + struct.pack('>I', 8 + len(joined)) + joined


def _pamc(remaps: Sequence[bytes]) -> bytes:
    return b'PAMC' + struct.pack('>II', 1, len(remaps)) + b''.join(remaps)


def _vanb(nodes: Sequence[tuple[int, Sequence[tuple[int, int]], int, int]]) -> bytes:
    out = bytearray(b'VANB' + struct.pack('>I', 2))
    for name_hash, entries, child, sibling in nodes:
        out += struct.pack('>II', name_hash, len(entries))
        for tag, ref in entries:
            out += struct.pack('>II', tag, ref)
        out += struct.pack('>II', child, sibling)
    return bytes(out)


def _fntx(glyphs: Sequence[tuple[int, int, int, int, int, int]], height: int = 2) -> bytes:
    region = max(1, (len(glyphs) * 16 + 15) // 16)
    head = bytearray(0x80)
    head[0:4] = b'FntX'
    struct.pack_into('<H', head, 0x08, region)
    struct.pack_into('<H', head, 0x0A, len(glyphs))
    table = bytearray(region * 16)
    for i, (cp, width, glyph_height, atlas_x, atlas_y, advance) in enumerate(glyphs):
        o = i * 16
        struct.pack_into('<H', table, o, cp)
        table[o + 2] = width
        table[o + 3] = glyph_height
        struct.pack_into('<H', table, o + 4, atlas_x)
        struct.pack_into('<H', table, o + 6, atlas_y)
        struct.pack_into('<H', table, o + 14, advance)
    return bytes(head + table + bytes(range(256)) * height)


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


# --------------------------------------------------------------------------- #
# .bin                                                                         #
# --------------------------------------------------------------------------- #


def test_bin_place(tmp_path: Path) -> None:
    source = _write(tmp_path, 'p.bin', _place([float(i) for i in range(14)], b'\x01\x02'))
    out, data = convert_bin(source)
    assert out == tmp_path / 'p.json'
    assert data['format'] == 'place'
    assert data['version'] == 3
    assert data['selfHash'] == '0xaabbccdd'
    assert data['refHash'] == '0x11223344'
    assert data['transform3x4'] == [[0.0, 1.0, 2.0, 3.0], [4.0, 5.0, 6.0, 7.0],
                                    [8.0, 9.0, 10.0, 11.0]]
    assert data['extraFloats'] == [12.0, 13.0]
    assert json.loads(out.read_text())['format'] == 'place'


def test_bin_place_without_a_transform(tmp_path: Path) -> None:
    _out, data = convert_bin(_write(tmp_path, 'p.bin', _place([1.0, 2.0])))
    assert data['transform3x4'] is None
    assert data['extraFloats'] == []


def test_bin_text(tmp_path: Path) -> None:
    records = ((0x11111111, 'Hello'.encode('utf-16-be') + b'\x00\x00\x2a\x2a'),
               (0x22222222, 'Hi'.encode('utf-16-be')), (0x33333333, b''))
    _out, data = convert_bin(_write(tmp_path, 't.bin', _text(records)))
    assert data['format'] == 'text'
    assert data['count'] == 2
    assert data['strings'] == [{
        'hash': '0x11111111',
        'text': 'Hello'
    }, {
        'hash': '0x22222222',
        'text': 'Hi'
    }]


def test_bin_text_consuming_the_whole_file(tmp_path: Path) -> None:
    body = _text(((0x11111111, 'Hi'.encode('utf-16-be')),))
    _out, data = convert_bin(_write(tmp_path, 't.bin', body))
    assert data['count'] == 1


def test_bin_text_stops_at_a_record_past_the_end(tmp_path: Path) -> None:
    body = bytearray(_text(((0x11111111, 'Hi'.encode('utf-16-be')),)))
    body += struct.pack('>IIII', 0, 0, 0x44444444, 999)
    _out, data = convert_bin(_write(tmp_path, 't.bin', bytes(body)))
    assert data['count'] == 1


def test_bin_fontlist(tmp_path: Path) -> None:
    _out, data = convert_bin(
        _write(tmp_path, 'f.bin', b'0:Arial\x001:Times\x00nocolon\x00EOF\x00\x00'))
    assert data == {
        'format': 'fontlist',
        '_confidence': 'high',
        'entries': {
            '0': 'Arial',
            '1': 'Times'
        }
    }


def test_bin_namesle(tmp_path: Path) -> None:
    body = b'\xcc\x03\x00\x00' + struct.pack('<3I', 1, 2, 3) + b'scene_one\x00scene_two\x00'
    _out, data = convert_bin(_write(tmp_path, 'n.bin', body))
    assert data['format'] == 'namesle'
    assert data['header'] == [0x03CC, 1, 2, 3]
    assert data['names'] == ['scene_one', 'scene_two']


def test_bin_feng(tmp_path: Path) -> None:
    body = (b'\x46\x45\x6e\xe7' + struct.pack('>I', 100) + b'\x00HEAD\x00art\\ui.xmap\x00'
            b'MainMono\x00plain\x00')
    _out, data = convert_bin(_write(tmp_path, 'g.bin', body))
    assert data['format'] == 'feng'
    assert data['size'] == 100
    assert 'HEAD' in data['chunkTags']
    assert data['resources'] == ['art\\ui.xmap', 'MainMono']


def test_bin_stv(tmp_path: Path) -> None:
    body = b' STV' + struct.pack('>III', 0, 0xDEADBEEF, 3) + struct.pack('>3f', 1.5, 2.5, 3.5)
    _out, data = convert_bin(_write(tmp_path, 's.bin', body))
    assert data['format'] == 'stv'
    assert data['hash'] == '0xdeadbeef'
    assert data['sampleCount'] == 3
    assert data['floats'] == [1.5, 2.5, 3.5]


def test_bin_bbb(tmp_path: Path) -> None:
    body = _padded(b' BBB' + struct.pack('>II', 1, 64) + b'\x00\x00\x00\x00name_one\x00', 64)
    _out, data = convert_bin(_write(tmp_path, 'b.bin', body))
    assert data['format'] == 'bbb'
    assert data['size'] == 64
    assert data['strings'] == [' BBB', 'name_one']


def test_bin_fx(tmp_path: Path) -> None:
    body = _padded(b'\x46\x58\x0b\x00' + struct.pack('>II', 160, 4), 160)
    _out, data = convert_bin(_write(tmp_path, 'x.bin', body))
    assert data['format'] == 'fx'
    assert data['size'] == 160
    assert len(data['words']) == 40


def test_bin_cfg(tmp_path: Path) -> None:
    body = _padded(b'\x06\x66\x0d\x01' + struct.pack('>III', 0x30, 2, 0), 0x30)
    body = body[:0x10] + struct.pack('>I', 0x2EA8FB98) + body[0x14:]
    _out, data = convert_bin(_write(tmp_path, 'c.bin', body))
    assert data['format'] == 'cfg'
    assert data['variant'] == '0x06660d01'
    assert data['typeHash'] == '0x2ea8fb98'


def test_bin_rec(tmp_path: Path) -> None:
    body = _padded(b'\x00\x01\x00\x01' + struct.pack('>II', 0x02000000, 5), 0x40)
    _out, data = convert_bin(_write(tmp_path, 'r.bin', body))
    assert data['format'] == 'rec'
    assert data['version'] == '0x00010001'
    assert data['hashes'] == ['0x02000000']


def test_bin_script(tmp_path: Path) -> None:
    body = bytearray(0x40)
    struct.pack_into('>I', body, 0, 7)
    struct.pack_into('>I', body, 8, 0x0000BEEF)
    struct.pack_into('>I', body, 0x0C, 0x0000CAFE)
    body[0x10] = 0x05
    _out, data = convert_bin(_write(tmp_path, 'sc.bin', bytes(body)))
    assert data['format'] == 'script'
    assert data['headerWord0'] == 7
    assert data['value'] == '0x0000beef'
    assert data['codeHash'] == '0x0000cafe'
    assert data['codeSize'] == 0x30


def test_bin_blob(tmp_path: Path) -> None:
    _out, data = convert_bin(_write(tmp_path, 'bl.bin', _padded(b'', 0x20) + b'inner_name\x00'))
    assert data['format'] == 'blob'
    assert data['strings'] == ['inner_name']


def test_bin_toc(tmp_path: Path) -> None:
    _out, data = convert_bin(_write(tmp_path, 'toc.bin', _toc(3, (40, 48, 56))))
    assert data['format'] == 'toc'
    assert data['declaredCount'] == 3
    assert data['decodedEntries'] == 3
    assert data['entries'][0] == {'hash': '0x00001000', 'offset': 40}


def test_bin_toc_stops_at_a_non_increasing_offset(tmp_path: Path) -> None:
    _out, data = convert_bin(_write(tmp_path, 'toc.bin', _toc(4, (40, 48, 0, 0))))
    assert data['format'] == 'toc'
    assert data['declaredCount'] == 4
    assert data['decodedEntries'] == 2


@pytest.mark.parametrize('body', [
    _padded(b'ZZZZ', 0x40),
    b'\x00\x00\x00\x01\x00\x00\x00\x02',
    _padded(struct.pack('>II', 0, 1), 0x20),
    _padded(struct.pack('>II', 16385, 1), 0x20),
    _padded(struct.pack('>II', 100, 1), 0x20),
    _toc(4, (40, 40, 40, 40)),
    _toc(4, (40, 4096, 0, 0)),
])
def test_bin_unknown(body: bytes, tmp_path: Path) -> None:
    _out, data = convert_bin(_write(tmp_path, 'u.bin', body))
    assert data['format'] == 'unknown'
    assert data['_confidence'] == 'none'
    assert data['size'] == len(body)


def test_bin_writes_to_an_explicit_output(tmp_path: Path) -> None:
    source = _write(tmp_path, 'p.bin', _place([1.0, 2.0]))
    out, _data = convert_bin(source, tmp_path / 'custom.json')
    assert out == tmp_path / 'custom.json'
    assert out.is_file()


# --------------------------------------------------------------------------- #
# .anim                                                                        #
# --------------------------------------------------------------------------- #


def test_anim(tmp_path: Path) -> None:
    source = _write(
        tmp_path, 'a.anim',
        _anim([('root.posX', [(0.0, -1e-9, 0.25, 0.5, 0.75, 1.0), (1.0, 2.0, 0.0, 0.0, 0.0, 0.0)]),
               ('bare', [])]))
    out, data = convert_anim(source)
    assert out == tmp_path / 'a.json'
    assert data['format'] == 'ANIM'
    assert data['version'] == pytest.approx(1.5)
    assert data['duration'] == pytest.approx(2.25)
    assert data['channelCount'] == 2
    assert data['channels'][0]['node'] == 'root'
    assert data['channels'][0]['property'] == 'posX'
    assert data['channels'][0]['nameHash'] == '0xabcdef01'
    assert data['channels'][0]['keyframes'][0]['value'] == pytest.approx(0.0)
    assert data['channels'][0]['keyframes'][0]['inTangent'] == [0.25, 0.5]
    assert data['channels'][1] == {
        'name': 'bare',
        'node': 'bare',
        'property': '',
        'nameHash': '0xabcdef01',
        'keyframeCount': 0,
        'keyframes': []
    }
    assert out.read_text().endswith('\n')


def test_anim_rejects_bad_magic(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='not an ANIM file'):
        convert_anim(_write(tmp_path, 'a.anim', _padded(b'NOPE', 0x40)))


def test_anim_writes_to_an_explicit_output(tmp_path: Path) -> None:
    out, _data = convert_anim(_write(tmp_path, 'a.anim', _anim([])), tmp_path / 'custom.json')
    assert out == tmp_path / 'custom.json'


# --------------------------------------------------------------------------- #
# .mixr                                                                        #
# --------------------------------------------------------------------------- #

_NAMES = {0x00000001: 'project', 0x00000002: 'master', 0x00000003: 'music'}


def test_mixr(tmp_path: Path) -> None:
    body = _mixr(_strt(_NAMES), _chunk(b'INFO', struct.pack('>IIIf', 1, 7, 2, 0.5)),
                 _faders([(2, 1.0), (0xDEADBEEF, 0.25)]),
                 _chunk(b'FTRE', struct.pack('>III', 3, 1, 2)), _indexed(b'DTRE', [(2, 0, 1)]),
                 _indexed(b'PSET', [(3, 4, 5)]))
    out, data = convert_mixr(_write(tmp_path, 'm.mixr', body))
    assert out == tmp_path / 'm.json'
    assert data['format'] == 'MIXR'
    assert data['names'] == {'0x00000001': 'project', '0x00000002': 'master', '0x00000003': 'music'}
    assert data['info'] == {'project': 'project', 'version': 7, 'name2': 'master', 'gain': 0.5}
    assert data['faders'] == {'master': 1.0, '#deadbeef': 0.25}
    assert data['faderTree'] == [{'node': 'music', 'a': 1, 'b': 2}]
    assert data['nodeTree'] == [{'name': 'master', 'a': 0, 'b': 1}]
    assert data['pluginSet'] == [{'name': 'music', 'a': 4, 'b': 5}]
    assert set(data['_chunks']) == {'STRT', 'INFO', 'FRDS', 'FTRE', 'DTRE', 'PSET'}


def test_mixr_without_chunks(tmp_path: Path) -> None:
    _out, data = convert_mixr(_write(tmp_path, 'm.mixr', _mixr()))
    assert data == {'format': 'MIXR', 'names': {}, '_chunks': {}}


def test_mixr_rejects_bad_magic(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='not MIXR'):
        convert_mixr(_write(tmp_path, 'm.mixr', _padded(b'NOPE', 16)))


def test_mixr_writes_to_an_explicit_output(tmp_path: Path) -> None:
    out, _data = convert_mixr(_write(tmp_path, 'm.mixr', _mixr()), tmp_path / 'custom.json')
    assert out == tmp_path / 'custom.json'


# --------------------------------------------------------------------------- #
# .pamc                                                                        #
# --------------------------------------------------------------------------- #


def test_pamc(tmp_path: Path) -> None:
    out, data = convert_pamc(
        _write(tmp_path, 'p.pamc', _pamc([b'\xff\x00\x00\x00\xff\x00\xab\xcd'])))
    assert out == tmp_path / 'p.json'
    assert data == {
        'format': 'PAMC',
        'version': 1,
        'count': 1,
        'remaps': [{
            'key': '#FF0000',
            'replacement': '#00FF00',
            'marker': '0xABCD'
        }]
    }


def test_pamc_rejects_bad_magic(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='not PAMC'):
        convert_pamc(_write(tmp_path, 'p.pamc', _padded(b'NOPE', 16)))


def test_pamc_writes_to_an_explicit_output(tmp_path: Path) -> None:
    out, _data = convert_pamc(_write(tmp_path, 'p.pamc', _pamc([])), tmp_path / 'custom.json')
    assert out == tmp_path / 'custom.json'


# --------------------------------------------------------------------------- #
# .vanb                                                                        #
# --------------------------------------------------------------------------- #


def test_vanb(tmp_path: Path) -> None:
    out, data = convert_vanb(
        _write(tmp_path, 'v.vanb', _vanb([(0x0A0B0C0D, [(1, 0x3F800000),
                                                        (2, 0)], 0xFFFFFFFF, 0x20)])))
    assert out == tmp_path / 'v.json'
    assert data['format'] == 'VANB'
    assert data['version'] == 2
    assert data['nodeCount'] == 1
    node = data['nodes'][0]
    assert node['hash'] == '0x0a0b0c0d'
    assert node['entries'] == [{
        'tag': 1,
        'ref': '0x3f800000',
        'refFloat': 1.0
    }, {
        'tag': 2,
        'ref': '0x00000000'
    }]
    assert node['child'] is None
    assert node['sibling'] == 0x20


def test_vanb_rejects_bad_magic(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='not VANB'):
        convert_vanb(_write(tmp_path, 'v.vanb', _padded(b'NOPE', 16)))


def test_vanb_writes_to_an_explicit_output(tmp_path: Path) -> None:
    out, _data = convert_vanb(_write(tmp_path, 'v.vanb', _vanb([])), tmp_path / 'custom.json')
    assert out == tmp_path / 'custom.json'


# --------------------------------------------------------------------------- #
# .fntx                                                                        #
# --------------------------------------------------------------------------- #

_GLYPHS: tuple[tuple[int, int, int, int, int, int],
               ...] = ((0x41, 8, 12, 0, 0, 9), (0x00, 0, 0, 0, 0, 0))


def test_fntx(tmp_path: Path) -> None:
    out, info = convert_fntx(_write(tmp_path, 'f.fntx', _fntx(_GLYPHS)))
    assert out == tmp_path / 'f.png'
    assert info['glyphCount'] == 2
    assert info['atlasWidth'] == 256
    assert info['atlasHeight'] == 2
    assert info['glyphs'][0] == {
        'codepoint': 0x41,
        'char': 'A',
        'width': 8,
        'height': 12,
        'atlasX': 0,
        'atlasY': 0,
        'advance': 9
    }
    assert info['glyphs'][1]['char'] is None
    with Image.open(out) as image:
        assert image.size == (256, 2)
        assert image.mode == 'L'


def test_fntx_writes_the_glyph_sidecar(tmp_path: Path) -> None:
    source = _write(tmp_path, 'f.fntx', _fntx(_GLYPHS))
    convert_fntx(source, tmp_path / 'custom.png', write_glyphs=True)
    sidecar: dict[str, Any] = json.loads((tmp_path / 'f.glyphs.json').read_text())
    assert sidecar['glyphCount'] == 2
    assert sidecar['glyphs'][0]['char'] == 'A'
    assert (tmp_path / 'custom.png').is_file()


def test_fntx_rejects_bad_magic(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='not a FntX file'):
        convert_fntx(_write(tmp_path, 'f.fntx', _padded(b'NOPE', 0x100)))


# --------------------------------------------------------------------------- #
# Dispatch                                                                     #
# --------------------------------------------------------------------------- #


def test_extensions() -> None:
    assert {'.anim', '.bin', '.fntx', '.mixr', '.pamc', '.vanb'} == EXTENSIONS


@pytest.mark.parametrize(('name', 'body', 'expected'), [('d.bin', _place([1.0, 2.0]), 'd.json'),
                                                        ('d.anim', _anim([]), 'd.json'),
                                                        ('d.mixr', _mixr(), 'd.json'),
                                                        ('d.pamc', _pamc([]), 'd.json'),
                                                        ('d.vanb', _vanb([]), 'd.json'),
                                                        ('d.fntx', _fntx(()), 'd.png')])
def test_convert_dispatch(name: str, body: bytes, expected: str, tmp_path: Path) -> None:
    assert convert(_write(tmp_path, name, body)) == tmp_path / expected


def test_convert_rejects_an_unhandled_extension(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='unhandled extension'):
        convert(_write(tmp_path, 'd.xyz', b''))
