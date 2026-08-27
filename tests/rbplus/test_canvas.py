"""Tests for :py:mod:`dade.rbplus.canvas`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET  # noqa: S405

from PIL import Image
import pytest

from dade.rbplus.canvas import PillowCanvas, SVGCanvas, canvas_for

if TYPE_CHECKING:
    from pathlib import Path

_SVG_NS = '{http://www.w3.org/2000/svg}'
_BACKGROUND = (24, 24, 32)
_RED = (255, 0, 0)
_GREEN = (0, 255, 0)


def _svg_root(markup: str) -> ET.Element:
    return ET.fromstring(markup)  # noqa: S314


@pytest.mark.parametrize(('suffix', 'expected'), [('.png', PillowCanvas), ('.PNG', PillowCanvas),
                                                  ('.svg', SVGCanvas)])
def test_canvas_for_picks_by_suffix(suffix: str, expected: type) -> None:
    assert type(canvas_for(suffix, 10, 10, _BACKGROUND)) is expected


def test_canvas_for_refuses_an_unknown_suffix() -> None:
    with pytest.raises(ValueError, match='No surface writes'):
        canvas_for('.gif', 10, 10, _BACKGROUND)


@pytest.mark.parametrize('suffix', ['.html', '.htm'])
def test_canvas_for_sends_a_page_to_the_site_command(suffix: str) -> None:
    with pytest.raises(ValueError, match='dade rbplus site'):
        canvas_for(suffix, 10, 10, _BACKGROUND)


def test_the_raster_surface_writes_a_png(tmp_path: Path) -> None:
    canvas = PillowCanvas(90, 60, _BACKGROUND)
    canvas.rect((0, 0, 30, 30), fill=_RED, outline=_GREEN, width=2)
    canvas.ellipse((30, 0, 60, 30), fill=_RED)
    canvas.pieslice((60, 0, 90, 30), 180, 360, fill=_GREEN)
    canvas.line((0, 40, 45, 50, 90, 40), fill=_RED, width=3, joint='curve')
    canvas.text((0, 50), 'hello', fill=_GREEN, size=9)
    out = tmp_path / 'canvas.png'
    assert canvas.save(out, scale=1.0, supersample=3) == (30, 20)
    with Image.open(out) as image:
        assert image.size == (30, 20)


def test_the_raster_surface_scales(tmp_path: Path) -> None:
    canvas = PillowCanvas(90, 60, _BACKGROUND)
    assert canvas.save(tmp_path / 'canvas.png', scale=3.0, supersample=3) == (90, 60)


def test_the_raster_surface_drops_a_note_s_details(tmp_path: Path) -> None:
    canvas = PillowCanvas(30, 30, _BACKGROUND)
    with canvas.note({'id': '1'}):
        canvas.ellipse((0, 0, 10, 10), fill=_RED)
    assert canvas.save(tmp_path / 'canvas.png', scale=1.0, supersample=1) == (30, 30)


def test_the_vector_surface_is_well_formed_xml() -> None:
    canvas = SVGCanvas(90, 60, _BACKGROUND)
    canvas.rect((0, 0, 30, 30), fill=_RED, outline=_GREEN, width=2)
    canvas.ellipse((30, 0, 60, 30), fill=_RED)
    canvas.line((0, 40, 45, 50), fill=_RED, width=3)
    canvas.text((0, 50), 'hello', fill=_GREEN, size=9)
    root = _svg_root(canvas.to_svg(scale=1.0, supersample=3))
    assert root.tag == f'{_SVG_NS}svg'
    assert root.get('viewBox') == '0 0 90 60'
    assert root.get('width') == '30'
    assert root.get('height') == '20'
    assert root.find(f'.//{_SVG_NS}rect') is not None
    assert root.find(f'.//{_SVG_NS}ellipse') is not None
    assert root.find(f'.//{_SVG_NS}polyline') is not None
    assert root.find(f'.//{_SVG_NS}text') is not None


def test_the_vector_surface_paints_a_hollow_shape() -> None:
    canvas = SVGCanvas(30, 30, _BACKGROUND)
    canvas.rect((0, 0, 10, 10), outline=_GREEN)
    rect = _svg_root(canvas.to_svg(scale=1.0, supersample=1)).find(f'.//{_SVG_NS}rect[@stroke]')
    assert rect is not None
    assert rect.get('fill') == 'none'


def test_the_vector_surface_rounds_a_curved_joint() -> None:
    canvas = SVGCanvas(30, 30, _BACKGROUND)
    canvas.line((0, 0, 10, 10, 20, 0), fill=_RED, joint='curve')
    canvas.line((0, 20, 20, 20), fill=_RED)
    lines = _svg_root(canvas.to_svg(scale=1.0, supersample=1)).findall(f'.//{_SVG_NS}polyline')
    assert lines[0].get('stroke-linejoin') == 'round'
    assert lines[1].get('stroke-linejoin') is None


def test_the_vector_surface_draws_a_pie_slice() -> None:
    canvas = SVGCanvas(30, 30, _BACKGROUND)
    canvas.pieslice((0, 0, 20, 20), 180, 360, fill=_GREEN)
    path = _svg_root(canvas.to_svg(scale=1.0, supersample=1)).find(f'.//{_SVG_NS}path')
    assert path is not None
    assert path.get('d', '').startswith('M 10 10 L')


def test_a_pie_slice_the_long_way_round_says_so() -> None:
    canvas = SVGCanvas(30, 30, _BACKGROUND)
    canvas.pieslice((0, 0, 20, 20), 0, 270, fill=_GREEN)
    path = _svg_root(canvas.to_svg(scale=1.0, supersample=1)).find(f'.//{_SVG_NS}path')
    assert path is not None
    assert ' 1 1 ' in path.get('d', '')


def test_the_vector_surface_escapes_its_text() -> None:
    canvas = SVGCanvas(30, 30, _BACKGROUND)
    canvas.text((0, 0), 'a & b <c>', fill=_GREEN, size=9)
    text = _svg_root(canvas.to_svg(scale=1.0, supersample=1)).find(f'.//{_SVG_NS}text')
    assert text is not None
    assert text.text == 'a & b <c>'


def test_the_vector_surface_groups_a_note() -> None:
    canvas = SVGCanvas(30, 30, _BACKGROUND)
    with canvas.note({'id': '7'}):
        canvas.ellipse((0, 0, 10, 10), fill=_RED)
    assert canvas.notes == ({'id': '7'},)
    group = _svg_root(canvas.to_svg(scale=1.0,
                                    supersample=1)).find(f'.//{_SVG_NS}g[@class="rb-note"]')
    assert group is not None
    assert group.get('data-note') == '0'
    assert [child.tag for child in group] == [f'{_SVG_NS}ellipse']


def test_the_vector_surface_writes_no_group_for_a_note_that_drew_nothing() -> None:
    canvas = SVGCanvas(30, 30, _BACKGROUND)
    with canvas.note({'id': '7'}):
        pass
    assert _svg_root(canvas.to_svg(scale=1.0,
                                   supersample=1)).find(f'.//{_SVG_NS}g[@class="rb-note"]') is None


def test_the_vector_surface_writes_no_group_for_a_head_that_drew_nothing() -> None:
    canvas = SVGCanvas(30, 30, _BACKGROUND)
    with canvas.head():
        pass
    assert _svg_root(canvas.to_svg(scale=1.0,
                                   supersample=1)).find(f'.//{_SVG_NS}g[@class="rb-head"]') is None


def _raise_while_drawing(canvas: SVGCanvas) -> None:
    with canvas.note({'id': '1'}):
        msg = 'drawing went wrong'
        raise RuntimeError(msg)


def test_the_vector_surface_closes_a_group_that_raised() -> None:
    canvas = SVGCanvas(30, 30, _BACKGROUND)
    with pytest.raises(RuntimeError):
        _raise_while_drawing(canvas)
    # The group is still closed, so the document parses.
    assert _svg_root(canvas.to_svg(scale=1.0, supersample=1)) is not None


def test_the_vector_surface_writes_a_file(tmp_path: Path) -> None:
    canvas = SVGCanvas(90, 60, _BACKGROUND)
    out = tmp_path / 'canvas.svg'
    assert canvas.save(out, scale=1.0, supersample=3) == (30, 20)
    assert _svg_root(out.read_text()) is not None


def test_the_vector_surface_marks_ruling_by_kind() -> None:
    canvas = SVGCanvas(90, 60, _BACKGROUND)
    with canvas.marks('lane'):
        canvas.line((0, 0, 0, 60), fill=_GREEN)
    with canvas.marks('time'):
        canvas.line((0, 0, 90, 0), fill=_GREEN)
    markup = canvas.to_svg(scale=1.0, supersample=3)
    assert 'class="rb-rule rb-rule-lane"' in markup
    assert 'class="rb-rule rb-rule-time"' in markup


def test_the_vector_surface_ties_a_shape_to_a_note() -> None:
    canvas = SVGCanvas(90, 60, _BACKGROUND)
    with canvas.tied(7):
        canvas.line((0, 0, 10, 10), fill=_GREEN)
    assert 'data-tie="7"' in canvas.to_svg(scale=1.0, supersample=3)


@pytest.mark.parametrize('wrapper', ['marks', 'tied'])
def test_the_vector_surface_writes_nothing_for_an_empty_group(wrapper: str) -> None:
    canvas = SVGCanvas(90, 60, _BACKGROUND)
    with getattr(canvas, wrapper)('lane' if wrapper == 'marks' else 0):
        pass
    markup = canvas.to_svg(scale=1.0, supersample=3)
    assert 'rb-rule' not in markup
    assert 'data-tie' not in markup
