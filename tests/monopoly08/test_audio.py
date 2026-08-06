from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
import logging
import struct

import pytest

from .conftest import VgmPlan

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from types import ModuleType

    from pytest_mock import MockerFixture

_SNR_HEADER = struct.pack('>II', (5 << 24) | (0 << 18) | 22050, (1 << 30) | 2048)
"""A plausible eight-byte EAAC header for an EA-XMA ``.mus`` segment."""
_JUNK = (
    b'\xff\xff\xff\xff'  # Flag byte outside {0x00, 0x80}.
    b'\x00\x00\x00\x04'  # Block size below the eight-byte minimum.
    b'\x00\xff\xff\xff'  # Block size running past the end of the bank.
    b'\x00\x00\x00\x10\x00\x01\x00\x00')  # More samples than one MPEG frame holds.
"""Bytes between streams that must not be mistaken for EA-SNS blocks."""
_UNTERMINATED = b'\x00\x00\x00\x10\x00\x00\x01\x00' + bytes(8)
"""A well-formed block whose run reaches the end of the bank without a terminator."""


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _headerless(data_start: int, body: bytes) -> bytes:
    return struct.pack('>I', data_start) + b'\x00\x00\xff\xff' + body


def _adat_raw(sub3_body: bytes, streams: bytes = b'') -> bytes:
    return b'ADAT' + bytes(12) + b'SUB3' + struct.pack('>I', len(sub3_body)) + sub3_body + streams


def test_extensions(audio_module: ModuleType) -> None:
    assert {'.mus', '.sdt'} == audio_module.EXTENSIONS


# --------------------------------------------------------------------------- #
# EA SCHl                                                                      #
# --------------------------------------------------------------------------- #


def test_jobs_for_schl(audio_module: ModuleType, make_schl: Callable[..., bytes],
                       tmp_path: Path) -> None:
    source = _write(tmp_path, 'bank.sdt', make_schl([b'first-unit', b'second-unit']))
    jobs = audio_module.jobs_for(source)
    assert [job.kind for job in jobs] == ['schl', 'schl']
    assert [job.out_wav.name for job in jobs] == ['bank_0000.wav', 'bank_0001.wav']
    assert jobs[0].start == 0


def test_jobs_for_schl_with_unpaired_terminators(audio_module: ModuleType,
                                                 make_schl: Callable[..., bytes],
                                                 tmp_path: Path) -> None:
    body = make_schl([b'first-unit', b'second-unit'], drop_last_terminator=True)
    source = _write(tmp_path, 'bank.sdt', body)
    jobs = audio_module.jobs_for(source)
    assert len(jobs) == 2
    assert jobs[1].end == len(body)


def test_run_job_schl(audio_module: ModuleType, fake_vgmstream: Callable[..., Any],
                      make_schl: Callable[..., bytes], tmp_path: Path) -> None:
    fake_vgmstream()
    source = _write(tmp_path, 'bank.sdt', make_schl([b'first-unit']))
    out, ok, message = audio_module.run_job(audio_module.jobs_for(source)[0])
    assert ok
    assert not message
    assert out.is_file()
    assert not (tmp_path / 'bank_0000.asf').exists()


def test_run_job_schl_skips_an_existing_wav(audio_module: ModuleType, fake_vgmstream: Callable[...,
                                                                                               Any],
                                            make_schl: Callable[...,
                                                                bytes], tmp_path: Path) -> None:
    run = fake_vgmstream()
    (tmp_path / 'bank_0000.wav').write_bytes(b'\x00' * 100)
    source = _write(tmp_path, 'bank.sdt', make_schl([b'first-unit']))
    _out, ok, message = audio_module.run_job(audio_module.jobs_for(source)[0])
    assert (ok, message) == (True, 'skip')
    run.assert_not_called()


def test_run_job_schl_reports_a_failure(audio_module: ModuleType, fake_vgmstream: Callable[...,
                                                                                           Any],
                                        make_schl: Callable[..., bytes], tmp_path: Path) -> None:
    fake_vgmstream(VgmPlan(message='decode failed', output=False, returncode=1))
    source = _write(tmp_path, 'bank.sdt', make_schl([b'first-unit']))
    _out, ok, message = audio_module.run_job(audio_module.jobs_for(source)[0])
    assert not ok
    assert 'decode failed' in message


