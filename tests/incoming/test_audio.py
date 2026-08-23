from __future__ import annotations

from typing import TYPE_CHECKING
import wave

import pytest

from destin.incoming.converters import ConversionError
from destin.incoming.converters.audio import raw_to_wav

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture


def test_raw_to_wav(tmp_path: Path) -> None:
    source = tmp_path / 't.raw'
    source.write_bytes(bytes(2352 * 2))
    out = raw_to_wav(source, tmp_path)
    with wave.open(str(out)) as wav:
        assert wav.getnchannels() == 2
        assert wav.getframerate() == 44100
        assert wav.getsampwidth() == 2


def test_raw_bad_size(tmp_path: Path) -> None:
    source = tmp_path / 'b.raw'
    source.write_bytes(bytes(100))
    with pytest.raises(ConversionError, match='CDDA'):
        raw_to_wav(source, tmp_path)


def test_raw_io_error(tmp_path: Path, mocker: MockerFixture) -> None:
    source = tmp_path / 't.raw'
    source.write_bytes(bytes(2352))
    mocker.patch('destin.incoming.converters.audio.wave.open', side_effect=OSError('disk full'))
    with pytest.raises(ConversionError, match='Failed to convert'):
        raw_to_wav(source, tmp_path)
