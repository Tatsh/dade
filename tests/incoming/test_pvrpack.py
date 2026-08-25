from __future__ import annotations

import logging
import struct

import pytest

from dade.incoming.pvrpack import iter_pack_textures
from dade.incoming.test_utils import pvr_pack, pvrt_chunk


def test_single_pvrt() -> None:
    data = pvrt_chunk(2, 2)
    textures = list(iter_pack_textures(data))
    assert len(textures) == 1
    assert (textures[0].width, textures[0].height, textures[0].position) == (2, 2, 0)
    assert textures[0].data == data


def test_pack_multiple() -> None:
    data = pvr_pack([pvrt_chunk(2, 2), pvrt_chunk(4, 4)])
    textures = list(iter_pack_textures(data))
    assert [t.position for t in textures] == [0, 1]
    assert [t.width for t in textures] == [2, 4]


def test_zero_terminated_toc() -> None:
    chunk = pvrt_chunk(2, 2)
    data = struct.pack('<II', 16, len(chunk)) + struct.pack('<II', 0, 0) + chunk
    assert len(list(iter_pack_textures(data))) == 1


def test_truncated_last_entry(caplog: pytest.LogCaptureFixture) -> None:
    chunk = pvrt_chunk(2, 2)
    data = pvr_pack([chunk], sizes=[len(chunk) + 8])
    with caplog.at_level(logging.WARNING, logger='dade.incoming.pvrpack'):
        textures = list(iter_pack_textures(data))
    assert len(textures[0].data) == len(chunk)
    assert 'truncated' in caplog.text


def test_too_small() -> None:
    with pytest.raises(ValueError, match='too small'):
        list(iter_pack_textures(b'\x00\x00'))


def test_invalid_toc_length() -> None:
    with pytest.raises(ValueError, match='Invalid table-of-contents'):
        list(iter_pack_textures(struct.pack('<I', 7) + bytes(20)))


def test_entry_bad_magic() -> None:
    data = struct.pack('<II', 8, 8) + b'XXXX' + bytes(4)
    with pytest.raises(ValueError, match='not start with a PVRT'):
        list(iter_pack_textures(data))