def test_run_job_schl_reports_an_os_error(audio_module: ModuleType, fake_vgmstream: Callable[...,
                                                                                             Any],
                                          make_schl: Callable[..., bytes], tmp_path: Path) -> None:
    fake_vgmstream()
    source = _write(tmp_path, 'bank.sdt', make_schl([b'first-unit']))
    job = audio_module.jobs_for(source)[0]
    source.unlink()
    _out, ok, message = audio_module.run_job(job)
    assert not ok
    assert 'bank.sdt' in message


# --------------------------------------------------------------------------- #
# EAAC .mus containers holding EA-XMA segments                                 #
# --------------------------------------------------------------------------- #


def test_jobs_for_mus(audio_module: ModuleType, make_mus: Callable[..., bytes],
                      tmp_path: Path) -> None:
    body = make_mus([(_SNR_HEADER, b'A' * 32), (_SNR_HEADER, b'B' * 32)])
    jobs = audio_module.jobs_for(_write(tmp_path, 'music.mus', body))
    assert [job.kind for job in jobs] == ['mus', 'mus']
    assert jobs[0].header == _SNR_HEADER
    assert jobs[0].end == jobs[1].start
    assert jobs[1].end == len(body)


def test_jobs_for_mus_stops_at_a_descending_offset(audio_module: ModuleType,
                                                   make_mus: Callable[..., bytes],
                                                   tmp_path: Path) -> None:
    body = make_mus([(_SNR_HEADER, b'A' * 32), (_SNR_HEADER, b'B' * 32)], descending=True)
    assert len(audio_module.jobs_for(_write(tmp_path, 'music.mus', body))) == 1


def test_jobs_for_mus_with_a_full_seek_table(audio_module: ModuleType, make_mus: Callable[...,
                                                                                          bytes],
                                             tmp_path: Path) -> None:
    # 1150 twelve-byte slots is exactly what fits before the SNR header table.
    body = make_mus([(_SNR_HEADER, b'A')] * 1150)
    assert len(audio_module.jobs_for(_write(tmp_path, 'music.mus', body))) == 1150


def test_jobs_for_mus_rejects_bad_magic(audio_module: ModuleType, make_mus: Callable[..., bytes],
                                        tmp_path: Path) -> None:
    body = make_mus([(_SNR_HEADER, b'A' * 32)], magic=0x12345678)
    with pytest.raises(ValueError, match=r'bad \.mus magic'):
        audio_module.jobs_for(_write(tmp_path, 'music.mus', body))


def test_run_job_mus(audio_module: ModuleType, fake_vgmstream: Callable[..., Any],
                     make_mus: Callable[..., bytes], tmp_path: Path) -> None:
    fake_vgmstream()
    source = _write(tmp_path, 'music.mus', make_mus([(_SNR_HEADER, b'A' * 32)]))
    out, ok, message = audio_module.run_job(audio_module.jobs_for(source)[0])
    assert (ok, message) == (True, '')
    assert out.name == 'music_0000.wav'


def test_run_job_mus_skips_an_existing_wav(audio_module: ModuleType, fake_vgmstream: Callable[...,
                                                                                              Any],
                                           make_mus: Callable[..., bytes], tmp_path: Path) -> None:
    fake_vgmstream()
    (tmp_path / 'music_0000.wav').write_bytes(b'\x00' * 100)
    source = _write(tmp_path, 'music.mus', make_mus([(_SNR_HEADER, b'A' * 32)]))
    _out, ok, message = audio_module.run_job(audio_module.jobs_for(source)[0])
    assert (ok, message) == (True, 'skip')


def test_run_job_mus_reports_a_failure(audio_module: ModuleType, fake_vgmstream: Callable[..., Any],
                                       make_mus: Callable[..., bytes], tmp_path: Path) -> None:
    fake_vgmstream(VgmPlan(message='no decoder', output=False))
    source = _write(tmp_path, 'music.mus', make_mus([(_SNR_HEADER, b'A' * 32)]))
    _out, ok, message = audio_module.run_job(audio_module.jobs_for(source)[0])
    assert not ok
    assert 'no decoder' in message


