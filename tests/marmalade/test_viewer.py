"""Tests for :mod:`destin.marmalade.viewer`."""
from __future__ import annotations

from destin.marmalade.model import decode_model
from destin.marmalade.test_utils import build_model
from destin.marmalade.viewer import obj_to_html


def test_obj_to_html_embeds_geometry() -> None:
    obj = decode_model(build_model([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])).to_obj()
    html = obj_to_html(obj, title='spinny')
    assert html is not None
    assert '<canvas' in html
    assert 'const POS' in html
    assert 'spinny' in html
    # The render loop is embedded verbatim, not escaped.
    assert 'requestAnimationFrame' in html
    assert 'i&lt;' not in html


def test_obj_to_html_returns_none_without_faces() -> None:
    assert obj_to_html('v 0 0 0\nv 1 0 0\n') is None


def test_obj_to_html_ignores_blank_lines() -> None:
    obj = '\nv 0 0 0\nv 1 0 0\nv 0 1 0\n\nf 1 2 3\n'
    assert obj_to_html(obj) is not None
