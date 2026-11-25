from __future__ import annotations

import pytest

from dade.common.exceptions import InvalidFormatError
from dade.itgps2.av import AVHeader, read_av
from dade.itgps2.test_utils import av_stream


def test_read_av_separates_audio_and_video() -> None:
    stream = read_av(av_stream(b'\x01\x02' * 6, b'\x00\x00\x01\xb3video'))
    assert stream.header == AVHeader(has_video=True,
                                     channels=2,
                                     frames=3,
                                     sample_rate=48000,
                                     width=320,
                                     height=240)
    assert stream.audio == b'\x01\x02' * 6
    assert stream.video == b'\x00\x00\x01\xb3video'


def test_read_av_reads_audio_only_streams() -> None:
    stream = read_av(av_stream(b'\x05\x06' * 4, channels=1, sample_rate=44100))
    assert stream.header == AVHeader(has_video=False,
                                     channels=1,
                                     frames=4,
                                     sample_rate=44100,
                                     width=0,
                                     height=0)
    assert stream.audio == b'\x05\x06' * 4
    assert not stream.video


def test_read_av_stops_at_the_end_of_the_data() -> None:
    assert not read_av(av_stream(b'')[:0x201C]).audio


def test_read_av_rejects_a_truncated_header() -> None:
    with pytest.raises(InvalidFormatError, match='truncated'):
        read_av(b'\0' * 8)


def test_read_av_rejects_a_truncated_packet() -> None:
    with pytest.raises(InvalidFormatError, match='runs past the end'):
        read_av(av_stream(b'\x01' * 32)[:-24])
