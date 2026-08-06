from __future__ import annotations

from typing import TYPE_CHECKING

from destin.monopoly08.refpack import decompress, is_refpack
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

_LITERAL_RUN = b'\xe0ABCD'
"""Literal-run opcode emitting four bytes."""
_SHORT_COPY = b'\x02\x05EF'
"""Short copy: two literals then a three-byte back-reference to offset zero."""
_MEDIUM_COPY = b'\x80\x40\x09G'
"""Medium copy: one literal then a four-byte back-reference to offset zero."""
_LONG_COPY = b'\xc1\x00\x0e\x00H'
"""Long copy: one literal then a five-byte back-reference to offset zero."""
_EOF = b'\xfeIJ'
"""End-of-stream opcode with a trailing two-byte literal run."""
_ALL_OPCODES = _LITERAL_RUN + _SHORT_COPY + _MEDIUM_COPY + _LONG_COPY + _EOF
_EXPECTED = b'ABCDEFABCGABCDHABCDEIJ'


@pytest.mark.parametrize(('data', 'expected'), [(b'\x10\xfb\x00\x00\x00', True),
                                                (b'\x10\x00\x00', False), (b'\x10', False),
                                                (b'', False)])
def test_is_refpack(*, data: bytes, expected: bool) -> None:
    assert is_refpack(data) is expected


@pytest.mark.parametrize('flags', [0x10, 0x11, 0x90, 0x91])
def test_decompress_every_opcode(make_refpack: Callable[[bytes, int, int], bytes],
                                 flags: int) -> None:
    out, size = decompress(make_refpack(_ALL_OPCODES, len(_EXPECTED), flags))
    assert out == _EXPECTED
    assert size == len(_EXPECTED)


def test_decompress_without_eof_opcode(make_refpack: Callable[[bytes, int, int], bytes]) -> None:
    out, size = decompress(make_refpack(_LITERAL_RUN, 4, 0x10))
    assert out == b'ABCD'
    assert size == 4


def test_decompress_rejects_bad_signature() -> None:
    with pytest.raises(ValueError, match='not refpack'):
        decompress(b'\x10\x00\x00\x00\x00')