def test_run_job_mus_reports_an_os_error(audio_module: ModuleType, fake_vgmstream: Callable[...,
                                                                                            Any],
                                         make_mus: Callable[..., bytes], tmp_path: Path) -> None:
    fake_vgmstream()
    source = _write(tmp_path, 'music.mus', make_mus([(_SNR_HEADER, b'A' * 32)]))
    job = audio_module.jobs_for(source)[0]
    source.unlink()
    _out, ok, _message = audio_module.run_job(job)
    assert not ok


# --------------------------------------------------------------------------- #
# EAAC .sdt (EALayer3) stream discovery                                        #
# --------------------------------------------------------------------------- #


def test_jobs_for_headerless_sdt(audio_module: ModuleType, make_sns: Callable[..., bytes],
                                 tmp_path: Path) -> None:
    body = _headerless(8, make_sns() + _JUNK + make_sns() + _UNTERMINATED)
    jobs = audio_module.jobs_for(_write(tmp_path, 'speech.sdt', body))
    assert [job.kind for job in jobs] == ['sdt', 'sdt']
    assert jobs[0].nsamp == 2048


def test_jobs_for_sdt_scans_past_leading_junk(audio_module: ModuleType, make_sns: Callable[...,
                                                                                           bytes],
                                              tmp_path: Path) -> None:
    body = _headerless(6, make_sns())
    assert len(audio_module.jobs_for(_write(tmp_path, 'speech.sdt', body))) == 1


def test_jobs_for_sdt_drops_streams_with_a_bad_sample_rate(audio_module: ModuleType,
                                                           make_sns: Callable[..., bytes],
                                                           tmp_path: Path) -> None:
    body = _headerless(8, make_sns(version=1))
    assert audio_module.jobs_for(_write(tmp_path, 'speech.sdt', body)) == []


def test_jobs_for_adat_writes_subtitles(audio_module: ModuleType, make_adat: Callable[..., bytes],
                                        make_sns: Callable[..., bytes], tmp_path: Path) -> None:
    body = make_adat([([(0x11111111, 'Go to jail'),
                        (0x22222222, 'Pass Go')], [make_sns(), make_sns()]), ((), [make_sns()])])
    jobs = audio_module.jobs_for(_write(tmp_path, 'speech.sdt', body))
    assert len(jobs) == 3
    assert (tmp_path / 'speech.subtitles.txt').read_text().splitlines() == [
        '0\t11111111\tGo to jail', '1\t22222222\tPass Go', '2\t00000000\t'
    ]


def test_jobs_for_adat_skips_padding_between_streams(audio_module: ModuleType,
                                                     make_adat: Callable[..., bytes],
                                                     make_sns: Callable[..., bytes],
                                                     tmp_path: Path) -> None:
    body = make_adat([((), [make_sns(), make_sns()])], b'\xff\xff\xff\xff')
    assert len(audio_module.jobs_for(_write(tmp_path, 'speech.sdt', body))) == 2


def test_jobs_for_adat_reads_the_alternate_hash_slot(audio_module: ModuleType,
                                                     make_adat: Callable[..., bytes],
                                                     make_sns: Callable[..., bytes],
                                                     tmp_path: Path) -> None:
    body = make_adat([([(0x33333333, 'Chance')], [make_sns()])], hash_in_second_slot=True)
    audio_module.jobs_for(_write(tmp_path, 'speech.sdt', body))
    assert '33333333\tChance' in (tmp_path / 'speech.subtitles.txt').read_text()


def test_jobs_for_adat_with_malformed_subtitles(audio_module: ModuleType, tmp_path: Path) -> None:
    oversized = struct.pack('>I', 1) + struct.pack('>IIII', 1, 0, 0, 5000)
    truncated = struct.pack('>I', 2) + struct.pack('>IIII', 2, 0, 0, 1) + b'\x00A'
    body = _adat_raw(oversized) + _adat_raw(truncated)
    assert audio_module.jobs_for(_write(tmp_path, 'speech.sdt', body)) == []
    assert (tmp_path / 'speech.subtitles.txt').read_text() == '\n'


