from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from PIL import Image
from destin.amplitude import bitmap
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

decode_abm = bitmap.decode_freq_abm
decode_hmx = bitmap.decode_hmx_bitmap


def _proxy(ref: str) -> bytes:
    # A reference proxy: a small header, the referenced name, then NUL padding.
    return bytes(20) + ref.encode() + b'\x00\x00\x00'


def test_parse_tex_reference_proxy() -> None:
    assert bitmap.parse_tex_reference(_proxy('image/bg_fog.bmp')) == 'image/bg_fog.bmp'


def test_parse_tex_reference_not_a_proxy() -> None:
    assert bitmap.parse_tex_reference(b'\x00\x01\x02\x03no name here') is None


def test_parse_tex_reference_too_large() -> None:
    assert bitmap.parse_tex_reference(b'\x00' * 5000 + b'x.bmp\x00') is None


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_link_references_symlink(tmp_path: Path) -> None:
    proxy = _write(tmp_path / 'screen' / 'bg_fog.bmp', _proxy('image/bg_fog.bmp'))
    target = _write(tmp_path / 'image' / 'gen' / 'bg_fog.png', b'real-png-bytes')
    assert bitmap.link_references(tmp_path, copy=False) == 1
    link = proxy.with_suffix('.png')
    assert link.is_symlink()
    assert link.resolve() == target.resolve()
    assert not proxy.exists()  # The redundant proxy is removed.


def test_link_references_copy(tmp_path: Path) -> None:
    proxy = _write(tmp_path / 'screen' / 'bg_fog.bmp', _proxy('image/bg_fog.bmp'))
    _write(tmp_path / 'image' / 'gen' / 'bg_fog.png', b'real-png-bytes')
    assert bitmap.link_references(tmp_path, copy=True) == 1
    link = proxy.with_suffix('.png')
    assert not link.is_symlink()
    assert link.read_bytes() == b'real-png-bytes'
    assert not proxy.exists()  # The redundant proxy is removed.


def test_link_references_cleans_orphaned_proxy(tmp_path: Path) -> None:
    # A proxy left beside a symlink by an earlier run is cleaned up on a later run.
    target = _write(tmp_path / 'image' / 'bg.png', b'real')
    proxy = _write(tmp_path / 'screen' / 'bg.bmp', _proxy('image/bg.bmp'))
    link = proxy.with_suffix('.png')
    link.symlink_to(target)
    assert bitmap.link_references(tmp_path, copy=False) == 1
    assert not proxy.exists()
    assert link.is_symlink()


def test_link_references_picks_nearest(tmp_path: Path) -> None:
    proxy = _write(tmp_path / 'a' / 'b' / 'tex.bmp', _proxy('tex.bmp'))
    near = _write(tmp_path / 'a' / 'b' / 'pool' / 'tex.png', b'near')
    _write(tmp_path / 'z' / 'tex.png', b'far')
    assert bitmap.link_references(tmp_path, copy=False) == 1
    assert proxy.with_suffix('.png').resolve() == near.resolve()


def test_link_references_dangling(tmp_path: Path) -> None:
    proxy = _write(tmp_path / 'screen' / 'missing.bmp', _proxy('image/missing.bmp'))
    assert bitmap.link_references(tmp_path, copy=False) == 0
    assert not proxy.with_suffix('.png').exists()


def test_link_references_skips_existing(tmp_path: Path) -> None:
    proxy = _write(tmp_path / 'screen' / 'bg.bmp', _proxy('image/bg.bmp'))
    _write(tmp_path / 'image' / 'bg.png', b'real')
    _write(proxy.with_suffix('.png'), b'already-here')
    assert bitmap.link_references(tmp_path, copy=False) == 0
    assert proxy.with_suffix('.png').read_bytes() == b'already-here'
    assert proxy.exists()  # A real PNG holds the slot, so the proxy is left untouched.


@pytest.mark.parametrize('ref', ['ab.tex', 'sub/dir/thing.bmp', 'image/xx.tga'])
def test_parse_tex_reference_extensions(ref: str) -> None:
    assert bitmap.parse_tex_reference(_proxy(ref)) == ref


def _freq_tex(name: str = 'circ_shuttle.bmp',
              *,
              version: int = 4,
              width: int = 64,
              height: int = 64,
              bpp: int = 8) -> bytes:
    return struct.pack('<4I', version, width, height, bpp) + name.encode() + b'\x00' * 8


@pytest.mark.parametrize('bpp', [4, 8, 32])
def test_decode_hmx_bitmap(make_hmx_bitmap: Callable[..., bytes], bpp: int) -> None:
    decoded = decode_hmx(make_hmx_bitmap(4, 4, bpp=bpp))
    assert decoded is not None
    width, height, rgba = decoded
    assert (width, height) == (4, 4)
    assert len(rgba) == 4 * 4 * 4


def test_decode_hmx_bitmap_scales_alpha(make_hmx_bitmap: Callable[..., bytes]) -> None:
    decoded = decode_hmx(make_hmx_bitmap(2, 2, bpp=32))
    assert decoded is not None
    assert decoded[2][3] == min(255, 3 * 2)


@pytest.mark.parametrize('data', [
    b'\x00' * 8,
    b'\x01' + bytes(31),
    b'\x00\x08\x09' + bytes(29),
])
def test_decode_hmx_bitmap_not_an_hmx(data: bytes) -> None:
    assert decode_hmx(data) is None


@pytest.mark.parametrize(('bpp', 'width', 'height'), [(16, 4, 4), (8, 0, 4), (8, 4, 0)])
def test_decode_hmx_bitmap_bad_header(bpp: int, width: int, height: int) -> None:
    data = bytes((0, bpp, 3, 1)) + struct.pack('<HH', width, height) + bytes(1024)
    assert decode_hmx(data) is None


