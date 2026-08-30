from __future__ import annotations

import struct

import pytest

from dade.sopranos.prop import (
    is_alternate,
    read_items,
    read_materials,
    read_packets,
    read_sections,
    wardrobe_key,
)

from .conftest import build_library, build_section, gif_tag, prop_packet

_TRIANGLE = [(0.0, 0.0, 0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 1.0, 0.0), (0.0, 1.0, 0.0, 0.0, 1.0)]


def _one_section() -> bytes:
    return build_library([
        build_section('lib/chair', [('body.tga',), ('shadow.tga',)],
                      [('chair', [(0, [prop_packet(_TRIANGLE)])]),
                       ('shadow', [(1, [prop_packet(_TRIANGLE)])])])
    ])


def _body(data: bytes) -> bytes:
    section, = read_sections(data)
    return data[section.offset:section.offset + section.size]


def test_read_sections_walks_the_chain() -> None:
    first = build_section('lib/a', [], [])
    second = build_section('lib/b', [], [])
    assert [s.name for s in read_sections(build_library([first, second]))] == ['lib/a', 'lib/b']


def test_read_sections_ignores_a_tiny_file() -> None:
    assert read_sections(b'abc') == ()


def test_read_sections_stops_on_a_zero_length_section() -> None:
    data = bytearray(_one_section())
    section, = read_sections(bytes(data))
    struct.pack_into('<I', data, section.offset + 0x0C, 0)
    assert read_sections(bytes(data)) == ()


def test_read_sections_stops_when_a_section_runs_past_the_end() -> None:
    data = bytearray(_one_section())
    section, = read_sections(bytes(data))
    struct.pack_into('<I', data, section.offset + 0x0C, 0xFFFFFF)
    assert read_sections(bytes(data)) == ()


def test_read_sections_stops_on_a_name_past_the_end() -> None:
    data = bytearray(_one_section())
    section, = read_sections(bytes(data))
    struct.pack_into('<I', data, section.offset + 0x08, 0xFFFFFF)
    assert read_sections(bytes(data)) == ()


def test_read_sections_stops_when_a_name_is_unterminated() -> None:
    data = bytearray(_one_section())
    section, = read_sections(bytes(data))
    struct.pack_into('<I', data, section.offset + 0x08, 0x08)
    assert read_sections(bytes(data).replace(b'\0', b'x')) == ()


def test_read_materials_lists_each_materials_maps() -> None:
    section = build_section('lib/x', [('base.tga', 'ref.tga'), ()], [])
    assert read_materials(_body(build_library([section]))) == (('base.tga', 'ref.tga'), ())


def test_read_materials_ignores_a_tiny_section() -> None:
    assert read_materials(bytes(16)) == ()


def test_read_materials_ignores_a_table_past_the_end() -> None:
    data = bytearray(_one_section())
    section, = read_sections(bytes(data))
    struct.pack_into('<I', data, section.offset + 0x50, 0xFFFFFF)
    assert read_materials(_body(bytes(data))) == ()


def test_read_items_gives_each_group_its_material() -> None:
    items = read_items(_body(_one_section()))
    assert [item.name for item in items] == ['chair', 'shadow']
    assert [group.material for item in items for group in item.groups] == [0, 1]
    assert len(items[0].groups[0].packets[0][1]) == 3


def test_read_items_ignores_a_tiny_section() -> None:
    assert read_items(bytes(16)) == ()


def test_read_items_ignores_a_table_past_the_end() -> None:
    data = bytearray(_one_section())
    section, = read_sections(bytes(data))
    struct.pack_into('<I', data, section.offset + 0x54, 0xFFFFFF)
    assert read_items(_body(bytes(data))) == ()


def test_read_items_skips_an_item_with_no_geometry() -> None:
    data = bytearray(_one_section())
    section, = read_sections(bytes(data))
    table = section.offset + struct.unpack_from('<I', data, section.offset + 0x54)[0]
    struct.pack_into('<I', data, table + 0x08, 0)
    assert [item.name for item in read_items(_body(bytes(data)))] == ['shadow']


def test_read_items_skips_an_item_pointing_outside_the_section() -> None:
    data = bytearray(_one_section())
    section, = read_sections(bytes(data))
    table = section.offset + struct.unpack_from('<I', data, section.offset + 0x54)[0]
    struct.pack_into('<i', data, table + 0x0C, -0xFFFF)
    assert [item.name for item in read_items(_body(bytes(data)))] == ['shadow']


