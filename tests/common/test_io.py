from __future__ import annotations

from typing import TYPE_CHECKING
import io
import struct

import pytest

from destin.common.io import (
    BytesReader,
    MmapReader,
    Reader,
    copy_region,
    f32,
    i16,
    i32,
    read_cstring,
    read_cstring_at,
    resolve_reader,
    u8,
    u16,
    u32,
)

if TYPE_CHECKING:
    from pathlib import Path

    from destin.common.typing import Endian


def test_bytes_reader_size_and_read() -> None:
    reader = BytesReader(b'0123456789')
    assert reader.size == 10
    assert reader.read(2, 3) == b'234'


def test_bytes_reader_is_reader() -> None:
    assert isinstance(BytesReader(b''), Reader)


def test_mmap_reader_reads_file(tmp_path: Path) -> None:
    path = tmp_path / 'data.bin'
    path.write_bytes(b'abcdefgh')
    with MmapReader(path) as reader:
        assert reader.size == 8
        assert reader.read(2, 3) == b'cde'


def test_mmap_reader_rejects_empty_file(tmp_path: Path) -> None:
    empty = tmp_path / 'empty.bin'
    empty.touch()
    with pytest.raises(ValueError, match='mmap'):
        MmapReader(empty)


def test_resolve_reader_bytes_owns_nothing() -> None:
    reader, owned = resolve_reader(b'payload')
    assert isinstance(reader, BytesReader)
    assert owned is None


def test_resolve_reader_path_owns_mmap(tmp_path: Path) -> None:
    path = tmp_path / 'data.bin'
    path.write_bytes(b'payload')
    reader, owned = resolve_reader(path)
    assert isinstance(reader, MmapReader)
    assert owned is reader
    owned.close()


def test_resolve_reader_passes_through_existing_reader() -> None:
    existing = BytesReader(b'x')
    reader, owned = resolve_reader(existing)
    assert reader is existing
    assert owned is None


def test_u8_reads_at_offset() -> None:
    assert u8(b'\x00\x2a', 1) == 0x2a


@pytest.mark.parametrize(('endian', 'raw'), [('<', b'\x2a\x01'), ('>', b'\x01\x2a')])
def test_u16_respects_endianness(endian: Endian, raw: bytes) -> None:
    assert u16(raw, endian=endian) == 0x012a


@pytest.mark.parametrize(('endian', 'raw'), [('<', b'\x2a\x01\x00\x00'),
                                             ('>', b'\x00\x00\x01\x2a')])
def test_u32_respects_endianness(endian: Endian, raw: bytes) -> None:
    assert u32(raw, endian=endian) == 0x0000012a


def test_u16_defaults_to_little_endian() -> None:
    assert u16(b'\x01\x00') == 1


def test_i16_reads_signed() -> None:
    assert i16(b'\xff\xff') == -1


def test_i32_reads_signed() -> None:
    assert i32(b'\xff\xff\xff\xff') == -1


def test_f32_reads_float() -> None:
    assert f32(struct.pack('<f', 1.5)) == pytest.approx(1.5)


def test_scalar_reads_apply_offset() -> None:
    assert u32(b'\xff\xff' + struct.pack('<I', 0x0badf00d), 2) == 0x0badf00d


def test_read_cstring_reads_to_terminator() -> None:
    assert read_cstring(b'\x00name\x00rest', 1) == 'name'


def test_read_cstring_without_terminator_reads_to_end() -> None:
    assert read_cstring(b'tail') == 'tail'


def test_read_cstring_honours_encoding() -> None:
    assert read_cstring(b'caf\xc3\xa9\x00', encoding='utf-8') == 'café'


def test_read_cstring_at_advances_past_terminator() -> None:
    assert read_cstring_at(b'ab\x00cd\x00', 3) == ('cd', 6)


def test_read_cstring_at_without_terminator_returns_length() -> None:
    assert read_cstring_at(b'xyz') == ('xyz', 3)


def test_read_cstring_at_honours_encoding() -> None:
    assert read_cstring_at(b'\xc3\xa9\x00', encoding='utf-8') == ('é', 3)


def test_copy_region_copies_slice(tmp_path: Path) -> None:
    dst = tmp_path / 'out.bin'
    assert copy_region(io.BytesIO(b'0123456789'), 2, 3, dst) == 3
    assert dst.read_bytes() == b'234'


def test_copy_region_copies_in_chunks(tmp_path: Path) -> None:
    dst = tmp_path / 'out.bin'
    assert copy_region(io.BytesIO(b'abcdef'), 0, 6, dst, chunk=2) == 6
    assert dst.read_bytes() == b'abcdef'


def test_copy_region_stops_early_on_short_read(tmp_path: Path) -> None:
    dst = tmp_path / 'out.bin'
    assert copy_region(io.BytesIO(b'ab'), 0, 5, dst) == 2
    assert dst.read_bytes() == b'ab'


def test_copy_region_strict_raises_on_short_read(tmp_path: Path) -> None:
    dst = tmp_path / 'out.bin'
    with pytest.raises(EOFError, match='short read'):
        copy_region(io.BytesIO(b'ab'), 0, 5, dst, strict=True)
