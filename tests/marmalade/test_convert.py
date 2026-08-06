"""Tests for :mod:`destin.marmalade.convert`."""
from __future__ import annotations

from typing import TYPE_CHECKING

from destin.marmalade.convert import ConvertOptions, decode_group_to_dir
from destin.marmalade.test_utils import (
    build_font,
    build_material,
    build_model,
    build_resgroup,
    build_texture,
)

if TYPE_CHECKING:
    from pathlib import Path


def _group() -> bytes:
    model = build_model([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])
    texture = build_texture(2, 2, 4, bytes(range(16)))
    return build_resgroup('demo', {
        'CIwModel': [model],
        'CIwTexture': [texture],
        'UnknownThing': [b'\xca\xfe']
    })


def test_decode_group_writes_open_formats(tmp_path: Path) -> None:
    counts = decode_group_to_dir(_group(), tmp_path)
    assert counts['CIwModel'] == 1
    assert counts['CIwTexture'] == 1
    assert list((tmp_path / 'CIwModel').glob('*.obj'))
    assert list((tmp_path / 'CIwModel').glob('*.html'))
    assert list((tmp_path / 'CIwTexture').glob('*.png'))
    # Resource names are not stored in a group, so an unknown class surfaces as
    # 'class_<hash>' and its body is dumped raw as a .bin.
    unknown = [name for name in counts if name.startswith('class_')]
    assert len(unknown) == 1
    assert list((tmp_path / unknown[0]).glob('*.bin'))


def test_html_can_be_disabled(tmp_path: Path) -> None:
    decode_group_to_dir(_group(), tmp_path, ConvertOptions(html=False))
    assert list((tmp_path / 'CIwModel').glob('*.obj'))
    assert not list((tmp_path / 'CIwModel').glob('*.html'))


def test_raw_mode_dumps_bin(tmp_path: Path) -> None:
    decode_group_to_dir(_group(), tmp_path,
                        ConvertOptions(png=False, material_json=False, obj=False, html=False))
    assert list((tmp_path / 'CIwModel').glob('*.bin'))
    assert not list((tmp_path / 'CIwModel').glob('*.obj'))


def _mixed_group() -> bytes:
    good_model = build_model([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])
    faceless_model = build_model([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 0, 1)])
    return build_resgroup(
        'demo', {
            'CIwModel': [good_model, faceless_model, b'\x00\x00\x00\x00'],
            'CIwTexture': [build_texture(2, 2, 4, bytes(range(16))), b'\x00' * 8],
            'CIwGxFont': [build_font(pitch=2, height=2), b'\x00' * 0x60],
            'CIwMaterial': [build_material(flags=0x1, texture_hashes=(0xABC,))]
        })


def test_decode_group_converts_fonts_and_materials(tmp_path: Path) -> None:
    decode_group_to_dir(_mixed_group(), tmp_path)
    assert list((tmp_path / 'CIwGxFont').glob('*.png'))
    assert list((tmp_path / 'CIwMaterial').glob('*.json'))
    # The undecodable font (decoder returns None) is dumped raw alongside the converted one.
    assert len(list((tmp_path / 'CIwGxFont').glob('*.bin'))) == 1


def test_undecodable_resources_fall_back_to_raw(tmp_path: Path) -> None:
    decode_group_to_dir(_mixed_group(), tmp_path)
    # The undecodable texture (decoder returns None) and the malformed model (decoder raises)
    # are both dumped as raw .bin alongside the converted resources.
    assert len(list((tmp_path / 'CIwTexture').glob('*.png'))) == 1
    assert len(list((tmp_path / 'CIwTexture').glob('*.bin'))) == 1
    assert len(list((tmp_path / 'CIwModel').glob('*.obj'))) == 2
    assert len(list((tmp_path / 'CIwModel').glob('*.bin'))) == 1


def test_faceless_model_emits_obj_but_no_viewer(tmp_path: Path) -> None:
    # A model whose only triangle is degenerate has no faces, so the viewer is skipped while the
    # OBJ is still written.
    group = build_resgroup(
        'demo', {'CIwModel': [build_model([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 0, 1)])]})
    decode_group_to_dir(group, tmp_path)
    assert list((tmp_path / 'CIwModel').glob('*.obj'))
    assert not list((tmp_path / 'CIwModel').glob('*.html'))
