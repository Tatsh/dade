"""Tests for :mod:`destin.thps2pc.raster`."""
from __future__ import annotations

import pytest

from destin.thps2pc import raster


def _pixel(framebuffer: raster.Framebuffer, x: int, y: int) -> tuple[int, int, int]:
    body = framebuffer.to_ppm().split(b'255\n', 1)[1]
    offset = (y * framebuffer.width + x) * 3
    return (body[offset], body[offset + 1], body[offset + 2])


def test_framebuffer_starts_filled_with_the_background() -> None:
    framebuffer = raster.Framebuffer(2, 2, (1, 2, 3))
    assert _pixel(framebuffer, 0, 0) == (1, 2, 3)


def test_to_ppm_header_and_length() -> None:
    ppm = raster.Framebuffer(3, 2).to_ppm()
    assert ppm.startswith(b'P6\n3 2\n255\n')
    assert len(ppm) == len(b'P6\n3 2\n255\n') + 3 * 2 * 3


def test_put_writes_a_pixel() -> None:
    framebuffer = raster.Framebuffer(4, 4)
    framebuffer.put(1, 2, (9, 8, 7))
    assert _pixel(framebuffer, 1, 2) == (9, 8, 7)


@pytest.mark.parametrize(('x', 'y'), [(-1, 0), (0, -1), (4, 0), (0, 4)])
def test_put_ignores_out_of_bounds(x: int, y: int) -> None:
    framebuffer = raster.Framebuffer(4, 4, (5, 5, 5))
    framebuffer.put(x, y, (200, 200, 200))
    assert framebuffer.to_ppm().count(bytes((200, 200, 200))) == 0


def test_fill_triangle_covers_its_interior() -> None:
    framebuffer = raster.Framebuffer(8, 8)
    framebuffer.fill_triangle(((0.0, 0.0), (7.0, 0.0), (0.0, 7.0)), (255, 0, 0))
    assert _pixel(framebuffer, 1, 1) == (255, 0, 0)
    assert _pixel(framebuffer, 7, 7) == (0, 0, 0)


def test_fill_triangle_ignores_degenerate_input() -> None:
    framebuffer = raster.Framebuffer(4, 4, (7, 7, 7))
    framebuffer.fill_triangle(((0.0, 0.0), (2.0, 2.0), (1.0, 1.0)), (255, 255, 255))
    assert framebuffer.to_ppm().count(bytes((255, 255, 255))) == 0


def test_fill_triangle_draws_both_windings() -> None:
    clockwise = raster.Framebuffer(8, 8)
    clockwise.fill_triangle(((0.0, 0.0), (0.0, 7.0), (7.0, 0.0)), (1, 2, 3))
    assert _pixel(clockwise, 1, 1) == (1, 2, 3)


def test_depth_buffer_keeps_the_nearest_triangle() -> None:
    framebuffer = raster.Framebuffer(8, 8)
    corners = ((0.0, 0.0), (7.0, 0.0), (0.0, 7.0))
    framebuffer.fill_triangle(corners, (10, 10, 10), 5.0)
    framebuffer.fill_triangle(corners, (20, 20, 20), 9.0)
    assert _pixel(framebuffer, 1, 1) == (10, 10, 10)
    framebuffer.fill_triangle(corners, (30, 30, 30), 1.0)
    assert _pixel(framebuffer, 1, 1) == (30, 30, 30)


def test_fill_disc_covers_a_radius() -> None:
    framebuffer = raster.Framebuffer(11, 11)
    framebuffer.fill_disc((5.0, 5.0), 2, (4, 5, 6))
    assert _pixel(framebuffer, 5, 5) == (4, 5, 6)
    assert _pixel(framebuffer, 5, 7) == (4, 5, 6)
    assert _pixel(framebuffer, 5, 9) == (0, 0, 0)


def test_fit_maps_the_bounds_into_the_padded_canvas() -> None:
    projection = raster.fit(((0.0, 0.0), (10.0, 10.0)), 120, 120, 10)
    assert projection.apply((0.0, 0.0)) == (10.0, 10.0)
    assert projection.apply((10.0, 10.0)) == (110.0, 110.0)


def test_fit_preserves_aspect_ratio() -> None:
    projection = raster.fit(((0.0, 0.0), (10.0, 5.0)), 120, 120, 10)
    assert projection.scale == pytest.approx(10.0)


def test_fit_rejects_an_empty_point_set() -> None:
    with pytest.raises(ValueError, match=r'empty set of points'):
        raster.fit((), 10, 10, 1)


def test_project_isometric() -> None:
    assert raster.project_isometric((0, 0, 0)) == (0.0, 0.0)
    x, y = raster.project_isometric((10, 0, -10))
    assert x == pytest.approx(14.14)
    assert y == pytest.approx(0.0)
