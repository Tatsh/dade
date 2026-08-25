"""Tests for :py:mod:`dade.misc.macho`."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
import hashlib
import struct

import pytest

from dade.misc.macho import read_macho

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def test_thin_arm64_header(macho_arm64: Path) -> None:
    info = read_macho(macho_arm64)
    assert info['is_universal'] is False
    assert info['name'] == 'Example'
    assert info['size'] == macho_arm64.stat().st_size
    assert len(info['architectures']) == 1
    arch = info['architectures'][0]
    assert arch['architecture'] == 'arm64'
    assert arch['file_type'] == 'execute'
    assert arch['load_command_count'] == 10


def test_thin_arm64_flags(macho_arm64: Path) -> None:
    assert read_macho(macho_arm64)['architectures'][0]['flags'] == [
        'NOUNDEFS', 'DYLDLINK', 'TWOLEVEL', 'PIE'
    ]


def test_thin_arm64_segments(macho_arm64: Path) -> None:
    segments = read_macho(macho_arm64)['architectures'][0]['segments']
    assert [s['name'] for s in segments] == ['__PAGEZERO', '__TEXT']
    assert segments[1]['sections'] == ['__TEXT,__text', '__TEXT,__cstring']
    assert segments[1]['vm_address'] == 0x1000
    assert segments[1]['file_offset'] == 0x3000


def test_thin_arm64_dylibs(macho_arm64: Path) -> None:
    arch = read_macho(macho_arm64)['architectures'][0]
    assert arch['dylibs'] == ['/usr/lib/libSystem.B.dylib']
    assert arch['weak_dylibs'] == ['/System/Library/Frameworks/WebKit.framework/WebKit']
    assert arch['rpaths'] == ['@executable_path/Frameworks']


def test_thin_arm64_uuid_and_versions(macho_arm64: Path) -> None:
    arch = read_macho(macho_arm64)['architectures'][0]
    assert arch['uuid'] == '00010203-0405-0607-0809-0A0B0C0D0E0F'
    assert arch['source_version'] == '1.2.3.0.0'
    assert arch['minimum_os'] == {'platform': 'iOS', 'sdk': '10.3.0', 'version': '9.0.0'}


def test_thin_arm64_encryption(macho_arm64: Path) -> None:
    assert read_macho(macho_arm64)['architectures'][0]['encryption'] == {
        'encrypted': True,
        'id': 1,
        'offset': 0x4000,
        'size': 0x1000
    }


def test_thin_arm64_entitlements(macho_arm64: Path) -> None:
    assert read_macho(macho_arm64)['architectures'][0]['entitlements'] == {
        'application-identifier': 'ABCDE12345.com.example.app'
    }


def test_thin_armv7(macho_armv7: Path) -> None:
    arch = read_macho(macho_armv7)['architectures'][0]
    assert arch['architecture'] == 'armv7'
    assert [s['name'] for s in arch['segments']] == ['__TEXT']
    assert arch['segments'][0]['sections'] == ['__TEXT,__text']
    assert arch['minimum_os'] == {'platform': 'iOS', 'sdk': '7.1.0', 'version': '6.0.0'}
    assert arch['entitlements'] is None
    assert arch['encryption'] is None


def test_universal_reads_every_slice(macho_universal: Path) -> None:
    info = read_macho(macho_universal)
    assert info['is_universal'] is True
    assert [a['architecture'] for a in info['architectures']] == ['armv7', 'arm64']


@pytest.mark.parametrize(('cpu_type', 'cpu_subtype', 'expected'), [
    (0x0100_000C, 2, 'arm64e'),
    (0x0100_000C, 99, 'arm64(99)'),
    (12, 11, 'armv7s'),
    (12, 99, 'arm(99)'),
    (0x0100_0007, 3, 'x86_64'),
    (0x0BAD, 0, 'cpu(2989)'),
])
def test_architecture_names(tmp_path: Path, macho_builder: type[Any], cpu_type: int,
                            cpu_subtype: int, expected: str) -> None:
    path = tmp_path / 'Slice'
    path.write_bytes(macho_builder(cpu_type=cpu_type, cpu_subtype=cpu_subtype).build())
    assert read_macho(path)['architectures'][0]['architecture'] == expected


def test_unknown_file_type(tmp_path: Path, macho_builder: type[Any]) -> None:
    path = tmp_path / 'Odd'
    path.write_bytes(macho_builder(file_type=99).build())
    assert read_macho(path)['architectures'][0]['file_type'] == 'type(99)'


def test_unknown_build_platform(tmp_path: Path, macho_builder: type[Any]) -> None:
    builder = macho_builder()
    builder.add(0x32, struct.pack('<III', 99, 0x0001_0000, 0x0002_0000))
    path = tmp_path / 'Odd'
    path.write_bytes(builder.build())
    assert read_macho(path)['architectures'][0]['minimum_os'] == {
        'platform': 'platform(99)',
        'sdk': '2.0.0',
        'version': '1.0.0'
    }


def test_a_short_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / 'Stub'
    path.write_bytes(b'\xcf\xfa')
    with pytest.raises(ValueError, match='Too short to be a Mach-O image'):
        read_macho(path)


def test_a_foreign_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / 'Text'
    path.write_bytes(b'not a Mach-O image at all')
    with pytest.raises(ValueError, match='Not a little-endian Mach-O slice'):
        read_macho(path)


def test_a_truncated_load_command_stops_the_walk(tmp_path: Path, macho_builder: type[Any]) -> None:
    builder = macho_builder()
    builder.add_segment('__TEXT')
    # A command claiming more bytes than the image holds, which must end the walk rather than
    # read past the buffer.
    builder.add_raw(struct.pack('<II', 0x19, 0x1000))
    path = tmp_path / 'Truncated'
    path.write_bytes(builder.build())
    arch = read_macho(path)['architectures'][0]
    assert [s['name'] for s in arch['segments']] == ['__TEXT']


def test_a_command_smaller_than_its_header_stops_the_walk(tmp_path: Path,
                                                          macho_builder: type[Any]) -> None:
    builder = macho_builder()
    builder.add_raw(struct.pack('<II', 0x19, 4))
    path = tmp_path / 'Bad'
    path.write_bytes(builder.build())
    assert read_macho(path)['architectures'][0]['segments'] == []


def test_a_header_promising_more_commands_than_it_holds(tmp_path: Path,
                                                        macho_builder: type[Any]) -> None:
    builder = macho_builder()
    builder.add_segment('__TEXT')
    image = bytearray(builder.build())
    struct.pack_into('<I', image, 16, 4)
    path = tmp_path / 'Overpromised'
    path.write_bytes(bytes(image))
    assert [s['name'] for s in read_macho(path)['architectures'][0]['segments']] == ['__TEXT']


@pytest.mark.parametrize('signature', [
    b'',
    b'\x00' * 32,
    struct.pack('>III', 0xFADE_0CC0, 12, 4),
])
def test_an_unreadable_signature_yields_no_entitlements(make_signed_macho: Callable[[bytes], Path],
                                                        signature: bytes) -> None:
    assert read_macho(make_signed_macho(signature))['architectures'][0]['entitlements'] is None


@pytest.mark.parametrize('plist', [b'not a plist', b'<plist><array/></plist>'])
def test_entitlements_that_are_not_a_dictionary(make_signature: Callable[[bytes], bytes],
                                                make_signed_macho: Callable[[bytes], Path],
                                                plist: bytes) -> None:
    signed = make_signed_macho(make_signature(plist))
    assert read_macho(signed)['architectures'][0]['entitlements'] is None


def test_a_segment_claiming_more_sections_than_it_holds(tmp_path: Path,
                                                        macho_builder: type[Any]) -> None:
    builder = macho_builder()
    body = b'__TEXT'.ljust(16, b'\0') + struct.pack('<QQQQiiII', 0, 0, 0, 0, 7, 5, 4, 0)
    builder.add(0x19, body)
    path = tmp_path / 'Short'
    path.write_bytes(builder.build())
    assert read_macho(path)['architectures'][0]['segments'][0]['sections'] == []


def test_a_dylib_name_beyond_its_command(tmp_path: Path, macho_builder: type[Any]) -> None:
    builder = macho_builder()
    builder.add(0xC, struct.pack('<I', 0x1000))
    path = tmp_path / 'Odd'
    path.write_bytes(builder.build())
    assert read_macho(path)['architectures'][0]['dylibs'] == ['']


def test_a_signature_index_pointing_past_its_blob(
        make_signed_macho: Callable[[bytes], Path]) -> None:
    # One index entry whose blob offset lies outside the super-blob, which must be skipped rather
    # than read.
    signature = (struct.pack('>III', 0xFADE_0CC0, 28, 1) + struct.pack('>II', 5, 0x1000))
    assert read_macho(make_signed_macho(signature))['architectures'][0]['entitlements'] is None


def test_a_signature_holding_no_entitlements_blob(
        make_signed_macho: Callable[[bytes], Path]) -> None:
    # A well-formed super-blob whose only member is a requirements blob, so the loop runs to its
    # end without finding anything.
    other = struct.pack('>II', 0xFADE_0C00, 8)
    signature = (struct.pack('>III', 0xFADE_0CC0, 20 + len(other), 1) + struct.pack('>II', 2, 20) +
                 other)
    assert read_macho(make_signed_macho(signature))['architectures'][0]['entitlements'] is None


def test_a_load_command_the_reader_does_not_name(tmp_path: Path, macho_builder: type[Any]) -> None:
    builder = macho_builder()
    builder.add_segment('__TEXT')
    # LC_SYMTAB, which the reader walks past without recording.
    builder.add(0x2, struct.pack('<IIII', 0, 0, 0, 0))
    path = tmp_path / 'Plain'
    path.write_bytes(builder.build())
    assert [s['name'] for s in read_macho(path)['architectures'][0]['segments']] == ['__TEXT']


def test_the_digest_covers_the_whole_file(macho_arm64: Path) -> None:
    image = macho_arm64.read_bytes()
    info = read_macho(macho_arm64)
    assert info['sha256'] == hashlib.sha256(image).hexdigest()
    assert info['size'] == len(image)


@pytest.mark.parametrize(('wide', 'cpu_type'), [(True, 0x0100_000C), (False, 12)])
def test_a_segment_records_every_address_field(tmp_path: Path, macho_builder: type[Any],
                                               cpu_type: int, *, wide: bool) -> None:
    builder = macho_builder(cpu_type=cpu_type, wide=wide)
    builder.add_segment('__TEXT', ('__text',))
    path = tmp_path / 'Seg'
    path.write_bytes(builder.build())
    assert read_macho(path)['architectures'][0]['segments'][0] == {
        'file_offset': 0x3000,
        'file_size': 0x4000,
        'name': '__TEXT',
        'sections': ['__TEXT,__text'],
        'vm_address': 0x1000,
        'vm_size': 0x2000
    }


@pytest.mark.parametrize(('trim', 'expected'), [(0, ['__TEXT,__text']), (1, [])])
def test_a_section_is_kept_only_when_both_its_names_fit(tmp_path: Path, macho_builder: type[Any],
                                                        trim: int, expected: list[str]) -> None:
    # A section entry is only read for its two names, so 32 bytes is enough and 31 is not.
    whole = (b'__TEXT'.ljust(16, b'\0') + struct.pack('<QQQQiiII', 0, 0, 0, 0, 7, 5, 1, 0) +
             b'__text'.ljust(16, b'\0') + b'__TEXT'.ljust(16, b'\0'))
    body = whole[:len(whole) - trim]
    builder = macho_builder()
    # add() pads to a four-byte boundary, which would put the trimmed byte back.
    builder.add_raw(struct.pack('<II', 0x19, len(body) + 8) + body)
    path = tmp_path / 'Sections'
    path.write_bytes(builder.build())
    assert read_macho(path)['architectures'][0]['segments'][0]['sections'] == expected


@pytest.mark.parametrize(('command', 'crypt_id', 'encrypted'), [(0x21, 0, False), (0x21, 1, True),
                                                                (0x2C, 0, False), (0x2C, 2, True)])
def test_both_encryption_commands_and_both_states(tmp_path: Path, macho_builder: type[Any],
                                                  command: int, crypt_id: int, *,
                                                  encrypted: bool) -> None:
    builder = macho_builder()
    builder.add(command, struct.pack('<IIII', 0x4000, 0x1000, crypt_id, 0))
    path = tmp_path / 'Crypt'
    path.write_bytes(builder.build())
    assert read_macho(path)['architectures'][0]['encryption'] == {
        'encrypted': encrypted,
        'id': crypt_id,
        'offset': 0x4000,
        'size': 0x1000
    }


@pytest.mark.parametrize(('command', 'weak'), [(0xC, False), (0xD, False),
                                               (0x1F | 0x8000_0000, False),
                                               (0x18 | 0x8000_0000, True)])
def test_every_dylib_command_lands_in_its_own_list(tmp_path: Path, macho_builder: type[Any],
                                                   command: int, *, weak: bool) -> None:
    name = '/usr/lib/libSystem.B.dylib'
    builder = macho_builder()
    builder.add_string_command(command, name)
    path = tmp_path / 'Linked'
    path.write_bytes(builder.build())
    arch = read_macho(path)['architectures'][0]
    assert arch['dylibs'] == ([] if weak else [name])
    assert arch['weak_dylibs'] == ([name] if weak else [])


@pytest.mark.parametrize(('command', 'platform'), [(0x24, 'macOS'), (0x25, 'iOS'), (0x2E, 'tvOS'),
                                                   (0x30, 'watchOS')])
def test_every_older_minimum_os_command(tmp_path: Path, macho_builder: type[Any], command: int,
                                        platform: str) -> None:
    builder = macho_builder()
    builder.add(command, struct.pack('<II', 0x0001_0203, 0x0004_0506))
    path = tmp_path / 'Old'
    path.write_bytes(builder.build())
    assert read_macho(path)['architectures'][0]['minimum_os'] == {
        'platform': platform,
        'sdk': '4.5.6',
        'version': '1.2.3'
    }


def test_a_version_field_at_its_widest(tmp_path: Path, macho_builder: type[Any]) -> None:
    builder = macho_builder()
    builder.add(0x32, struct.pack('<III', 2, 0xFFFF_FFFF, 0x0102_0304))
    path = tmp_path / 'Wide'
    path.write_bytes(builder.build())
    assert read_macho(path)['architectures'][0]['minimum_os'] == {
        'platform': 'iOS',
        'sdk': '258.3.4',
        'version': '65535.255.255'
    }


def test_the_source_version_splits_into_five_fields(tmp_path: Path,
                                                    macho_builder: type[Any]) -> None:
    builder = macho_builder()
    builder.add(
        0x2A,
        struct.pack('<Q', (0xFF_FFFF << 40) | (1023 << 30) | (1022 << 20) | (1021 << 10) | 1020))
    path = tmp_path / 'Sourced'
    path.write_bytes(builder.build())
    assert read_macho(path)['architectures'][0]['source_version'] == '16777215.1023.1022.1021.1020'


@pytest.mark.parametrize(('flags', 'expected'), [(0, []), (0x3, ['NOUNDEFS', 'INCRLINK']),
                                                 (0x8000_0000, ['DYLIB_IN_CACHE'])])
def test_the_header_flags_are_named_in_order(tmp_path: Path, macho_builder: type[Any], flags: int,
                                             expected: list[str]) -> None:
    path = tmp_path / 'Flagged'
    path.write_bytes(macho_builder(flags=flags).build())
    assert read_macho(path)['architectures'][0]['flags'] == expected


def test_a_universal_slice_resolves_its_signature_at_its_own_offset(macho_universal: Path) -> None:
    # The signed slice does not start the file, so its code-signature offset only reaches the
    # super-blob once the slice's own offset is added to it.
    architectures = read_macho(macho_universal)['architectures']
    assert architectures[1]['entitlements'] == {
        'application-identifier': 'ABCDE12345.com.example.app'
    }
    assert architectures[0]['entitlements'] is None


def test_a_universal_image_with_the_sixty_four_bit_fat_header(tmp_path: Path,
                                                              macho_arm64: Path) -> None:
    data = macho_arm64.read_bytes()
    header = struct.pack('>II', 0xCAFE_BABF, 1)
    entry = struct.pack('>iiQQII', 0x0100_000C, 0, 0x1000, len(data), 12, 0)
    padding = b'\0' * (0x1000 - len(header) - len(entry))
    path = tmp_path / 'Fat64'
    path.write_bytes(header + entry + padding + data)
    info = read_macho(path)
    assert info['is_universal'] is True
    assert info['architectures'][0]['architecture'] == 'arm64'