# --------------------------------------------------------------------------- #
# EAAC .sdt decoding                                                           #
# --------------------------------------------------------------------------- #


def test_run_job_sdt_accepts_the_base_decode(audio_module: ModuleType,
                                             fake_vgmstream: Callable[..., Any],
                                             make_sns: Callable[...,
                                                                bytes], tmp_path: Path) -> None:
    fake_vgmstream(VgmPlan(channels=2))
    source = _write(tmp_path, 'speech.sdt', _headerless(8, make_sns()))
    out, ok, message = audio_module.run_job(audio_module.jobs_for(source)[0])
    assert (ok, message) == (True, '')
    assert out.read_bytes()[:4] == b'RIFF'


def test_run_job_sdt_skips_an_existing_wav(audio_module: ModuleType, fake_vgmstream: Callable[...,
                                                                                              Any],
                                           make_sns: Callable[..., bytes], tmp_path: Path) -> None:
    fake_vgmstream()
    (tmp_path / 'speech_0000.wav').write_bytes(b'\x00' * 100)
    source = _write(tmp_path, 'speech.sdt', _headerless(8, make_sns()))
    _out, ok, message = audio_module.run_job(audio_module.jobs_for(source)[0])
    assert (ok, message) == (True, 'skip')


def test_run_job_sdt_escalates_to_surround(audio_module: ModuleType, fake_vgmstream: Callable[...,
                                                                                              Any],
                                           make_sns: Callable[..., bytes], tmp_path: Path) -> None:
    fake_vgmstream(
        plans={
            2: VgmPlan(channels=2, mode='half'),
            4: VgmPlan(channels=4, message='data looks CORRUPT'),
            6: VgmPlan(channels=6)
        })
    source = _write(tmp_path, 'speech.sdt', _headerless(8, make_sns()))
    out, ok, _message = audio_module.run_job(audio_module.jobs_for(source)[0])
    assert ok
    raw = out.read_bytes()
    assert raw[:4] == b'RIFF'
    assert struct.unpack_from('<H', raw, 0x14)[0] == 0xFFFE  # WAVE_FORMAT_EXTENSIBLE.
    assert struct.unpack_from('<H', raw, 0x16)[0] == 6


def test_run_job_sdt_keeps_a_silent_decode(audio_module: ModuleType, fake_vgmstream: Callable[...,
                                                                                              Any],
                                           make_sns: Callable[..., bytes], tmp_path: Path) -> None:
    fake_vgmstream(VgmPlan(mode='silent'))
    source = _write(tmp_path, 'speech.sdt', _headerless(8, make_sns()))
    _out, ok, _message = audio_module.run_job(audio_module.jobs_for(source)[0])
    assert ok


def test_run_job_sdt_fails_when_no_channel_count_decodes(audio_module: ModuleType,
                                                         fake_vgmstream: Callable[..., Any],
                                                         make_sns: Callable[..., bytes],
                                                         tmp_path: Path) -> None:
    fake_vgmstream(VgmPlan(output=False))
    source = _write(tmp_path, 'speech.sdt', _headerless(8, make_sns()))
    _out, ok, message = audio_module.run_job(audio_module.jobs_for(source)[0])
    assert not ok
    assert 'vgmstream failed for all channel counts' in message


def test_run_job_sdt_rejects_a_bad_sample_rate(audio_module: ModuleType,
                                               fake_vgmstream: Callable[..., Any],
                                               make_sns: Callable[...,
                                                                  bytes], tmp_path: Path) -> None:
    fake_vgmstream()
    source = _write(tmp_path, 'speech.sdt', make_sns(version=1))
    job = audio_module.AudioJob('sdt', source, 0, len(source.read_bytes()), tmp_path / 'out.wav',
                                b'', 2048)
    _out, ok, message = audio_module.run_job(job)
    assert not ok
    assert 'bad sample rate' in message


