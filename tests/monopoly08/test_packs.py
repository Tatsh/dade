from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

from destin.monopoly08.namehash import name_hash
from destin.monopoly08.packs import extract, parse, read_rpk

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

_BACKGROUND_HASH = name_hash('Background01.xmap')
_STRINGS = ('TGA', 'tex\\firsttex.tga', 'art\\Background01.xmap', '/', 'plainword', 'ANIM',
            'sounds\\voice.wav')
_ASSETS: tuple[tuple[int, int, bytes],
               ...] = ((_BACKGROUND_HASH, 0x11, b'PAMXfirst'), (0x00000002, 0x12, b'PAMXsecond'),
                       (0x00000003, 0x13, b'\x89PNG\r\n\x1a\n'), (_BACKGROUND_HASH, 0x11,
                                                                  b'PAMXclash'))


def test_parse_big_endian(make_rpk: Callable[..., bytes], tmp_path: Path) -> None:
    pack = tmp_path / 'ui.rpk'
    pack.write_bytes(make_rpk(_ASSETS, _STRINGS))
    info = parse(pack)
    assert info.endian == '>'
    assert len(info.assets) == 4
    assert info.strings == _STRINGS
    assert info.assets[0].name_hash == _BACKGROUND_HASH
    assert info.assets[0].type_id == 0x11
    assert info.raw[info.assets[0].offset:info.assets[0].offset +
                    info.assets[0].size] == b'PAMXfirst'


def test_parse_little_endian(make_rpk: Callable[..., bytes], tmp_path: Path) -> None:
    pack = tmp_path / 'ui.rpk'
    pack.write_bytes(make_rpk(_ASSETS, _STRINGS, '<'))
    info = parse(pack)
    assert info.endian == '<'
    assert len(info.assets) == 4


def test_parse_skips_non_asset_group_chunks(make_rpk: Callable[..., bytes], tmp_path: Path) -> None:
    pack = tmp_path / 'ui.rpk'
    pack.write_bytes(make_rpk(_ASSETS, _STRINGS, '>', 2))
    assert len(parse(pack).assets) == 4


def test_parse_stops_at_a_truncated_asset_record(make_rpk: Callable[..., bytes],
                                                 tmp_path: Path) -> None:
    pack = tmp_path / 'ui.rpk'
    pack.write_bytes(make_rpk(_ASSETS, _STRINGS, truncate_first_aset=True))
    assert len(parse(pack).assets) == 1


def test_parse_stops_at_an_undersized_chunk(tmp_path: Path) -> None:
    pack = tmp_path / 'ui.rpk'
    pack.write_bytes(b'STRM' + struct.pack('>I', 16) + b'AGRP' + struct.pack('>I', 0))
    info = parse(pack)
    assert info.assets == ()
    assert info.strings == ()


def test_parse_stops_at_the_end_of_the_buffer(tmp_path: Path) -> None:
    pack = tmp_path / 'ui.rpk'
    pack.write_bytes(b'STRM' + struct.pack('>I', 24) + b'AGRP' + struct.pack('>I', 8) + b'STRS' +
                     struct.pack('>I', 8))
    assert parse(pack).assets == ()


def test_parse_rejects_an_unknown_container(tmp_path: Path) -> None:
    pack = tmp_path / 'ui.rpk'
    pack.write_bytes(b'NOPE' + b'\x00' * 12)
    with pytest.raises(ValueError, match='no STRM/MRTS'):
        parse(pack)


def test_read_rpk_decompresses_refpack(make_rpk: Callable[..., bytes],
                                       make_refpack_stream: Callable[[bytes], bytes],
                                       tmp_path: Path) -> None:
    raw = make_rpk(_ASSETS, _STRINGS)
    pack = tmp_path / 'ui.rpk'
    pack.write_bytes(make_refpack_stream(raw))
    assert read_rpk(pack) == raw


def test_extract_names_assets(make_rpk: Callable[..., bytes], tmp_path: Path) -> None:
    pack = tmp_path / 'ui.rpk'
    pack.write_bytes(make_rpk(_ASSETS, _STRINGS))
    out_dir, count = extract(pack)
    assert count == 4
    assert out_dir == tmp_path / 'ui'
    assert (out_dir / 'Background01.xmap').read_bytes() == b'PAMXfirst'
    assert (out_dir / 'firsttex.xmap').read_bytes() == b'PAMXsecond'
    assert (out_dir / 'asset0002_00000003.png').read_bytes() == b'\x89PNG\r\n\x1a\n'
    assert (out_dir / 'Background01_1.xmap').read_bytes() == b'PAMXclash'
    manifest = (out_dir / '_manifest.tsv').read_text().splitlines()
    assert manifest[0].split('\t') == ['name', 'magic', 'offset', 'size', 'nameHash', 'typeId']
    assert manifest[1].split('\t')[1] == 'PAMX'
    assert manifest[3].split('\t')[1] == '89504e47'


@pytest.mark.parametrize(('payload', 'ext'),
                         [(b'\x89PNG\r\n\x1a\n', 'png'), (b'OTTO\x00\x00\x00\x00', 'ttf'),
                          (b'RIFFsize', 'wav'), (b'true\x00\x00\x00\x00', 'ttf'),
                          (b'ttcf\x00\x00\x00\x00', 'ttf'), (b'\xff\xd8\xff\xe0data', 'jpg'),
                          (b'BM\x00\x00\x00\x00\x00\x00', 'bmp'), (b'ANIM\x00\x00\x00\x00', 'anim'),
                          (b'BUTT\x00\x00\x00\x00', 'butt'), (b'FntX\x00\x00\x00\x00', 'fntx'),
                          (b'MIXR\x00\x00\x00\x00', 'mixr'), (b'NPM7\x00\x00\x00\x00', 'npm7'),
                          (b'PAMC\x00\x00\x00\x00', 'pamc'), (b'PAMX\x00\x00\x00\x00', 'xmap'),
                          (b'SKUK\x00\x00\x00\x00', 'sku'), (b'VANB\x00\x00\x00\x00', 'vanb'),
                          (b'WXYZ\x00\x00\x00\x00', 'wxyz'),
                          (b'\x01\x02\x03\x04\x05\x06\x07\x08', 'bin')])
def test_extract_picks_the_extension(make_rpk: Callable[..., bytes], payload: bytes, ext: str,
                                     tmp_path: Path) -> None:
    pack = tmp_path / 'ui.rpk'
    pack.write_bytes(make_rpk(((0, 0, payload),)))
    out_dir, _count = extract(pack)
    assert (out_dir / f'asset0000_00000000.{ext}').read_bytes() == payload


def test_extract_without_assets(make_rpk: Callable[..., bytes], tmp_path: Path) -> None:
    pack = tmp_path / 'ui.rpk'
    pack.write_bytes(make_rpk((), ()))
    out_dir, count = extract(pack)
    assert count == 0
    assert sorted(p.name for p in out_dir.iterdir()) == ['_manifest.tsv']


def test_extract_all_assets_are_written(make_rpk: Callable[..., bytes], tmp_path: Path) -> None:
    assets: Sequence[tuple[int, int, bytes]] = tuple(
        (i, 0, b'ANIM' + bytes([i]) * 4) for i in range(3))
    pack = tmp_path / 'ui.rpk'
    pack.write_bytes(make_rpk(assets))
    out_dir, count = extract(pack)
    assert count == 3
    assert len(list(out_dir.glob('*.anim'))) == 3