def test_read_items_skips_an_item_with_an_absurd_command_count() -> None:
    data = bytearray(_one_section())
    section, = read_sections(bytes(data))
    table = section.offset + struct.unpack_from('<I', data, section.offset + 0x54)[0]
    geometry = table + struct.unpack_from('<i', data, table + 0x0C)[0]
    struct.pack_into('<I', data, geometry + 0x0C, 0xFFFF)
    assert [item.name for item in read_items(_body(bytes(data)))] == ['shadow']


def test_read_items_drops_a_group_that_draws_nothing() -> None:
    section = build_section('lib/x', [('a.tga',)], [('empty', [(0, [])])])
    assert read_items(_body(build_library([section]))) == ()


@pytest.mark.parametrize(('name', 'alternate', 'key'), [('*BODY17', True, 'BODY'),
                                                        ('*BODY18', True, 'BODY'),
                                                        ('*HEAD7_Face_0', True, 'HEAD_Face_'),
                                                        ('*HEAD08_Face_0', True, 'HEAD_Face_'),
                                                        ('VITO_BODY', False, 'VITO_BODY')])
def test_wardrobe_grouping(*, alternate: bool, key: str, name: str) -> None:
    assert is_alternate(name) is alternate
    assert wardrobe_key(name) == key


def test_read_packets_accepts_the_four_register_form() -> None:
    body = b''.join(struct.pack('<8f', 0, 0, 0, 0, 0, 0, 0, 0) for _ in range(3))
    packets = list(read_packets(gif_tag(3, 3, nreg=4) + body))
    assert len(packets) == 1
    assert len(packets[0][1]) == 3


def test_read_packets_skips_a_tag_with_the_wrong_register_count() -> None:
    body = b''.join(struct.pack('<8f', 0, 0, 0, 0, 0, 0, 0, 0) for _ in range(3))
    assert list(read_packets(gif_tag(3, 3, nreg=2) + body)) == []


def test_read_packets_skips_a_tag_with_an_unknown_primitive() -> None:
    body = b''.join(struct.pack('<8f', 0, 0, 0, 0, 0, 0, 0, 0) for _ in range(3))
    assert list(read_packets(gif_tag(3, 1) + body)) == []


def test_read_packets_skips_a_packet_running_past_the_end() -> None:
    assert list(read_packets(gif_tag(9, 3) + bytes(32))) == []


def test_read_packets_skips_a_vertex_that_is_not_finite() -> None:
    body = bytearray(b''.join(struct.pack('<8f', 0, 0, 0, 0, 0, 0, 0, 0) for _ in range(3)))
    struct.pack_into('<f', body, 0, float('nan'))
    assert list(read_packets(gif_tag(3, 3) + bytes(body))) == []


def test_read_packets_skips_a_vertex_far_outside_the_world() -> None:
    body = bytearray(b''.join(struct.pack('<8f', 0, 0, 0, 0, 0, 0, 0, 0) for _ in range(3)))
    struct.pack_into('<f', body, 0, 1e9)
    assert list(read_packets(gif_tag(3, 3) + bytes(body))) == []


def test_read_packets_honours_a_start_and_end() -> None:
    packet = prop_packet(_TRIANGLE)
    data = bytes(16) + packet
    assert list(read_packets(data, 0, 16)) == []
    assert len(list(read_packets(data, 16, len(data)))) == 1


def test_read_sections_stops_when_a_name_never_ends() -> None:
    raw = bytearray(0x38)
    struct.pack_into('<I', raw, 0x0C, 0x10)
    struct.pack_into('<I', raw, 0x10 + 0x08, 0x20)
    struct.pack_into('<I', raw, 0x10 + 0x0C, 0x20)
    raw[0x30:0x38] = b'AAAAAAAA'
    assert read_sections(bytes(raw)) == ()


def test_read_items_leaves_a_name_empty_when_the_offset_points_at_a_terminator() -> None:
    data = bytearray(_one_section())
    section, = read_sections(bytes(data))
    table = section.offset + struct.unpack_from('<I', data, section.offset + 0x54)[0]
    # 0x60 is the first byte of the string blob, which is the terminator itself.
    struct.pack_into('<i', data, table, 0x60 - (table - section.offset))
    assert not read_items(_body(bytes(data)))[0].name


def test_read_items_passes_over_commands_it_does_not_know() -> None:
    data = bytearray(_one_section())
    section, = read_sections(bytes(data))
    table = section.offset + struct.unpack_from('<I', data, section.offset + 0x54)[0]
    geometry = table + struct.unpack_from('<i', data, table + 0x0C)[0]
    commands = geometry + 0x10 + struct.unpack_from('<I', data, geometry)[0]
    struct.pack_into('<H', data, commands, 99)
    items = read_items(_body(bytes(data)))
    # The group still closes, but with the material left at its default.
    assert items[0].groups[0].material == 0
