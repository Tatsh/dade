"""Configuration for Pytest."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, cast
import binascii
import os
import struct
import zlib

from click.testing import CliRunner
import pytest

from destin.bitrock.crypto import Twofish, cbc_encrypt, derive_key

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

_COOKFS_SIGNATURE = b'CFS0002'
_COOKFS_INDEX_MAGIC = b'CFS2.200'
_CUSTOM_COMPRESSION = b'\xff'
_PAYLOAD_INFO_KEY = 'installbuilder.payloadinfo'
_ZERO_IV = bytes(16)

if os.getenv('_PYTEST_RAISE', '0') != '0':  # pragma no cover

    @pytest.hookimpl(tryfirst=True)
    def pytest_exception_interact(call: pytest.CallInfo[None]) -> NoReturn:
        assert call.excinfo is not None
        raise call.excinfo.value

    @pytest.hookimpl(tryfirst=True)
    def pytest_internalerror(excinfo: pytest.ExceptionInfo[BaseException]) -> NoReturn:
        raise excinfo.value


@pytest.fixture(autouse=True)
def recover_stale_process_cwd(request: pytest.FixtureRequest) -> None:
    """
    Recover when the process cwd was removed mid-session.

    Gentoo Portage test phases often run pytest with aggressive temporary-directory retention.
    The process working directory can then point at a path that no longer exists, so
    ``Path.cwd()`` raises ``FileNotFoundError`` before ``monkeypatch.chdir`` can save the
    prior cwd.
    """
    try:
        Path.cwd()
    except FileNotFoundError:
        os.chdir(Path(request.config.rootpath))


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _serialize_tree(node: dict[str, object]) -> bytes:
    out = struct.pack('>i', len(node))
    for name, value in node.items():
        encoded = name.encode('utf-8')
        out += bytes([len(encoded)]) + encoded + b'\x00'
        out += struct.pack('>q', 0)
        if isinstance(value, dict):
            out += struct.pack('>i', -1) + _serialize_tree(cast('dict[str, object]', value))
        else:
            page_index, offset, size = cast('tuple[int, int, int]', value)
            out += struct.pack('>iiii', 1, page_index, offset, size)
    return out


def _build_cookfs(entries: Mapping[str, bytes], prefix: bytes = b'STUB') -> bytes:
    names = list(entries)
    stored_pages = [b'\x00' + entries[name] for name in names]
    page_sizes = [len(page) for page in stored_pages]
    tree: dict[str, object] = {}
    for index, name in enumerate(names):
        node = tree
        parts = name.split('/')
        for part in parts[:-1]:
            node = cast('dict[str, object]', node.setdefault(part, {}))
        node[parts[-1]] = (index, 0, len(entries[name]))
    index_stored = b'\x00' + _COOKFS_INDEX_MAGIC + _serialize_tree(tree)
    numpages = len(stored_pages)
    directory = bytes(numpages * 16) + struct.pack(f'>{numpages}I', *page_sizes) + index_stored
    suffix = struct.pack('>IIB', len(index_stored), numpages, 0) + _COOKFS_SIGNATURE
    return prefix + b''.join(stored_pages) + directory + suffix


@pytest.fixture
def build_cookfs() -> Callable[..., bytes]:
    """Return a builder that assembles a minimal cookfs archive from a mapping of paths to bytes."""
    return _build_cookfs


def _build_encrypted_page(payload: bytes,
                          payload_key: bytes,
                          payload_ivs: bytes,
                          iv_index: int = 0) -> bytes:
    plaintext = bytes(36) + payload
    plaintext += bytes(-len(plaintext) % 16)
    iv = payload_ivs[iv_index * 16:iv_index * 16 + 16]
    ciphertext = cbc_encrypt(Twofish(payload_key), iv, plaintext)
    return struct.pack('>IB', binascii.crc32(plaintext), iv_index) + ciphertext


@pytest.fixture
def build_encrypted_page() -> Callable[..., bytes]:
    """
    Return a builder for an encrypted cookfs page body.

    The builder wraps an already-compressed payload in the ``[CRC32][iv index][ciphertext]``
    framing that :py:func:`destin.bitrock.crypto.decrypt_page` expects.
    """
    return _build_encrypted_page


def _zlib_raw(data: bytes) -> bytes:
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    return compressor.compress(data) + compressor.flush()


@pytest.fixture
def zlib_raw() -> Callable[[bytes], bytes]:
    """Return a helper that raw-deflates bytes the way cookfs stores ZIP pages."""
    return _zlib_raw


def _serialize_metadata(items: Mapping[str, bytes]) -> bytes:
    out = struct.pack('>i', len(items))
    for key, value in items.items():
        blob = key.encode('latin1') + b'\x00' + value
        out += struct.pack('>I', len(blob)) + blob
    return out


def _build_encrypted_cookfs(entries: Mapping[str, bytes],
                            password: bytes,
                            *,
                            decompress_command: str | None = 'zip',
                            times: int = 2) -> bytes:
    """Assemble a password-protected cookfs whose pages hold zip-compressed encrypted payloads."""
    password_key = bytes(range(32))
    iv = bytes(range(16))
    derived = Twofish(derive_key(password, password_key, iv, times))
    payload_key = bytes((i * 3) & 0xFF for i in range(32))
    payload_ivs = bytes((i * 5) & 0xFF for i in range(64))
    encrypted_key = cbc_encrypt(derived, _ZERO_IV, bytes(32) + payload_key)
    buffer = bytes(32) + payload_ivs
    for _ in range(0, times, 64):
        buffer = cbc_encrypt(Twofish(payload_key), _ZERO_IV, buffer)
    payload_info = (struct.pack('>I16s32s64s32s', times, iv, password_key, encrypted_key,
                                sha256(payload_ivs).digest()) + buffer)
    names = list(entries)
    stored_pages = [
        _CUSTOM_COMPRESSION +
        _build_encrypted_page(_zlib_raw(entries[name]), payload_key, payload_ivs) for name in names
    ]
    page_sizes = [len(page) for page in stored_pages]
    tree: dict[str, object] = {}
    for index, name in enumerate(names):
        node = tree
        parts = name.split('/')
        for part in parts[:-1]:
            node = cast('dict[str, object]', node.setdefault(part, {}))
        node[parts[-1]] = (index, 0, len(entries[name]))
    metadata = _serialize_metadata({_PAYLOAD_INFO_KEY: payload_info})
    index_stored = b'\x00' + _COOKFS_INDEX_MAGIC + _serialize_tree(tree) + metadata
    numpages = len(stored_pages)
    directory = bytes(numpages * 16) + struct.pack(f'>{numpages}I', *page_sizes) + index_stored
    suffix = struct.pack('>IIB', len(index_stored), numpages, 0) + _COOKFS_SIGNATURE
    tail = (b'' if decompress_command is None else
            f'-decompresscommand {{::maui::util::MI_oJ {decompress_command}}}'.encode())
    return b'STUB' + b''.join(stored_pages) + directory + suffix + tail


@pytest.fixture
def build_encrypted_cookfs() -> Callable[..., bytes]:
    """Return a builder that assembles a password-protected cookfs archive."""
    return _build_encrypted_cookfs
