"""Tests for :py:mod:`destin.common.image`."""
from __future__ import annotations

import pytest

from destin.common.image import double_ps2_alpha, expand5, expand6, ps2_clut_swizzle_index


@pytest.mark.parametrize(('alpha', 'expected'), [(0, 0), (1, 2), (64, 128), (127, 254), (128, 255),
                                                 (200, 255), (255, 255)])
def test_double_ps2_alpha(alpha: int, expected: int) -> None:
    assert double_ps2_alpha(alpha) == expected


@pytest.mark.parametrize(('value', 'expected'), [(0, 0), (1, 8), (0x10, 0x84), (0x1F, 0xFF)])
def test_expand5(value: int, expected: int) -> None:
    assert expand5(value) == expected


@pytest.mark.parametrize(('value', 'expected'), [(0, 0), (1, 4), (0x20, 0x82), (0x3F, 0xFF)])
def test_expand6(value: int, expected: int) -> None:
    assert expand6(value) == expected


@pytest.mark.parametrize(('index', 'expected'), [(0, 0), (0x08, 0x10), (0x10, 0x08), (0x18, 0x18),
                                                 (0x07, 0x07), (0xFF, 0xFF), (0x28, 0x30)])
def test_ps2_clut_swizzle_index(index: int, expected: int) -> None:
    assert ps2_clut_swizzle_index(index) == expected
