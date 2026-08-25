from __future__ import annotations

from typing import TYPE_CHECKING
import json
import logging
import wave

import pytest

from dade.incoming.converters import ConversionError
from dade.incoming.converters.sound_dc import mlt_to_json, osb_to_wav
from dade.incoming.test_utils import mlt_container, osb_bank

if TYPE_CHECKING:
    from pathlib import Path


def test_osb_to_wav(tmp_path: Path) -> None:
    data = bytearray(osb_bank(lea=4))
    data[0x4c:0x4e] = b'\x80\x07'  # mixed nibbles exercise both ADPCM delta signs
    source = tmp_path / 'b.osb'
    source.write_bytes(bytes(data))
    outputs = osb_to_wav(source, tmp_path)
    assert len(outputs) == 1
    with wave.open(str(outputs[0])) as wav:
        assert wav.getnchannels() == 1
        assert wav.getframerate() == 22050
        assert wav.getnframes() == 4


def test_osb_positive_octave(tmp_path: Path) -> None:
    source = tmp_path / 'b.osb'
    source.write_bytes(osb_bank(lea=2, pitch=0x0000))
    with wave.open(str(osb_to_wav(source, tmp_path)[0])) as wav:
        assert wav.getframerate() == 44100


def test_osb_skips_bad_record(tmp_path: Path) -> None:
    source = tmp_path / 'b.osb'
    source.write_bytes(osb_bank(sosp_magic=b'XXXX'))
    assert osb_to_wav(source, tmp_path) == ()


def test_osb_bad_bank_magic(tmp_path: Path) -> None:
    source = tmp_path / 'b.osb'
    source.write_bytes(osb_bank(bank_magic=b'XXXX'))
    with pytest.raises(ConversionError, match='SOSB'):
        osb_to_wav(source, tmp_path)


def test_osb_truncated_record(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    source = tmp_path / 'b.osb'
    source.write_bytes(osb_bank(lea=4)[:0x4c])  # drop the sample data
    with caplog.at_level(logging.WARNING, logger='dade.incoming.converters.sound_dc'):
        outputs = osb_to_wav(source, tmp_path)
    assert outputs == ()
    assert 'past the end' in caplog.text


def test_mlt(tmp_path: Path) -> None:
    source = tmp_path / 'm.mlt'
    source.write_bytes(mlt_container(count=2))
    obj = json.loads(mlt_to_json(source, tmp_path).read_text('utf-8'))
    assert obj['unit_count'] == 2
    assert obj['version'] == 0x101
    assert obj['units'][0]['type'] == 'SOSB'


def test_mlt_bad_magic(tmp_path: Path) -> None:
    source = tmp_path / 'm.mlt'
    source.write_bytes(mlt_container(magic=b'XXXX'))
    with pytest.raises(ConversionError, match='SMLT'):
        mlt_to_json(source, tmp_path)
