"""
A reader for the properties of a Mach-O executable.

The game ships one thin ``arm64`` executable, but a download from another era may hold a universal
image with several slices, so both are handled. Nothing here decrypts anything: an App Store
executable is still enciphered, which the ``LC_ENCRYPTION_INFO`` command in the result reports.

Only what describes the image is read - its header, its segments and sections, the libraries it
links, its UUID, its minimum OS, and the entitlements inside its code signature. The entitlements
are the one part that is not a load command: the signature is a super-blob of length-prefixed
blobs, and the entitlements are the one whose magic is ``0xfade7171``, holding an XML property
list.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final
from xml.parsers.expat import ExpatError
import hashlib
import plistlib
import struct

if TYPE_CHECKING:
    from pathlib import Path

    from destin.misc.typing import MachOArchDict, MachODict, MachOSegmentDict

__all__ = ('CPU_TYPES', 'FILE_TYPES', 'PLATFORMS', 'read_macho')

CPU_TYPES: Final = {
    7: 'x86',
    0x0100_0007: 'x86_64',
    12: 'arm',
    0x0100_000C: 'arm64',
    0x0200_000C: 'arm64_32'
}
"""CPU type to a readable name.

:meta hide-value:
"""
FILE_TYPES: Final = {
    1: 'object',
    2: 'execute',
    3: 'fvmlib',
    4: 'core',
    5: 'preload',
    6: 'dylib',
    7: 'dylinker',
    8: 'bundle',
    9: 'dylib_stub',
    10: 'dsym',
    11: 'kext_bundle'
}
"""Mach-O file type to a readable name.

:meta hide-value:
"""
PLATFORMS: Final = {
    1: 'macOS',
    2: 'iOS',
    3: 'tvOS',
    4: 'watchOS',
    5: 'bridgeOS',
    6: 'macCatalyst',
    7: 'iOSSimulator',
    8: 'tvOSSimulator',
    9: 'watchOSSimulator',
    10: 'driverKit'
}
"""``LC_BUILD_VERSION`` platform to a readable name.