# --------------------------------------------------------------------------- #
# convert_file                                                                 #
# --------------------------------------------------------------------------- #


def test_convert_file(audio_module: ModuleType, fake_vgmstream: Callable[..., Any],
                      make_schl: Callable[..., bytes], tmp_path: Path) -> None:
    fake_vgmstream()
    source = _write(tmp_path, 'bank.sdt', make_schl([b'first-unit', b'second-unit']))
    assert [p.name for p in audio_module.convert_file(source)] == ['bank_0000.wav', 'bank_0001.wav']


def test_convert_file_logs_failures(audio_module: ModuleType, caplog: pytest.LogCaptureFixture,
                                    fake_vgmstream: Callable[..., Any],
                                    make_schl: Callable[..., bytes], tmp_path: Path) -> None:
    fake_vgmstream(VgmPlan(message='broken', output=False))
    source = _write(tmp_path, 'bank.sdt', make_schl([b'first-unit']))
    with caplog.at_level(logging.WARNING, logger='destin.monopoly08.audio'):
        assert audio_module.convert_file(source) == []
    assert 'Failed to decode' in caplog.text


# --------------------------------------------------------------------------- #
# vgmstream-cli lookup                                                         #
# --------------------------------------------------------------------------- #


def _schl_job(audio_module: ModuleType, make_schl: Callable[..., bytes],
              tmp_path: Path) -> Sequence[Any]:
    source = _write(tmp_path, 'bank.sdt', make_schl([b'unit']))
    jobs: Sequence[Any] = audio_module.jobs_for(source)
    return jobs


def test_vgmstream_from_the_environment(audio_module: ModuleType, mocker: MockerFixture,
                                        monkeypatch: pytest.MonkeyPatch,
                                        make_schl: Callable[..., bytes], tmp_path: Path) -> None:
    binary = tmp_path / 'from-env'
    binary.write_bytes(b'')
    monkeypatch.setenv('VGMSTREAM_CLI', str(binary))
    run = mocker.patch('subprocess.run')
    audio_module.run_job(_schl_job(audio_module, make_schl, tmp_path)[0])
    assert run.call_args[0][0][0] == str(binary)


def test_vgmstream_from_a_bundled_copy(audio_module: ModuleType, mocker: MockerFixture,
                                       monkeypatch: pytest.MonkeyPatch,
                                       make_schl: Callable[..., bytes], tmp_path: Path) -> None:
    monkeypatch.delenv('VGMSTREAM_CLI', raising=False)
    real_is_file = Path.is_file
    monkeypatch.setattr(
        Path, 'is_file',
        lambda self: str(self).endswith('tools/vgmstream/vgmstream-cli') or real_is_file(self))
    run = mocker.patch('subprocess.run')
    audio_module.run_job(_schl_job(audio_module, make_schl, tmp_path)[0])
    assert run.call_args[0][0][0].endswith('tools/vgmstream/vgmstream-cli')


def test_vgmstream_from_the_path(audio_module: ModuleType, mocker: MockerFixture,
                                 monkeypatch: pytest.MonkeyPatch, make_schl: Callable[..., bytes],
                                 tmp_path: Path) -> None:
    monkeypatch.setenv('VGMSTREAM_CLI', str(tmp_path / 'missing'))
    mocker.patch('shutil.which', return_value='/usr/bin/vgmstream-cli')
    run = mocker.patch('subprocess.run')
    audio_module.run_job(_schl_job(audio_module, make_schl, tmp_path)[0])
    assert run.call_args[0][0][0] == '/usr/bin/vgmstream-cli'


def test_vgmstream_missing(audio_module: ModuleType, mocker: MockerFixture,
                           monkeypatch: pytest.MonkeyPatch, make_schl: Callable[..., bytes],
                           tmp_path: Path) -> None:
    monkeypatch.delenv('VGMSTREAM_CLI', raising=False)
    mocker.patch('shutil.which', return_value=None)
    _out, ok, message = audio_module.run_job(_schl_job(audio_module, make_schl, tmp_path)[0])
    assert not ok
    assert 'vgmstream-cli not found' in message
