from __future__ import annotations

from typing import Literal
import zlib

from destin.common.compress import GZIP_WBITS, inflate
import pytest

_PAYLOAD = b'the quick brown fox jumps over the lazy dog' * 8


@pytest.mark.parametrize(('mode', 'wbits'), [('zlib', zlib.MAX_WBITS), ('gzip', GZIP_WBITS),
                                             ('raw', -zlib.MAX_WBITS)])
def test_inflate_round_trip(mode: Literal['zlib', 'gzip', 'raw'], wbits: int) -> None:
    compressor = zlib.compressobj(wbits=wbits)
    compressed = compressor.compress(_PAYLOAD) + compressor.flush()
    assert inflate(compressed, mode=mode) == _PAYLOAD