def test_decode_hmx_bitmap_truncated_palette() -> None:
    assert decode_hmx(bytes((0, 8, 3, 1)) + struct.pack('<HH', 4, 4) + bytes(24)) is None


def test_decode_hmx_bitmap_truncated_pixels(make_hmx_bitmap: Callable[..., bytes]) -> None:
    assert decode_hmx(make_hmx_bitmap(4, 4, bpp=8)[:-4]) is None


def test_decode_hmx_bitmap_truncated_direct_pixels(make_hmx_bitmap: Callable[..., bytes]) -> None:
    assert decode_hmx(make_hmx_bitmap(4, 4, bpp=32)[:-4]) is None


@pytest.mark.parametrize('bpp', [4, 8, 32])
def test_decode_freq_abm(make_abm: Callable[..., bytes], bpp: int) -> None:
    decoded = decode_abm(make_abm(4, 4, bpp=bpp))
    assert decoded is not None
    assert decoded[:2] == (4, 4)
    assert len(decoded[2]) == 4 * 4 * 4


def test_decode_freq_abm_rle(make_abm: Callable[..., bytes]) -> None:
    plain = decode_abm(make_abm(4, 4, bpp=8))
    packed = decode_abm(make_abm(4, 4, bpp=8, rle=True))
    assert plain is not None
    assert packed == plain  # The run/literal codec round-trips to the same pixels.


@pytest.mark.parametrize('data', [b'\x00' * 16, b'\x01' + bytes(64)])
def test_decode_freq_abm_not_an_abm(data: bytes) -> None:
    assert decode_abm(data) is None


@pytest.mark.parametrize(('width', 'height', 'stride'), [(0, 4, 4), (4, 0, 4), (4, 4, 0),
                                                         (9000, 4, 4)])
def test_decode_freq_abm_bad_dimensions(width: int, height: int, stride: int) -> None:
    data = (bytes(6) + struct.pack('<HHH', width, height, stride) + bytes(4) +
            struct.pack('<I', 16) + bytes(1040))
    assert decode_abm(data) is None


def test_decode_freq_abm_unexpected_size(make_abm: Callable[..., bytes]) -> None:
    assert decode_abm(make_abm(4, 4, bpp=8) + b'extra') is None


def test_decode_freq_abm_truncated_rle() -> None:
    # One literal byte then a repeat control with no payload: the codec cannot fill the image.
    region = b'\x81A\x02'
    data = (bytes(6) + struct.pack('<HHH', 4, 4, 4) + bytes(4) + struct.pack('<I', len(region)) +
            bytes(12) + bytes(1024) + region)
    assert decode_abm(data) is None


def test_convert_hmx_bitmap(make_hmx_bitmap: Callable[..., bytes], tmp_path: Path) -> None:
    source = _write(tmp_path / 'logo.bmp', make_hmx_bitmap(4, 4, bpp=8))
    out = bitmap.convert(source)
    assert out == tmp_path / 'logo.png'
    assert not source.exists()
    with Image.open(out) as image:
        assert image.size == (4, 4)


def test_convert_freq_abm(make_abm: Callable[..., bytes], tmp_path: Path) -> None:
    source = _write(tmp_path / 'logo.abm', make_abm(4, 4, bpp=8))
    out = bitmap.convert(source)
    assert out == tmp_path / 'logo.png'
    assert not source.exists()


def test_convert_falls_back_to_pillow(tmp_path: Path) -> None:
    source = tmp_path / 'plain.bmp'
    Image.new('RGB', (3, 2), (10, 20, 30)).save(source)
    out = bitmap.convert(source)
    assert out == tmp_path / 'plain.png'
    assert not source.exists()
    with Image.open(out) as image:
        assert image.size == (3, 2)


def test_convert_returns_none_on_junk(tmp_path: Path) -> None:
    source = _write(tmp_path / 'junk.bmp', b'not an image at all' * 4)
    assert bitmap.convert(source) is None
    assert source.exists()


def test_parse_freq_tex_reference() -> None:
    assert bitmap.parse_freq_tex_reference(_freq_tex()) == 'circ_shuttle.bmp'


@pytest.mark.parametrize('data', [
    b'\x04\x00',
    struct.pack('<4I', 9, 64, 64, 8) + b'a.bmp\x00',
    struct.pack('<4I', 4, 0, 64, 8) + b'a.bmp\x00',
    struct.pack('<4I', 4, 64, 64, 7) + b'a.bmp\x00',
    struct.pack('<4I', 4, 64, 64, 8) + b'\x00' * 8,
    struct.pack('<4I', 4, 64, 64, 8) + b'a\x01b.bmp\x00',
    struct.pack('<4I', 4, 64, 64, 8) + b'a.png\x00',
])
def test_parse_freq_tex_reference_rejects(data: bytes) -> None:
    assert bitmap.parse_freq_tex_reference(data) is None


def test_link_references_resolves_freq_descriptor(tmp_path: Path) -> None:
    proxy = _write(tmp_path / 'screen' / 'circ.bmp', _freq_tex('circ_shuttle.bmp'))
    target = _write(tmp_path / 'image' / 'circ_shuttle_bmp.png', b'real')
    assert bitmap.link_references(tmp_path) == 1  # Defaults to a symlink on POSIX.
    assert proxy.with_suffix('.png').resolve() == target.resolve()


def test_link_references_ignores_non_proxies(tmp_path: Path) -> None:
    _write(tmp_path / 'screen' / 'thing.tex', b'\x11' * 64)
    _write(tmp_path / 'image' / 'thing.png', b'real')
    assert bitmap.link_references(tmp_path, copy=False) == 0
