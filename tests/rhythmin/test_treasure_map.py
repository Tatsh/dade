"""Tests for :py:mod:`destin.rhythmin.treasure_map`."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image
from destin.rhythmin.treasure_map import (
    map_to_json,
    parse_treasure_map,
    read_treasure_map,
    render_ascii,
    render_image,
)
import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture


def test_header_fields(treasure_map_bytes: bytes) -> None:
    board = parse_treasure_map(treasure_map_bytes, 'map_042.map')
    assert board.head == (1, 2)
    assert board.main_title == '探検航海'
    assert board.sub_title == '船出'
    assert board.header_value == 3
    assert board.trailing_bytes == 0
    assert board.title == '探検航海 - 船出'


def test_squares(treasure_map_bytes: bytes) -> None:
    squares = parse_treasure_map(treasure_map_bytes).squares
    assert len(squares) == 4
    assert squares[0].back is None
    assert squares[0].kind_name == 'start'
    assert squares[1].kind_name == 'treasure'
    # The format's line break is resolved on the way out.
    assert squares[1].text == 'たからばこ\nだ！'  # noqa: RUF001
    assert squares[1].links == (2, 3)
    assert squares[2].kind_name == 'warp'
    assert squares[2].slot == 5


def test_edges_are_deduplicated(treasure_map_bytes: bytes) -> None:
    # Squares 2 and 3 link to each other, so that corridor appears once.
    assert parse_treasure_map(treasure_map_bytes).edges == ((0, 1), (1, 2), (1, 3), (2, 3))


def test_kind_counts(treasure_map_bytes: bytes) -> None:
    assert parse_treasure_map(treasure_map_bytes).kind_counts == {
        'start': 1,
        'treasure': 1,
        'warp': 2
    }


def test_title_falls_back_to_the_file_name(treasure_map_bytes: bytes) -> None:
    board = parse_treasure_map(treasure_map_bytes, 'map_000.map')._replace(main_title='',
                                                                           sub_title='  ')
    assert board.title == 'map_000.map'


def test_map_to_json(treasure_map_bytes: bytes) -> None:
    rendered = map_to_json(parse_treasure_map(treasure_map_bytes, 'map_042.map'))
    assert rendered['file'] == 'map_042.map'
    assert rendered['square_count'] == 4
    assert rendered['edges'] == [[0, 1], [1, 2], [1, 3], [2, 3]]
    assert rendered['squares'][0]['type_name'] == 'start'
    assert rendered['type_counts'] == {'start': 1, 'treasure': 1, 'warp': 2}


def test_render_ascii(treasure_map_bytes: bytes) -> None:
    rows = render_ascii(parse_treasure_map(treasure_map_bytes))
    assert rows[0] == 'S---T---W'
    assert '|' in rows[1]


def test_render_image(treasure_map_bytes: bytes, tmp_path: Path) -> None:
    path = tmp_path / 'board.png'
    width, height = render_image(parse_treasure_map(treasure_map_bytes, 'map_042.map'), path)
    assert path.is_file()
    with Image.open(path) as image:
        assert image.size == (width, height)


def test_render_image_with_an_empty_legend(treasure_map_bytes: bytes, tmp_path: Path,
                                           mocker: MockerFixture) -> None:
    # With no glyphs the legend wraps to nothing, so the trailing-line append is skipped.
    mocker.patch('destin.rhythmin.treasure_map.GRID_GLYPHS', {})
    path = tmp_path / 'board.png'
    render_image(parse_treasure_map(treasure_map_bytes, 'map_042.map'), path)
    assert path.is_file()


def test_read_treasure_map(treasure_map_file: Path) -> None:
    assert read_treasure_map(treasure_map_file).name == 'map_042.map'


def test_rejects_a_short_file() -> None:
    with pytest.raises(ValueError, match='Too short for a map file'):
        parse_treasure_map(b'\0' * 16)


def test_rejects_a_bad_square_count() -> None:
    with pytest.raises(ValueError, match='Bad square count'):
        parse_treasure_map(b'\0' * (0x50 + 0xAA))