:meta hide-value:
"""

_FAT_MAGIC = 0xCAFE_BABE
_FAT_MAGIC_64 = 0xCAFE_BABF
_FAT_MAGICS = (_FAT_MAGIC, _FAT_MAGIC_64)
_MAGIC_64 = 0xFEED_FACF
_MAGIC_32 = 0xFEED_FACE
_CPU_TYPE_ARM = 12
_CPU_TYPE_ARM64 = 0x0100_000C
_ARM64_SUBTYPES = {0: 'arm64', 1: 'arm64v8', 2: 'arm64e'}
_ARM_SUBTYPES = {6: 'armv6', 9: 'armv7', 11: 'armv7s', 12: 'armv7k'}
_HEADER_FLAGS: Final = (
    (0x1, 'NOUNDEFS'),
    (0x2, 'INCRLINK'),
    (0x4, 'DYLDLINK'),
    (0x8, 'BINDATLOAD'),
    (0x10, 'PREBOUND'),
    (0x20, 'SPLIT_SEGS'),
    (0x40, 'LAZY_INIT'),
    (0x80, 'TWOLEVEL'),
    (0x100, 'FORCE_FLAT'),
    (0x200, 'NOMULTIDEFS'),
    (0x400, 'NOFIXPREBINDING'),
    (0x800, 'PREBINDABLE'),
    (0x1000, 'ALLMODSBOUND'),
    (0x2000, 'SUBSECTIONS_VIA_SYMBOLS'),
    (0x4000, 'CANONICAL'),
    (0x8000, 'WEAK_DEFINES'),
    (0x1_0000, 'BINDS_TO_WEAK'),
    (0x2_0000, 'ALLOW_STACK_EXECUTION'),
    (0x4_0000, 'ROOT_SAFE'),
    (0x8_0000, 'SETUID_SAFE'),
    (0x10_0000, 'NO_REEXPORTED_DYLIBS'),
    (0x20_0000, 'PIE'),
    (0x40_0000, 'DEAD_STRIPPABLE_DYLIB'),
    (0x80_0000, 'HAS_TLV_DESCRIPTORS'),
    (0x100_0000, 'NO_HEAP_EXECUTION'),
    (0x200_0000, 'APP_EXTENSION_SAFE'),
    (0x400_0000, 'NLIST_OUTOFSYNC_WITH_DYLDINFO'),
    (0x800_0000, 'SIM_SUPPORT'),
    (0x8000_0000, 'DYLIB_IN_CACHE'),
)
_LC_REQ_DYLD = 0x8000_0000
_LC_SEGMENT = 0x1
_LC_SEGMENT_64 = 0x19
_LC_LOAD_DYLIB = 0xC
_LC_ID_DYLIB = 0xD
_LC_LOAD_WEAK_DYLIB = 0x18 | _LC_REQ_DYLD
_LC_REEXPORT_DYLIB = 0x1F | _LC_REQ_DYLD
_LC_RPATH = 0x1C | _LC_REQ_DYLD
_LC_UUID = 0x1B
_LC_CODE_SIGNATURE = 0x1D
_LC_ENCRYPTION_INFO = 0x21
_LC_ENCRYPTION_INFO_64 = 0x2C
_LC_SOURCE_VERSION = 0x2A
_LC_BUILD_VERSION = 0x32
_VERSION_MIN_PLATFORMS = {0x24: 'macOS', 0x25: 'iOS', 0x2E: 'tvOS', 0x30: 'watchOS'}
_ENTITLEMENTS_MAGIC = 0xFADE_7171
_SUPER_BLOB_MAGICS = (0xFADE_0CC0, 0xFADE_0C01, 0xFADE_0C02)
_MIN_LOAD_COMMAND_SIZE = 8
_MIN_IMAGE_SIZE = 8
_FAT_ARCH_SIZE = 20
_FAT_ARCH_SIZE_64 = 32
_HEADER_SIZE_32 = 28
_HEADER_SIZE_64 = 32
_SUPER_BLOB_HEADER_SIZE = 12
_BLOB_HEADER_SIZE = 8


def _architecture(cpu_type: int, cpu_subtype: int) -> str:
    masked = cpu_subtype & 0x00FF_FFFF
    if cpu_type == _CPU_TYPE_ARM64:
        return _ARM64_SUBTYPES.get(masked, f'arm64({masked})')
    if cpu_type == _CPU_TYPE_ARM:
        return _ARM_SUBTYPES.get(masked, f'arm({masked})')
    return CPU_TYPES.get(cpu_type, f'cpu({cpu_type})')


def _version(packed: int) -> str:
    return f'{packed >> 16}.{(packed >> 8) & 0xFF}.{packed & 0xFF}'


def _source_version(packed: int) -> str:
    return (f'{packed >> 40}.{(packed >> 30) & 0x3FF}.{(packed >> 20) & 0x3FF}.'
            f'{(packed >> 10) & 0x3FF}.{packed & 0x3FF}')


def _cstring(body: bytes, offset: int) -> str:
    if offset >= len(body):
        return ''
    return body[offset:].split(b'\0', 1)[0].decode('utf-8', 'replace')


def _flag_names(flags: int) -> list[str]:
    return [name for bit, name in _HEADER_FLAGS if flags & bit]


def _sections(body: bytes, count: int, offset: int, stride: int) -> list[str]:
    out = []
    for i in range(count):
        base = offset + i * stride
        if base + 32 > len(body):
            break
        section = body[base:base + 16].split(b'\0', 1)[0].decode('utf-8', 'replace')
        segment = body[base + 16:base + 32].split(b'\0', 1)[0].decode('utf-8', 'replace')
        out.append(f'{segment},{section}')
    return out


def _segment(body: bytes, *, wide: bool) -> MachOSegmentDict:
    name = body[0:16].split(b'\0', 1)[0].decode('utf-8', 'replace')
    if wide:
        vm_address, vm_size, file_offset, file_size = struct.unpack_from('<QQQQ', body, 16)
        section_count = struct.unpack_from('<I', body, 56)[0]
        sections = _sections(body, section_count, 64, 80)
    else:
        vm_address, vm_size, file_offset, file_size = struct.unpack_from('<IIII', body, 16)
        section_count = struct.unpack_from('<I', body, 40)[0]
        sections = _sections(body, section_count, 48, 68)
    return {
        'file_offset': file_offset,
        'file_size': file_size,
        'name': name,
        'sections': sections,
        'vm_address': vm_address,
        'vm_size': vm_size
    }


def _entitlements(image: bytes, offset: int, size: int) -> dict[str, Any] | None:
    blob = image[offset:offset + size]
    if len(blob) < _SUPER_BLOB_HEADER_SIZE:
        return None
    magic, _, count = struct.unpack_from('>III', blob, 0)
    if magic not in _SUPER_BLOB_MAGICS:
        return None
    for i in range(count):
        base = _SUPER_BLOB_HEADER_SIZE + i * _BLOB_HEADER_SIZE
        if base + _BLOB_HEADER_SIZE > len(blob):
            break
        entry_offset = struct.unpack_from('>I', blob, base + 4)[0]
        if entry_offset + _BLOB_HEADER_SIZE > len(blob):
            continue
        entry_magic, entry_length = struct.unpack_from('>II', blob, entry_offset)
        if entry_magic != _ENTITLEMENTS_MAGIC:
            continue
        body = blob[entry_offset + _BLOB_HEADER_SIZE:entry_offset + entry_length]
        try:
            loaded = plistlib.loads(body)
        except (plistlib.InvalidFileException, ValueError, ExpatError):
            return None
        return loaded if isinstance(loaded, dict) else None
    return None


# Fold one load command into the slice being built. The image and its slice offset are still
# needed because the code-signature command points at bytes outside its own body.
def _apply_command(arch: MachOArchDict, command: int, body: bytes, image: bytes,
                   offset: int) -> None:
    if command in {_LC_SEGMENT, _LC_SEGMENT_64}:
        arch['segments'].append(_segment(body, wide=command == _LC_SEGMENT_64))
    elif command in {_LC_LOAD_DYLIB, _LC_ID_DYLIB, _LC_REEXPORT_DYLIB, _LC_LOAD_WEAK_DYLIB}:
        name = _cstring(body, struct.unpack_from('<I', body, 0)[0] - _MIN_LOAD_COMMAND_SIZE)
        if command == _LC_LOAD_WEAK_DYLIB:
            arch['weak_dylibs'].append(name)
        else:
            arch['dylibs'].append(name)
    elif command == _LC_RPATH:
        arch['rpaths'].append(
            _cstring(body,
                     struct.unpack_from('<I', body, 0)[0] - _MIN_LOAD_COMMAND_SIZE))
    elif command == _LC_UUID:
        raw = body[:16].hex().upper()
        arch['uuid'] = f'{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}'
    elif command == _LC_SOURCE_VERSION:
        arch['source_version'] = _source_version(struct.unpack_from('<Q', body, 0)[0])
    elif command in _VERSION_MIN_PLATFORMS:
        version, sdk = struct.unpack_from('<II', body, 0)
        arch['minimum_os'] = {
            'platform': _VERSION_MIN_PLATFORMS[command],
            'sdk': _version(sdk),
            'version': _version(version)
        }
    elif command == _LC_BUILD_VERSION:
        platform, version, sdk = struct.unpack_from('<III', body, 0)
        arch['minimum_os'] = {
            'platform': PLATFORMS.get(platform, f'platform({platform})'),
            'sdk': _version(sdk),
            'version': _version(version)
        }
    elif command in {_LC_ENCRYPTION_INFO, _LC_ENCRYPTION_INFO_64}:
        crypt_offset, crypt_size, crypt_id = struct.unpack_from('<III', body, 0)
        arch['encryption'] = {
            'encrypted': crypt_id != 0,
            'id': crypt_id,
            'offset': crypt_offset,
            'size': crypt_size
        }
    elif command == _LC_CODE_SIGNATURE:
        data_offset, data_size = struct.unpack_from('<II', body, 0)
        arch['entitlements'] = _entitlements(image, offset + data_offset, data_size)


def _read_slice(image: bytes, offset: int) -> MachOArchDict:
    magic = struct.unpack_from('<I', image, offset)[0]
    if magic not in {_MAGIC_32, _MAGIC_64}:
        msg = f'Not a little-endian Mach-O slice at {offset:#x}: magic {magic:#010x}.'
        raise ValueError(msg)
    wide = magic == _MAGIC_64
    cpu_type, cpu_subtype, file_type, command_count, _, flags = struct.unpack_from(
        '<IIIIII', image, offset + 4)
    arch: MachOArchDict = {
        'architecture': _architecture(cpu_type, cpu_subtype),
        'cpu_subtype': cpu_subtype,
        'cpu_type': cpu_type,
        'dylibs': [],
        'encryption': None,
        'entitlements': None,
        'file_type': FILE_TYPES.get(file_type, f'type({file_type})'),
        'flags': _flag_names(flags),
        'load_command_count': command_count,
        'minimum_os': None,
        'rpaths': [],
        'segments': [],
        'source_version': None,
        'uuid': None,
        'weak_dylibs': []
    }
    cursor = offset + (_HEADER_SIZE_64 if wide else _HEADER_SIZE_32)
    for _ in range(command_count):
        if cursor + _MIN_LOAD_COMMAND_SIZE > len(image):
            break
        command, command_size = struct.unpack_from('<II', image, cursor)
        if command_size < _MIN_LOAD_COMMAND_SIZE or cursor + command_size > len(image):
            break
        _apply_command(arch, command, image[cursor + _MIN_LOAD_COMMAND_SIZE:cursor + command_size],
                       image, offset)
        cursor += command_size
    return arch


def read_macho(path: Path) -> MachODict:
    """
    Read a Mach-O image's properties.

    Parameters
    ----------
    path : pathlib.Path
        The executable to read.

    Returns
    -------
    MachODict
        One entry per architecture slice, plus the file's size and digest.

    Raises
    ------
    ValueError
        If the file is too short to hold a header, or its magic is neither a universal header nor a
        little-endian Mach-O.
    """
    image = path.read_bytes()
    if len(image) < _MIN_IMAGE_SIZE:
        msg = f'Too short to be a Mach-O image: {len(image)} bytes.'
        raise ValueError(msg)
    magic = struct.unpack_from('>I', image, 0)[0]
    offsets = [0]
    universal = magic in _FAT_MAGICS
    if universal:
        count = struct.unpack_from('>I', image, 4)[0]
        wide = magic == _FAT_MAGIC_64
        stride = _FAT_ARCH_SIZE_64 if wide else _FAT_ARCH_SIZE
        # A fat_arch entry opens with its CPU type and subtype, so the slice offset is eight bytes
        # in whichever width the entry is; only the offset field's own width differs.
        offsets = [
            struct.unpack_from('>Q' if wide else '>I', image, 8 + i * stride + 8)[0]
            for i in range(count)
        ]
    return {
        'architectures': [_read_slice(image, offset) for offset in offsets],
        'is_universal': universal,
        'name': path.name,
        'sha256': hashlib.sha256(image).hexdigest(),
        'size': len(image)
    }
