from __future__ import annotations

from typing import TYPE_CHECKING

from destin.amplitude import bitmap
import pytest

if TYPE_CHECKING:
    from pathlib import Path


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
